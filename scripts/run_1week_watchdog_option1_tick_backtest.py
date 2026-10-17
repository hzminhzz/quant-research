"""1-Week Truthful Tick & L2 Backtest with Option 1 Atomic Execution Watchdog.

Strategy Architecture:
  - 1-Week Horizon: 2026-01-01 to 2026-01-07 (7 Full Days, 604,800 seconds)
  - Account: $500.00 Initial Capital | Clip: $250.00/leg ($500 gross notional)
  - Option 1 Entry Watchdog:
      * Place Limit Maker orders on both legs.
      * If both fill within timeout (20s) -> 100% Maker (0.0 bps).
      * If Leg A fills and Leg B times out -> Immediate Market (IOC) hedge on Leg B
        (Leg A pays 0.0 bps Maker, Leg B pays 4.0 bps taker + 2.0 bps slippage).
  - Option 1 Exit Watchdog:
      * Place Limit Maker exit orders on both legs.
      * If Leg A exits and Leg B times out -> Immediate Market exit on Leg B
        (preventing lingering naked exposure).
"""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import polars as pl
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
STORE_BASE = Path("/home/quant/dev/quant/ml4t-data/.data/store")

def run_watchdog_week_backtest(clip_size: float = 250.0):
    print("======================================================================")
    print("  1-WEEK TICK & L2 BACKTEST WITH OPTION 1 ATOMIC WATCHDOG")
    print(f"  Period: 2026-01-01 to 2026-01-07 (7 Full Days)")
    print(f"  Account: $500.00 | Clip Size: ${clip_size:,.2f} per leg")
    print("======================================================================\n")

    initial_capital = 500.0
    cash = initial_capital
    peak_equity = initial_capital
    max_drawdown = 0.0

    z_entry = 2.5
    z_exit = 0.0
    z_stop = 3.5
    max_queue_wait_sec = 20   # 20-second watchdog timer
    max_hold_sec = 360        # 6-minute holding timer
    taker_friction_rate = 0.00060  # 4 bps taker fee + 2 bps slippage on forced market legs

    total_volume_farmed = 0.0
    total_trades_completed = 0
    clean_both_maker_entries = 0
    forced_market_hedge_entries = 0
    clean_both_maker_exits = 0
    forced_market_hedge_exits = 0
    total_taker_friction_paid = 0.0
    trade_pnls = []

    daily_stats = {}
    daily_equity_series = [initial_capital]
    daily_volume_series = []
    dates_list = []

    days = list(range(1, 8))  # 7 days

    for day in days:
        date_str = f"2026-01-{day:02d}"

        f_btc_tick = STORE_BASE / f"crypto_futures_tick_BTCUSDT_PERP/year=2026/month=1/day={day}/data.parquet"
        f_eth_tick = STORE_BASE / f"crypto_futures_tick_ETHUSDT_PERP/year=2026/month=1/day={day}/data.parquet"
        f_btc_l2 = STORE_BASE / f"crypto_futures_l2_BTCUSDT_PERP_top10/year=2026/month=01/day={day:02d}/data.parquet"
        f_eth_l2 = STORE_BASE / f"crypto_futures_l2_ETHUSDT_PERP_top10/year=2026/month=01/day={day:02d}/data.parquet"

        # Downsample L2 to 1-second top of book
        l2_b = (
            pl.read_parquet(f_btc_l2)
            .select(["timestamp", "bid_p1", "bid_q1", "ask_p1", "ask_q1"])
            .with_columns(ts_sec=(pl.col("timestamp") // 1000).cast(pl.Int64))
            .group_by("ts_sec")
            .agg([pl.last("bid_p1"), pl.last("bid_q1"), pl.last("ask_p1"), pl.last("ask_q1")])
            .sort("ts_sec")
        )
        l2_e = (
            pl.read_parquet(f_eth_l2)
            .select(["timestamp", "bid_p1", "bid_q1", "ask_p1", "ask_q1"])
            .with_columns(ts_sec=(pl.col("timestamp") // 1000).cast(pl.Int64))
            .group_by("ts_sec")
            .agg([pl.last("bid_p1"), pl.last("bid_q1"), pl.last("ask_p1"), pl.last("ask_q1")])
            .sort("ts_sec")
        )

        book = (
            l2_b.rename({c: f"btc_{c}" for c in ["bid_p1", "bid_q1", "ask_p1", "ask_q1"]})
            .join(l2_e.rename({c: f"eth_{c}" for c in ["bid_p1", "bid_q1", "ask_p1", "ask_q1"]}), on="ts_sec", how="inner")
            .sort("ts_sec")
        )
        n_sec = book.height

        ts_sec = book["ts_sec"].to_numpy()
        btc_bid_p = book["btc_bid_p1"].to_numpy()
        btc_bid_q = book["btc_bid_q1"].to_numpy()
        btc_ask_p = book["btc_ask_p1"].to_numpy()
        btc_ask_q = book["btc_ask_q1"].to_numpy()

        eth_bid_p = book["eth_bid_p1"].to_numpy()
        eth_bid_q = book["eth_bid_q1"].to_numpy()
        eth_ask_p = book["eth_ask_p1"].to_numpy()
        eth_ask_q = book["eth_ask_q1"].to_numpy()

        btc_mid = (btc_bid_p + btc_ask_p) / 2.0
        eth_mid = (eth_bid_p + eth_ask_p) / 2.0

        # Index trade ticks for queue depletion
        ticks_b = pl.read_parquet(f_btc_tick).select(["timestamp", "price", "qty", "side"]).with_columns(ts_sec=(pl.col("timestamp") // 1000).cast(pl.Int64))
        ticks_e = pl.read_parquet(f_eth_tick).select(["timestamp", "price", "qty", "side"]).with_columns(ts_sec=(pl.col("timestamp") // 1000).cast(pl.Int64))

        btc_sells_map = dict(zip(ticks_b.filter(pl.col("side") == "S").group_by("ts_sec").agg(pl.sum("qty")).sort("ts_sec")["ts_sec"].to_list(), ticks_b.filter(pl.col("side") == "S").group_by("ts_sec").agg(pl.sum("qty")).sort("ts_sec")["qty"].to_list()))
        btc_buys_map = dict(zip(ticks_b.filter(pl.col("side") == "B").group_by("ts_sec").agg(pl.sum("qty")).sort("ts_sec")["ts_sec"].to_list(), ticks_b.filter(pl.col("side") == "B").group_by("ts_sec").agg(pl.sum("qty")).sort("ts_sec")["qty"].to_list()))
        eth_sells_map = dict(zip(ticks_e.filter(pl.col("side") == "S").group_by("ts_sec").agg(pl.sum("qty")).sort("ts_sec")["ts_sec"].to_list(), ticks_e.filter(pl.col("side") == "S").group_by("ts_sec").agg(pl.sum("qty")).sort("ts_sec")["qty"].to_list()))
        eth_buys_map = dict(zip(ticks_e.filter(pl.col("side") == "B").group_by("ts_sec").agg(pl.sum("qty")).sort("ts_sec")["ts_sec"].to_list(), ticks_e.filter(pl.col("side") == "B").group_by("ts_sec").agg(pl.sum("qty")).sort("ts_sec")["qty"].to_list()))

        # Kalman Filter
        x = np.log(btc_mid)
        y = np.log(eth_mid)
        V = 1e-4
        W = np.diag([1e-6, 1e-6])
        theta = np.array([0.0, 1.0])
        P = np.eye(2) * 1.0

        innovations = np.zeros(n_sec)
        betas = np.zeros(n_sec)

        for t in range(n_sec):
            P = P + W
            F = np.array([1.0, x[t]])
            e = y[t] - F @ theta
            Q = F @ P @ F + V
            K = (P @ F) / Q
            theta = theta + K * e
            P = P - np.outer(K, F @ P)
            betas[t] = theta[1]
            innovations[t] = e

        df_innov = pl.DataFrame({"e": innovations}).with_columns([
            pl.col("e").rolling_mean(3600).alias("m"),
            pl.col("e").rolling_std(3600).alias("s"),
        ]).with_columns([
            ((pl.col("e") - pl.col("m")) / (pl.col("s") + 1e-12)).alias("z")
        ]).fill_null(0.0)

        z_arr = df_innov["z"].to_numpy()
        beta_arr = betas

        # Position and Watchdog State
        in_pos = False
        trade_dir = 0
        trade_entry_sec = 0
        trade_pos_btc = 0.0
        trade_pos_eth = 0.0
        trade_entry_cost = 0.0

        # Entry Pending State
        pending_entry = False
        entry_submit_sec = 0
        entry_dir = 0
        entry_b_p, entry_b_q_ahead = 0.0, 0.0
        entry_e_p, entry_e_q_ahead = 0.0, 0.0
        entry_b_qty, entry_e_qty = 0.0, 0.0

        # Exit Pending State (Watchdog for closing)
        pending_exit = False
        exit_submit_sec = 0
        exit_b_p, exit_b_q_ahead = 0.0, 0.0
        exit_e_p, exit_e_q_ahead = 0.0, 0.0

        last_exit_sec = -9999
        day_start_cash = cash
        day_volume = 0.0
        day_trades = 0
        day_wins = 0

        for t in range(3600, n_sec - 1):
            now = ts_sec[t]

            # ---------------------------------------------------------------
            # 1. Active Position Check -> Trigger Exit Watchdog
            # ---------------------------------------------------------------
            if in_pos and not pending_exit:
                held = now - trade_entry_sec
                cur_z = z_arr[t]
                ou_exit = (trade_dir == 1 and cur_z <= z_exit) or (trade_dir == -1 and cur_z >= -z_exit)
                stop_out = (trade_dir == 1 and cur_z >= z_stop) or (trade_dir == -1 and cur_z <= -z_stop)
                time_up = held >= max_hold_sec

                if ou_exit or stop_out or time_up:
                    pending_exit = True
                    exit_submit_sec = now

                    # Target maker limit prices at inside quotes
                    exit_b_p = btc_bid_p[t] if trade_pos_btc > 0 else btc_ask_p[t]
                    exit_b_q_ahead = btc_bid_q[t] if trade_pos_btc > 0 else btc_ask_q[t]

                    exit_e_p = eth_bid_p[t] if trade_pos_eth > 0 else eth_ask_p[t]
                    exit_e_q_ahead = eth_ask_q[t] if trade_pos_eth > 0 else eth_bid_q[t]

            # ---------------------------------------------------------------
            # 2. Manage Exit Queue & Option 1 Exit Watchdog
            # ---------------------------------------------------------------
            if in_pos and pending_exit:
                wait_sec = now - exit_submit_sec

                # Deplete queues via trade ticks
                if trade_pos_btc > 0:
                    exit_b_q_ahead -= btc_sells_map.get(now, 0.0)
                else:
                    exit_b_q_ahead -= btc_buys_map.get(now, 0.0)

                if trade_pos_eth > 0:
                    exit_e_q_ahead -= eth_sells_map.get(now, 0.0)
                else:
                    exit_e_q_ahead -= eth_buys_map.get(now, 0.0)

                b_filled = exit_b_q_ahead <= 0
                e_filled = exit_e_q_ahead <= 0

                # Scenario A: Clean Maker Exit (both filled within 20s)
                if b_filled and e_filled:
                    clean_both_maker_exits += 1
                    val_b = trade_pos_btc * exit_b_p
                    val_e = trade_pos_eth * exit_e_p
                    gross_pnl = val_b + val_e - trade_entry_cost

                    cash += gross_pnl
                    notional = abs(val_b) + abs(val_e)
                    day_volume += notional
                    total_volume_farmed += notional

                    trade_pnls.append(gross_pnl)
                    total_trades_completed += 1
                    day_trades += 1
                    if gross_pnl > 0:
                        day_wins += 1

                    in_pos = False
                    pending_exit = False
                    last_exit_sec = now
                    continue

                # Scenario B: Option 1 Exit Watchdog Trigger (20s timeout elapsed)
                elif wait_sec >= max_queue_wait_sec:
                    forced_market_hedge_exits += 1
                    # Fill filled leg at limit, fill unfilled leg at market (IOC)
                    val_b = trade_pos_btc * (exit_b_p if b_filled else (btc_bid_p[t] if trade_pos_btc > 0 else btc_ask_p[t]))
                    val_e = trade_pos_eth * (exit_e_p if e_filled else (eth_bid_p[t] if trade_pos_eth > 0 else eth_ask_p[t]))

                    # Taker fee applied only to the unfilled leg
                    unfilled_leg_notional = abs(val_b) if not b_filled else abs(val_e)
                    taker_fee = unfilled_leg_notional * taker_friction_rate

                    gross_pnl = val_b + val_e - trade_entry_cost - taker_fee
                    total_taker_friction_paid += taker_fee

                    cash += gross_pnl
                    notional = abs(val_b) + abs(val_e)
                    day_volume += notional
                    total_volume_farmed += notional

                    trade_pnls.append(gross_pnl)
                    total_trades_completed += 1
                    day_trades += 1
                    if gross_pnl > 0:
                        day_wins += 1

                    in_pos = False
                    pending_exit = False
                    last_exit_sec = now
                    continue

            # ---------------------------------------------------------------
            # 3. Manage Entry Queue & Option 1 Entry Watchdog
            # ---------------------------------------------------------------
            if pending_entry:
                wait_sec = now - entry_submit_sec

                # Deplete queues via trade ticks
                if entry_dir == 1:
                    entry_b_q_ahead -= btc_sells_map.get(now, 0.0)
                    entry_e_q_ahead -= eth_buys_map.get(now, 0.0)
                else:
                    entry_b_q_ahead -= btc_buys_map.get(now, 0.0)
                    entry_e_q_ahead -= eth_sells_map.get(now, 0.0)

                b_filled = entry_b_q_ahead <= 0
                e_filled = entry_e_q_ahead <= 0

                # Scenario A: Clean Both Maker Entry Fills
                if b_filled and e_filled:
                    clean_both_maker_entries += 1
                    pending_entry = False
                    in_pos = True
                    trade_entry_sec = now
                    trade_dir = entry_dir

                    if entry_dir == 1:
                        trade_pos_btc = entry_b_qty
                        trade_pos_eth = -entry_e_qty
                        trade_entry_cost = (entry_b_qty * entry_b_p) - (entry_e_qty * entry_e_p)
                    else:
                        trade_pos_btc = -entry_b_qty
                        trade_pos_eth = entry_e_qty
                        trade_entry_cost = (-entry_b_qty * entry_b_p) + (entry_e_qty * entry_e_p)

                    entry_notional = (entry_b_qty * entry_b_p) + (entry_e_qty * entry_e_p)
                    day_volume += entry_notional
                    total_volume_farmed += entry_notional
                    continue

                # Scenario B: Watchdog Trigger on Entry Timeout (20s)
                elif wait_sec >= max_queue_wait_sec:
                    pending_entry = False

                    # Sub-case B1: Neither leg filled -> clean timeout, zero cost
                    if not b_filled and not e_filled:
                        continue

                    # Sub-case B2: One leg filled -> Option 1 Immediate Market Hedge!
                    forced_market_hedge_entries += 1
                    in_pos = True
                    trade_entry_sec = now
                    trade_dir = entry_dir

                    # Market order fills the unfilled leg at opposite side
                    if b_filled and not e_filled:
                        # BTC filled at limit, ETH hedge filled at market ask/bid
                        fill_eth_mkt = eth_ask_p[t] if entry_dir == 1 else eth_bid_p[t]
                        taker_fee = (entry_e_qty * fill_eth_mkt) * taker_friction_rate
                        total_taker_friction_paid += taker_fee

                        if entry_dir == 1:
                            trade_pos_btc = entry_b_qty
                            trade_pos_eth = -entry_e_qty
                            trade_entry_cost = (entry_b_qty * entry_b_p) - (entry_e_qty * fill_eth_mkt) + taker_fee
                        else:
                            trade_pos_btc = -entry_b_qty
                            trade_pos_eth = entry_e_qty
                            trade_entry_cost = (-entry_b_qty * entry_b_p) + (entry_e_qty * fill_eth_mkt) + taker_fee

                    elif e_filled and not b_filled:
                        # ETH filled at limit, BTC hedge filled at market
                        fill_btc_mkt = btc_ask_p[t] if entry_dir == -1 else btc_bid_p[t]
                        taker_fee = (entry_b_qty * fill_btc_mkt) * taker_friction_rate
                        total_taker_friction_paid += taker_fee

                        if entry_dir == 1:
                            trade_pos_btc = entry_b_qty
                            trade_pos_eth = -entry_e_qty
                            trade_entry_cost = (entry_b_qty * fill_btc_mkt) - (entry_e_qty * entry_e_p) + taker_fee
                        else:
                            trade_pos_btc = -entry_b_qty
                            trade_pos_eth = entry_e_qty
                            trade_entry_cost = (-entry_b_qty * fill_btc_mkt) + (entry_e_qty * entry_e_p) + taker_fee

                    entry_notional = (entry_b_qty * entry_b_p) + (entry_e_qty * entry_e_p)
                    day_volume += entry_notional
                    total_volume_farmed += entry_notional
                    continue

            # ---------------------------------------------------------------
            # 4. New Entry Signal Evaluation
            # ---------------------------------------------------------------
            cooldown_ok = (now - last_exit_sec) >= 60
            if not in_pos and not pending_entry and not pending_exit and cooldown_ok:
                z = z_arr[t]
                if abs(z) >= z_entry:
                    s = 1 if z >= z_entry else -1
                    b = beta_arr[t]

                    target_b = btc_bid_p[t] if s == 1 else btc_ask_p[t]
                    target_e = eth_ask_p[t] if s == 1 else eth_bid_p[t]
                    q_b = btc_bid_q[t] if s == 1 else btc_ask_q[t]
                    q_e = eth_ask_q[t] if s == 1 else eth_bid_q[t]

                    btc_notional = clip_size * b
                    entry_b_qty = btc_notional / target_b
                    entry_e_qty = clip_size / target_e

                    pending_entry = True
                    entry_submit_sec = now
                    entry_dir = s
                    entry_b_p, entry_b_q_ahead = target_b, q_b
                    entry_e_p, entry_e_q_ahead = target_e, q_e

            # Mark to Market Equity Tracking
            unrealized_pnl = (trade_pos_btc * btc_mid[t] + trade_pos_eth * eth_mid[t] - trade_entry_cost) if in_pos else 0.0
            cur_eq = cash + unrealized_pnl
            if cur_eq > peak_equity:
                peak_equity = cur_eq
            dd = (peak_equity - cur_eq) / peak_equity
            if dd > max_drawdown:
                max_drawdown = dd

        day_end_cash = cash
        day_net_pnl = day_end_cash - day_start_cash
        daily_stats[date_str] = {
            "day": date_str,
            "day_pnl": day_net_pnl,
            "day_volume": day_volume,
            "trades": day_trades,
            "win_rate": day_wins / day_trades if day_trades > 0 else 0.0,
            "ending_cash": day_end_cash,
        }
        dates_list.append(date_str)
        daily_equity_series.append(day_end_cash)
        daily_volume_series.append(day_volume)

        print(f"[{date_str}] PnL: ${day_net_pnl:+,.2f} | Vol: ${day_volume/1000:,.1f}k | Trades: {day_trades:3d} | Cash: ${day_end_cash:,.2f}")

    # Summary
    final_equity = cash
    total_net_pnl = final_equity - initial_capital
    total_return_pct = total_net_pnl / initial_capital

    print("\n" + "=" * 80)
    print("      1-WEEK OPTION 1 WATCHDOG TICK & L2 BACKTEST RESULTS ($500 ACCOUNT)")
    print("=" * 80)
    print(f"Period:                         2026-01-01 to 2026-01-07 (7 Full Days)")
    print(f"Starting Capital:               ${initial_capital:,.2f}")
    print(f"Ending Capital:                 ${final_equity:,.2f}")
    print(f"Net PnL (after market hedges):  ${total_net_pnl:+,.2f} ({total_return_pct:+.2%})")
    print(f"Max MTM Drawdown:               {max_drawdown:.2%}")
    print("-" * 80)
    print(f"TOTAL VOLUME FARMED:            ${total_volume_farmed:,.2f} (${total_volume_farmed/1_000_000:,.2f}M)")
    print(f"Average Daily Volume:           ${total_volume_farmed/7.0:,.2f} / day")
    print(f"Capital Turnover:               {total_volume_farmed/initial_capital:,.1f}x of account capital")
    print("-" * 80)
    print(f"Completed Round-Trip Trades:    {total_trades_completed:,} ({total_trades_completed/7.0:.1f} trades/day)")
    print(f"Trade Win Rate:                 {sum(p > 0 for p in trade_pnls)/len(trade_pnls):.1%}")
    print(f"Average Net PnL per Trade:      ${np.mean(trade_pnls) if trade_pnls else 0.0:+,.4f}")
    print("-" * 80)
    print(f"Clean Dual-Maker Entry Fills:   {clean_both_maker_entries:,} ({clean_both_maker_entries/total_trades_completed:.1%})")
    print(f"Forced Market Hedge Entries:    {forced_market_hedge_entries:,} ({forced_market_hedge_entries/total_trades_completed:.1%})")
    print(f"Clean Dual-Maker Exit Fills:    {clean_both_maker_exits:,} ({clean_both_maker_exits/total_trades_completed:.1%})")
    print(f"Forced Market Hedge Exits:      {forced_market_hedge_exits:,} ({forced_market_hedge_exits/total_trades_completed:.1%})")
    print(f"Total Taker Friction Paid:      ${total_taker_friction_paid:,.2f}")
    print("=" * 80)

    # Plot
    fig, axes = plt.subplots(3, 1, figsize=(11, 10))
    fig.patch.set_facecolor("#ffffff")
    day_idx = np.arange(len(dates_list))

    axes[0].plot(day_idx, np.cumsum(daily_volume_series) / 1_000_000.0, color="#1f77b4", linewidth=2.0)
    axes[0].set_title(f"1. Cumulative Volume Farmed: ${total_volume_farmed/1_000_000:,.2f}M (7 Days)", fontsize=11, fontweight="bold")
    axes[0].set_ylabel("Volume ($M)")
    axes[0].grid(True, linestyle="--", alpha=0.5)

    axes[1].plot(day_idx, daily_equity_series[1:], color="#2ca02c" if total_net_pnl >= 0 else "#d62728", linewidth=2.0, marker="o")
    axes[1].axhline(initial_capital, color="gray", linestyle="--")
    axes[1].set_title(f"2. Portfolio Equity Progression ($500 -> ${final_equity:,.2f})", fontsize=11, fontweight="bold")
    axes[1].set_ylabel("Equity ($)")
    axes[1].grid(True, linestyle="--", alpha=0.5)

    axes[2].bar(day_idx, [v / 1000.0 for v in daily_volume_series], color="#ff7f0e", alpha=0.75, edgecolor="black")
    axes[2].set_title("3. Daily Volume Farmed ($k / day)", fontsize=11, fontweight="bold")
    axes[2].set_ylabel("Volume ($k)")
    axes[2].set_xticks(day_idx)
    axes[2].set_xticklabels(dates_list, rotation=20, ha="right")
    axes[2].grid(True, linestyle="--", alpha=0.5, axis="y")

    plt.tight_layout()
    out_dir = ROOT / "docs/audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    fig_path = out_dir / "option1_watchdog_1week_tearsheet.png"
    plt.savefig(fig_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"\nSaved Option 1 Tearsheet to: {fig_path}")

    out_file = ROOT / "run_log/btc_eth_pair_trading_scalp/option1_watchdog_1week_results.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "period": "2026-01-01 to 2026-01-07 (7 Full Days)",
        "initial_capital": initial_capital,
        "final_capital": final_equity,
        "total_net_pnl": total_net_pnl,
        "total_return_pct": total_return_pct * 100.0,
        "max_drawdown_pct": max_drawdown * 100.0,
        "total_volume_farmed": total_volume_farmed,
        "capital_turnover": total_volume_farmed / initial_capital,
        "trades_completed": total_trades_completed,
        "clean_maker_entries": clean_both_maker_entries,
        "forced_market_hedge_entries": forced_market_hedge_entries,
        "total_taker_friction_paid": total_taker_friction_paid,
        "daily_breakdown": daily_stats,
    }
    out_file.write_text(json.dumps(report, indent=2))
    print(f"Saved Option 1 Watchdog results to: {out_file}")
    return report

if __name__ == "__main__":
    run_watchdog_week_backtest(clip_size=250.0)
