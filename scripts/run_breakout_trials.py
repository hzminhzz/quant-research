"""Execution and Ledger Recording Runner for Intraday Volatility Breakout Research.

Implements:
- Trial 1: Baseline Peter Rules (0.4 * ATR(5), no filter)
- Trial 2: Low-Volatility Regime Filter (ATR(5) >= 20th percentile)
- Trial 3: Breakout Multiplier Sensitivity Sweep [0.25, 0.30, 0.40, 0.50, 0.60]
"""

from __future__ import annotations
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import polars as pl
from ml4t.backtest import BacktestConfig, DataFeed, Engine, Strategy
from ml4t.backtest.config import CommissionType, ShareType, SlippageType
from src.features_breakout import build_breakout_feature_matrix
class BreakoutStrategy(Strategy):
    def __init__(
        self,
        risk_fraction: float = 0.0033,
        breakout_mult: float = 0.40,
        use_vol_filter: bool = False,
    ):
        super().__init__()
        self.risk_fraction = risk_fraction
        self.breakout_mult = breakout_mult
        self.use_vol_filter = use_vol_filter
        self.daily_counts = {}

    def on_data(self, timestamp: datetime, data: dict[str, dict], context: dict, broker):
        equity = broker.get_account_value()
        dt = timestamp.date()

        for symbol, bar in data.items():
            sigs = bar.get("signals", {})
            key = (symbol, dt)
            if key not in self.daily_counts:
                self.daily_counts[key] = {"long": 0, "short": 0}

            pos = broker.get_position(symbol)
            is_flat = pos is None or pos.quantity == 0

            # 1. Exit checks
            if not is_flat:
                # EOD Exit
                if sigs.get("is_session_end", False):
                    broker.close_position(symbol)
                    continue

                # Stop Loss check
                stop_price = sigs.get("stop_loss") or sigs.get("session_open")
                if stop_price is not None and pos is not None:
                    if pos.quantity > 0 and bar["low"] <= stop_price:
                        broker.close_position(symbol)
                        continue
                    elif pos.quantity < 0 and bar["high"] >= stop_price:
                        broker.close_position(symbol)
                        continue

            # 2. Entry checks
            if is_flat and not sigs.get("is_session_end", False):
                if self.use_vol_filter and not sigs.get("vol_filter_active", True):
                    continue

                prior_atr = sigs.get("prior_atr")
                session_open = sigs.get("session_open")
                if prior_atr is None or prior_atr <= 0 or session_open is None:
                    continue

                risk_dist = self.breakout_mult * prior_atr
                if risk_dist <= 0:
                    continue

                long_trig = session_open + risk_dist
                short_trig = session_open - risk_dist

                shares = (equity * self.risk_fraction) / risk_dist

                # Long breakout
                if bar["high"] >= long_trig and self.daily_counts[key]["long"] < 1:
                    broker.buy(symbol, shares=shares)
                    self.daily_counts[key]["long"] += 1

                # Short breakout
                elif bar["low"] <= short_trig and self.daily_counts[key]["short"] < 1:
                    broker.sell(symbol, shares=shares)
                    self.daily_counts[key]["short"] += 1


def run_single_simulation(
    df: pl.DataFrame,
    breakout_mult: float,
    use_vol_filter: bool,
    risk_fraction: float = 0.0033,
) -> Dict[str, Any]:
    prices = df.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
    signals = df.select([
        "timestamp", "symbol", "prior_atr", "session_open", "stop_loss",
        "vol_filter_active", "is_session_end",
    ])

    feed = DataFeed(prices_df=prices, signals_df=signals)
    config = BacktestConfig(
        initial_cash=100_000.0,
        allow_short_selling=True,
        allow_leverage=True,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=0.00005,  # 0.5 bps
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=0.00005,    # 0.5 bps
    )

    strat = BreakoutStrategy(
        risk_fraction=risk_fraction,
        breakout_mult=breakout_mult,
        use_vol_filter=use_vol_filter,
    )

    result = Engine(feed, strat, config).run()

    # Extract metrics safely
    wins = result.metrics.get("winning_trades", 0) or 0
    losses = result.metrics.get("losing_trades", 0) or 0
    total_trades = wins + losses
    win_rate = (wins / total_trades) if total_trades > 0 else 0.0
    tot_ret = float(result.metrics.get("total_return", 0.0) or 0.0)
    max_dd = float(result.metrics.get("max_drawdown", 0.0) or 0.0)
    pf = float(result.metrics.get("profit_factor", 0.0) or 0.0)
    sharpe = result.metrics.get("sharpe_ratio")
    sharpe_val = float(sharpe) if sharpe is not None else 0.0

    return {
        "total_return": tot_ret,
        "max_drawdown": max_dd,
        "profit_factor": pf,
        "win_rate": win_rate,
        "sharpe_ratio": sharpe_val,
        "total_trades": total_trades,
        "winning_trades": wins,
        "losing_trades": losses,
        "breakout_mult": breakout_mult,
        "use_vol_filter": use_vol_filter,
    }


def main():
    root = Path(".")
    log_dir = root / "run_log" / "intraday_volatility_breakout"
    log_dir.mkdir(parents=True, exist_ok=True)

    features_path = root / "data" / "features" / "breakout_features.parquet"
    if not features_path.exists():
        build_breakout_feature_matrix(output_path=features_path)

    full_df = pl.read_parquet(features_path)
    # Development window: 2024-01-02 to 2025-06-30
    dev_df = full_df.filter(
        (pl.col("timestamp") >= pl.datetime(2024, 1, 2, time_zone="UTC")) &
        (pl.col("timestamp") <= pl.datetime(2025, 6, 30, 23, 59, 59, time_zone="UTC"))
    )

    print(f"Running trials across {dev_df.height:,} development bars...")

    # Trial 1: Baseline Peter rules
    print("Executing Trial 1: Peter Baseline (mult=0.40, vol_filter=False)...")
    res1 = run_single_simulation(dev_df, breakout_mult=0.40, use_vol_filter=False)
    t1_dir = log_dir / "trial_1_peter_baseline"
    t1_dir.mkdir(parents=True, exist_ok=True)
    (t1_dir / "result.json").write_text(json.dumps(res1, indent=2))
    print(f"Trial 1: Return={res1['total_return']:.2%}, DD={res1['max_drawdown']:.2%}, PF={res1['profit_factor']:.3f}, WinRate={res1['win_rate']:.2%}, Trades={res1['total_trades']}")

    # Trial 2: Low-Volatility Regime Filter
    print("Executing Trial 2: Low-Vol Filter (mult=0.40, vol_filter=True)...")
    res2 = run_single_simulation(dev_df, breakout_mult=0.40, use_vol_filter=True)
    t2_dir = log_dir / "trial_2_low_vol_regime_filter"
    t2_dir.mkdir(parents=True, exist_ok=True)
    (t2_dir / "result.json").write_text(json.dumps(res2, indent=2))
    print(f"Trial 2: Return={res2['total_return']:.2%}, DD={res2['max_drawdown']:.2%}, PF={res2['profit_factor']:.3f}, WinRate={res2['win_rate']:.2%}, Trades={res2['total_trades']}")

    # Trial 3: Sensitivity Sweep
    print("Executing Trial 3: Multiplier Sensitivity Sweep...")
    sweep_results = {}
    for m in [0.25, 0.30, 0.40, 0.50, 0.60]:
        sweep_res = run_single_simulation(dev_df, breakout_mult=m, use_vol_filter=True)
        sweep_results[f"mult_{m:.2f}"] = sweep_res
        print(f"  Multiplier {m:.2f}: Return={sweep_res['total_return']:.2%}, DD={sweep_res['max_drawdown']:.2%}, PF={sweep_res['profit_factor']:.3f}, Trades={sweep_res['total_trades']}")

    t3_dir = log_dir / "trial_3_multiplier_sensitivity"
    t3_dir.mkdir(parents=True, exist_ok=True)
    (t3_dir / "result.json").write_text(json.dumps(sweep_results, indent=2))

    print("All trials completed successfully.")


if __name__ == "__main__":
    main()
