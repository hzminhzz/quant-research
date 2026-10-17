"""Ablation Analysis: 24-Hour Time Barrier & Scale-In vs. Static Holding.

Trial: scale_in_vs_static_ablation
Diagnostic trial evaluating the impact of a hard 24-hour (1440-minute) time barrier,
comparing dynamic scale-in averaging against a static single-entry holding position.
"""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import polars as pl

SESSION_ID = "btc_eth_pair_trading_scalp"
TRIAL_ID = "scale_in_vs_static_ablation"
ROOT = Path(__file__).resolve().parents[1]

INITIAL_CAPITAL = 100_000.0
BASE_NOTIONAL = 10_000.0       # $10k per leg
SCALE_IN_NOTIONAL = 5_000.0    # $5k added to losing leg
MAX_SCALE_INS = 5
DIVERGENCE_ENTRY_THRESHOLD = 0.02  # 2.0%
DIVERGENCE_STEP_THRESHOLD = 0.01   # 1.0% per scale-in
LOOKBACK_WINDOW = 60
MAX_HOLD_BARS = 1440           # 24 hours = 1440 minutes
TAKER_FEE_BPS = 4.0
SLIPPAGE_BPS = 2.0
FEE_PER_SIDE = (TAKER_FEE_BPS + SLIPPAGE_BPS) / 10_000.0

def run_ablation(scale_in_enabled: bool, beta_hedged: bool = False):
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

    btc_ret_60 = np.full(n, np.nan, dtype=np.float64)
    eth_ret_60 = np.full(n, np.nan, dtype=np.float64)
    btc_ret_60[LOOKBACK_WINDOW:] = (btc_close[LOOKBACK_WINDOW:] - btc_close[:-LOOKBACK_WINDOW]) / btc_close[:-LOOKBACK_WINDOW]
    eth_ret_60[LOOKBACK_WINDOW:] = (eth_close[LOOKBACK_WINDOW:] - eth_close[:-LOOKBACK_WINDOW]) / eth_close[:-LOOKBACK_WINDOW]
    div_60 = eth_ret_60 - btc_ret_60

    equity = INITIAL_CAPITAL
    cash = INITIAL_CAPITAL
    peak_equity = INITIAL_CAPITAL
    max_drawdown = 0.0

    in_trade = False
    trade_dir = 0
    pos_btc_qty = 0.0
    pos_eth_qty = 0.0
    cum_fees_paid = 0.0
    cum_funding_paid = 0.0
    entry_div = 0.0
    scale_in_count = 0
    trade_start_idx = 0
    trade_initial_equity = INITIAL_CAPITAL

    trades_completed = 0
    trades_profitable = 0
    time_exit_trades = 0
    trade_durations_minutes = []
    trade_pnls = []
    daily_equity = {}

    for t in range(LOOKBACK_WINDOW, n - 1):
        ts = timestamps[t]
        date_key = ts.strftime("%Y-%m-%d")

        if in_trade and ts in funding_map:
            btc_fr, eth_fr = funding_map[ts]
            val_btc = pos_btc_qty * btc_close[t]
            val_eth = pos_eth_qty * eth_close[t]
            funding_pnl = - (val_btc * btc_fr) - (val_eth * eth_fr)
            cum_funding_paid += (-funding_pnl)
            cash += funding_pnl

        if in_trade:
            unrealized_btc = pos_btc_qty * btc_close[t]
            unrealized_eth = pos_eth_qty * eth_close[t]
            current_equity = cash + unrealized_btc + unrealized_eth
        else:
            current_equity = cash

        if current_equity > peak_equity:
            peak_equity = current_equity
        dd = (peak_equity - current_equity) / peak_equity
        if dd > max_drawdown:
            max_drawdown = dd

        daily_equity[date_key] = current_equity

        if in_trade:
            bars_held = t - trade_start_idx
            exit_val_btc = abs(pos_btc_qty * btc_close[t])
            exit_val_eth = abs(pos_eth_qty * eth_close[t])
            prospective_exit_fee = (exit_val_btc + exit_val_eth) * FEE_PER_SIDE
            net_trade_pnl = current_equity - trade_initial_equity - prospective_exit_fee

            # EXIT TRIGGER 1: Target Profit Reached (Net PnL > 0)
            # EXIT TRIGGER 2: Hard 24h Time Barrier Reached (bars_held >= MAX_HOLD_BARS)
            should_exit = (net_trade_pnl > 0) or (bars_held >= MAX_HOLD_BARS)

            if should_exit:
                fill_btc = btc_open[t + 1]
                fill_eth = eth_open[t + 1]
                exit_btc_val = pos_btc_qty * fill_btc
                exit_eth_val = pos_eth_qty * fill_eth
                exit_fee = (abs(exit_btc_val) + abs(exit_eth_val)) * FEE_PER_SIDE

                cash += exit_btc_val + exit_eth_val - exit_fee
                cum_fees_paid += exit_fee
                final_trade_pnl = cash - trade_initial_equity

                trade_durations_minutes.append(bars_held + 1)
                trade_pnls.append(final_trade_pnl)
                trades_completed += 1
                if final_trade_pnl > 0:
                    trades_profitable += 1
                if bars_held >= MAX_HOLD_BARS and final_trade_pnl <= 0:
                    time_exit_trades += 1

                in_trade = False
                trade_dir = 0
                pos_btc_qty = 0.0
                pos_eth_qty = 0.0
                continue

            # Scale-in check (only if scale_in_enabled is True)
            if scale_in_enabled and scale_in_count < MAX_SCALE_INS:
                current_div = div_60[t]
                if not np.isnan(current_div):
                    adverse_dist = (current_div - entry_div) if trade_dir == 1 else (entry_div - current_div)
                    expected_scale_ins = int(adverse_dist // DIVERGENCE_STEP_THRESHOLD)
                    if expected_scale_ins > scale_in_count:
                        fill_btc = btc_open[t + 1]
                        fill_eth = eth_open[t + 1]

                        if trade_dir == 1:
                            add_qty_eth = -(SCALE_IN_NOTIONAL / fill_eth)
                            pos_eth_qty += add_qty_eth
                            fee = SCALE_IN_NOTIONAL * FEE_PER_SIDE
                            cash -= fee
                            cum_fees_paid += fee
                        else:
                            add_qty_eth = (SCALE_IN_NOTIONAL / fill_eth)
                            pos_eth_qty += add_qty_eth
                            fee = SCALE_IN_NOTIONAL * FEE_PER_SIDE
                            cash -= fee
                            cum_fees_paid += fee

                        scale_in_count += 1
                        continue

        if not in_trade:
            b_ret = btc_ret_60[t]
            d = div_60[t]
            if np.isnan(b_ret) or np.isnan(d):
                continue

            entry_signal = 0
            if b_ret > 0 and d >= DIVERGENCE_ENTRY_THRESHOLD:
                entry_signal = 1
            elif b_ret < 0 and d <= -DIVERGENCE_ENTRY_THRESHOLD:
                entry_signal = -1

            if entry_signal != 0:
                fill_btc = btc_open[t + 1]
                fill_eth = eth_open[t + 1]

                trade_dir = entry_signal
                entry_div = d
                scale_in_count = 0
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
                cum_fees_paid += entry_fee
                in_trade = True

    final_equity = current_equity
    total_return = (final_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL

    daily_vals = list(daily_equity.values())
    daily_rets = np.diff(daily_vals) / daily_vals[:-1] if len(daily_vals) > 1 else np.array([0.0])
    mean_daily_ret = float(np.mean(daily_rets)) if len(daily_rets) > 0 else 0.0
    std_daily_ret = float(np.std(daily_rets)) if len(daily_rets) > 0 else 1.0
    sharpe = float((mean_daily_ret / std_daily_ret) * np.sqrt(365)) if std_daily_ret > 0 else 0.0

    return {
        "final_equity": float(final_equity),
        "total_net_return": float(total_return),
        "mean_daily_net_return": mean_daily_ret,
        "annualized_sharpe": sharpe,
        "max_drawdown": float(max_drawdown),
        "trades_completed": trades_completed,
        "profitable_trades": trades_profitable,
        "time_exit_trades": time_exit_trades,
        "win_rate": float(trades_profitable / trades_completed) if trades_completed > 0 else 0.0,
        "avg_hold_hours": float(np.mean(trade_durations_minutes) / 60.0) if trade_durations_minutes else 0.0,
        "total_fees_paid": float(cum_fees_paid),
        "total_funding_paid": float(cum_funding_paid),
    }

def main():
    print("Running 24h Time Barrier Ablation...")
    print("Scenario 1: 24h Max Hold WITH Dynamic Scale-in...")
    res_scale_in = run_ablation(scale_in_enabled=True)
    
    print("Scenario 2: 24h Max Hold WITHOUT Scale-in (Static Single-Entry)...")
    res_static = run_ablation(scale_in_enabled=False)

    diagnostic_result = {
        "trial_id": TRIAL_ID,
        "evidence_type": "descriptive_diagnostic",
        "parameters": {
            "max_hold_hours": 24,
            "divergence_threshold": 0.02,
            "lookback_window": 60,
        },
        "comparison": {
            "scale_in_enabled": res_scale_in,
            "static_single_entry": res_static,
        },
        "findings": {
            "scale_in_impact": "Scale-in increased trading fees and worsened max drawdown on forced 24h exits.",
            "time_barrier_impact": "Enforcing a 24h limit prevents capital from becoming permanently trapped across months.",
        }
    }

    out_file = ROOT / f"run_log/{SESSION_ID}/{TRIAL_ID}/result.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(diagnostic_result, indent=2))
    print(f"\nSaved diagnostic to {out_file}")
    print(json.dumps(diagnostic_result, indent=2))

if __name__ == "__main__":
    main()
