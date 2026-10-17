"""Pure Maker High-Quality Spread Experiment using hftbacktest.

Key Adjustments:
  1. Higher Quality Dislocation: z_entry = 3.0 (higher threshold, fewer trades, larger gross alpha).
  2. Pure Maker Quoting: ZERO taker orders.
     - If an order is not filled within REPEG_SECONDS (10s), cancel and re-peg to top-of-book (GTX).
     - Continue re-pegging until filled.
     - On exit, continuously re-peg at the top of the book until completely flat.
  3. Strict Decomposition:
     gross_alpha -> maker_adverse_selection -> repeg_cost -> taker_cost (0) -> net_pnl
"""

import time
from pathlib import Path
import numpy as np
import hftbacktest
from hftbacktest import (
    BacktestAsset,
    HashMapMarketDepthBacktest,
    GTX,
    LIMIT,
    FILLED,
    CANCELED,
    EXPIRED,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data/hftbacktest"

def run_pure_maker_experiment(z_threshold: float = 3.0, repeg_interval_sec: int = 10, days=(1, 2, 3)):
    print(f"\n======================================================================")
    print(f"  PURE MAKER EXPERIMENT: Z={z_threshold} | Repeg={repeg_interval_sec}s | Days={days}")
    print(f"======================================================================\n")

    # Load cached npz data
    merged = {}
    for sym in ("btcusdt", "ethusdt"):
        arrays = [np.load(DATA_DIR / f"{sym}_202601{d:02d}.npz")["data"] for d in days]
        merged[sym] = np.concatenate(arrays)

    asset_btc = (
        BacktestAsset()
        .data([merged["btcusdt"]])
        .linear_asset(1.0)
        .constant_order_latency(10_000_000, 10_000_000)
        .risk_adverse_queue_model()
        .no_partial_fill_exchange()
        .trading_value_fee_model(0.0, 0.0004)
        .tick_size(0.1)
        .lot_size(0.001)
    )

    asset_eth = (
        BacktestAsset()
        .data([merged["ethusdt"]])
        .linear_asset(1.0)
        .constant_order_latency(10_000_000, 10_000_000)
        .risk_adverse_queue_model()
        .no_partial_fill_exchange()
        .trading_value_fee_model(0.0, 0.0004)
        .tick_size(0.01)
        .lot_size(0.01)
    )

    hbt = HashMapMarketDepthBacktest([asset_btc, asset_eth])

    # Simulation State
    initial_cash = 500.0
    clip_size = 250.0
    step_ns = int(1e9)
    day_ns = 86_400 * step_ns
    warmup_sec = 3600

    # Kalman parameters
    V, W0, W1 = 1e-4, 1e-6, 1e-6
    theta_0, theta_1 = 0.0, 1.0
    P00, P01, P10, P11 = 1.0, 0.0, 0.0, 1.0
    rolling_e = np.zeros(warmup_sec, dtype=np.float64)
    rolling_idx = 0
    rolling_filled = False
    current_utc_day = None

    # Lifecycle State
    in_pos = False
    pos_dir = 0
    entry_sec = 0
    last_exit_sec = -9999
    order_id_counter = 100

    # Order tracking
    pending_entry = False
    entry_start_sec = 0
    entry_dir = 0
    btc_entry_oid, eth_entry_oid = 0, 0
    target_btc_qty, target_eth_qty = 0.0, 0.0
    entry_orig_px_b, entry_orig_px_e = 0.0, 0.0
    entry_ref_mid_b, entry_ref_mid_e = 0.0, 0.0
    entry_last_repeg_sec = 0

    pending_exit = False
    exit_start_sec = 0
    btc_exit_oid, eth_exit_oid = 0, 0
    exit_orig_px_b, exit_orig_px_e = 0.0, 0.0
    exit_ref_mid_b, exit_ref_mid_e = 0.0, 0.0
    exit_last_repeg_sec = 0
    exit_btc_qty, exit_eth_qty = 0.0, 0.0

    # Attribution tracking
    trades_completed = 0
    trade_pnls = []
    repeg_events_entry = 0
    repeg_events_exit = 0
    total_volume = 0.0

    gross_alpha_total = 0.0
    maker_adverse_selection_total = 0.0
    repeg_cost_total = 0.0

    sec_count = 0
    t0 = time.time()

    def _filled(order):
        return order is not None and order.status == FILLED

    def _inactive(order):
        return order is None or order.status in (CANCELED, EXPIRED)

    while hbt.elapse(step_ns) == 0:
        sec_count += 1
        d_b = hbt.depth(0)
        d_e = hbt.depth(1)
        b_mid = (d_b.best_bid + d_b.best_ask) / 2.0
        e_mid = (d_e.best_bid + d_e.best_ask) / 2.0

        if np.isnan(b_mid) or np.isnan(e_mid) or b_mid <= 0 or e_mid <= 0:
            continue

        now_ns = int(hbt.current_timestamp)
        utc_day = now_ns // day_ns
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
        P00 -= K0 * (P00 + lx * P01)
        P01 -= K0 * (P10 + lx * P11)
        P10 -= K1 * (P00 + lx * P01)
        P11 -= K1 * (P10 + lx * P11)

        rolling_e[rolling_idx] = e_innov
        rolling_idx = (rolling_idx + 1) % warmup_sec
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
        # 1. Active Exit Management (Pure Continuous Re-Pegging)
        # =====================================================================
        if in_pos and pending_exit:
            orders_b = hbt.orders(0)
            orders_e = hbt.orders(1)
            b_order = orders_b.get(btc_exit_oid) if btc_exit_oid in orders_b else None
            e_order = orders_e.get(eth_exit_oid) if eth_exit_oid in orders_e else None

            b_filled = _filled(b_order)
            e_filled = _filled(e_order)

            # Both exit legs filled and net position is flat
            if b_filled and e_filled and abs(pos_b) <= 1e-12 and abs(pos_e) <= 1e-12:
                px_exit_b = float(b_order.exec_price)
                px_exit_e = float(e_order.exec_price)

                # Gross Alpha
                gross_alpha = (
                    trade_pos_b * (exit_ref_mid_b - entry_ref_mid_b)
                    + trade_pos_e * (exit_ref_mid_e - entry_ref_mid_e)
                )

                # Shortfall decomposition for maker fills
                # Maker adverse selection = original quote vs reference midpoint
                # Repeg cost = executed quote vs original quote
                as_entry_b = trade_pos_b * (entry_orig_px_b - entry_ref_mid_b)
                repeg_entry_b = trade_pos_b * (entry_exec_px_b - entry_orig_px_b)

                as_entry_e = trade_pos_e * (entry_orig_px_e - entry_ref_mid_e)
                repeg_entry_e = trade_pos_e * (entry_exec_px_e - entry_orig_px_e)

                as_exit_b = -trade_pos_b * (exit_orig_px_b - exit_ref_mid_b)
                repeg_exit_b = -trade_pos_b * (px_exit_b - exit_orig_px_b)

                as_exit_e = -trade_pos_e * (exit_orig_px_e - exit_ref_mid_e)
                repeg_exit_e = -trade_pos_e * (px_exit_e - exit_orig_px_e)

                trade_as = as_entry_b + as_entry_e + as_exit_b + as_exit_e
                trade_repeg = repeg_entry_b + repeg_entry_e + repeg_exit_b + repeg_exit_e

                trade_net_pnl = gross_alpha - trade_as - trade_repeg

                gross_alpha_total += gross_alpha
                maker_adverse_selection_total += trade_as
                repeg_cost_total += trade_repeg
                trade_pnls.append(trade_net_pnl)
                trades_completed += 1

                total_volume += (abs(trade_pos_b * px_exit_b) + abs(trade_pos_e * px_exit_e))

                hbt.clear_inactive_orders(0)
                hbt.clear_inactive_orders(1)
                in_pos = False
                pending_exit = False
                last_exit_sec = sec_count
                continue

            # Continuous Re-Peg check on unfilled exit leg(s)
            time_since_exit_repeg = sec_count - exit_last_repeg_sec
            if time_since_exit_repeg >= repeg_interval_sec:
                exit_last_repeg_sec = sec_count
                if not b_filled:
                    if b_order is not None and b_order.cancellable:
                        hbt.cancel(0, btc_exit_oid, True)
                    order_id_counter += 1
                    btc_exit_oid = order_id_counter
                    px = d_b.best_ask if trade_pos_b > 0 else d_b.best_bid
                    if trade_pos_b > 0:
                        hbt.submit_sell_order(0, btc_exit_oid, px, exit_btc_qty, GTX, LIMIT, False)
                    else:
                        hbt.submit_buy_order(0, btc_exit_oid, px, exit_btc_qty, GTX, LIMIT, False)
                    repeg_events_exit += 1

                if not e_filled:
                    if e_order is not None and e_order.cancellable:
                        hbt.cancel(1, eth_exit_oid, True)
                    order_id_counter += 1
                    eth_exit_oid = order_id_counter
                    px = d_e.best_ask if trade_pos_e > 0 else d_e.best_bid
                    if trade_pos_e > 0:
                        hbt.submit_sell_order(1, eth_exit_oid, px, exit_eth_qty, GTX, LIMIT, False)
                    else:
                        hbt.submit_buy_order(1, eth_exit_oid, px, exit_eth_qty, GTX, LIMIT, False)
                    repeg_events_exit += 1
                continue

        # =====================================================================
        # 2. Exit Trigger Evaluation
        # =====================================================================
        if in_pos and not pending_exit:
            held = sec_count - entry_sec
            ou_exit = (pos_dir == 1 and z <= 0.0) or (pos_dir == -1 and z >= 0.0)
            stop_out = (pos_dir == 1 and z >= 4.0) or (pos_dir == -1 and z <= -4.0)
            time_up = held >= 600  # 10 minutes max hold for wider dislocations

            if ou_exit or stop_out or time_up:
                pending_exit = True
                exit_start_sec = sec_count
                exit_last_repeg_sec = sec_count
                exit_ref_mid_b = b_mid
                exit_ref_mid_e = e_mid
                exit_btc_qty = abs(pos_b)
                exit_eth_qty = abs(pos_e)

                exit_orig_px_b = d_b.best_ask if pos_b > 0 else d_b.best_bid
                exit_orig_px_e = d_e.best_ask if pos_e > 0 else d_e.best_bid

                order_id_counter += 1
                btc_exit_oid = order_id_counter
                order_id_counter += 1
                eth_exit_oid = order_id_counter

                if pos_b > 0:
                    hbt.submit_sell_order(0, btc_exit_oid, exit_orig_px_b, exit_btc_qty, GTX, LIMIT, False)
                else:
                    hbt.submit_buy_order(0, btc_exit_oid, exit_orig_px_b, exit_btc_qty, GTX, LIMIT, False)

                if pos_e > 0:
                    hbt.submit_sell_order(1, eth_exit_oid, exit_orig_px_e, exit_eth_qty, GTX, LIMIT, False)
                else:
                    hbt.submit_buy_order(1, eth_exit_oid, exit_orig_px_e, exit_eth_qty, GTX, LIMIT, False)
                continue

        # =====================================================================
        # 3. Active Entry Management (Pure Continuous Re-Pegging)
        # =====================================================================
        if pending_entry:
            orders_b = hbt.orders(0)
            orders_e = hbt.orders(1)
            b_order = orders_b.get(btc_entry_oid) if btc_entry_oid in orders_b else None
            e_order = orders_e.get(eth_entry_oid) if eth_entry_oid in orders_e else None

            b_filled = _filled(b_order)
            e_filled = _filled(e_order)

            # Both entry legs filled -> confirmed open trade
            if b_filled and e_filled and pos_b != 0.0 and pos_e != 0.0:
                trade_pos_b = pos_b
                trade_pos_e = pos_e
                entry_exec_px_b = float(b_order.exec_price)
                entry_exec_px_e = float(e_order.exec_price)

                pending_entry = False
                in_pos = True
                entry_sec = sec_count
                pos_dir = entry_dir
                total_volume += (abs(trade_pos_b * entry_exec_px_b) + abs(trade_pos_e * entry_exec_px_e))

                hbt.clear_inactive_orders(0)
                hbt.clear_inactive_orders(1)
                continue

            # Continuous Re-Peg on entry
            time_since_entry_repeg = sec_count - entry_last_repeg_sec
            wait_from_start = sec_count - entry_start_sec

            # If NEITHER leg filled after 60s -> cancel both and abort cleanly
            if wait_from_start >= 60 and not b_filled and not e_filled:
                if b_order is not None and b_order.cancellable:
                    hbt.cancel(0, btc_entry_oid, True)
                if e_order is not None and e_order.cancellable:
                    hbt.cancel(1, eth_entry_oid, True)
                pending_entry = False
                hbt.clear_inactive_orders(0)
                hbt.clear_inactive_orders(1)
                continue

            # If one or both unfilled, re-peg to top of book
            if time_since_entry_repeg >= repeg_interval_sec:
                entry_last_repeg_sec = sec_count
                if not b_filled:
                    if b_order is not None and b_order.cancellable:
                        hbt.cancel(0, btc_entry_oid, True)
                    order_id_counter += 1
                    btc_entry_oid = order_id_counter
                    px = d_b.best_bid if entry_dir == 1 else d_b.best_ask
                    if entry_dir == 1:
                        hbt.submit_buy_order(0, btc_entry_oid, px, target_btc_qty, GTX, LIMIT, False)
                    else:
                        hbt.submit_sell_order(0, btc_entry_oid, px, target_btc_qty, GTX, LIMIT, False)
                    repeg_events_entry += 1

                if not e_filled:
                    if e_order is not None and e_order.cancellable:
                        hbt.cancel(1, eth_entry_oid, True)
                    order_id_counter += 1
                    eth_entry_oid = order_id_counter
                    px = d_e.best_ask if entry_dir == 1 else d_e.best_bid
                    if entry_dir == 1:
                        hbt.submit_sell_order(1, eth_entry_oid, px, target_eth_qty, GTX, LIMIT, False)
                    else:
                        hbt.submit_buy_order(1, eth_entry_oid, px, target_eth_qty, GTX, LIMIT, False)
                    repeg_events_entry += 1
                continue

        # =====================================================================
        # 4. Entry Signal Trigger (Higher Quality Dislocation)
        # =====================================================================
        cooldown_ok = (sec_count - last_exit_sec) >= 60
        if not in_pos and not pending_entry and not pending_exit and cooldown_ok:
            if abs(z) >= z_threshold:
                entry_dir = 1 if z >= z_threshold else -1
                pending_entry = True
                entry_start_sec = sec_count
                entry_last_repeg_sec = sec_count
                entry_ref_mid_b = b_mid
                entry_ref_mid_e = e_mid

                btc_notional = clip_size * beta
                target_btc_qty = round(btc_notional / b_mid, 3)
                target_eth_qty = round(clip_size / e_mid, 2)

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
    net_pnl_total = sum(trade_pnls)
    win_rate = sum(p > 0 for p in trade_pnls) / len(trade_pnls) if trade_pnls else 0.0

    print(f"Results for Z={z_threshold}:")
    print(f"  Trades Completed:             {trades_completed}")
    print(f"  Farmed Volume:                ${total_volume:,.2f}")
    print(f"  Win Rate:                     {win_rate:.1%}")
    print(f"  Gross Alpha:                  ${gross_alpha_total:+,.4f}")
    print(f"  Maker Adverse Selection:      ${maker_adverse_selection_total:+,.4f}")
    print(f"  Re-peg Cost:                  ${repeg_cost_total:+,.4f}")
    print(f"  Taker Cost:                   $0.0000 (Pure Maker)")
    print(f"  Net Realized PnL:             ${net_pnl_total:+,.4f}")
    print(f"  Re-peg Events (Entry / Exit): {repeg_events_entry} / {repeg_events_exit}")
    print(f"  Execution Wall Time:          {time.time()-t0:.2f}s\n")

    return {
        "z_threshold": z_threshold,
        "trades": trades_completed,
        "volume": total_volume,
        "win_rate": win_rate,
        "gross_alpha": gross_alpha_total,
        "maker_adverse_selection": maker_adverse_selection_total,
        "repeg_cost": repeg_cost_total,
        "taker_cost": 0.0,
        "net_pnl": net_pnl_total,
    }

if __name__ == "__main__":
    for z in [2.5, 3.0, 3.5]:
        run_pure_maker_experiment(z_threshold=z, repeg_interval_sec=10, days=(1, 2, 3))
