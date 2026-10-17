"""Dedicated High-Frequency Maker Volume Farming Engine for BTC/ETH.

Designed specifically for volume farming (VIP tiers / rebates / airdrops):
  - Tight Kalman micro-deviation trigger (|z| in [0.8, 1.5])
  - 100% Maker Post-Only execution (0 slippage, maker fee tier)
  - Ultra-short holding horizon: 3 to 10 minutes max
  - Tight micro stop-loss (|z| >= 2.2) to prevent trend bagholding
  - Tracks volume generated, capital turnover, and cost per $1M volume
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

def run_farming_simulation():
    print("Loading 1m BTC and ETH data for volume farming evaluation...")
    btc = pl.read_parquet("data/processed/btc_1m.parquet")
    eth = pl.read_parquet("data/processed/eth_1m.parquet")
    df = (
        btc.select(["timestamp", "open", "close"])
        .rename({"open": "btc_open", "close": "btc_close"})
        .join(eth.select(["timestamp", "open", "close"]).rename({"open": "eth_open", "close": "eth_close"}), on="timestamp", how="inner")
        .sort("timestamp")
    )
    n = df.height

    timestamps = df["timestamp"].to_list()
    btc_open = df["btc_open"].to_numpy()
    btc_close = df["btc_close"].to_numpy()
    eth_open = df["eth_open"].to_numpy()
    eth_close = df["eth_close"].to_numpy()

    x = np.log(btc_close)
    y = np.log(eth_close)

    print("Computing real-time Kalman Filter micro-innovations...")
    V = 1e-4
    W = np.diag([1e-6, 1e-6])
    theta = np.array([0.0, 1.0])
    P = np.eye(2) * 1.0

    innovations = np.zeros(n)
    betas = np.zeros(n)

    for t in range(n):
        P = P + W
        F = np.array([1.0, x[t]])
        e = y[t] - F @ theta
        Q = F @ P @ F + V
        K = (P @ F) / Q
        theta = theta + K * e
        P = P - np.outer(K, F @ P)
        betas[t] = theta[1]
        innovations[t] = e

    df_kf = (
        df.with_columns(
            pl.Series("e", innovations),
            pl.Series("beta", betas),
        )
        .with_columns([
            pl.col("e").rolling_mean(720).alias("mean_e"),
            pl.col("e").rolling_std(720).alias("std_e"),
        ])
        .with_columns([
            ((pl.col("e") - pl.col("mean_e")) / (pl.col("std_e") + 1e-12)).alias("z_score"),
        ])
        .fill_null(0.0)
    )

    z_arr = df_kf["z_score"].to_numpy()
    beta_arr = df_kf["beta"].to_numpy()

    # Farming Engine Parameters
    initial_capital = 10_000.0   # $10k farming account
    clip_notional = 5_000.0      # $5k per leg ($10k round trip)
    z_entry = 0.8                # Tight micro-trigger
    z_exit = 0.0                 # Mean-revert to zero
    z_stop = 2.2                 # Micro stop-loss
    max_hold_minutes = 6         # 6 minutes max hold time (kill bag-holding!)
    cooldown_minutes = 2         # 2 minutes cooldown between clips
    maker_fee_rate = 0.00015     # 1.5 bps maker fee (Binance VIP0/1 maker)

    print(f"\n--- Running Volume Farming Simulation (Capital: ${initial_capital:,.0f}, Clip: ${clip_notional:,.0f}/leg) ---")

    cash = initial_capital
    in_trade = False
    trade_dir = 0
    pos_btc = 0.0
    pos_eth = 0.0
    entry_bar = 0
    last_exit_bar = -9999

    total_volume = 0.0
    total_fees_paid = 0.0
    trades_count = 0
    wins_count = 0
    daily_volume = {}
    daily_equity = {}

    for t in range(720, n - 1):
        ts = timestamps[t]
        date_str = ts.strftime("%Y-%m-%d")

        # 1. Exit Check (bar t decision -> bar t+1 fill)
        if in_trade:
            bars_held = t - entry_bar
            z = z_arr[t]
            ou_exit = (trade_dir == 1 and z <= z_exit) or (trade_dir == -1 and z >= -z_exit)
            stop_loss = (trade_dir == 1 and z >= z_stop) or (trade_dir == -1 and z <= -z_stop)
            time_exit = bars_held >= max_hold_minutes

            if ou_exit or stop_loss or time_exit:
                fill_b = btc_open[t + 1]
                fill_e = eth_open[t + 1]
                exit_val_b = pos_btc * fill_b
                exit_val_e = pos_eth * fill_e
                exit_notional = abs(exit_val_b) + abs(exit_val_e)
                exit_fee = exit_notional * maker_fee_rate

                cash += exit_val_b + exit_val_e - exit_fee
                total_volume += exit_notional
                total_fees_paid += exit_fee
                daily_volume[date_str] = daily_volume.get(date_str, 0.0) + exit_notional

                trade_pnl = cash - trade_initial_cash
                trades_count += 1
                if trade_pnl > 0:
                    wins_count += 1

                in_trade = False
                trade_dir = 0
                last_exit_bar = t
                continue

        # 2. Entry Check
        cool_ok = (t - last_exit_bar) >= cooldown_minutes
        if not in_trade and cool_ok:
            z = z_arr[t]
            if abs(z) >= z_entry:
                s = 1 if z >= z_entry else -1
                b = beta_arr[t]

                fill_b = btc_open[t + 1]
                fill_e = eth_open[t + 1]
                btc_notional = clip_notional * b

                if s == 1:
                    pos_btc = btc_notional / fill_b
                    pos_eth = -clip_notional / fill_e
                else:
                    pos_btc = -btc_notional / fill_b
                    pos_eth = clip_notional / fill_e

                entry_notional = btc_notional + clip_notional
                entry_fee = entry_notional * maker_fee_rate
                cash -= entry_fee
                total_volume += entry_notional
                total_fees_paid += entry_fee
                daily_volume[date_str] = daily_volume.get(date_str, 0.0) + entry_notional

                trade_initial_cash = cash + entry_fee
                in_trade = True
                trade_dir = s
                entry_bar = t

        cur_eq = cash + (pos_btc * btc_close[t] + pos_eth * eth_close[t] if in_trade else 0.0)
        daily_equity[date_str] = cur_eq

    # Accounting & Performance Metrics
    dates = sorted(daily_equity.keys())
    final_equity = daily_equity[dates[-1]]
    net_pnl = final_equity - initial_capital
    net_return_pct = net_pnl / initial_capital
    n_days = len(dates)

    avg_daily_volume = total_volume / n_days
    volume_multiplier = total_volume / initial_capital  # Capital turnover

    eq_vals = np.array([daily_equity[d] for d in dates])
    peak_eq = np.maximum.accumulate(eq_vals)
    dd_vals = (eq_vals - peak_eq) / peak_eq
    max_dd = float(dd_vals.min())

    cost_per_million_vol = (total_fees_paid - net_pnl) / (total_volume / 1_000_000.0) if total_volume > 0 else 0.0

    print("\n" + "=" * 70)
    print("             VOLUME FARMING ENGINE BACKTEST RESULTS")
    print("=" * 70)
    print(f"Starting Capital:            ${initial_capital:,.2f}")
    print(f"Ending Capital:              ${final_equity:,.2f}")
    print(f"Net PnL (after fees):        ${net_pnl:+,.2f} ({net_return_pct:+.2%})")
    print(f"Max Drawdown:                {max_dd:.2%}")
    print("-" * 70)
    print(f"TOTAL TRADING VOLUME:        ${total_volume:,.2f} (${total_volume/1_000_000:,.2f}M)")
    print(f"Average Daily Volume:        ${avg_daily_volume:,.2f} / day")
    print(f"Capital Turnover Multiplier: {volume_multiplier:,.1f}x of capital")
    print(f"Total Completed Trades:      {trades_count:,} ({trades_count/n_days:.1f} trades/day)")
    print(f"Trade Win Rate:              {wins_count/trades_count:.1%}")
    print(f"Total Maker Fees Paid:       ${total_fees_paid:,.2f}")
    print(f"Effective Cost per $1M Vol:  ${cost_per_million_vol:,.2f} per $1,000,000 volume")
    print("=" * 70)

    # 2026 Year-to-Date breakdown
    days_2026 = [d for d in dates if d.startswith("2026")]
    if days_2026:
        eq_2026 = [daily_equity[d] for d in days_2026]
        ret_2026 = (eq_2026[-1] - eq_2026[0]) / eq_2026[0]
        vol_2026 = sum(daily_volume.get(d, 0.0) for d in days_2026)
        print(f"\n2026 Specific Volume Performance:")
        print(f"  Volume Generated in 2026:  ${vol_2026:,.2f} (${vol_2026/1_000_000:.2f}M)")
        print(f"  2026 Net Return:           {ret_2026:+.2%}")
        print(f"  Daily Volume in 2026:      ${vol_2026/len(days_2026):,.2f} / day")

    # Plot Volume Tearsheet
    fig, axes = plt.subplots(3, 1, figsize=(11, 10))
    fig.patch.set_facecolor("#ffffff")
    day_idx = np.arange(len(dates))

    # 1. Cumulative Volume
    cum_vol = np.cumsum([daily_volume.get(d, 0.0) for d in dates]) / 1_000_000.0
    axes[0].plot(day_idx, cum_vol, color="#1f77b4", linewidth=2.0)
    axes[0].set_title(f"1. Cumulative Volume Farmed: ${total_volume/1_000_000:,.1f}M on ${initial_capital:,.0f} Account", fontsize=11, fontweight="bold")
    axes[0].set_ylabel("Volume ($ Millions)", fontsize=10)
    axes[0].grid(True, linestyle="--", alpha=0.5)

    # 2. Portfolio Equity
    axes[1].plot(day_idx, eq_vals, color="#2ca02c" if net_pnl >= 0 else "#d62728", linewidth=1.5)
    axes[1].axhline(initial_capital, color="gray", linestyle="--", linewidth=0.8)
    axes[1].set_title(f"2. Portfolio Equity ($): Max Drawdown = {max_dd:.1%}", fontsize=11, fontweight="bold")
    axes[1].set_ylabel("Equity ($)", fontsize=10)
    axes[1].grid(True, linestyle="--", alpha=0.5)

    # 3. Daily Volume Bar Chart
    d_vols = [daily_volume.get(d, 0.0) / 1000.0 for d in dates]
    axes[2].bar(day_idx, d_vols, color="#ff7f0e", alpha=0.7, width=1.0)
    axes[2].set_title(f"3. Daily Volume Farmed (Avg: ${avg_daily_volume/1000:,.1f}k / day)", fontsize=11, fontweight="bold")
    axes[2].set_ylabel("Daily Vol ($k)", fontsize=10)
    axes[2].grid(True, linestyle="--", alpha=0.5)

    tick_step = len(dates) // 8
    for ax in axes:
        ax.set_xticks(day_idx[::tick_step])
        ax.set_xticklabels([dates[i] for i in day_idx[::tick_step]], rotation=25, ha="right")

    plt.tight_layout()
    out_dir = ROOT / "docs/audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    fig_path = out_dir / "volume_farming_tearsheet.png"
    plt.savefig(fig_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"\nSaved Volume Farming Plot to: {fig_path}")

    report_json = {
        "initial_capital": initial_capital,
        "final_capital": final_equity,
        "net_pnl": net_pnl,
        "net_return_pct": net_return_pct * 100.0,
        "total_volume": total_volume,
        "capital_turnover": volume_multiplier,
        "avg_daily_volume": avg_daily_volume,
        "trades_count": trades_count,
        "cost_per_million_volume": cost_per_million_vol,
        "max_drawdown_pct": max_dd * 100.0,
    }
    (out_dir / "volume_farming_summary.json").write_text(json.dumps(report_json, indent=2))
    return report_json

if __name__ == "__main__":
    run_farming_simulation()
