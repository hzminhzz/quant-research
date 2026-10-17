"""Three-day execution/accounting audit for BTC/ETH Kalman pair trading.

The alpha parameters are frozen. This runner audits order lifecycle and accounting
on 2026-01-01 through 2026-01-03 only. Input caches contain tick trades plus BBO
(best bid/offer) depth derived from a top-10 source; they are not full top-10 L2.
Funding is not modeled in this short execution audit.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hftbacktest import (
    BacktestAsset,
    CANCELED,
    EXPIRED,
    FILLED,
    GTX,
    HashMapMarketDepthBacktest,
    LIMIT,
    MARKET,
)
from hftbacktest.order import IOC
from src.hftbacktest_accounting import (
    assert_trade_reconciliation,
    attribute_trade,
    entry_fully_confirmed,
    execution_cost,
    exit_fully_confirmed,
)

DATA_DIR = ROOT / "data/hftbacktest"
AUDIT_DIR = ROOT / "run_log/btc_eth_maker_kalman_20261006"

Z_ENTRY = 2.5
Z_EXIT = 0.0
Z_STOP = 3.5
MAX_HOLD_SECONDS = 360
COOLDOWN_SECONDS = 60
REPEG_SECONDS = 10
EMERGENCY_SECONDS = 25
DAILY_END_GUARD_SECONDS = 600
STEP_NS = 1_000_000_000
DAY_NS = 86_400 * STEP_NS
WARMUP_SECONDS = 3600


def _load_period(days: tuple[int, ...]) -> tuple[np.ndarray, np.ndarray]:
    if days != (1, 2, 3):
        raise ValueError("audit period is frozen to 2026-01-01 through 2026-01-03")

    merged: dict[str, np.ndarray] = {}
    for symbol in ("btcusdt", "ethusdt"):
        arrays = []
        for day in days:
            path = DATA_DIR / f"{symbol}_202601{day:02d}.npz"
            if not path.exists():
                raise FileNotFoundError(
                    f"Missing {path}; run scripts/prepare_hftbacktest_data.py first"
                )
            arrays.append(np.load(path)["data"])
        merged[symbol] = np.concatenate(arrays)

    return merged["btcusdt"], merged["ethusdt"]


def _asset(events: np.ndarray, tick_size: float, lot_size: float) -> BacktestAsset:
    return (
        BacktestAsset()
        .data([events])
        .linear_asset(1.0)
        .constant_order_latency(10_000_000, 10_000_000)
        .risk_adverse_queue_model()
        .no_partial_fill_exchange()
        .trading_value_fee_model(0.0, 0.0004)
        .tick_size(tick_size)
        .lot_size(lot_size)
    )


def _filled(order) -> bool:
    return order is not None and order.status == FILLED


def _inactive(order) -> bool:
    return order is None or order.status in (CANCELED, EXPIRED)


def _mid(depth) -> float:
    return (depth.best_bid + depth.best_ask) / 2.0


def _flat_realized(hbt: HashMapMarketDepthBacktest) -> float:
    fees = hbt.state_values(0).fee + hbt.state_values(1).fee
    return hbt.state_values(0).balance + hbt.state_values(1).balance - fees


def _fees(hbt: HashMapMarketDepthBacktest) -> float:
    return hbt.state_values(0).fee + hbt.state_values(1).fee


def _iso(timestamp_ns: int) -> str:
    return datetime.fromtimestamp(timestamp_ns / 1e9, tz=timezone.utc).isoformat()


def _submit_market(
    hbt: HashMapMarketDepthBacktest,
    *,
    asset_no: int,
    order_id: int,
    signed_qty: float,
    best_bid: float,
    best_ask: float,
) -> None:
    qty = abs(signed_qty)
    if signed_qty > 0:
        hbt.submit_buy_order(asset_no, order_id, best_ask, qty, IOC, MARKET, True)
    else:
        hbt.submit_sell_order(asset_no, order_id, best_bid, qty, IOC, MARKET, True)


def _cancel_if_active(
    hbt: HashMapMarketDepthBacktest,
    asset_no: int,
    order_id: int,
    order,
) -> None:
    if order is not None and order.cancellable:
        hbt.cancel(asset_no, order_id, True)


def _aggregate_attribution(ledger: list[dict]) -> dict[str, float]:
    fields = (
        "gross_alpha",
        "maker_adverse_selection",
        "repeg_cost",
        "taker_timing_cost",
        "taker_crossing_cost",
        "taker_fee",
        "taker_cost",
        "net_pnl",
        "reconciliation_residual",
    )
    return {field: float(sum(float(row[field]) for row in ledger)) for field in fields}


def _daily_breakdown(ledger: list[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for row in ledger:
        day = row["exit_time"][:10]
        stats = result.setdefault(
            day,
            {
                "trades": 0,
                "wins": 0,
                "volume": 0.0,
                "gross_alpha": 0.0,
                "maker_adverse_selection": 0.0,
                "repeg_cost": 0.0,
                "taker_cost": 0.0,
                "net_pnl": 0.0,
            },
        )
        stats["trades"] += 1
        stats["wins"] += int(row["net_pnl"] > 0)
        stats["volume"] += row["entry_notional"] + row["exit_notional"]
        for field in (
            "gross_alpha",
            "maker_adverse_selection",
            "repeg_cost",
            "taker_cost",
            "net_pnl",
        ):
            stats[field] += row[field]

    for stats in result.values():
        stats["win_rate"] = stats["wins"] / stats["trades"] if stats["trades"] else 0.0
    return result


def run_hftbacktest_period(
    days: tuple[int, ...] = (1, 2, 3),
    clip_size: float = 250.0,
    initial_cash: float = 500.0,
) -> tuple[dict, list[dict]]:
    """Run one continuous engine, Kalman state, and capital account."""

    btc_events, eth_events = _load_period(days)
    print(
        f"Loaded Jan 1-3 continuous stream: "
        f"{len(btc_events):,} BTC events, {len(eth_events):,} ETH events"
    )

    hbt = HashMapMarketDepthBacktest(
        [_asset(btc_events, 0.1, 0.001), _asset(eth_events, 0.01, 0.01)]
    )

    # Online Kalman state. The historical runner reset this state each
    # UTC day. Preserve that alpha process while keeping one continuous engine
    # and one continuous capital account.
    V = 1e-4
    W0 = 1e-6
    W1 = 1e-6
    theta_0 = 0.0
    theta_1 = 1.0
    P00 = 1.0
    P01 = 0.0
    P10 = 0.0
    P11 = 1.0

    rolling_e = np.zeros(WARMUP_SECONDS, dtype=np.float64)
    rolling_idx = 0
    rolling_filled = False
    current_utc_day: int | None = None
    kalman_daily_resets = 0
    simulation_start_time_ns: int | None = None
    simulation_end_time_ns: int | None = None

    # Position lifecycle.
    in_pos = False
    pos_dir = 0
    entry_sec = 0
    last_exit_sec = -9999
    order_id_counter = 100

    # Entry order state.
    pending_entry = False
    entry_start_sec = 0
    entry_dir = 0
    btc_entry_oid = 0
    eth_entry_oid = 0
    target_btc_qty = 0.0
    target_eth_qty = 0.0
    entry_repeg_attempted = False
    entry_style_b = "maker_original"
    entry_style_e = "maker_original"
    entry_orig_px_b = 0.0
    entry_orig_px_e = 0.0
    entry_taker_mid_b: float | None = None
    entry_taker_mid_e: float | None = None
    entry_had_taker = False
    signal_time_ns = 0
    signal_z = 0.0
    trade_realized_baseline = 0.0
    trade_fee_baseline = 0.0

    # Confirmed open-trade state.
    trade_pos_b = 0.0
    trade_pos_e = 0.0
    entry_exec_px_b = 0.0
    entry_exec_px_e = 0.0
    entry_ref_mid_b = 0.0
    entry_ref_mid_e = 0.0
    entry_complete_time_ns = 0
    entry_notional = 0.0

    # Exit order state.
    pending_exit = False
    exit_start_sec = 0
    btc_exit_oid = 0
    eth_exit_oid = 0
    exit_btc_qty = 0.0
    exit_eth_qty = 0.0
    exit_repeg_attempted = False
    exit_style_b = "maker_original"
    exit_style_e = "maker_original"
    exit_orig_px_b = 0.0
    exit_orig_px_e = 0.0
    exit_taker_mid_b: float | None = None
    exit_taker_mid_e: float | None = None
    exit_had_taker = False
    exit_ref_mid_b = 0.0
    exit_ref_mid_e = 0.0
    exit_trigger_time_ns = 0
    exit_reason = ""

    # Audit statistics.
    clean_maker_entries = 0
    repegged_maker_entries = 0
    emergency_taker_entries = 0
    clean_maker_exits = 0
    repegged_maker_exits = 0
    emergency_taker_exits = 0
    max_open_exposure = 0.0
    equity_curve: list[float] = []
    ledger: list[dict] = []
    sec_count = 0
    t0 = time.time()

    while hbt.elapse(STEP_NS) == 0:
        sec_count += 1
        d_b = hbt.depth(0)
        d_e = hbt.depth(1)
        b_mid = _mid(d_b)
        e_mid = _mid(d_e)
        if not np.isfinite(b_mid) or not np.isfinite(e_mid) or b_mid <= 0 or e_mid <= 0:
            continue

        now_ns = int(hbt.current_timestamp)
        if simulation_start_time_ns is None:
            simulation_start_time_ns = now_ns
        simulation_end_time_ns = now_ns

        utc_day = now_ns // DAY_NS
        if current_utc_day is None:
            current_utc_day = utc_day
        elif utc_day != current_utc_day:
            if (
                in_pos
                or pending_entry
                or pending_exit
                or abs(hbt.position(0)) > 1e-12
                or abs(hbt.position(1)) > 1e-12
            ):
                raise AssertionError("UTC day boundary reached with open or pending exposure")
            theta_0 = 0.0
            theta_1 = 1.0
            P00 = 1.0
            P01 = 0.0
            P10 = 0.0
            P11 = 1.0
            rolling_e.fill(0.0)
            rolling_idx = 0
            rolling_filled = False
            current_utc_day = utc_day
            kalman_daily_resets += 1

        # Online Kalman update.
        lx = np.log(b_mid)
        ly = np.log(e_mid)
        P00 += W0
        P11 += W1
        e_innov = ly - (theta_0 + theta_1 * lx)
        Q_var = P00 + P01 * lx + lx * (P10 + P11 * lx) + V
        K0 = (P00 + P01 * lx) / Q_var
        K1 = (P10 + P11 * lx) / Q_var
        theta_0 += K0 * e_innov
        theta_1 += K1 * e_innov

        # Preserve the historical runner's exact covariance-update ordering.
        # This audit changes execution/accounting only, not the alpha process.
        P00 -= K0 * (P00 + lx * P01)
        P01 -= K0 * (P10 + lx * P11)
        P10 -= K1 * (P00 + lx * P01)
        P11 -= K1 * (P10 + lx * P11)

        rolling_e[rolling_idx] = e_innov
        rolling_idx = (rolling_idx + 1) % WARMUP_SECONDS
        if rolling_idx == 0:
            rolling_filled = True
        if not rolling_filled:
            continue

        mean_e = float(np.mean(rolling_e))
        std_e = float(np.std(rolling_e)) + 1e-12
        z = (e_innov - mean_e) / std_e
        beta = theta_1

        pos_b = float(hbt.position(0))
        pos_e = float(hbt.position(1))
        fees = _fees(hbt)
        equity = (
            initial_cash
            + hbt.state_values(0).balance
            + pos_b * b_mid
            + hbt.state_values(1).balance
            + pos_e * e_mid
            - fees
        )
        equity_curve.append(equity)
        max_open_exposure = max(
            max_open_exposure,
            abs(pos_b * b_mid) + abs(pos_e * e_mid),
        )

        # ---------------------------------------------------------------
        # Active exit lifecycle.
        # ---------------------------------------------------------------
        if in_pos and pending_exit:
            orders_b = hbt.orders(0)
            orders_e = hbt.orders(1)
            b_order = orders_b.get(btc_exit_oid) if btc_exit_oid in orders_b else None
            e_order = orders_e.get(eth_exit_oid) if eth_exit_oid in orders_e else None
            b_filled = _filled(b_order)
            e_filled = _filled(e_order)

            if exit_fully_confirmed(b_filled, e_filled, pos_b, pos_e):
                exit_exec_px_b = float(b_order.exec_price)
                exit_exec_px_e = float(e_order.exec_price)
                exit_notional = (
                    abs(trade_pos_b * exit_exec_px_b)
                    + abs(trade_pos_e * exit_exec_px_e)
                )
                total_fees = _fees(hbt)
                cur_realized = _flat_realized(hbt)
                net_pnl = cur_realized - trade_realized_baseline

                gross_alpha = (
                    trade_pos_b * (exit_ref_mid_b - entry_ref_mid_b)
                    + trade_pos_e * (exit_ref_mid_e - entry_ref_mid_e)
                )

                components = [
                    execution_cost(
                        signed_order_qty=trade_pos_b,
                        exec_price=entry_exec_px_b,
                        reference_mid=entry_ref_mid_b,
                        style=entry_style_b,
                        original_quote=entry_orig_px_b,
                        taker_submit_mid=entry_taker_mid_b,
                    ),
                    execution_cost(
                        signed_order_qty=trade_pos_e,
                        exec_price=entry_exec_px_e,
                        reference_mid=entry_ref_mid_e,
                        style=entry_style_e,
                        original_quote=entry_orig_px_e,
                        taker_submit_mid=entry_taker_mid_e,
                    ),
                    execution_cost(
                        signed_order_qty=-trade_pos_b,
                        exec_price=exit_exec_px_b,
                        reference_mid=exit_ref_mid_b,
                        style=exit_style_b,
                        original_quote=exit_orig_px_b,
                        taker_submit_mid=exit_taker_mid_b,
                    ),
                    execution_cost(
                        signed_order_qty=-trade_pos_e,
                        exec_price=exit_exec_px_e,
                        reference_mid=exit_ref_mid_e,
                        style=exit_style_e,
                        original_quote=exit_orig_px_e,
                        taker_submit_mid=exit_taker_mid_e,
                    ),
                ]
                maker_cost = sum(item.maker_adverse_selection for item in components)
                repeg_cost = sum(item.repeg_cost for item in components)
                taker_timing = sum(item.taker_timing_cost for item in components)
                taker_crossing = sum(item.taker_crossing_cost for item in components)
                taker_fee = total_fees - trade_fee_baseline
                attribution = attribute_trade(
                    gross_alpha=gross_alpha,
                    maker_adverse_selection=maker_cost,
                    repeg_cost=repeg_cost,
                    taker_timing_cost=taker_timing,
                    taker_crossing_cost=taker_crossing,
                    taker_fee=taker_fee,
                    net_pnl=net_pnl,
                )

                if exit_had_taker:
                    emergency_taker_exits += 1
                    exit_category = "emergency_taker"
                elif exit_style_b == "maker_repeg" or exit_style_e == "maker_repeg":
                    repegged_maker_exits += 1
                    exit_category = "repegged_maker"
                else:
                    clean_maker_exits += 1
                    exit_category = "clean_maker"

                trade_id = len(ledger) + 1
                row = {
                    "trade_id": trade_id,
                    "signal_time": _iso(signal_time_ns),
                    "entry_time": _iso(entry_complete_time_ns),
                    "exit_trigger_time": _iso(exit_trigger_time_ns),
                    "exit_time": _iso(int(hbt.current_timestamp)),
                    "signal_z": float(signal_z),
                    "direction": "long_btc_short_eth" if pos_dir == 1 else "short_btc_long_eth",
                    "exit_reason": exit_reason,
                    "btc_qty": trade_pos_b,
                    "eth_qty": trade_pos_e,
                    "entry_ref_mid_btc": entry_ref_mid_b,
                    "entry_ref_mid_eth": entry_ref_mid_e,
                    "exit_ref_mid_btc": exit_ref_mid_b,
                    "exit_ref_mid_eth": exit_ref_mid_e,
                    "entry_exec_btc": entry_exec_px_b,
                    "entry_exec_eth": entry_exec_px_e,
                    "exit_exec_btc": exit_exec_px_b,
                    "exit_exec_eth": exit_exec_px_e,
                    "entry_style_btc": entry_style_b,
                    "entry_style_eth": entry_style_e,
                    "exit_style_btc": exit_style_b,
                    "exit_style_eth": exit_style_e,
                    "entry_category": (
                        "emergency_taker"
                        if entry_had_taker
                        else (
                            "repegged_maker"
                            if entry_style_b == "maker_repeg" or entry_style_e == "maker_repeg"
                            else "clean_maker"
                        )
                    ),
                    "exit_category": exit_category,
                    "entry_notional": entry_notional,
                    "exit_notional": exit_notional,
                    **attribution.to_dict(),
                }
                ledger.append(row)

                if abs(net_pnl) > 0.25 * max(entry_notional, 1e-12):
                    raise AssertionError(
                        f"trade {trade_id} PnL is implausibly large relative to entry notional"
                    )
                if abs(attribution.reconciliation_residual) > 1e-5:
                    raise AssertionError(
                        f"trade {trade_id} attribution residual is too large: "
                        f"{attribution.reconciliation_residual}"
                    )

                hbt.clear_inactive_orders(0)
                hbt.clear_inactive_orders(1)
                in_pos = False
                pending_exit = False
                last_exit_sec = sec_count
                continue

            wait_time = sec_count - exit_start_sec

            if wait_time >= REPEG_SECONDS and not exit_repeg_attempted:
                exit_repeg_attempted = True
                for asset_no, oid, order, signed_close_qty in (
                    (0, btc_exit_oid, b_order, -trade_pos_b),
                    (1, eth_exit_oid, e_order, -trade_pos_e),
                ):
                    if _filled(order):
                        continue
                    _cancel_if_active(hbt, asset_no, oid, order)
                    orders = hbt.orders(asset_no)
                    current = orders.get(oid) if oid in orders else None
                    if not _inactive(current):
                        continue

                    order_id_counter += 1
                    new_oid = order_id_counter
                    depth = hbt.depth(asset_no)
                    if signed_close_qty > 0:
                        price = depth.best_bid
                        hbt.submit_buy_order(
                            asset_no, new_oid, price, abs(signed_close_qty), GTX, LIMIT, False
                        )
                    else:
                        price = depth.best_ask
                        hbt.submit_sell_order(
                            asset_no, new_oid, price, abs(signed_close_qty), GTX, LIMIT, False
                        )
                    if asset_no == 0:
                        btc_exit_oid = new_oid
                        exit_style_b = "maker_repeg"
                    else:
                        eth_exit_oid = new_oid
                        exit_style_e = "maker_repeg"
                continue

            if wait_time >= EMERGENCY_SECONDS:
                any_taker = False
                for asset_no in (0, 1):
                    oid = btc_exit_oid if asset_no == 0 else eth_exit_oid
                    orders = hbt.orders(asset_no)
                    order = orders.get(oid) if oid in orders else None
                    if _filled(order):
                        continue

                    _cancel_if_active(hbt, asset_no, oid, order)
                    orders = hbt.orders(asset_no)
                    current = orders.get(oid) if oid in orders else None
                    if _filled(current):
                        continue
                    if not _inactive(current):
                        continue

                    depth = hbt.depth(asset_no)
                    submit_mid = _mid(depth)
                    signed_close_qty = -trade_pos_b if asset_no == 0 else -trade_pos_e
                    order_id_counter += 1
                    new_oid = order_id_counter
                    _submit_market(
                        hbt,
                        asset_no=asset_no,
                        order_id=new_oid,
                        signed_qty=signed_close_qty,
                        best_bid=depth.best_bid,
                        best_ask=depth.best_ask,
                    )
                    if asset_no == 0:
                        btc_exit_oid = new_oid
                        exit_style_b = "taker"
                        exit_taker_mid_b = submit_mid
                    else:
                        eth_exit_oid = new_oid
                        exit_style_e = "taker"
                        exit_taker_mid_e = submit_mid
                    any_taker = True
                exit_had_taker = exit_had_taker or any_taker
                continue

        # ---------------------------------------------------------------
        # Exit signal.
        # ---------------------------------------------------------------
        if in_pos and not pending_exit:
            held = sec_count - entry_sec
            ou_exit = (pos_dir == 1 and z <= Z_EXIT) or (pos_dir == -1 and z >= -Z_EXIT)
            stop_out = (pos_dir == 1 and z >= Z_STOP) or (pos_dir == -1 and z <= -Z_STOP)
            time_up = held >= MAX_HOLD_SECONDS

            if ou_exit or stop_out or time_up:
                if stop_out:
                    exit_reason = "z_stop"
                elif time_up:
                    exit_reason = "time_stop"
                else:
                    exit_reason = "zero_cross"

                pending_exit = True
                exit_start_sec = sec_count
                exit_repeg_attempted = False
                exit_had_taker = False
                exit_style_b = "maker_original"
                exit_style_e = "maker_original"
                exit_taker_mid_b = None
                exit_taker_mid_e = None
                exit_ref_mid_b = b_mid
                exit_ref_mid_e = e_mid
                exit_trigger_time_ns = int(hbt.current_timestamp)
                exit_btc_qty = abs(trade_pos_b)
                exit_eth_qty = abs(trade_pos_e)

                exit_orig_px_b = d_b.best_ask if trade_pos_b > 0 else d_b.best_bid
                exit_orig_px_e = d_e.best_ask if trade_pos_e > 0 else d_e.best_bid

                order_id_counter += 1
                btc_exit_oid = order_id_counter
                order_id_counter += 1
                eth_exit_oid = order_id_counter

                if trade_pos_b > 0:
                    hbt.submit_sell_order(
                        0, btc_exit_oid, exit_orig_px_b, exit_btc_qty, GTX, LIMIT, False
                    )
                else:
                    hbt.submit_buy_order(
                        0, btc_exit_oid, exit_orig_px_b, exit_btc_qty, GTX, LIMIT, False
                    )
                if trade_pos_e > 0:
                    hbt.submit_sell_order(
                        1, eth_exit_oid, exit_orig_px_e, exit_eth_qty, GTX, LIMIT, False
                    )
                else:
                    hbt.submit_buy_order(
                        1, eth_exit_oid, exit_orig_px_e, exit_eth_qty, GTX, LIMIT, False
                    )
                continue

        # ---------------------------------------------------------------
        # Active entry lifecycle.
        # ---------------------------------------------------------------
        if pending_entry:
            orders_b = hbt.orders(0)
            orders_e = hbt.orders(1)
            b_order = orders_b.get(btc_entry_oid) if btc_entry_oid in orders_b else None
            e_order = orders_e.get(eth_entry_oid) if eth_entry_oid in orders_e else None
            b_filled = _filled(b_order)
            e_filled = _filled(e_order)
            pos_b = float(hbt.position(0))
            pos_e = float(hbt.position(1))

            if entry_fully_confirmed(b_filled, e_filled, pos_b, pos_e):
                trade_pos_b = pos_b
                trade_pos_e = pos_e
                if trade_pos_b * trade_pos_e >= 0:
                    raise AssertionError("confirmed pair entry is not oppositely signed")

                entry_exec_px_b = float(b_order.exec_price)
                entry_exec_px_e = float(e_order.exec_price)
                entry_complete_time_ns = int(hbt.current_timestamp)
                entry_notional = (
                    abs(trade_pos_b * entry_exec_px_b)
                    + abs(trade_pos_e * entry_exec_px_e)
                )

                if entry_had_taker:
                    emergency_taker_entries += 1
                elif entry_style_b == "maker_repeg" or entry_style_e == "maker_repeg":
                    repegged_maker_entries += 1
                else:
                    clean_maker_entries += 1

                pending_entry = False
                in_pos = True
                entry_sec = sec_count
                pos_dir = entry_dir
                hbt.clear_inactive_orders(0)
                hbt.clear_inactive_orders(1)
                continue

            wait_time = sec_count - entry_start_sec

            if wait_time >= REPEG_SECONDS and not entry_repeg_attempted:
                entry_repeg_attempted = True
                for asset_no, oid, order, signed_target_qty in (
                    (0, btc_entry_oid, b_order, target_btc_qty if entry_dir == 1 else -target_btc_qty),
                    (1, eth_entry_oid, e_order, -target_eth_qty if entry_dir == 1 else target_eth_qty),
                ):
                    if _filled(order):
                        continue
                    _cancel_if_active(hbt, asset_no, oid, order)
                    orders = hbt.orders(asset_no)
                    current = orders.get(oid) if oid in orders else None
                    if not _inactive(current):
                        continue

                    order_id_counter += 1
                    new_oid = order_id_counter
                    depth = hbt.depth(asset_no)
                    if signed_target_qty > 0:
                        price = depth.best_bid
                        hbt.submit_buy_order(
                            asset_no, new_oid, price, abs(signed_target_qty), GTX, LIMIT, False
                        )
                    else:
                        price = depth.best_ask
                        hbt.submit_sell_order(
                            asset_no, new_oid, price, abs(signed_target_qty), GTX, LIMIT, False
                        )
                    if asset_no == 0:
                        btc_entry_oid = new_oid
                        entry_style_b = "maker_repeg"
                    else:
                        eth_entry_oid = new_oid
                        entry_style_e = "maker_repeg"
                continue

            if wait_time >= EMERGENCY_SECONDS:
                # Synchronously cancel any remaining maker order first. A fill
                # won by the cancel race remains a maker fill; only a confirmed
                # inactive order is replaced with a market IOC.
                for asset_no in (0, 1):
                    oid = btc_entry_oid if asset_no == 0 else eth_entry_oid
                    orders = hbt.orders(asset_no)
                    order = orders.get(oid) if oid in orders else None
                    if _filled(order):
                        continue
                    _cancel_if_active(hbt, asset_no, oid, order)

                orders_b = hbt.orders(0)
                orders_e = hbt.orders(1)
                b_order = orders_b.get(btc_entry_oid) if btc_entry_oid in orders_b else None
                e_order = orders_e.get(eth_entry_oid) if eth_entry_oid in orders_e else None
                b_filled = _filled(b_order)
                e_filled = _filled(e_order)

                if not b_filled and not e_filled:
                    if _inactive(b_order) and _inactive(e_order):
                        if abs(hbt.position(0)) > 1e-12 or abs(hbt.position(1)) > 1e-12:
                            raise AssertionError("cancelled entry left an unexplained position")
                        pending_entry = False
                        hbt.clear_inactive_orders(0)
                        hbt.clear_inactive_orders(1)
                    continue

                if b_filled != e_filled:
                    unfilled_asset = 1 if b_filled else 0
                    current_oid = eth_entry_oid if unfilled_asset == 1 else btc_entry_oid
                    orders = hbt.orders(unfilled_asset)
                    current = orders.get(current_oid) if current_oid in orders else None
                    if not _inactive(current):
                        continue

                    depth = hbt.depth(unfilled_asset)
                    submit_mid = _mid(depth)
                    if unfilled_asset == 0:
                        signed_qty = target_btc_qty if entry_dir == 1 else -target_btc_qty
                    else:
                        signed_qty = -target_eth_qty if entry_dir == 1 else target_eth_qty

                    order_id_counter += 1
                    new_oid = order_id_counter
                    _submit_market(
                        hbt,
                        asset_no=unfilled_asset,
                        order_id=new_oid,
                        signed_qty=signed_qty,
                        best_bid=depth.best_bid,
                        best_ask=depth.best_ask,
                    )
                    entry_had_taker = True
                    if unfilled_asset == 0:
                        btc_entry_oid = new_oid
                        entry_style_b = "taker"
                        entry_taker_mid_b = submit_mid
                    else:
                        eth_entry_oid = new_oid
                        entry_style_e = "taker"
                        entry_taker_mid_e = submit_mid
                continue

        # ---------------------------------------------------------------
        # New entry signal.
        # ---------------------------------------------------------------
        cooldown_ok = (sec_count - last_exit_sec) >= COOLDOWN_SECONDS
        ns_into_utc_day = int(hbt.current_timestamp) % DAY_NS
        before_daily_cutoff = (
            ns_into_utc_day < DAY_NS - DAILY_END_GUARD_SECONDS * STEP_NS
        )
        if (
            not in_pos
            and not pending_entry
            and not pending_exit
            and cooldown_ok
            and before_daily_cutoff
            and abs(z) >= Z_ENTRY
        ):
            if beta <= 0 or not np.isfinite(beta):
                continue

            entry_dir = 1 if z >= Z_ENTRY else -1
            pending_entry = True
            entry_start_sec = sec_count
            entry_repeg_attempted = False
            entry_had_taker = False
            entry_style_b = "maker_original"
            entry_style_e = "maker_original"
            entry_taker_mid_b = None
            entry_taker_mid_e = None
            signal_time_ns = int(hbt.current_timestamp)
            signal_z = float(z)
            entry_ref_mid_b = b_mid
            entry_ref_mid_e = e_mid
            trade_realized_baseline = _flat_realized(hbt)
            trade_fee_baseline = _fees(hbt)

            btc_notional = clip_size * beta
            target_btc_qty = round(btc_notional / b_mid, 3)
            target_eth_qty = round(clip_size / e_mid, 2)
            if target_btc_qty <= 0 or target_eth_qty <= 0:
                pending_entry = False
                continue

            entry_orig_px_b = d_b.best_bid if entry_dir == 1 else d_b.best_ask
            entry_orig_px_e = d_e.best_ask if entry_dir == 1 else d_e.best_bid

            order_id_counter += 1
            btc_entry_oid = order_id_counter
            order_id_counter += 1
            eth_entry_oid = order_id_counter

            if entry_dir == 1:
                hbt.submit_buy_order(
                    0, btc_entry_oid, entry_orig_px_b, target_btc_qty, GTX, LIMIT, False
                )
                hbt.submit_sell_order(
                    1, eth_entry_oid, entry_orig_px_e, target_eth_qty, GTX, LIMIT, False
                )
            else:
                hbt.submit_sell_order(
                    0, btc_entry_oid, entry_orig_px_b, target_btc_qty, GTX, LIMIT, False
                )
                hbt.submit_buy_order(
                    1, eth_entry_oid, entry_orig_px_e, target_eth_qty, GTX, LIMIT, False
                )

    # The 10-minute no-new-entry guard before each UTC boundary must leave the engine flat.
    end_pos_b = float(hbt.position(0))
    end_pos_e = float(hbt.position(1))
    open_at_end = (
        in_pos
        or pending_entry
        or pending_exit
        or abs(end_pos_b) > 1e-12
        or abs(end_pos_e) > 1e-12
    )

    final_mid_b = _mid(hbt.depth(0))
    final_mid_e = _mid(hbt.depth(1))
    total_fees = _fees(hbt)
    engine_mtm_pnl = (
        hbt.state_values(0).balance
        + end_pos_b * final_mid_b
        + hbt.state_values(1).balance
        + end_pos_e * final_mid_e
        - total_fees
    )
    realized_pnl = _flat_realized(hbt)

    if open_at_end:
        hbt.close()
        raise AssertionError(
            "audit ended with open/pending exposure; increase only the audit boundary guard"
        )

    trade_pnls = [float(row["net_pnl"]) for row in ledger]
    pnl_reconciliation_error = assert_trade_reconciliation(
        trade_pnls,
        realized_pnl,
        tolerance=1e-6,
    )
    aggregate = _aggregate_attribution(ledger)
    attribution_reconciliation_error = float(aggregate["reconciliation_residual"])

    completed_volume = float(
        sum(row["entry_notional"] + row["exit_notional"] for row in ledger)
    )
    engine_volume = float(
        hbt.state_values(0).trading_value + hbt.state_values(1).trading_value
    )
    max_abs_trade_pnl = max((abs(value) for value in trade_pnls), default=0.0)
    max_pnl_ratio = max(
        (
            abs(float(row["net_pnl"])) / max(float(row["entry_notional"]), 1e-12)
            for row in ledger
        ),
        default=0.0,
    )
    if max_pnl_ratio > 0.25:
        hbt.close()
        raise AssertionError(f"trade PnL sanity ratio is too large: {max_pnl_ratio}")

    summary = {
        "audit_session_id": "btc_eth_maker_kalman_exec_audit_20261006_v3",
        "framework": f"hftbacktest {version('hftbacktest')}",
        "classification": "EXPLORATORY_EXECUTION_ACCOUNTING_AUDIT",
        "period": "2026-01-01 through 2026-01-03",
        "continuous_engine_state": True,
        "continuous_kalman_state": False,
        "kalman_reset_policy": "reset at each UTC day to preserve historical runner alpha mechanics",
        "kalman_daily_resets": kalman_daily_resets,
        "simulation_start_time": (
            _iso(simulation_start_time_ns) if simulation_start_time_ns is not None else None
        ),
        "simulation_end_time": (
            _iso(simulation_end_time_ns) if simulation_end_time_ns is not None else None
        ),
        "simulated_seconds": sec_count,
        "initial_capital": initial_cash,
        "final_equity": initial_cash + engine_mtm_pnl,
        "total_net_pnl": engine_mtm_pnl,
        "total_return_pct": engine_mtm_pnl / initial_cash * 100.0,
        "realized_pnl": realized_pnl,
        "engine_total_fees": total_fees,
        "completed_trade_volume": completed_volume,
        "engine_total_trading_value": engine_volume,
        "trades_completed": len(ledger),
        "win_rate": (
            sum(row["net_pnl"] > 0 for row in ledger) / len(ledger) if ledger else 0.0
        ),
        "average_holding_seconds": (
            sum(
                (
                    datetime.fromisoformat(row["exit_time"])
                    - datetime.fromisoformat(row["entry_time"])
                ).total_seconds()
                for row in ledger
            )
            / len(ledger)
            if ledger
            else 0.0
        ),
        "clean_maker_entries": clean_maker_entries,
        "repegged_maker_entries": repegged_maker_entries,
        "emergency_taker_entries": emergency_taker_entries,
        "clean_maker_exits": clean_maker_exits,
        "repegged_maker_exits": repegged_maker_exits,
        "emergency_taker_exits": emergency_taker_exits,
        "max_open_gross_exposure": max_open_exposure,
        "max_abs_trade_pnl": max_abs_trade_pnl,
        "max_abs_trade_pnl_to_entry_notional": max_pnl_ratio,
        "pnl_reconciliation_error": pnl_reconciliation_error,
        "attribution": aggregate,
        "attribution_reconciliation_error": attribution_reconciliation_error,
        "open_position_at_end": False,
        "daily_end_entry_guard_seconds": DAILY_END_GUARD_SECONDS,
        "data_semantics": (
            "tick trades plus best bid/offer depth derived from source top10; "
            "not full top10 L2"
        ),
        "funding_included": False,
        "execution": {
            "latency_ms_inbound": 10,
            "latency_ms_response": 10,
            "queue_model": "risk_adverse_queue_model",
            "partial_fills": False,
            "maker_fee_bps": 0.0,
            "taker_fee_bps": 4.0,
            "repeg_seconds": REPEG_SECONDS,
            "emergency_seconds": EMERGENCY_SECONDS,
        },
        "strategy": {
            "z_entry": Z_ENTRY,
            "z_exit": Z_EXIT,
            "z_stop": Z_STOP,
            "max_hold_seconds": MAX_HOLD_SECONDS,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "kalman_V": V,
            "kalman_W0": W0,
            "kalman_W1": W1,
        },
        "daily_breakdown": _daily_breakdown(ledger),
        "historical_one_week_artifact": {
            "path": (
                "run_log/btc_eth_pair_trading_scalp/"
                "hftbacktest_official_1week_results.json"
            ),
            "accounting_validity": "SUPERSEDED_BY_AUDIT",
            "reason": (
                "historical runner declared emergency entry/exit completion "
                "before fills were confirmed and mixed non-flat balance snapshots"
            ),
        },
        "runtime_seconds": time.time() - t0,
    }

    hbt.close()
    return summary, ledger


def _write_artifacts(summary: dict, ledger: list[dict]) -> None:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = AUDIT_DIR / "three_day_audit_summary_v3.json"
    ledger_json_path = AUDIT_DIR / "three_day_trade_ledger_v3.json"
    ledger_csv_path = AUDIT_DIR / "three_day_trade_ledger_v3.csv"

    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    ledger_json_path.write_text(json.dumps(ledger, indent=2) + "\n")

    if ledger:
        with ledger_csv_path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(ledger[0].keys()))
            writer.writeheader()
            writer.writerows(ledger)
    else:
        ledger_csv_path.write_text("")

    print(f"Saved audit summary: {summary_path}")
    print(f"Saved trade ledger: {ledger_json_path}")
    print(f"Saved trade ledger CSV: {ledger_csv_path}")


def main() -> None:
    summary, ledger = run_hftbacktest_period()
    _write_artifacts(summary, ledger)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
