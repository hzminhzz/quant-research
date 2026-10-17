"""Full 1-Month (January 2026) Truthful Tick & L2 Queue Backtest.

Complete 31-Day HFT Microstructure Simulation for a $500 Account:
  - Date Range: 2026-01-01 to 2026-01-31 (31 Full Days, 2.68M seconds)
  - Starting Capital: $500.00
  - Clip Size: $250.00 per leg ($500.00 gross notional per trade)
  - True Order Book Queue Priority (FIFO depletion via trade ticks)
  - 30s limit order timeout & both-leg fill enforcement
  - Zero-fee maker promo (0.0 bps)
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

def run_1month_backtest(clip_size: float = 250.0):
    print("======================================================================")
    print("  FULL 1-MONTH TRUTHFUL TICK & L2 BACKTEST: 2026-01-01 TO 2026-01-31")
    print(f"  Initial Portfolio: $500.00 | Clip Size: ${clip_size:,.2f} per leg")
    print("======================================================================\n")

    initial_capital = 500.0
    cash = initial_capital
    peak_equity = initial_capital
    max_drawdown = 0.0

    z_entry = 2.5
    z_exit = 0.0
    z_stop = 3.5
    max_queue_wait_sec = 30
    max_hold_sec = 360  # 6 minutes

    total_volume_farmed = 0.0
    total_trades_completed = 0
    total_orders_submitted = 0
    total_orders_filled = 0
    total_orders_timed_out = 0
    trade_pnls = []

    daily_stats = {}
    daily_equity_series = [initial_capital]
    daily_volume_series = []
    dates_list = []

    for day in range(1, 32):
        date_str = f"2026-01-{day:02d}"

        f_btc_tick = STORE_BASE / f"crypto_futures_tick_BTCUSDT_PERP/year=2026/month=1/day={day}/data.parquet"
        f_eth_tick = STORE_BASE / f"crypto_futures_tick_ETHUSDT_PERP/year=2026/month=1/day={day}/data.parquet"
        f_btc_l2 = STORE_BASE / f"crypto_futures_l2_BTCUSDT_PERP_top10/year=2026/month=01/day={day:02d}/data.parquet"
        f_eth_l2 = STORE_BASE / f"crypto_futures_l2_ETHUSDT_PERP_top10/year=2026/month=01/day={day:02d}/data.parquet"

        # 1. Downsample L2 to 1-second top of book
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

        # 2. Index Trade Ticks for Queue Depletion
        ticks_b = pl.read_parquet(f_btc_tick).select(["timestamp", "price", "qty", "side"]).with_columns(ts_sec=(pl.col("timestamp") // 1000).cast(pl.Int64))
        ticks_e = pl.read_parquet(f_eth_tick).select(["timestamp", "price", "qty", "side"]).with_columns(ts_sec=(pl.col("timestamp") // 1000).cast(pl.Int64))

        btc_sells_map = dict(zip(ticks_b.filter(pl.col("side") == "S").group_by("ts_sec").agg(pl.sum("qty")).sort("ts_sec")["ts_sec"].to_list(), ticks_b.filter(pl.col("side") == "S").group_by("ts_sec").agg(pl.sum("qty")).sort("ts_sec")["qty"].to_list()))
        btc_buys_map = dict(zip(ticks_b.filter(pl.col("side") == "B").group_by("ts_sec").agg(pl.sum("qty")).sort("ts_sec")["ts_sec"].to_list(), ticks_b.filter(pl.col("side") == "B").group_by("ts_sec").agg(pl.sum("qty")).sort("ts_sec")["qty"].to_list()))
        eth_sells_map = dict(zip(ticks_e.filter(pl.col("side") == "S").group_by("ts_sec").agg(pl.sum("qty")).sort("ts_sec")["ts_sec"].to_list(), ticks_e.filter(pl.col("side") == "S").group_by("ts_sec").agg(pl.sum("qty")).sort("ts_sec")["qty"].to_list()))
        eth_buys_map = dict(zip(ticks_e.filter(pl.col("side") == "B").group_by("ts_sec").agg(pl.sum("qty")).sort("ts_sec")["ts_sec"].to_list(), ticks_e.filter(pl.col("side") == "B").group_by("ts_sec").agg(pl.sum("qty")).sort("ts_sec")["qty"].to_list()))

        # 3. Kalman Filter on Mid-Prices
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

        # 4. Day Simulation Loop
        in_pos = False
        trade_dir = 0
        trade_entry_sec = 0
        trade_pos_btc = 0.0
        trade_pos_eth = 0.0
        trade_entry_cost = 0.0

        pending = False
        p_sec = 0
        p_dir = 0
        p_b_p, p_b_q_ahead = 0.0, 0.0
        p_e_p, p_e_q_ahead = 0.0, 0.0
        p_b_qty, p_e_qty = 0.0, 0.0
        last_exit = -9999

        day_start_cash = cash
        day_volume = 0.0
        day_trades = 0
        day_wins = 0

        for t in range(3600, n_sec - 1):
            now = ts_sec[t]

            # Exit active trade
            if in_pos:
                held = now - trade_entry_sec
                cur_z = z_arr[t]
                ou_exit = (trade_dir == 1 and cur_z <= z_exit) or (trade_dir == -1 and cur_z >= -z_exit)
                stop = (trade_dir == 1 and cur_z >= z_stop) or (trade_dir == -1 and cur_z <= -z_stop)
                time_up = held >= max_hold_sec

                if ou_exit or stop or time_up:
                    exit_b = btc_bid_p[t] if trade_pos_btc > 0 else btc_ask_p[t]
                    exit_e = eth_bid_p[t] if trade_pos_eth > 0 else eth_ask_p[t]
                    exit_val_b = trade_pos_btc * exit_b
                    exit_val_e = trade_pos_eth * exit_e
                    trade_gross_pnl = exit_val_b + exit_val_e - trade_entry_cost

                    cash += trade_gross_pnl
                    exit_notional = abs(exit_val_b) + abs(exit_val_e)
                    day_volume += exit_notional
                    total_volume_farmed += exit_notional

                    trade_pnls.append(trade_gross_pnl)
                    total_trades_completed += 1
                    day_trades += 1
                    if trade_gross_pnl > 0:
                        day_wins += 1

                    in_pos = False
                    trade_dir = 0
                    last_exit = now
                    continue

            # Check pending limit orders in FIFO queue
            if pending:
                if (now - p_sec) >= max_queue_wait_sec:
                    pending = False
                    total_orders_timed_out += 1
                    continue

                if p_dir == 1:
                    p_b_q_ahead -= btc_sells_map.get(now, 0.0)
                    p_e_q_ahead -= eth_buys_map.get(now, 0.0)
                else:
                    p_b_q_ahead -= btc_buys_map.get(now, 0.0)
                    p_e_q_ahead -= eth_sells_map.get(now, 0.0)

                if p_b_q_ahead <= 0 and p_e_q_ahead <= 0:
                    total_orders_filled += 1
                    pending = False
                    in_pos = True
                    trade_entry_sec = now
                    trade_dir = p_dir

                    if p_dir == 1:
                        trade_pos_btc = p_b_qty
                        trade_pos_eth = -p_e_qty
                        trade_entry_cost = (p_b_qty * p_b_p) - (p_e_qty * p_e_p)
                    else:
                        trade_pos_btc = -p_b_qty
                        trade_pos_eth = p_e_qty
                        trade_entry_cost = (-p_b_qty * p_b_p) + (p_e_qty * p_e_p)

                    entry_notional = (p_b_qty * p_b_p) + (p_e_qty * p_e_p)
                    day_volume += entry_notional
                    total_volume_farmed += entry_notional
                    continue

            # New Entry Check
            cooldown_ok = (now - last_exit) >= 60
            if not in_pos and not pending and cooldown_ok:
                z = z_arr[t]
                if abs(z) >= z_entry:
                    s = 1 if z >= z_entry else -1
                    b = beta_arr[t]

                    target_b = btc_bid_p[t] if s == 1 else btc_ask_p[t]
                    target_e = eth_ask_p[t] if s == 1 else eth_bid_p[t]
                    q_b = btc_bid_q[t] if s == 1 else btc_ask_q[t]
                    q_e = eth_ask_q[t] if s == 1 else eth_bid_q[t]

                    btc_notional = clip_size * b
                    p_b_qty = btc_notional / target_b
                    p_e_qty = clip_size / target_e

                    pending = True
                    p_sec = now
                    p_dir = s
                    p_b_p, p_b_q_ahead = target_b, q_b
                    p_e_p, p_e_q_ahead = target_e, q_e

                    total_orders_submitted += 1

            # Mark to market equity
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

    # Full 31-day Summary
    final_equity = cash
    total_net_pnl = final_equity - initial_capital
    total_return_pct = total_net_pnl / initial_capital

    d_rets = np.diff(daily_equity_series) / daily_equity_series[:-1]
    sharpe_daily = (d_rets.mean() / (d_rets.std() + 1e-12)) * np.sqrt(365) if len(d_rets) > 1 else 0.0

    print("\n" + "=" * 75)
    print("      FULL 1-MONTH (31-DAY) TRUTHFUL TICK & L2 BACKTEST RESULTS")
    print("=" * 75)
    print(f"Evaluation Period:             2026-01-01 to 2026-01-31 (Full Month)")
    print(f"Initial Starting Capital:      ${initial_capital:,.2f}")
    print(f"Final Ending Capital:          ${final_equity:,.2f}")
    print(f"Total Net Profit:              ${total_net_pnl:+,.2f} ({total_return_pct:+.2%})")
    print(f"Annualized Sharpe Ratio:       {sharpe_daily:.2f}")
    print(f"Maximum MTM Drawdown:          {max_drawdown:.2%}")
    print("-" * 75)
    print(f"TOTAL VOLUME FARMED (31 DAYS): ${total_volume_farmed:,.2f} (${total_volume_farmed/1_000_000:,.2f}M)")
    print(f"Average Daily Volume:          ${total_volume_farmed/31.0:,.2f} / day (${(total_volume_farmed/31.0)/1000:,.1f}k/day)")
    print(f"Capital Turnover:              {total_volume_farmed/initial_capital:,.1f}x of account capital")
    print("-" * 75)
    print(f"Limit Orders Submitted:        {total_orders_submitted:,}")
    print(f"Limit Orders Filled:           {total_orders_filled:,} ({total_orders_filled/total_orders_submitted:.1%} Fill Rate)")
    print(f"Orders Timed Out / Missed:     {total_orders_timed_out:,} ({total_orders_timed_out/total_orders_submitted:.1%} Miss Rate)")
    print(f"Completed Round-Trip Trades:   {total_trades_completed:,} ({total_trades_completed/31.0:.1f} trades/day)")
    print(f"Trade Win Rate:                {sum(p > 0 for p in trade_pnls)/len(trade_pnls):.1%}")
    print(f"Average PnL per Trade:         ${np.mean(trade_pnls) if trade_pnls else 0.0:+,.4f}")
    print("=" * 75)

    # Plot 1-Month Tearsheet
    fig, axes = plt.subplots(3, 1, figsize=(12, 11))
    fig.patch.set_facecolor("#ffffff")
    day_idx = np.arange(len(dates_list))

    # 1. Cumulative Farmed Volume
    cum_vol_m = np.cumsum(daily_volume_series) / 1_000_000.0
    axes[0].plot(day_idx, cum_vol_m, color="#1f77b4", linewidth=2.0)
    axes[0].set_title(f"1. Cumulative Farmed Volume: ${total_volume_farmed/1_000_000:,.2f}M on $500 Account (Jan 2026)", fontsize=11, fontweight="bold")
    axes[0].set_ylabel("Volume ($ Millions)", fontsize=10)
    axes[0].grid(True, linestyle="--", alpha=0.5)

    # 2. Portfolio Equity Progression
    axes[1].plot(day_idx, daily_equity_series[1:], color="#2ca02c", linewidth=2.0, marker="o", markersize=4)
    axes[1].axhline(initial_capital, color="gray", linestyle="--", linewidth=0.8)
    axes[1].set_title(f"2. Portfolio Cash Equity Progression (Ending: ${final_equity:,.2f}, Return: {total_return_pct:+.2%})", fontsize=11, fontweight="bold")
    axes[1].set_ylabel("Equity ($)", fontsize=10)
    axes[1].grid(True, linestyle="--", alpha=0.5)

    # 3. Daily Farmed Volume Bars
    axes[2].bar(day_idx, [v / 1000.0 for v in daily_volume_series], color="#ff7f0e", alpha=0.75, edgecolor="black", linewidth=0.5)
    axes[2].set_title(f"3. Daily Farmed Volume (Avg: ${(total_volume_farmed/31.0)/1000:,.1f}k / day)", fontsize=11, fontweight="bold")
    axes[2].set_ylabel("Volume ($ Thousands)", fontsize=10)
    axes[2].grid(True, linestyle="--", alpha=0.5, axis="y")

    step = max(1, len(dates_list) // 8)
    for ax in axes:
        ax.set_xticks(day_idx[::step])
        ax.set_xticklabels([dates_list[i] for i in day_idx[::step]], rotation=25, ha="right")

    plt.tight_layout()
    out_dir = ROOT / "docs/audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    fig_path = out_dir / "january_2026_full_month_tearsheet.png"
    plt.savefig(fig_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"\nSaved 1-Month Tearsheet Plot to: {fig_path}")

    out_file = ROOT / "run_log/btc_eth_pair_trading_scalp/january_2026_full_month_tick_results.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "period": "2026-01-01 to 2026-01-31 (31 Full Days)",
        "initial_capital": initial_capital,
        "final_capital": final_equity,
        "total_net_pnl": total_net_pnl,
        "total_return_pct": total_return_pct * 100.0,
        "sharpe_annualized": sharpe_daily,
        "max_drawdown_pct": max_drawdown * 100.0,
        "total_volume_farmed": total_volume_farmed,
        "avg_daily_volume": total_volume_farmed / 31.0,
        "capital_turnover": total_volume_farmed / initial_capital,
        "orders_submitted": total_orders_submitted,
        "orders_filled": total_orders_filled,
        "fill_rate": total_orders_filled / total_orders_submitted,
        "trades_completed": total_trades_completed,
        "daily_breakdown": daily_stats,
    }
    out_file.write_text(json.dumps(report, indent=2))
    print(f"Saved 1-Month JSON results to: {out_file}")
    return report

if __name__ == "__main__":
    run_1month_backtest(clip_size=250.0)
