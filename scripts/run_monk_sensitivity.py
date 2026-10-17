"""Sensitivity Analysis: Lookback Horizons and Entry Thresholds (Trial 4: lookback_horizon_sensitivity).

Preregistered trial testing divergence measurement windows (15m, 30m, 60m, 240m)
and divergence thresholds (1.5%, 2.0%, 2.5%, 3.0%) under the 24h time barrier.
"""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import polars as pl

SESSION_ID = "btc_eth_pair_trading_scalp"
TRIAL_ID = "lookback_horizon_sensitivity"
ROOT = Path(__file__).resolve().parents[1]

INITIAL_CAPITAL = 100_000.0
BASE_NOTIONAL = 10_000.0
MAX_HOLD_BARS = 1440
TAKER_FEE_BPS = 4.0
SLIPPAGE_BPS = 2.0
FEE_PER_SIDE = (TAKER_FEE_BPS + SLIPPAGE_BPS) / 10_000.0

def run_grid():
    btc_path = ROOT / "data/processed/btc_1m.parquet"
    eth_path = ROOT / "data/processed/eth_1m.parquet"
    btc_funding_path = ROOT / "data/processed/btc_funding.parquet"
    eth_funding_path = ROOT / "data/processed/eth_funding.parquet"

    df_btc = pl.read_parquet(btc_path).select(["timestamp", "open", "close"]).rename({"open": "btc_open", "close": "btc_close"})
    df_eth = pl.read_parquet(eth_path).select(["timestamp", "open", "close"]).rename({"open": "eth_open", "close": "eth_close"})
    df = df_btc.join(df_eth, on="timestamp", how="inner").sort("timestamp")
    n = df.height

    btc_f = pl.read_parquet(btc_funding_path).select(["timestamp", "funding_rate"]).rename({"funding_rate": "btc_fr"})
    eth_f = pl.read_parquet(eth_funding_path).select(["timestamp", "funding_rate"]).rename({"funding_rate": "eth_fr"})
    funding = btc_f.join(eth_f, on="timestamp", how="inner").sort("timestamp")
    funding_map = {row["timestamp"]: (row["btc_fr"], row["eth_fr"]) for row in funding.iter_rows(named=True)}

    timestamps = df["timestamp"].to_list()
    btc_open = df["btc_open"].to_numpy()
    btc_close = df["btc_close"].to_numpy()
    eth_open = df["eth_open"].to_numpy()
    eth_close = df["eth_close"].to_numpy()

    horizons = [15, 30, 60, 240]
    thresholds = [0.015, 0.020, 0.025, 0.030]

    grid_results = {}

    for w in horizons:
        # Precompute rolling returns
        btc_ret = np.full(n, np.nan, dtype=np.float64)
        eth_ret = np.full(n, np.nan, dtype=np.float64)
        btc_ret[w:] = (btc_close[w:] - btc_close[:-w]) / btc_close[:-w]
        eth_ret[w:] = (eth_close[w:] - eth_close[:-w]) / eth_close[:-w]
        div = eth_ret - btc_ret

        for thresh in thresholds:
            key = f"W_{w}m_Thresh_{int(thresh*1000)}bps"

            cash = INITIAL_CAPITAL
            in_trade = False
            trade_dir = 0
            pos_btc_qty = 0.0
            pos_eth_qty = 0.0
            trade_start_idx = 0
            trade_initial_equity = INITIAL_CAPITAL

            trades_completed = 0
            trades_profitable = 0
            total_fees = 0.0

            for t in range(w, n - 1):
                ts = timestamps[t]

                # Funding
                if in_trade and ts in funding_map:
                    btc_fr, eth_fr = funding_map[ts]
                    val_btc = pos_btc_qty * btc_close[t]
                    val_eth = pos_eth_qty * eth_close[t]
                    cash -= ((val_btc * btc_fr) + (val_eth * eth_fr))

                if in_trade:
                    current_equity = cash + (pos_btc_qty * btc_close[t]) + (pos_eth_qty * eth_close[t])
                    bars_held = t - trade_start_idx
                    exit_val_btc = abs(pos_btc_qty * btc_close[t])
                    exit_val_eth = abs(pos_eth_qty * eth_close[t])
                    prospective_exit_fee = (exit_val_btc + exit_val_eth) * FEE_PER_SIDE
                    net_trade_pnl = current_equity - trade_initial_equity - prospective_exit_fee

                    should_exit = (net_trade_pnl > 0) or (bars_held >= MAX_HOLD_BARS)
                    if should_exit:
                        fill_btc = btc_open[t + 1]
                        fill_eth = eth_open[t + 1]
                        exit_fee = (abs(pos_btc_qty * fill_btc) + abs(pos_eth_qty * fill_eth)) * FEE_PER_SIDE
                        cash += (pos_btc_qty * fill_btc) + (pos_eth_qty * fill_eth) - exit_fee
                        total_fees += exit_fee
                        final_pnl = cash - trade_initial_equity

                        trades_completed += 1
                        if final_pnl > 0:
                            trades_profitable += 1

                        in_trade = False
                        trade_dir = 0
                        pos_btc_qty = 0.0
                        pos_eth_qty = 0.0
                        continue

                if not in_trade:
                    b_ret = btc_ret[t]
                    d = div[t]
                    if np.isnan(b_ret) or np.isnan(d):
                        continue

                    entry_signal = 0
                    if b_ret > 0 and d >= thresh:
                        entry_signal = 1
                    elif b_ret < 0 and d <= -thresh:
                        entry_signal = -1

                    if entry_signal != 0:
                        fill_btc = btc_open[t + 1]
                        fill_eth = eth_open[t + 1]
                        trade_dir = entry_signal
                        trade_start_idx = t + 1
                        trade_initial_equity = cash

                        if trade_dir == 1:
                            pos_btc_qty = BASE_NOTIONAL / fill_btc
                            pos_eth_qty = -(BASE_NOTIONAL / fill_eth)
                        else:
                            pos_btc_qty = -(BASE_NOTIONAL / fill_btc)
                            pos_eth_qty = BASE_NOTIONAL / fill_eth

                        entry_fee = (BASE_NOTIONAL * 2) * FEE_PER_SIDE
                        cash -= entry_fee
                        total_fees += entry_fee
                        in_trade = True

            final_equity = cash + (pos_btc_qty * btc_close[-1] + pos_eth_qty * eth_close[-1] if in_trade else 0.0)
            net_ret = (final_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL
            win_rate = (trades_profitable / trades_completed) if trades_completed > 0 else 0.0

            grid_results[key] = {
                "window_minutes": w,
                "threshold_pct": thresh * 100.0,
                "trades_completed": trades_completed,
                "win_rate": win_rate,
                "net_return": net_ret,
                "total_fees": total_fees,
            }
            print(f"[{key}] Trades: {trades_completed}, WinRate: {win_rate:.1%}, NetRet: {net_ret:.2%}, Fees: ${total_fees:,.1f}")

    return grid_results

def main():
    print("Running Sensitivity Analysis Grid...")
    grid = run_grid()

    result = {
        "trial_id": TRIAL_ID,
        "max_hold_hours": 24,
        "grid_results": grid,
        "best_configuration": max(grid.items(), key=lambda item: item[1]["net_return"])[0] if grid else None,
    }

    out_file = ROOT / f"run_log/{SESSION_ID}/{TRIAL_ID}/result.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(result, indent=2))
    print(f"\nSaved sensitivity results to {out_file}")

if __name__ == "__main__":
    main()
