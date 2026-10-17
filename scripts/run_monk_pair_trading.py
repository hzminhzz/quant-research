"""Simulation of Monk's BTC/ETH Continuous Pair Trading Scalp (Trial 1: monk_continuous_equal_dollar).

Single preregistered trial according to config/research_sessions/btc_eth_pair_trading_scalp.yaml.
"""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import polars as pl

# 1. Configuration & Parameters
SESSION_ID = "btc_eth_pair_trading_scalp"
TRIAL_ID = "monk_continuous_equal_dollar"
ROOT = Path(__file__).resolve().parents[1]

INITIAL_CAPITAL = 100_000.0
BASE_LEG_NOTIONAL = 10_000.0  # $10k BTC, $10k ETH
SCALE_IN_NOTIONAL = 5_000.0   # $5k added to losing leg per step
MAX_SCALE_INS = 5
DIVERGENCE_ENTRY_THRESHOLD = 0.02  # 2.0%
DIVERGENCE_STEP_THRESHOLD = 0.01   # 1.0% per additional scale-in
LOOKBACK_WINDOW = 60  # 60 minutes
TAKER_FEE_BPS = 4.0
SLIPPAGE_BPS = 2.0
FEE_PER_SIDE = (TAKER_FEE_BPS + SLIPPAGE_BPS) / 10_000.0  # 6 bps = 0.0006

def run_simulation():
    # Load 1m price data
    btc_path = ROOT / "data/processed/btc_1m.parquet"
    eth_path = ROOT / "data/processed/eth_1m.parquet"
    btc_funding_path = ROOT / "data/processed/btc_funding.parquet"
    eth_funding_path = ROOT / "data/processed/eth_funding.parquet"

    print("Loading price and funding data...")
    df_btc = pl.read_parquet(btc_path).select(["timestamp", "open", "close"]).rename({"open": "btc_open", "close": "btc_close"})
    df_eth = pl.read_parquet(eth_path).select(["timestamp", "open", "close"]).rename({"open": "eth_open", "close": "eth_close"})
    
    # Merge on timestamp
    df = df_btc.join(df_eth, on="timestamp", how="inner").sort("timestamp")
    n = df.height
    print(f"Merged aligned dataset: {n} rows")

    # Load funding rates
    btc_f = pl.read_parquet(btc_funding_path).select(["timestamp", "funding_rate"]).rename({"funding_rate": "btc_fr"})
    eth_f = pl.read_parquet(eth_funding_path).select(["timestamp", "funding_rate"]).rename({"funding_rate": "eth_fr"})
    funding = btc_f.join(eth_f, on="timestamp", how="inner").sort("timestamp")
    
    # Map funding by timestamp
    funding_map = {row["timestamp"]: (row["btc_fr"], row["eth_fr"]) for row in funding.iter_rows(named=True)}

    # Convert columns to numpy arrays for speed
    timestamps = df["timestamp"].to_list()
    btc_open = df["btc_open"].to_numpy()
    btc_close = df["btc_close"].to_numpy()
    eth_open = df["eth_open"].to_numpy()
    eth_close = df["eth_close"].to_numpy()

    # Precompute rolling returns over LOOKBACK_WINDOW (60 bars)
    # R_t = (close_t - close_{t-W}) / close_{t-W}
    btc_ret_60 = np.full(n, np.nan, dtype=np.float64)
    eth_ret_60 = np.full(n, np.nan, dtype=np.float64)
    btc_ret_60[LOOKBACK_WINDOW:] = (btc_close[LOOKBACK_WINDOW:] - btc_close[:-LOOKBACK_WINDOW]) / btc_close[:-LOOKBACK_WINDOW]
    eth_ret_60[LOOKBACK_WINDOW:] = (eth_close[LOOKBACK_WINDOW:] - eth_close[:-LOOKBACK_WINDOW]) / eth_close[:-LOOKBACK_WINDOW]
    div_60 = eth_ret_60 - btc_ret_60

    print("Running event-driven simulation loop...")

    # Portfolio State
    equity = INITIAL_CAPITAL
    cash = INITIAL_CAPITAL
    peak_equity = INITIAL_CAPITAL
    max_drawdown = 0.0

    # Trade state
    in_trade = False
    trade_dir = 0  # +1: Long BTC / Short ETH (Pump), -1: Short BTC / Long ETH (Dump)
    pos_btc_qty = 0.0
    pos_eth_qty = 0.0
    cum_fees_paid = 0.0
    cum_funding_paid = 0.0
    entry_div = 0.0
    scale_in_count = 0
    trade_start_idx = 0

    # Metrics
    trades_completed = 0
    trades_profitable = 0
    trade_durations_minutes = []
    trade_pnls = []
    liquidation_triggered = False
    liquidation_idx = -1

    daily_equity = {}

    for t in range(LOOKBACK_WINDOW, n - 1):
        ts = timestamps[t]
        date_key = ts.strftime("%Y-%m-%d")

        # 1. Apply 8h funding settlement if timestamp matches
        if in_trade and ts in funding_map:
            btc_fr, eth_fr = funding_map[ts]
            # Funding cost = position_val * funding_rate
            # Long pays if fr > 0, short receives if fr > 0
            val_btc = pos_btc_qty * btc_close[t]
            val_eth = pos_eth_qty * eth_close[t]
            funding_pnl = - (val_btc * btc_fr) - (val_eth * eth_fr)
            cum_funding_paid += (-funding_pnl)
            cash += funding_pnl

        # 2. Mark-to-market current equity
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

        # Check margin liquidation (e.g. equity <= 10% of initial capital)
        if current_equity <= 0.10 * INITIAL_CAPITAL:
            liquidation_triggered = True
            liquidation_idx = t
            print(f"LIQUIDATION TRIGGERED at {ts}! Equity: ${current_equity:,.2f}")
            break

        # Track daily equity
        daily_equity[date_key] = current_equity

        # 3. If in trade: check exit and scale-in conditions based on bar t close
        if in_trade:
            # Current prospective exit value and fees
            exit_val_btc = abs(pos_btc_qty * btc_close[t])
            exit_val_eth = abs(pos_eth_qty * eth_close[t])
            prospective_exit_fee = (exit_val_btc + exit_val_eth) * FEE_PER_SIDE

            # Net trade PnL if closed now
            # Net PnL = (Unrealized Value + Cash change during trade) - prospective exit fee
            trade_unrealized_pnl = (pos_btc_qty * btc_close[t]) + (pos_eth_qty * eth_close[t])
            # Total cash spent on trade entries:
            net_trade_pnl = current_equity - trade_initial_equity - prospective_exit_fee

            # Exit condition: overall position turns green (Net PnL > 0)
            if net_trade_pnl > 0:
                # Close at next bar open (t+1)
                fill_btc = btc_open[t + 1]
                fill_eth = eth_open[t + 1]
                exit_btc_val = pos_btc_qty * fill_btc
                exit_eth_val = pos_eth_qty * fill_eth
                exit_fee = (abs(exit_btc_val) + abs(exit_eth_val)) * FEE_PER_SIDE
                
                cash += exit_btc_val + exit_eth_val - exit_fee
                cum_fees_paid += exit_fee
                final_trade_pnl = cash - trade_initial_equity

                trade_durations_minutes.append(t + 1 - trade_start_idx)
                trade_pnls.append(final_trade_pnl)
                trades_completed += 1
                if final_trade_pnl > 0:
                    trades_profitable += 1

                # Reset trade
                in_trade = False
                trade_dir = 0
                pos_btc_qty = 0.0
                pos_eth_qty = 0.0
                continue

            # Scale-in check: adverse spread movement
            # For Pump (Long BTC, Short ETH): adverse move is ETH continuing to out-pump (div_60 > entry_div)
            # For Dump (Short BTC, Long ETH): adverse move is ETH continuing to out-dump (div_60 < entry_div)
            current_div = div_60[t]
            if not np.isnan(current_div) and scale_in_count < MAX_SCALE_INS:
                adverse_dist = (current_div - entry_div) if trade_dir == 1 else (entry_div - current_div)
                expected_scale_ins = int(adverse_dist // DIVERGENCE_STEP_THRESHOLD)
                if expected_scale_ins > scale_in_count:
                    # Execute scale-in at next bar open (t+1)
                    fill_btc = btc_open[t + 1]
                    fill_eth = eth_open[t + 1]
                    
                    # Add to the underperforming/losing leg:
                    # In Pump (trade_dir == +1), losing leg is Short ETH
                    # In Dump (trade_dir == -1), losing leg is Long ETH
                    if trade_dir == 1:
                        # Add Short ETH
                        add_qty_eth = -(SCALE_IN_NOTIONAL / fill_eth)
                        pos_eth_qty += add_qty_eth
                        fee = SCALE_IN_NOTIONAL * FEE_PER_SIDE
                        cash -= fee
                        cum_fees_paid += fee
                    else:
                        # Add Long ETH
                        add_qty_eth = (SCALE_IN_NOTIONAL / fill_eth)
                        pos_eth_qty += add_qty_eth
                        fee = SCALE_IN_NOTIONAL * FEE_PER_SIDE
                        cash -= fee
                        cum_fees_paid += fee
                    
                    scale_in_count += 1
                    continue

        # 4. If NOT in trade: check entry condition on bar t
        if not in_trade:
            b_ret = btc_ret_60[t]
            d = div_60[t]
            if np.isnan(b_ret) or np.isnan(d):
                continue

            entry_signal = 0
            if b_ret > 0 and d >= DIVERGENCE_ENTRY_THRESHOLD:
                # Strategy 1: Pump -> Long BTC, Short ETH
                entry_signal = 1
            elif b_ret < 0 and d <= -DIVERGENCE_ENTRY_THRESHOLD:
                # Strategy 2: Dump -> Short BTC, Long ETH
                entry_signal = -1

            if entry_signal != 0:
                # Open trade at t+1 open
                fill_btc = btc_open[t + 1]
                fill_eth = eth_open[t + 1]

                trade_dir = entry_signal
                entry_div = d
                scale_in_count = 0
                trade_start_idx = t + 1
                trade_initial_equity = cash

                if trade_dir == 1:
                    pos_btc_qty = BASE_LEG_NOTIONAL / fill_btc
                    pos_eth_qty = -(BASE_LEG_NOTIONAL / fill_eth)
                else:
                    pos_btc_qty = -(BASE_LEG_NOTIONAL / fill_btc)
                    pos_eth_qty = BASE_LEG_NOTIONAL / fill_eth

                entry_fee = (BASE_LEG_NOTIONAL * 2) * FEE_PER_SIDE
                cash -= entry_fee
                cum_fees_paid += entry_fee
                in_trade = True

    # End of simulation accounting
    final_equity = current_equity
    total_return = (final_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL

    # Daily returns for Sharpe
    daily_vals = list(daily_equity.values())
    daily_rets = np.diff(daily_vals) / daily_vals[:-1] if len(daily_vals) > 1 else np.array([0.0])
    mean_daily_ret = float(np.mean(daily_rets)) if len(daily_rets) > 0 else 0.0
    std_daily_ret = float(np.std(daily_rets)) if len(daily_rets) > 0 else 1.0
    sharpe = float((mean_daily_ret / std_daily_ret) * np.sqrt(365)) if std_daily_ret > 0 else 0.0

    results = {
        "trial_id": TRIAL_ID,
        "initial_capital": INITIAL_CAPITAL,
        "final_equity": float(final_equity),
        "total_net_return": float(total_return),
        "mean_daily_net_return": mean_daily_ret,
        "annualized_sharpe": sharpe,
        "max_drawdown": float(max_drawdown),
        "liquidation_triggered": liquidation_triggered,
        "liquidation_timestamp": str(timestamps[liquidation_idx]) if liquidation_triggered else None,
        "total_trades_completed": trades_completed,
        "profitable_trades": trades_profitable,
        "win_rate": float(trades_profitable / trades_completed) if trades_completed > 0 else 0.0,
        "avg_trade_duration_hours": float(np.mean(trade_durations_minutes) / 60.0) if trade_durations_minutes else 0.0,
        "max_trade_duration_hours": float(np.max(trade_durations_minutes) / 60.0) if trade_durations_minutes else 0.0,
        "total_fees_paid": float(cum_fees_paid),
        "total_funding_paid": float(cum_funding_paid),
        "in_trade_at_end": in_trade,
    }

    out_file = ROOT / f"run_log/{SESSION_ID}/{TRIAL_ID}/result.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, indent=2))
    print(f"\nSaved trial result to {out_file}")
    print(json.dumps(results, indent=2))
    return out_file

if __name__ == "__main__":
    run_simulation()
