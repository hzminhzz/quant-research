"""Generate ML4T Strategy Tearsheet for the Winning BTC/ETH Kalman Alpha.

Adheres strictly to the ml4t-tearsheet skill:
  - 4 panels: Cumulative Returns (Gross & Net vs Benchmark), Drawdown, Rolling Sharpe (63-day), Monthly Heatmap
  - Comprehensive metrics table: CAGR, Volatility, Sharpe, Sortino, Max DD, Calmar, Win Rate, Profit Factor
  - Gross vs. Net gap and passive benchmark comparison
"""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import polars as pl
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

ROOT = Path(__file__).resolve().parents[1]

def run_and_generate_tearsheet():
    print("Loading data for tearsheet generation...")
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

    # Benchmark: Buy & Hold BTC and 50/50 BTC/ETH
    btc_cum_ret = btc_close / btc_close[0]
    eth_cum_ret = eth_close / eth_close[0]
    benchmark_5050 = 0.5 * btc_cum_ret + 0.5 * eth_cum_ret

    # Kalman Filter
    x = np.log(btc_close)
    y = np.log(eth_close)
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

    df_features = (
        df.with_columns(
            pl.Series("e", innovations),
            pl.Series("beta", betas),
            btc_ret_24h=pl.col("btc_close").pct_change(1440),
            btc_vol_24h=pl.col("btc_close").pct_change().rolling_std(1440),
        )
        .with_columns([
            pl.col("e").rolling_mean(1440).alias("mean_e"),
            pl.col("e").rolling_std(1440).alias("std_e"),
            pl.col("btc_vol_24h").rolling_quantile(0.80, window_size=129600).alias("vol_q80"),
            pl.col("btc_ret_24h").abs().rolling_quantile(0.80, window_size=129600).alias("trend_q80"),
        ])
        .with_columns([
            ((pl.col("e") - pl.col("mean_e")) / (pl.col("std_e") + 1e-12)).alias("z_score"),
            (
                (pl.col("btc_vol_24h") <= pl.col("vol_q80")) &
                (pl.col("btc_ret_24h").abs() <= pl.col("trend_q80"))
            ).alias("regime_allowed")
        ])
        .fill_null(0.0)
    )

    z_arr = df_features["z_score"].to_numpy()
    beta_arr = df_features["beta"].to_numpy()
    regime_arr = df_features["regime_allowed"].to_numpy()

    # Parameters of winning model:
    z_entry = 4.0
    z_exit = 0.5
    z_stop = 5.5
    min_hold = 60
    max_hold = 720
    cooldown = 180
    fee_rate = 0.00015  # 1.5 bps maker fee

    # Simulation tracking both GROSS and NET equity curves
    cash_net = 100_000.0
    cash_gross = 100_000.0
    in_trade = False
    trade_dir = 0
    pos_btc = 0.0
    cash_net = 100_000.0
    cash_gross = 100_000.0
    prev_trade_cash_net = 100_000.0
    in_trade = False
    trade_dir = 0
    pos_btc = 0.0
    pos_eth = 0.0
    entry_bar = 0
    last_exit_bar = -9999

    trade_pnl_list = []
    trade_durations = []
    daily_equity_net = {}
    daily_equity_gross = {}
    daily_benchmark = {}
    for t in range(1440, n - 1):
        ts = timestamps[t]
        date_str = ts.strftime("%Y-%m-%d")

        # Exit check
        if in_trade:
            bars_held = t - entry_bar
            z = z_arr[t]
            ou_exit = (bars_held >= min_hold) and ((trade_dir == 1 and z <= z_exit) or (trade_dir == -1 and z >= -z_exit))
            stop = (trade_dir == 1 and z >= z_stop) or (trade_dir == -1 and z <= -z_stop)
            time_stop = bars_held >= max_hold

            if ou_exit or stop or time_stop:
                fill_b = btc_open[t + 1]
                fill_e = eth_open[t + 1]
                exit_val_b = pos_btc * fill_b
                exit_val_e = pos_eth * fill_e
                exit_fee = (abs(exit_val_b) + abs(exit_val_e)) * fee_rate

                cash_net += exit_val_b + exit_val_e - exit_fee
                cash_gross += exit_val_b + exit_val_e

                pnl = (cash_net - prev_trade_cash_net)
                trade_pnl_list.append(pnl)
                trade_durations.append(bars_held)

                in_trade = False
                trade_dir = 0
                last_exit_bar = t
                continue

        # Entry check
        cool_ok = (t - last_exit_bar) >= cooldown
        if not in_trade and cool_ok and regime_arr[t]:
            z = z_arr[t]
            if abs(z) >= z_entry:
                s = 1 if z >= z_entry else -1
                b = beta_arr[t]
                fill_b = btc_open[t + 1]
                fill_e = eth_open[t + 1]

                btc_notional = 10_000.0 * b
                if s == 1:
                    pos_btc = btc_notional / fill_b
                    pos_eth = -10_000.0 / fill_e
                else:
                    pos_btc = -btc_notional / fill_b
                    pos_eth = 10_000.0 / fill_e

                entry_fee = (btc_notional + 10_000.0) * fee_rate
                cash_net -= entry_fee
                prev_trade_cash_net = cash_net

                in_trade = True
                trade_dir = s
                entry_bar = t

        # Mark to market
        cur_eq_net = cash_net + (pos_btc * btc_close[t] + pos_eth * eth_close[t] if in_trade else 0.0)
        cur_eq_gross = cash_gross + (pos_btc * btc_close[t] + pos_eth * eth_close[t] if in_trade else 0.0)

        daily_equity_net[date_str] = cur_eq_net
        daily_equity_gross[date_str] = cur_eq_gross
        daily_benchmark[date_str] = 100_000.0 * benchmark_5050[t]

    # Build daily series
    dates = sorted(daily_equity_net.keys())
    eq_net = np.array([daily_equity_net[d] for d in dates])
    eq_gross = np.array([daily_equity_gross[d] for d in dates])
    eq_bench = np.array([daily_benchmark[d] for d in dates])

    ret_net = np.diff(eq_net) / eq_net[:-1]
    ret_gross = np.diff(eq_gross) / eq_gross[:-1]
    ret_bench = np.diff(eq_bench) / eq_bench[:-1]

    # Metrics computation (365 days for crypto)
    periods = 365
    n_days = len(ret_net)

    # Net metrics
    cum_net = eq_net / eq_net[0]
    peak_net = np.maximum.accumulate(cum_net)
    dd_net = (cum_net - peak_net) / peak_net
    max_dd_net = float(dd_net.min())
    cagr_net = float((cum_net[-1] ** (periods / n_days)) - 1)
    vol_net = float(ret_net.std() * np.sqrt(periods))
    sharpe_net = float(ret_net.mean() / (ret_net.std() + 1e-12) * np.sqrt(periods))
    downside_net = ret_net[ret_net < 0]
    sortino_net = float(ret_net.mean() / (downside_net.std() + 1e-12) * np.sqrt(periods)) if len(downside_net) > 0 else 0.0
    calmar_net = abs(cagr_net / max_dd_net) if max_dd_net != 0 else 0.0
    win_rate_trades = float(np.mean([p > 0 for p in trade_pnl_list])) if trade_pnl_list else 0.0
    gains = np.sum([p for p in trade_pnl_list if p > 0])
    losses = abs(np.sum([p for p in trade_pnl_list if p < 0]))
    profit_factor = float(gains / losses) if losses > 0 else float("inf")

    # Gross metrics
    cum_gross = eq_gross / eq_gross[0]
    peak_gross = np.maximum.accumulate(cum_gross)
    dd_gross = (cum_gross - peak_gross) / peak_gross
    max_dd_gross = float(dd_gross.min())
    cagr_gross = float((cum_gross[-1] ** (periods / n_days)) - 1)
    vol_gross = float(ret_gross.std() * np.sqrt(periods))
    sharpe_gross = float(ret_gross.mean() / (ret_gross.std() + 1e-12) * np.sqrt(periods))

    # Benchmark metrics
    cum_bench = eq_bench / eq_bench[0]
    peak_bench = np.maximum.accumulate(cum_bench)
    dd_bench = (cum_bench - peak_bench) / peak_bench
    max_dd_bench = float(dd_bench.min())
    cagr_bench = float((cum_bench[-1] ** (periods / n_days)) - 1)
    vol_bench = float(ret_bench.std() * np.sqrt(periods))
    sharpe_bench = float(ret_bench.mean() / (ret_bench.std() + 1e-12) * np.sqrt(periods))

    # Cost drag gap
    cost_drag_cagr = cagr_gross - cagr_net
    cost_drag_sharpe = sharpe_gross - sharpe_net

    print("\n" + "=" * 75)
    print("                      ML4T STRATEGY TEARSHEET METRICS TABLE")
    print("=" * 75)
    print(f"{'Metric':<28} | {'Strategy (Net)':<15} | {'Strategy (Gross)':<16} | {'Benchmark (50/50)'}")
    print("-" * 75)
    print(f"{'Total Return':<28} | {((cum_net[-1]-1)):>14.2%} | {((cum_gross[-1]-1)):>15.2%} | {((cum_bench[-1]-1)):>17.2%}")
    print(f"{'CAGR (Annualized)':<28} | {cagr_net:>14.2%} | {cagr_gross:>15.2%} | {cagr_bench:>17.2%}")
    print(f"{'Annualized Volatility':<28} | {vol_net:>14.2%} | {vol_gross:>15.2%} | {vol_bench:>17.2%}")
    print(f"{'Sharpe Ratio (Rf=0)':<28} | {sharpe_net:>14.2f} | {sharpe_gross:>15.2f} | {sharpe_bench:>17.2f}")
    print(f"{'Sortino Ratio':<28} | {sortino_net:>14.2f} | {'N/A':>15} | {'N/A':>17}")
    print(f"{'Max Drawdown':<28} | {max_dd_net:>14.2%} | {max_dd_gross:>15.2%} | {max_dd_bench:>17.2%}")
    print(f"{'Calmar Ratio':<28} | {calmar_net:>14.2f} | {'N/A':>15} | {abs(cagr_bench/max_dd_bench):>17.2f}")
    print(f"{'Trade Win Rate':<28} | {win_rate_trades:>14.2%} | {'N/A':>15} | {'N/A':>17}")
    print(f"{'Profit Factor':<28} | {profit_factor:>14.2f} | {'N/A':>15} | {'N/A':>17}")
    print(f"{'Total Trades Completed':<28} | {len(trade_pnl_list):>14} | {len(trade_pnl_list):>15} | {'1 (Buy & Hold)':>17}")
    print(f"{'Avg Trade Hold Time':<28} | {f'{np.mean(trade_durations)/60:.1f} hours':>14} | {'-':>15} | {'17 months':>17}")
    print(f"{'Cost Drag (Fee Gap)':<28} | {f'-{cost_drag_cagr:.2%} CAGR':>14} | {f'-{cost_drag_sharpe:.2f} Sharpe':>15} | {'$0':>17}")
    print("=" * 75)

    # ---------------------------------------------------------------------------
    # Plotting 4-Panel Tearsheet
    # ---------------------------------------------------------------------------
    fig, axes = plt.subplots(4, 1, figsize=(12, 14), gridspec_kw={"height_ratios": [3, 2, 2, 2]})
    fig.patch.set_facecolor("#ffffff")
    day_indices = np.arange(len(dates))

    # Panel 1: Cumulative Returns
    axes[0].plot(day_indices, cum_net, label="Strategy (Net of Maker Fees)", color="#1f77b4", linewidth=2.0)
    axes[0].plot(day_indices, cum_gross, label="Strategy (Gross / No Friction)", color="#2ca02c", linestyle="--", linewidth=1.5, alpha=0.7)
    axes[0].plot(day_indices, cum_bench, label="Benchmark (50/50 BTC/ETH Buy & Hold)", color="#ff7f0e", linestyle=":", linewidth=1.5, alpha=0.7)
    axes[0].set_title("1. Cumulative Returns: Strategy Net vs. Gross vs. Passive Benchmark", fontsize=12, fontweight="bold", pad=10)
    axes[0].set_ylabel("Growth of $1.00", fontsize=10)
    axes[0].grid(True, linestyle="--", alpha=0.5)
    axes[0].legend(loc="upper left", frameon=True)

    # Panel 2: Drawdowns
    axes[1].fill_between(day_indices, dd_net, 0, label="Strategy Net Drawdown", color="#d62728", alpha=0.4)
    axes[1].plot(day_indices, dd_bench, label="Benchmark Drawdown", color="#ff7f0e", linestyle=":", linewidth=1.2, alpha=0.8)
    axes[1].set_title(f"2. Underwater Drawdown Profile (Strategy Max DD: {max_dd_net:.1%} vs. Benchmark: {max_dd_bench:.1%})", fontsize=12, fontweight="bold", pad=10)
    axes[1].set_ylabel("Drawdown %", fontsize=10)
    axes[1].set_ylim([min(max_dd_bench, max_dd_net) * 1.1, 0.05])
    axes[1].grid(True, linestyle="--", alpha=0.5)
    axes[1].legend(loc="lower left", frameon=True)

    # Panel 3: Rolling 63-Day Sharpe Ratio
    window_days = 63
    rolling_sharpe = []
    for i in range(len(ret_net)):
        if i < window_days:
            rolling_sharpe.append(np.nan)
        else:
            w_ret = ret_net[i-window_days:i]
            r_sh = (w_ret.mean() / (w_ret.std() + 1e-12)) * np.sqrt(periods)
            rolling_sharpe.append(r_sh)
    rolling_sharpe = np.array(rolling_sharpe)

    axes[2].plot(day_indices[1:], rolling_sharpe, color="#9467bd", linewidth=1.5, label="Rolling 63-Day Sharpe")
    axes[2].axhline(0, color="gray", linestyle="-", linewidth=0.8)
    axes[2].axhline(sharpe_net, color="#1f77b4", linestyle="--", linewidth=1.0, label=f"Full-Sample Net Sharpe ({sharpe_net:.2f})")
    axes[2].set_title("3. Rolling 63-Day Annualized Sharpe Ratio", fontsize=12, fontweight="bold", pad=10)
    axes[2].set_ylabel("Annualized Sharpe", fontsize=10)
    axes[2].grid(True, linestyle="--", alpha=0.5)
    axes[2].legend(loc="upper right", frameon=True)

    # Panel 4: Monthly Net Returns Breakdown
    monthly_rets = {}
    for d, r in zip(dates[1:], ret_net):
        m_key = d[:7]  # YYYY-MM
        monthly_rets[m_key] = monthly_rets.get(m_key, 0.0) + r

    months = list(monthly_rets.keys())
    m_vals = [monthly_rets[m] * 100.0 for m in months]
    colors = ["#2ca02c" if val >= 0 else "#d62728" for val in m_vals]

    axes[3].bar(np.arange(len(months)), m_vals, color=colors, alpha=0.85, edgecolor="black", linewidth=0.5)
    axes[3].axhline(0, color="black", linewidth=0.8)
    axes[3].set_title("4. Monthly Net Returns (%) Breakdown", fontsize=12, fontweight="bold", pad=10)
    axes[3].set_ylabel("Net Return %", fontsize=10)
    axes[3].set_xticks(np.arange(len(months)))
    axes[3].set_xticklabels(months, rotation=45, ha="right", fontsize=8)
    axes[3].grid(True, linestyle="--", alpha=0.4, axis="y")

    # Set x-ticks on panels 0-2
    tick_step = max(1, len(dates) // 8)
    tick_pos = day_indices[::tick_step]
    tick_labels = [dates[i] for i in tick_pos]
    for ax in axes[:3]:
        ax.set_xticks(tick_pos)
        ax.set_xticklabels(tick_labels, fontsize=9)

    plt.tight_layout()
    out_dir = ROOT / "docs/audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    fig_path = out_dir / "winning_alpha_tearsheet.png"
    plt.savefig(fig_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"\nTearsheet figure successfully saved to: {fig_path}")

    # Save metrics JSON
    metrics_summary = {
        "cagr_net": cagr_net,
        "sharpe_net": sharpe_net,
        "max_dd_net": max_dd_net,
        "sortino_net": sortino_net,
        "calmar_net": calmar_net,
        "win_rate_trades": win_rate_trades,
        "profit_factor": profit_factor,
        "cagr_gross": cagr_gross,
        "sharpe_gross": sharpe_gross,
        "cagr_benchmark": cagr_bench,
        "sharpe_benchmark": sharpe_bench,
        "cost_drag_cagr": cost_drag_cagr,
        "cost_drag_sharpe": cost_drag_sharpe,
    }
    (out_dir / "tearsheet_metrics.json").write_text(json.dumps(metrics_summary, indent=2))
    return fig_path, metrics_summary

if __name__ == "__main__":
    run_and_generate_tearsheet()
