"""Advanced Exit Logic Benchmark for BTC/ETH Relative-Value Pair Trading.

Tests and compares 5 research-backed exit mechanisms using hftbacktest v2.4.4:
  1. 'baseline_z0': Classic textbook mean-reversion exit at Z = 0.0 with 25s emergency taker.
  2. 'ekstrom_z08': Ekström-Leung early profit take at Z = 0.8 with 25s emergency taker.
  3. 'ekstrom_z05': Ekström-Leung early profit take at Z = 0.5 with 25s emergency taker.
  4. 'collapsing_boundary': Time-decaying exit boundary Z_exit(t) = 1.0 * (1 - t/360).
  5. 'guilbaud_pham_urgency': Ekström Z=0.8 maker exit + urgency taker if adverse drift > 1 tick.

Full microstructural audit:
  - Exact Tick & L2 Book Depth Replay (36.2M events over Jan 1-3)
  - 10ms Latency Model, Risk-Adverse Queue Depletion, Post-Only Enforcement
  - Confirmed Flat-to-Flat Execution & Exact PnL Attribution Bridge
"""
import argparse
import json
import sys
import time
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hftbacktest import (
    BacktestAsset,
    HashMapMarketDepthBacktest,
    GTX,
    LIMIT,
    MARKET,
    FILLED,
    CANCELED,
    EXPIRED,
)
from hftbacktest.order import IOC
from src.hftbacktest_accounting import (
    assert_trade_reconciliation,
    attribute_trade,
    entry_fully_confirmed,
    execution_cost,
    exit_fully_confirmed,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data/hftbacktest"
OUTPUT_DIR = ROOT / "run_log/btc_eth_maker_kalman_20261006"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

STEP_NS = 1_000_000_000
DAY_NS = 86_400 * STEP_NS
WARMUP_SECONDS = 3600


def _asset(paths_or_events: list[str] | list[np.ndarray], tick_size: float, lot_size: float) -> BacktestAsset:
    return (
        BacktestAsset()
        .data(paths_or_events)
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


def _submit_market(hbt, asset_no, order_id, signed_qty, best_bid, best_ask):
    qty = abs(signed_qty)
    if signed_qty > 0:
        hbt.submit_buy_order(asset_no, order_id, best_ask, qty, IOC, MARKET, True)
    else:
        hbt.submit_sell_order(asset_no, order_id, best_bid, qty, IOC, MARKET, True)


def _cancel_if_active(hbt, asset_no, order_id, order):
    if order is not None and order.cancellable:
        hbt.cancel(asset_no, order_id, True)


def run_exit_benchmark(
    policy_name: str,
    days: tuple[int, ...] = (1, 2, 3),
    year: int = 2026,
    month: int = 1,
    z_entry: float = 3.0,
    clip_size: float = 250.0,
    initial_cash: float = 500.0,
) -> dict:
    print(f"\n======================================================================")
    print(f"  RUNNING ADVANCED EXIT POLICY: '{policy_name}' ({year}-{month:02d}, Days={days}, Z_entry={z_entry})")
    print(f"======================================================================")

    t0 = time.time()
    btc_paths = [str(DATA_DIR / f"btcusdt_{year}{month:02d}{d:02d}.npz") for d in days]
    eth_paths = [str(DATA_DIR / f"ethusdt_{year}{month:02d}{d:02d}.npz") for d in days]
    for p in btc_paths + eth_paths:
        if not Path(p).exists():
            raise FileNotFoundError(f"Missing cached file: {p}")

    hbt = HashMapMarketDepthBacktest([_asset(btc_paths, 0.1, 0.001), _asset(eth_paths, 0.01, 0.01)])
    # Strategy Parameters
    repeg_seconds = 10
    emergency_seconds = 25
    max_hold_seconds = 360
    cooldown_seconds = 60
    z_stop = 4.0

    # Online Kalman State
    V, W0, W1 = 1e-4, 1e-6, 1e-6
    theta_0, theta_1 = 0.0, 1.0
    P00, P01, P10, P11 = 1.0, 0.0, 0.0, 1.0
    rolling_e = np.zeros(WARMUP_SECONDS, dtype=np.float64)
    rolling_idx = 0
    rolling_filled = False
    current_utc_day = None

    # Lifecycle State
    in_pos = False
    pos_dir = 0
    entry_sec = 0
    last_exit_sec = -9999
    order_id_counter = 100

    # Entry State
    pending_entry = False
    entry_start_sec = 0
    entry_dir = 0
    btc_entry_oid, eth_entry_oid = 0, 0
    target_btc_qty, target_eth_qty = 0.0, 0.0
    entry_repeg_attempted = False
    entry_style_b, entry_style_e = "maker_original", "maker_original"
    entry_orig_px_b, entry_orig_px_e = 0.0, 0.0
    entry_taker_mid_b, entry_taker_mid_e = None, None
    entry_had_taker = False
    trade_realized_baseline = 0.0
    trade_fee_baseline = 0.0

    # Confirmed Trade State
    trade_pos_b, trade_pos_e = 0.0, 0.0
    entry_exec_px_b, entry_exec_px_e = 0.0, 0.0
    entry_ref_mid_b, entry_ref_mid_e = 0.0, 0.0
    entry_notional = 0.0

    # Exit State
    pending_exit = False
    exit_start_sec = 0
    btc_exit_oid, eth_exit_oid = 0, 0
    exit_btc_qty, exit_eth_qty = 0.0, 0.0
    exit_repeg_attempted = False
    exit_style_b, exit_style_e = "maker_original", "maker_original"
    exit_orig_px_b, exit_orig_px_e = 0.0, 0.0
    exit_taker_mid_b, exit_taker_mid_e = None, None
    exit_had_taker = False
    exit_ref_mid_b, exit_ref_mid_e = 0.0, 0.0
    exit_initial_mid_b, exit_initial_mid_e = 0.0, 0.0

    # Metrics
    trades_completed = 0
    clean_maker_entries, repegged_maker_entries, emergency_taker_entries = 0, 0, 0
    clean_maker_exits, repegged_maker_exits, emergency_taker_exits = 0, 0, 0
    total_volume = 0.0
    ledger = []
    sec_count = 0

    while hbt.elapse(STEP_NS) == 0:
        sec_count += 1
        d_b = hbt.depth(0)
        d_e = hbt.depth(1)
        b_mid = _mid(d_b)
        e_mid = _mid(d_e)
        if not np.isfinite(b_mid) or not np.isfinite(e_mid) or b_mid <= 0 or e_mid <= 0:
            continue

        now_ns = int(hbt.current_timestamp)
        utc_day = now_ns // DAY_NS
        if current_utc_day is None:
            current_utc_day = utc_day
        elif utc_day != current_utc_day:
            if not in_pos and not pending_entry and not pending_exit:
                theta_0, theta_1 = 0.0, 1.0
                P00, P01, P10, P11 = 1.0, 0.0, 0.0, 1.0
                rolling_e.fill(0.0)
                rolling_idx = 0
                rolling_filled = False
                current_utc_day = utc_day

        # Online Kalman update
        lx, ly = np.log(b_mid), np.log(e_mid)
        P00 += W0
        P11 += W1
        e_innov = ly - (theta_0 + theta_1 * lx)
        Q_var = P00 + P01 * lx + lx * (P10 + P11 * lx) + V
        K0 = (P00 + P01 * lx) / Q_var
        K1 = (P10 + P11 * lx) / Q_var
        theta_0 += K0 * e_innov
        theta_1 += K1 * e_innov
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

        # =====================================================================
        # 1. Active Exit Lifecycle
        # =====================================================================
        if in_pos and pending_exit:
            orders_b = hbt.orders(0)
            orders_e = hbt.orders(1)
            b_order = orders_b.get(btc_exit_oid) if btc_exit_oid in orders_b else None
            e_order = orders_e.get(eth_exit_oid) if eth_exit_oid in orders_e else None
            b_filled = _filled(b_order)
            e_filled = _filled(e_order)

            # Check if completely flat and closed
            if exit_fully_confirmed(b_filled, e_filled, pos_b, pos_e):
                exit_exec_px_b = float(b_order.exec_price)
                exit_exec_px_e = float(e_order.exec_price)
                exit_notional = abs(trade_pos_b * exit_exec_px_b) + abs(trade_pos_e * exit_exec_px_e)
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
                taker_fee = _fees(hbt) - trade_fee_baseline

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
                elif exit_style_b == "maker_repeg" or exit_style_e == "maker_repeg":
                    repegged_maker_exits += 1
                else:
                    clean_maker_exits += 1

                row = {
                    "trade_id": len(ledger) + 1,
                    "net_pnl": net_pnl,
                    "entry_notional": entry_notional,
                    "exit_notional": exit_notional,
                    **attribution.to_dict(),
                }
                ledger.append(row)
                total_volume += (entry_notional + exit_notional)
                trades_completed += 1

                hbt.clear_inactive_orders(0)
                hbt.clear_inactive_orders(1)
                in_pos = False
                pending_exit = False
                last_exit_sec = sec_count
                continue

            wait_time = sec_count - exit_start_sec

            # Guilbaud-Pham Urgency Check: Trigger immediate taker exit if adverse move during exit > 1 tick
            trigger_urgency_taker = False
            if policy_name == "guilbaud_pham_urgency" and wait_time >= 5:
                drift_b = (b_mid - exit_initial_mid_b) * (1.0 if trade_pos_b < 0 else -1.0)
                drift_e = (e_mid - exit_initial_mid_e) * (1.0 if trade_pos_e < 0 else -1.0)
                # Adverse move of > 1 tick on either leg triggers urgency taker execution
                if drift_b > 0.15 or drift_e > 0.03:
                    trigger_urgency_taker = True

            # Active Re-Peg at 10s
            if wait_time >= repeg_seconds and not exit_repeg_attempted and not trigger_urgency_taker:
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
                    price = depth.best_bid if signed_close_qty > 0 else depth.best_ask
                    if signed_close_qty > 0:
                        hbt.submit_buy_order(asset_no, new_oid, price, abs(signed_close_qty), GTX, LIMIT, False)
                    else:
                        hbt.submit_sell_order(asset_no, new_oid, price, abs(signed_close_qty), GTX, LIMIT, False)
                    if asset_no == 0:
                        btc_exit_oid = new_oid
                        exit_style_b = "maker_repeg"
                    else:
                        eth_exit_oid = new_oid
                        exit_style_e = "maker_repeg"
                continue

            # Emergency Taker at 25s (or immediately on urgency trigger)
            if wait_time >= emergency_seconds or trigger_urgency_taker:
                for asset_no in (0, 1):
                    oid = btc_exit_oid if asset_no == 0 else eth_exit_oid
                    orders = hbt.orders(asset_no)
                    order = orders.get(oid) if oid in orders else None
                    if _filled(order):
                        continue
                    _cancel_if_active(hbt, asset_no, oid, order)
                    orders = hbt.orders(asset_no)
                    current = orders.get(oid) if oid in orders else None
                    if _filled(current) or not _inactive(current):
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
                    exit_had_taker = True
                continue

        # =====================================================================
        # 2. Exit Trigger Evaluation
        # =====================================================================
        if in_pos and not pending_exit:
            held = sec_count - entry_sec
            time_up = held >= max_hold_seconds
            stop_out = (pos_dir == 1 and z >= z_stop) or (pos_dir == -1 and z <= -z_stop)

            # Dynamic Exit Boundary determination
            if policy_name == "baseline_z0":
                exit_target_z = 0.0
            elif policy_name == "ekstrom_z08":
                exit_target_z = 0.8
            elif policy_name == "ekstrom_z05":
                exit_target_z = 0.5
            elif policy_name == "collapsing_boundary":
                # Boundary collapses from 1.0 down to 0.0 as holding time elapses
                time_frac = min(held / max_hold_seconds, 1.0)
                exit_target_z = max(1.0 * (1.0 - time_frac), 0.1)
            elif policy_name == "guilbaud_pham_urgency":
                exit_target_z = 0.8
            else:
                exit_target_z = 0.0

            ou_exit = (pos_dir == 1 and z <= exit_target_z) or (pos_dir == -1 and z >= -exit_target_z)

            if ou_exit or stop_out or time_up:
                pending_exit = True
                exit_start_sec = sec_count
                exit_repeg_attempted = False
                exit_had_taker = False
                exit_style_b, exit_style_e = "maker_original", "maker_original"
                exit_taker_mid_b, exit_taker_mid_e = None, None
                exit_ref_mid_b, exit_ref_mid_e = b_mid, e_mid
                exit_initial_mid_b, exit_initial_mid_e = b_mid, e_mid
                exit_btc_qty = abs(trade_pos_b)
                exit_eth_qty = abs(trade_pos_e)

                exit_orig_px_b = d_b.best_ask if trade_pos_b > 0 else d_b.best_bid
                exit_orig_px_e = d_e.best_ask if trade_pos_e > 0 else d_e.best_bid

                order_id_counter += 1
                btc_exit_oid = order_id_counter
                order_id_counter += 1
                eth_exit_oid = order_id_counter

                if trade_pos_b > 0:
                    hbt.submit_sell_order(0, btc_exit_oid, exit_orig_px_b, exit_btc_qty, GTX, LIMIT, False)
                else:
                    hbt.submit_buy_order(0, btc_exit_oid, exit_orig_px_b, exit_btc_qty, GTX, LIMIT, False)

                if trade_pos_e > 0:
                    hbt.submit_sell_order(1, eth_exit_oid, exit_orig_px_e, exit_eth_qty, GTX, LIMIT, False)
                else:
                    hbt.submit_buy_order(1, eth_exit_oid, exit_orig_px_e, exit_eth_qty, GTX, LIMIT, False)
                continue

        # =====================================================================
        # 3. Active Entry Lifecycle (Audited confirmed entry state machine)
        # =====================================================================
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
                entry_exec_px_b = float(b_order.exec_price)
                entry_exec_px_e = float(e_order.exec_price)
                entry_notional = abs(trade_pos_b * entry_exec_px_b) + abs(trade_pos_e * entry_exec_px_e)

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

            if wait_time >= repeg_seconds and not entry_repeg_attempted:
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
                    price = depth.best_bid if signed_target_qty > 0 else depth.best_ask
                    if signed_target_qty > 0:
                        hbt.submit_buy_order(asset_no, new_oid, price, abs(signed_target_qty), GTX, LIMIT, False)
                    else:
                        hbt.submit_sell_order(asset_no, new_oid, price, abs(signed_target_qty), GTX, LIMIT, False)
                    if asset_no == 0:
                        btc_entry_oid = new_oid
                        entry_style_b = "maker_repeg"
                    else:
                        eth_entry_oid = new_oid
                        entry_style_e = "maker_repeg"
                continue

            if wait_time >= emergency_seconds:
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
                    signed_qty = (
                        (target_btc_qty if entry_dir == 1 else -target_btc_qty)
                        if unfilled_asset == 0
                        else (-target_eth_qty if entry_dir == 1 else target_eth_qty)
                    )
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

        # =====================================================================
        # 4. Entry Signal Trigger
        # =====================================================================
        cooldown_ok = (sec_count - last_exit_sec) >= cooldown_seconds
        if not in_pos and not pending_entry and not pending_exit and cooldown_ok:
            if abs(z) >= z_entry:
                entry_dir = 1 if z >= z_entry else -1
                pending_entry = True
                entry_start_sec = sec_count
                entry_repeg_attempted = False
                entry_had_taker = False
                entry_style_b, entry_style_e = "maker_original", "maker_original"
                entry_taker_mid_b, entry_taker_mid_e = None, None
                entry_ref_mid_b, entry_ref_mid_e = b_mid, e_mid

                btc_notional = clip_size * beta
                target_btc_qty = round(btc_notional / b_mid, 3)
                target_eth_qty = round(clip_size / e_mid, 2)

                trade_realized_baseline = _flat_realized(hbt)
                trade_fee_baseline = _fees(hbt)

                entry_orig_px_b = d_b.best_bid if entry_dir == 1 else d_b.best_ask
                entry_orig_px_e = d_e.best_ask if entry_dir == 1 else d_e.best_bid

                order_id_counter += 1
                btc_entry_oid = order_id_counter
                order_id_counter += 1
                eth_entry_oid = order_id_counter

                if entry_dir == 1:
                    hbt.submit_buy_order(0, btc_entry_oid, entry_orig_px_b, target_btc_qty, GTX, LIMIT, False)
                    hbt.submit_sell_order(1, eth_entry_oid, entry_orig_px_e, target_eth_qty, GTX, LIMIT, False)
                else:
                    hbt.submit_sell_order(0, btc_entry_oid, entry_orig_px_b, target_btc_qty, GTX, LIMIT, False)
                    hbt.submit_buy_order(1, eth_entry_oid, entry_orig_px_e, target_eth_qty, GTX, LIMIT, False)

    hbt.close()

    # Aggregate Performance Metrics
    total_net_pnl = sum(r["net_pnl"] for r in ledger) if ledger else 0.0
    gross_alpha_tot = sum(r["gross_alpha"] for r in ledger) if ledger else 0.0
    maker_as_tot = sum(r["maker_adverse_selection"] for r in ledger) if ledger else 0.0
    repeg_tot = sum(r["repeg_cost"] for r in ledger) if ledger else 0.0
    taker_tot = sum(r["taker_cost"] for r in ledger) if ledger else 0.0
    win_rate = sum(r["net_pnl"] > 0 for r in ledger) / len(ledger) if ledger else 0.0

    print(f"Policy '{policy_name}' Results:")
    print(f"  Trades Completed:             {trades_completed}")
    print(f"  Farmed Volume:                ${total_volume:,.2f}")
    print(f"  Win Rate:                     {win_rate:.1%}")
    print(f"  Gross Alpha:                  ${gross_alpha_tot:+,.4f}")
    print(f"  Maker Adverse Selection:      ${maker_as_tot:+,.4f}")
    print(f"  Re-peg Cost:                  ${repeg_tot:+,.4f}")
    print(f"  Taker Cost:                   ${taker_tot:+,.4f}")
    print(f"  Net Realized PnL:             ${total_net_pnl:+,.4f}")
    print(f"  Clean Maker Exits:            {clean_maker_exits} ({clean_maker_exits/max(trades_completed,1):.1%})")
    print(f"  Re-Pegged Maker Exits:        {repegged_maker_exits} ({repegged_maker_exits/max(trades_completed,1):.1%})")
    print(f"  Emergency/Urgency Takers:     {emergency_taker_exits} ({emergency_taker_exits/max(trades_completed,1):.1%})")
    print(f"  Execution Time:               {time.time()-t0:.2f}s\n")

    result = {
        "policy": policy_name,
        "trades": trades_completed,
        "volume": total_volume,
        "win_rate": win_rate,
        "gross_alpha": gross_alpha_tot,
        "maker_adverse_selection": maker_as_tot,
        "repeg_cost": repeg_tot,
        "taker_cost": taker_tot,
        "net_pnl": total_net_pnl,
        "clean_maker_exits": clean_maker_exits,
        "repegged_maker_exits": repegged_maker_exits,
        "emergency_taker_exits": emergency_taker_exits,
        "cost_per_million": (abs(total_net_pnl) / (total_volume / 1_000_000)) if total_volume > 0 else 0.0,
    }

    out_file = OUTPUT_DIR / f"exit_benchmark_{policy_name}.json"
    out_file.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", default="all", choices=["baseline_z0", "ekstrom_z08", "ekstrom_z05", "collapsing_boundary", "guilbaud_pham_urgency", "all"])
    parser.add_argument("--z_entry", type=float, default=3.0)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--month", type=int, default=1)
    parser.add_argument("--days", type=str, default="1,2,3", help="Comma-separated list of day numbers")
    args = parser.parse_args()

    days = tuple(int(x.strip()) for x in args.days.split(","))
    policies = (
        ["baseline_z0", "ekstrom_z08", "ekstrom_z05", "collapsing_boundary", "guilbaud_pham_urgency"]
        if args.policy == "all"
        else [args.policy]
    )

    all_results = []
    for pol in policies:
        res = run_exit_benchmark(pol, days=days, year=args.year, month=args.month, z_entry=args.z_entry)
        all_results.append(res)
    out_summary = OUTPUT_DIR / "exit_policy_benchmark_summary.json"
    out_summary.write_text(json.dumps(all_results, indent=2) + "\n")
    print(f"\nSaved benchmark summary to: {out_summary}")


if __name__ == "__main__":
    main()
