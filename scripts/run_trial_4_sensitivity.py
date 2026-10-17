"""Trial 4: Sensitivity Surface Mapping & Optimization Grid.

Trial ID: trial_4_parameter_sensitivity
Research Session: btc_eth_statarb_kalman_regime
"""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
SESSION_ID = "btc_eth_statarb_kalman_regime"
TRIAL_ID = "trial_4_parameter_sensitivity"

def run_grid():
    btc = pl.read_parquet("data/processed/btc_1m.parquet")
    eth = pl.read_parquet("data/processed/eth_1m.parquet")
    df = (
        btc.select(["timestamp", "open", "close"])
        .rename({"open": "btc_open", "close": "btc_close"})
        .join(eth.select(["timestamp", "open", "close"]).rename({"open": "eth_open", "close": "eth_close"}), on="timestamp", how="inner")
        .sort("timestamp")
    )
    n = df.height

    btc_open = df["btc_open"].to_numpy()
    btc_close = df["btc_close"].to_numpy()
    eth_open = df["eth_open"].to_numpy()
    eth_close = df["eth_close"].to_numpy()

    x = np.log(btc_close)
    y = np.log(eth_close)

    # Kalman Filter
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

    # Grid testing
    z_entries = [2.5, 3.0, 3.5, 4.0]
    min_holds = [15, 60, 120]
    cooldowns = [60, 180, 360]
    fee_rates = [0.00015, 0.00040]  # Maker (1.5 bps) vs Taker (4.0 bps)

    grid_results = {}
    best_config = None
    best_sharpe = -999.0

    print("Running parameter sensitivity grid search...")
    for fee in fee_rates:
        fee_name = "maker_1p5bps" if fee == 0.00015 else "taker_4bps"
        for z_entry in z_entries:
            for min_hold in min_holds:
                for cool in cooldowns:
                    config_key = f"{fee_name}_z{z_entry}_minHold{min_hold}_cool{cool}"

                    cash = 100_000.0
                    in_trade = False
                    trade_dir = 0
                    pos_btc = 0.0
                    pos_eth = 0.0
                    entry_bar = 0
                    last_exit_bar = -9999
                    trades = 0
                    wins = 0
                    total_fees = 0.0
                    daily_equity = {}

                    for t in range(1440, n - 1):
                        ts_day = t // 1440

                        # Exit
                        if in_trade:
                            bars_held = t - entry_bar
                            z = z_arr[t]
                            ou_exit = (bars_held >= min_hold) and ((trade_dir == 1 and z <= 0.5) or (trade_dir == -1 and z >= -0.5))
                            stop = (trade_dir == 1 and z >= 5.0) or (trade_dir == -1 and z <= -5.0)
                            time_stop = bars_held >= 720  # 12h max hold

                            if ou_exit or stop or time_stop:
                                fill_b = btc_open[t + 1]
                                fill_e = eth_open[t + 1]
                                exit_fee = (abs(pos_btc * fill_b) + abs(pos_eth * fill_e)) * fee
                                cash += (pos_btc * fill_b) + (pos_eth * fill_e) - exit_fee
                                total_fees += exit_fee

                                trades += 1
                                if cash > 100_000.0:
                                    wins += 1

                                in_trade = False
                                trade_dir = 0
                                last_exit_bar = t
                                continue

                        # Entry
                        cool_ok = (t - last_exit_bar) >= cool
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

                                entry_fee = (btc_notional + 10_000.0) * fee
                                cash -= entry_fee
                                total_fees += entry_fee

                                in_trade = True
                                trade_dir = s
                                entry_bar = t

                        current_eq = cash + (pos_btc * btc_close[t] + pos_eth * eth_close[t] if in_trade else 0.0)
                        daily_equity[ts_day] = current_eq

                    eq_vals = list(daily_equity.values())
                    daily_rets = np.diff(eq_vals) / eq_vals[:-1] if len(eq_vals) > 1 else np.array([0.0])
                    mean_r = float(np.mean(daily_rets)) if len(daily_rets) > 0 else 0.0
                    std_r = float(np.std(daily_rets)) if len(daily_rets) > 0 else 1.0
                    sharpe = float((mean_r / std_r) * np.sqrt(365)) if std_r > 0 else 0.0
                    tot_ret = (eq_vals[-1] - 100_000.0) / 100_000.0 if eq_vals else 0.0

                    grid_results[config_key] = {
                        "fee": fee,
                        "z_entry": z_entry,
                        "min_hold": min_hold,
                        "cooldown": cool,
                        "trades": trades,
                        "total_return_pct": tot_ret * 100.0,
                        "annualized_sharpe": sharpe,
                        "total_fees": total_fees,
                    }

                    if sharpe > best_sharpe:
                        best_sharpe = sharpe
                        best_config = config_key
                        print(f"--> NEW BEST [{config_key}]: Return: {tot_ret:.2%}, Sharpe: {sharpe:.2f}, Trades: {trades}, Fees: ${total_fees:,.1f}")

    print(f"\nOptimization complete. Best configuration: {best_config} with Sharpe: {best_sharpe:.2f}")

    out_file = ROOT / f"run_log/{SESSION_ID}/{TRIAL_ID}/result.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps({
        "trial_id": TRIAL_ID,
        "best_config": best_config,
        "best_sharpe": best_sharpe,
        "best_metrics": grid_results[best_config] if best_config else None,
        "sample_top_configs": sorted(grid_results.items(), key=lambda x: x[1]["annualized_sharpe"], reverse=True)[:5]
    }, indent=2))
    print(f"Saved artifact to {out_file}")
    return out_file

if __name__ == "__main__":
    run_grid()
