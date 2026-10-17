"""Simulation of Monk's BTC/ETH Continuous Pair Trading Scalp (Trial 2: monk_continuous_beta_hedged).

Beta-hedged variant using rolling OLS beta to maintain delta neutrality on entry.
Preregistered trial according to config/research_sessions/btc_eth_pair_trading_scalp.yaml.
"""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import polars as pl

SESSION_ID = "btc_eth_pair_trading_scalp"
TRIAL_ID = "monk_continuous_beta_hedged"
ROOT = Path(__file__).resolve().parents[1]

INITIAL_CAPITAL = 100_000.0
BASE_ETH_NOTIONAL = 10_000.0   # $10k ETH leg base
SCALE_IN_NOTIONAL = 5_000.0    # $5k added to losing leg per step
MAX_SCALE_INS = 5
DIVERGENCE_ENTRY_THRESHOLD = 0.02  # 2.0%
DIVERGENCE_STEP_THRESHOLD = 0.01   # 1.0% per additional scale-in
LOOKBACK_WINDOW = 60          # 60 minutes for divergence
BETA_WINDOW = 1440            # 1440 bars (24 hours) rolling for stable beta
TAKER_FEE_BPS = 4.0
SLIPPAGE_BPS = 2.0
FEE_PER_SIDE = (TAKER_FEE_BPS + SLIPPAGE_BPS) / 10_000.0  # 6 bps = 0.0006

def run_simulation():
    btc_path = ROOT / "data/processed/btc_1m.parquet"
    eth_path = ROOT / "data/processed/eth_1m.parquet"
    btc_funding_path = ROOT / "data/processed/btc_funding.parquet"
    eth_funding_path = ROOT / "data/processed/eth_funding.parquet"

    print("Loading price and funding data...")
    df_btc = pl.read_parquet(btc_path).select(["timestamp", "open", "close"]).rename({"open": "btc_open", "close": "btc_close"})
    df_eth = pl.read_parquet(eth_path).select(["timestamp", "open", "close"]).rename({"open": "eth_open", "close": "eth_close"})
    df = df_btc.join(df_eth, on="timestamp", how="inner").sort("timestamp")
    n = df.height
    print(f"Merged aligned dataset: {n} rows")

    btc_f = pl.read_parquet(btc_funding_path).select(["timestamp", "funding_rate"]).rename({"funding_rate": "btc_fr"})
    eth_f = pl.read_parquet(eth_funding_path).select(["timestamp", "funding_rate"]).rename({"funding_rate": "eth_fr"})
    funding = btc_f.join(eth_f, on="timestamp", how="inner").sort("timestamp")
    funding_map = {row["timestamp"]: (row["btc_fr"], row["eth_fr"]) for row in funding.iter_rows(named=True)}

    timestamps = df["timestamp"].to_list()
    btc_open = df["btc_open"].to_numpy()
    btc_close = df["btc_close"].to_numpy()
    eth_open = df["eth_open"].to_numpy()
    eth_close = df["eth_close"].to_numpy()

    # 1m returns for beta calculation
    btc_1m_ret = np.zeros(n, dtype=np.float64)
    eth_1m_ret = np.zeros(n, dtype=np.float64)
    btc_1m_ret[1:] = (btc_close[1:] - btc_close[:-1]) / btc_close[:-1]
    eth_1m_ret[1:] = (eth_close[1:] - eth_close[:-1]) / eth_close[:-1]

    # Precompute rolling returns over LOOKBACK_WINDOW (60 bars)
    btc_ret_60 = np.full(n, np.nan, dtype=np.float64)
    eth_ret_60 = np.full(n, np.nan, dtype=np.float64)
    btc_ret_60[LOOKBACK_WINDOW:] = (btc_close[LOOKBACK_WINDOW:] - btc_close[:-LOOKBACK_WINDOW]) / btc_close[:-LOOKBACK_WINDOW]
    eth_ret_60[LOOKBACK_WINDOW:] = (eth_close[LOOKBACK_WINDOW:] - eth_close[:-LOOKBACK_WINDOW]) / eth_close[:-LOOKBACK_WINDOW]
    div_60 = eth_ret_60 - btc_ret_60

    # Rolling beta: cov(r_eth, r_btc) / var(r_btc) over rolling 24h window
    print("Computing rolling beta series...")
    # Use polars rolling functions for fast calculation
    df_ret = pl.DataFrame({
        "rb": btc_1m_ret,
        "re": eth_1m_ret,
    }).with_columns([
        (pl.col("rb") * pl.col("re")).rolling_mean(window_size=BETA_WINDOW).alias("mean_prod"),
        pl.col("rb").rolling_mean(window_size=BETA_WINDOW).alias("mean_b"),
        pl.col("re").rolling_mean(window_size=BETA_WINDOW).alias("mean_e"),
        (pl.col("rb") ** 2).rolling_mean(window_size=BETA_WINDOW).alias("mean_b2"),
    ]).with_columns([
        (pl.col("mean_prod") - pl.col("mean_b") * pl.col("mean_e")).alias("cov"),
        (pl.col("mean_b2") - pl.col("mean_b") ** 2).alias("var_b"),
    ]).with_columns([
        (pl.col("cov") / (pl.col("var_b") + 1e-12)).clip(0.5, 2.5).fill_nan(1.2).fill_null(1.2).alias("beta")
    ])
    rolling_beta = df_ret["beta"].to_numpy()

    print("Running event-driven simulation loop (Beta-Hedged)...")

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

    trades_completed = 0
    trades_profitable = 0
    trade_durations_minutes = []
    trade_pnls = []
    liquidation_triggered = False
    liquidation_idx = -1

    daily_equity = {}
    start_bar = max(LOOKBACK_WINDOW, BETA_WINDOW)

    for t in range(start_bar, n - 1):
        ts = timestamps[t]
        date_key = ts.strftime("%Y-%m-%d")

        # 1. 8h funding settlement
        if in_trade and ts in funding_map:
            btc_fr, eth_fr = funding_map[ts]
            val_btc = pos_btc_qty * btc_close[t]
            val_eth = pos_eth_qty * eth_close[t]
            funding_pnl = - (val_btc * btc_fr) - (val_eth * eth_fr)
            cum_funding_paid += (-funding_pnl)
            cash += funding_pnl

        # 2. Mark-to-market
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

        if current_equity <= 0.10 * INITIAL_CAPITAL:
            liquidation_triggered = True
            liquidation_idx = t
            print(f"LIQUIDATION TRIGGERED at {ts}! Equity: ${current_equity:,.2f}")
            break

        daily_equity[date_key] = current_equity

        # 3. Check exit & scale-in if in trade
        if in_trade:
            exit_val_btc = abs(pos_btc_qty * btc_close[t])
            exit_val_eth = abs(pos_eth_qty * eth_close[t])
            prospective_exit_fee = (exit_val_btc + exit_val_eth) * FEE_PER_SIDE
            net_trade_pnl = current_equity - trade_initial_equity - prospective_exit_fee

            if net_trade_pnl > 0:
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

                in_trade = False
                trade_dir = 0
                pos_btc_qty = 0.0
                pos_eth_qty = 0.0
                continue

            current_div = div_60[t]
            if not np.isnan(current_div) and scale_in_count < MAX_SCALE_INS:
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

        # 4. Check entry if not in trade
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
                b_ratio = float(rolling_beta[t])

                trade_dir = entry_signal
                entry_div = d
                scale_in_count = 0
                trade_start_idx = t + 1
                trade_initial_equity = cash

                # Beta-hedged notional:
                # ETH notional = $10,000
                # BTC notional = beta * $10,000
                btc_notional = BASE_ETH_NOTIONAL * b_ratio
                if trade_dir == 1:
                    pos_btc_qty = btc_notional / fill_btc
                    pos_eth_qty = -(BASE_ETH_NOTIONAL / fill_eth)
                else:
                    pos_btc_qty = -(btc_notional / fill_btc)
                    pos_eth_qty = BASE_ETH_NOTIONAL / fill_eth

                entry_fee = (btc_notional + BASE_ETH_NOTIONAL) * FEE_PER_SIDE
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
