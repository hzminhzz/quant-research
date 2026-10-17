"""Execution and Ledger Recording Runner for Regime-Gated Breakout Research.

Implements:
- Trial 1: Regime-Gated Breakout at 0.40 * ATR with Continuous Risk Scaling
- Trial 2: Regime-Gated Breakout at 0.50 * ATR with Continuous Risk Scaling
- Trial 3: Adaptive Multi-Tier Regime Execution Matrix
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import polars as pl
from ml4t.backtest import BacktestConfig, DataFeed, Engine, Strategy
from ml4t.backtest.config import CommissionType, ShareType, SlippageType


class RegimeStrategy(Strategy):
    def __init__(
        self,
        mode: str = "fixed_mult",  # "fixed_mult" or "adaptive_matrix"
        fixed_mult: float = 0.40,
        min_vol_rank: float = 0.25,
        base_risk: float = 0.0033,
    ):
        super().__init__()
        self.mode = mode
        self.fixed_mult = fixed_mult
        self.min_vol_rank = min_vol_rank
        self.base_risk = base_risk
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
                vol_rank = sigs.get("prior_vol_rank") or 0.0
                prior_atr = sigs.get("prior_atr")
                session_open = sigs.get("session_open")

                if prior_atr is None or prior_atr <= 0 or session_open is None:
                    continue

                # Determine multiplier and risk multiplier by regime
                if self.mode == "adaptive_matrix":
                    if vol_rank < 0.20:
                        continue  # Skip chop tier
                    elif vol_rank < 0.50:
                        # Moderate tier: wider barrier, reduced risk
                        mult = 0.55
                        risk_mult = 0.60
                    else:
                        # Expansion tier: tight barrier, full risk
                        mult = 0.40
                        risk_mult = 1.00
                else:
                    if vol_rank < self.min_vol_rank:
                        continue
                    mult = self.fixed_mult
                    # Continuous scaling: 0.5x at min_vol_rank up to 1.5x at max
                    risk_mult = min(1.5, max(0.5, 0.5 + vol_rank))

                risk_dist = mult * prior_atr
                if risk_dist <= 0:
                    continue

                risk_dollars = equity * self.base_risk * risk_mult
                shares = risk_dollars / risk_dist

                long_trig = session_open + risk_dist
                short_trig = session_open - risk_dist

                # Long breakout
                if bar["high"] >= long_trig and self.daily_counts[key]["long"] < 1:
                    broker.buy(symbol, shares=shares)
                    self.daily_counts[key]["long"] += 1

                # Short breakout
                elif bar["low"] <= short_trig and self.daily_counts[key]["short"] < 1:
                    broker.sell(symbol, shares=shares)
                    self.daily_counts[key]["short"] += 1


def run_regime_sim(
    df: pl.DataFrame,
    mode: str = "fixed_mult",
    fixed_mult: float = 0.40,
    min_vol_rank: float = 0.25,
) -> Dict[str, Any]:
    prices = df.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
    signals = df.select([
        "timestamp", "symbol", "prior_atr", "session_open", "stop_loss",
        "prior_vol_rank", "prior_er_10", "is_session_end",
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

    strat = RegimeStrategy(
        mode=mode,
        fixed_mult=fixed_mult,
        min_vol_rank=min_vol_rank,
    )

    result = Engine(feed, strat, config).run()

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
        "mode": mode,
        "fixed_mult": fixed_mult,
        "min_vol_rank": min_vol_rank,
    }


def main():
    root = Path(".")
    log_dir = root / "run_log" / "intraday_volatility_breakout_regime"
    log_dir.mkdir(parents=True, exist_ok=True)

    features_path = root / "data" / "features" / "breakout_features.parquet"
    full_df = pl.read_parquet(features_path)

    dev_df = full_df.filter(
        (pl.col("timestamp") >= pl.datetime(2024, 1, 2, time_zone="UTC")) &
        (pl.col("timestamp") <= pl.datetime(2025, 6, 30, 23, 59, 59, time_zone="UTC"))
    )

    print(f"Running regime trials across {dev_df.height:,} development bars...")

    # Trial 1: Regime Gated 0.40
    print("Executing Trial 1: Regime Gated 0.40 with Continuous Scaling...")
    res1 = run_regime_sim(dev_df, mode="fixed_mult", fixed_mult=0.40, min_vol_rank=0.25)
    t1_dir = log_dir / "trial_1_regime_gated_040"
    t1_dir.mkdir(parents=True, exist_ok=True)
    (t1_dir / "result.json").write_text(json.dumps(res1, indent=2))
    print(f"Trial 1: Return={res1['total_return']:.2%}, DD={res1['max_drawdown']:.2%}, PF={res1['profit_factor']:.3f}, WinRate={res1['win_rate']:.2%}, Trades={res1['total_trades']}")

    # Trial 2: Regime Gated 0.50
    print("Executing Trial 2: Regime Gated 0.50 with Continuous Scaling...")
    res2 = run_regime_sim(dev_df, mode="fixed_mult", fixed_mult=0.50, min_vol_rank=0.25)
    t2_dir = log_dir / "trial_2_regime_gated_050"
    t2_dir.mkdir(parents=True, exist_ok=True)
    (t2_dir / "result.json").write_text(json.dumps(res2, indent=2))
    print(f"Trial 2: Return={res2['total_return']:.2%}, DD={res2['max_drawdown']:.2%}, PF={res2['profit_factor']:.3f}, WinRate={res2['win_rate']:.2%}, Trades={res2['total_trades']}")

    # Trial 3: Adaptive Multi-Tier Matrix
    print("Executing Trial 3: Adaptive Multi-Tier Regime Matrix...")
    res3 = run_regime_sim(dev_df, mode="adaptive_matrix")
    t3_dir = log_dir / "trial_3_adaptive_tier_matrix"
    t3_dir.mkdir(parents=True, exist_ok=True)
    (t3_dir / "result.json").write_text(json.dumps(res3, indent=2))
    print(f"Trial 3: Return={res3['total_return']:.2%}, DD={res3['max_drawdown']:.2%}, PF={res3['profit_factor']:.3f}, WinRate={res3['win_rate']:.2%}, Trades={res3['total_trades']}")

    print("All regime trials completed successfully.")


if __name__ == "__main__":
    main()
