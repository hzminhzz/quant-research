"""Multi-Year (2020-2026) Event-Driven Backtest & Edge Decay Analysis.

Adheres to:
  - ml4t-run-backtest: Decide on bar t, fill on bar t+1. Real cash & margin tracking.
  - ml4t-cost-model: Dual cost models (Maker 1.5 bps vs. Taker 4.0 bps + 2 bps slippage).
  - ml4t-polars-patterns: pl.scan_parquet lazy evaluation.
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

def run_multiyear_study():
    print("Scanning 2020-2026 Parquet stores lazily...")
    start_ts = pl.lit("2020-01-01T00:00:00Z").str.to_datetime(time_zone="UTC")
    end_ts = pl.lit("2026-06-01T00:00:00Z").str.to_datetime(time_zone="UTC")

    btc_store = STORE_BASE / "crypto_futures_minute_BTCUSDT_PERP"
    eth_store = STORE_BASE / "crypto_futures_minute_ETHUSDT_PERP"

    lf_btc = pl.scan_parquet(str(btc_store / "**/*.parquet")).filter((pl.col("timestamp") >= start_ts) & (pl.col("timestamp") < end_ts))
    lf_eth = pl.scan_parquet(str(eth_store / "**/*.parquet")).filter((pl.col("timestamp") >= start_ts) & (pl.col("timestamp") < end_ts))

    df_btc = lf_btc.select(["timestamp", "open", "close", "volume"]).rename({"open": "btc_open", "close": "btc_close", "volume": "btc_vol"})
    df_eth = lf_eth.select(["timestamp", "open", "close", "volume"]).rename({"open": "eth_open", "close": "eth_close", "volume": "eth_vol"})

    # Lazy join
    df_aligned = df_btc.join(df_eth, on="timestamp", how="inner").sort("timestamp").collect()
    n = df_aligned.height
    print(f"Loaded aligned dataset: {n:,} 1-minute bars spanning {df_aligned['timestamp'].min()} to {df_aligned['timestamp'].max()}")

    timestamps = df_aligned["timestamp"].to_list()
    btc_open = df_aligned["btc_open"].to_numpy()
    btc_close = df_aligned["btc_close"].to_numpy()
    eth_open = df_aligned["eth_open"].to_numpy()
    eth_close = df_aligned["eth_close"].to_numpy()

    # Log prices
    x = np.log(btc_close)
    y = np.log(eth_close)

    print("Executing recursive state-space Kalman Filter across 6.5 years...")
    V = 1e-4
    W = np.diag([1e-6, 1e-6])
    theta = np.array([0.0, 1.0])
    P = np.eye(2) * 1.0

    innovations = np.zeros(n, dtype=np.float64)
    betas = np.zeros(n, dtype=np.float64)

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

    print("Computing rolling regime gates and standardized z-scores...")
    df_features = (
        df_aligned.with_columns(
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

    # Winning strategy parameters
    z_entry = 4.0
    z_exit = 0.5
    z_stop = 5.5
    min_hold = 60
    max_hold = 720
    cooldown = 180
    base_notional = 10_000.0

    def run_sim(fee_rate, cost_model_name):
        print(f"\n--- Running Event-Driven Backtest: {cost_model_name} (fee={fee_rate*10000:.1f} bps) ---")
        cash = 100_000.0
        in_trade = False
        trade_dir = 0
        pos_btc = 0.0
        pos_eth = 0.0
        entry_bar = 0
        last_exit_bar = -9999
        trade_initial_cash = 100_000.0
        entry_fee_paid = 0.0

        daily_equity = {}
        trade_records = []

        for t in range(1440, n - 1):
            ts = timestamps[t]
            day_str = ts.strftime("%Y-%m-%d")

            # 1. Exit logic (bar t decision -> bar t+1 fill)
            if in_trade:
                bars_held = t - entry_bar
                z = z_arr[t]
                ou_exit = (bars_held >= min_hold) and ((trade_dir == 1 and z <= z_exit) or (trade_dir == -1 and z >= -z_exit))
                stop = (trade_dir == 1 and z >= z_stop) or (trade_dir == -1 and z <= -z_stop)
                time_stop = bars_held >= max_hold

                if ou_exit or stop or time_stop:
                    # FILL at t+1 open
                    fill_b = btc_open[t + 1]
                    fill_e = eth_open[t + 1]
                    val_b = pos_btc * fill_b
                    val_e = pos_eth * fill_e
                    fee = (abs(val_b) + abs(val_e)) * fee_rate

                    cash += val_b + val_e - fee
                    trade_pnl = cash - trade_initial_cash
                    trade_records.append({
                        "exit_ts": timestamps[t + 1].strftime("%Y-%m-%d %H:%M"),
                        "year": timestamps[t + 1].year,
                        "pnl": trade_pnl,
                        "held_bars": bars_held + 1,
                        "fee": fee + entry_fee_paid,
                    })

                    in_trade = False
                    trade_dir = 0
                    last_exit_bar = t
                    continue

            # 2. Entry logic (bar t decision -> bar t+1 fill)
            cool_ok = (t - last_exit_bar) >= cooldown
            if not in_trade and cool_ok and regime_arr[t]:
                z = z_arr[t]
                if abs(z) >= z_entry:
                    s = 1 if z >= z_entry else -1
                    b = beta_arr[t]

                    fill_b = btc_open[t + 1]
                    fill_e = eth_open[t + 1]
                    btc_notional = base_notional * b

                    if s == 1:
                        pos_btc = btc_notional / fill_b
                        pos_eth = -base_notional / fill_e
                    else:
                        pos_btc = -btc_notional / fill_b
                        pos_eth = base_notional / fill_e

                    fee = (btc_notional + base_notional) * fee_rate
                    cash -= fee
                    entry_fee_paid = fee
                    trade_initial_cash = cash + fee  # pre-trade benchmark

                    in_trade = True
                    trade_dir = s
                    entry_bar = t

            cur_eq = cash + (pos_btc * btc_close[t] + pos_eth * eth_close[t] if in_trade else 0.0)
            daily_equity[day_str] = cur_eq

        return daily_equity, trade_records

    # Run Maker Model (1.5 bps)
    daily_eq_maker, trades_maker = run_sim(0.00015, "Maker Execution Model (1.5 bps, 0 slippage)")
    # Run Taker Model (6.0 bps = 4 bps commission + 2 bps slippage)
    daily_eq_taker, trades_taker = run_sim(0.00060, "Taker Baseline Model (4.0 bps fee + 2.0 bps slippage)")

    # Analyze Year-by-Year Performance
    dates = sorted(daily_eq_maker.keys())
    eq_maker = np.array([daily_eq_maker[d] for d in dates])
    eq_taker = np.array([daily_eq_taker[d] for d in dates])

    daily_dates_dt = [pl.Series([d]).str.to_date().item() for d in dates]
    years = sorted(list(set(d[:4] for d in dates)))

    print("\n" + "=" * 80)
    print("            YEAR-BY-YEAR EDGE DECAY ANALYSIS (2020 - 2026)")
    print("=" * 80)
    print(f"{'Year':<6} | {'Trades':<8} | {'Maker Ret %':<12} | {'Maker Sharpe':<13} | {'Taker Ret %':<12} | {'Fee Gap'}")
    print("-" * 80)

    yearly_summary = {}
    for yr in years:
        yr_dates = [i for i, d in enumerate(dates) if d.startswith(yr)]
        if len(yr_dates) < 5:
            continue
        start_idx = yr_dates[0]
        end_idx = yr_dates[-1]

        # Maker metrics
        yr_eq_m = eq_maker[yr_dates]
        yr_ret_m = (yr_eq_m[-1] - yr_eq_m[0]) / yr_eq_m[0]
        d_rets_m = np.diff(yr_eq_m) / yr_eq_m[:-1]
        sh_m = (d_rets_m.mean() / (d_rets_m.std() + 1e-12)) * np.sqrt(365) if len(d_rets_m) > 1 else 0.0

        # Taker metrics
        yr_eq_t = eq_taker[yr_dates]
        yr_ret_t = (yr_eq_t[-1] - yr_eq_t[0]) / yr_eq_t[0]
        d_rets_t = np.diff(yr_eq_t) / yr_eq_t[:-1]
        sh_t = (d_rets_t.mean() / (d_rets_t.std() + 1e-12)) * np.sqrt(365) if len(d_rets_t) > 1 else 0.0

        yr_trades = [t for t in trades_maker if str(t["year"]) == yr]
        n_trades = len(yr_trades)
        fee_gap = yr_ret_m - yr_ret_t

        yearly_summary[yr] = {
            "trades": n_trades,
            "maker_return_pct": yr_ret_m * 100.0,
            "maker_sharpe": sh_m,
            "taker_return_pct": yr_ret_t * 100.0,
            "taker_sharpe": sh_t,
            "fee_gap_pct": fee_gap * 100.0,
        }

        print(f"{yr:<6} | {n_trades:>8} | {yr_ret_m:>11.2%} | {sh_m:>12.2f} | {yr_ret_t:>11.2%} | {fee_gap:>10.2%}")

    print("=" * 80)

    # Full Sample Metrics
    full_ret_m = (eq_maker[-1] - eq_maker[0]) / eq_maker[0]
    d_rets_all_m = np.diff(eq_maker) / eq_maker[:-1]
    full_sh_m = (d_rets_all_m.mean() / (d_rets_all_m.std() + 1e-12)) * np.sqrt(365)
    cum_m = eq_maker / eq_maker[0]
    peak_m = np.maximum.accumulate(cum_m)
    max_dd_m = ((cum_m - peak_m) / peak_m).min()

    print(f"\nFULL 6.5-YEAR OVERALL PERFORMANCE (Maker Model):")
    print(f"  Total Net Return:   {full_ret_m:+.2%}")
    print(f"  Annualized Sharpe:  {full_sh_m:.2f}")
    print(f"  Max Drawdown:       {max_dd_m:.2%}")
    print(f"  Total Trades:       {len(trades_maker):,}")

    # Plot Multi-Year Tearsheet
    fig, axes = plt.subplots(3, 1, figsize=(12, 12), gridspec_kw={"height_ratios": [3, 2, 2]})
    fig.patch.set_facecolor("#ffffff")
    day_indices = np.arange(len(dates))

    # 1. Cumulative Equity Curve
    axes[0].plot(day_indices, eq_maker / 1000.0, label="Maker Execution (1.5 bps)", color="#1f77b4", linewidth=2.0)
    axes[0].plot(day_indices, eq_taker / 1000.0, label="Taker Execution (6.0 bps friction)", color="#d62728", linestyle="--", linewidth=1.5)
    axes[0].set_title("1. Cumulative Portfolio Equity ($k): Maker vs. Taker (2020 - 2026)", fontsize=12, fontweight="bold", pad=10)
    axes[0].set_ylabel("Portfolio Value ($k)", fontsize=10)
    axes[0].grid(True, linestyle="--", alpha=0.5)
    axes[0].legend(loc="upper left")

    # 2. Drawdown
    dd_arr_m = (cum_m - peak_m) / peak_m
    axes[1].fill_between(day_indices, dd_arr_m, 0, color="#1f77b4", alpha=0.35, label="Maker Drawdown")
    axes[1].set_title(f"2. Multi-Year Drawdown Profile (Max Drawdown: {max_dd_m:.1%})", fontsize=12, fontweight="bold", pad=10)
    axes[1].set_ylabel("Drawdown %", fontsize=10)
    axes[1].grid(True, linestyle="--", alpha=0.5)
    axes[1].legend(loc="lower left")

    # 3. Rolling 180-Day Sharpe Ratio
    window_days = 180
    rolling_sh = []
    for i in range(len(d_rets_all_m)):
        if i < window_days:
            rolling_sh.append(np.nan)
        else:
            sub = d_rets_all_m[i-window_days:i]
            val = (sub.mean() / (sub.std() + 1e-12)) * np.sqrt(365)
            rolling_sh.append(val)
    rolling_sh = np.array(rolling_sh)

    axes[2].plot(day_indices[1:], rolling_sh, color="#2ca02c", linewidth=1.5, label="Rolling 180-Day Sharpe")
    axes[2].axhline(0, color="gray", linestyle="-", linewidth=0.8)
    axes[2].axhline(full_sh_m, color="#1f77b4", linestyle="--", linewidth=1.0, label=f"6.5-Year Mean Sharpe ({full_sh_m:.2f})")
    axes[2].set_title("3. Rolling 180-Day Annualized Sharpe Ratio (Edge Decay Diagnostic)", fontsize=12, fontweight="bold", pad=10)
    axes[2].set_ylabel("Annualized Sharpe", fontsize=10)
    axes[2].grid(True, linestyle="--", alpha=0.5)
    axes[2].legend(loc="upper right")

    tick_step = len(dates) // 10
    axes[2].set_xticks(day_indices[::tick_step])
    axes[2].set_xticklabels([dates[i] for i in day_indices[::tick_step]], rotation=30, ha="right")

    for ax in axes[:2]:
        ax.set_xticks(day_indices[::tick_step])
        ax.set_xticklabels([dates[i] for i in day_indices[::tick_step]])

    plt.tight_layout()
    out_dir = ROOT / "docs/audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    fig_path = out_dir / "multiyear_edge_decay_tearsheet.png"
    plt.savefig(fig_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"\nSaved Multi-Year Tearsheet to: {fig_path}")

    # Save summary JSON
    report_data = {
        "dataset_span": f"{dates[0]} to {dates[-1]}",
        "total_bars": n,
        "total_trades": len(trades_maker),
        "full_sample_maker": {
            "total_return_pct": full_ret_m * 100.0,
            "sharpe": full_sh_m,
            "max_drawdown_pct": max_dd_m * 100.0,
        },
        "yearly_breakdown": yearly_summary,
    }
    (out_dir / "multiyear_edge_decay.json").write_text(json.dumps(report_data, indent=2))
    print(f"Saved Multi-Year Edge Decay JSON to: {out_dir / 'multiyear_edge_decay.json'}")
    return report_data

if __name__ == "__main__":
    run_multiyear_study()
