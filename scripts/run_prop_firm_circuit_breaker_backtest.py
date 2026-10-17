"""Backtest Full-Risk Strategy with Built-in 4% Floating Daily Drawdown Circuit Breaker (2025-2026)."""

import json
from pathlib import Path
import sys
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml4t.backtest import Strategy, Engine, DataFeed, BacktestConfig
from ml4t.backtest.config import ShareType, CommissionType, SlippageType

FEATURES_PATH = Path("data/features/crypto_tsmom_two_stage_funnel_features.parquet")
OUT_DIR = Path("run_log/prop_firm_evaluation")
OUT_DIR.mkdir(parents=True, exist_ok=True)

df = pl.read_parquet(FEATURES_PATH).sort(["symbol", "timestamp"])
df = df.with_columns([
    pl.col("close").ewm_mean(span=120).over("symbol").alias("ema_120")
])

# Filter strictly to 2025-01-01 to 2026-07-31
df_holdout = df.filter(
    (pl.col("timestamp") >= pl.datetime(2025, 1, 1, time_zone="UTC")) &
    (pl.col("timestamp") <= pl.datetime(2026, 7, 31, 23, 59, 59, time_zone="UTC"))
)

active_syms = df_holdout.filter(pl.col("is_in_top10_universe") == 1.0)["symbol"].unique().to_list()
df_sub = df_holdout.filter(pl.col("symbol").is_in(active_syms))

prices_df = df_sub.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
signals_df = df_sub.select(["timestamp", "symbol", "roc_168", "ema_120", "vol_scaled_weight", "is_in_top10_universe"])

INITIAL_CASH = 100000.0


class FullRiskUnconstrainedStrategy(Strategy):
    """Full-risk symmetric strategy without daily circuit breaker."""
    def on_data(self, timestamp, data, context, broker):
        for sym, bar in data.items():
            in_univ = bar["signals"].get("is_in_top10_universe", 0.0) == 1.0
            sig = bar["signals"].get("roc_168")
            ema120 = bar["signals"].get("ema_120")
            vol_w = bar["signals"].get("vol_scaled_weight", 0.10)
            close_p = bar.get("close", 0.0)

            if sig is None or ema120 is None or vol_w is None or close_p is None:
                continue

            pos = broker.get_position(sym)
            current_qty = pos.quantity if pos is not None else 0.0

            if not in_univ and current_qty != 0:
                broker.order_target_percent(sym, 0.0)
                continue

            if in_univ:
                target_w = float(np.clip(float(vol_w), 0.03, 0.20))
                # Long
                if close_p > ema120 and sig > 0.015:
                    if current_qty <= 0:
                        broker.order_target_percent(sym, target_w)
                # Short
                elif close_p < ema120 and sig < -0.015:
                    if current_qty >= 0:
                        broker.order_target_percent(sym, -target_w)
                # Cash
                else:
                    if current_qty != 0:
                        broker.order_target_percent(sym, 0.0)


class FullRiskCircuitBreakerStrategy(Strategy):
    """Full-risk strategy with built-in 4% floating daily drawdown flatten."""
    def __init__(self, daily_limit_pct: float = 0.04):
        super().__init__()
        self.daily_limit_pct = daily_limit_pct
        self.current_date = None
        self.day_start_equity = INITIAL_CASH
        self.circuit_breaker_active = False
        self.circuit_breaker_triggers = 0
        self.trigger_dates = []

    def on_data(self, timestamp, data, context, broker):
        # Determine calendar date (UTC midnight reset)
        bar_date = timestamp.strftime("%Y-%m-%d")

        # Get current mark-to-market portfolio equity
        portfolio_equity = float(broker.equity())

        # Day rollover check
        if self.current_date != bar_date:
            self.current_date = bar_date
            self.day_start_equity = portfolio_equity
            self.circuit_breaker_active = False

        # Compute intraday floating drawdown from midnight start equity
        floating_daily_dd = (portfolio_equity - self.day_start_equity) / self.day_start_equity

        # Circuit breaker trigger check
        if not self.circuit_breaker_active and floating_daily_dd <= -self.daily_limit_pct:
            self.circuit_breaker_active = True
            self.circuit_breaker_triggers += 1
            self.trigger_dates.append(str(timestamp))
            # Flatten all open positions immediately to cash
            for sym in data.keys():
                pos = broker.get_position(sym)
                if pos is not None and pos.quantity != 0:
                    broker.order_target_percent(sym, 0.0)
            return

        # If circuit breaker is triggered for today, stay in 100% cash
        if self.circuit_breaker_active:
            for sym in data.keys():
                pos = broker.get_position(sym)
                if pos is not None and pos.quantity != 0:
                    broker.order_target_percent(sym, 0.0)
            return

        for sym, bar in data.items():
            in_univ = bar["signals"].get("is_in_top10_universe", 0.0) == 1.0
            sig = bar["signals"].get("roc_168")
            ema120 = bar["signals"].get("ema_120")
            vol_w = bar["signals"].get("vol_scaled_weight", 0.10)
            close_p = bar.get("close", 0.0)

            if sig is None or ema120 is None or vol_w is None or close_p is None:
                continue

            pos = broker.get_position(sym)
            current_qty = pos.quantity if pos is not None else 0.0

            if not in_univ and current_qty != 0:
                broker.order_target_percent(sym, 0.0)
                continue

            if in_univ:
                target_w = float(np.clip(float(vol_w), 0.03, 0.20))
                # Long
                if close_p > ema120 and sig > 0.015:
                    if current_qty <= 0:
                        broker.order_target_percent(sym, target_w)
                # Short
                elif close_p < ema120 and sig < -0.015:
                    if current_qty >= 0:
                        broker.order_target_percent(sym, -target_w)
                # Cash
                else:
                    if current_qty != 0:
                        broker.order_target_percent(sym, 0.0)


def run_comparison():
    print("Running 2025-2026 Holdout Backtest...")
    cfg = BacktestConfig(
        initial_cash=INITIAL_CASH,
        allow_short_selling=True,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=0.00018,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=0.0,
    )

    feed1 = DataFeed(prices_df=prices_df, signals_df=signals_df)
    strat1 = FullRiskUnconstrainedStrategy()
    engine1 = Engine(feed1, strat1, cfg)
    res1 = engine1.run()

    feed2 = DataFeed(prices_df=prices_df, signals_df=signals_df)
    strat2 = FullRiskCircuitBreakerStrategy(daily_limit_pct=0.04)
    engine2 = Engine(feed2, strat2, cfg)
    res2 = engine2.run()

    # Daily returns analysis
    d_ret1 = np.array(res1.to_daily_returns().drop_nulls().to_list())
    d_ret2 = np.array(res2.to_daily_returns().drop_nulls().to_list())

    worst_day1 = float(np.min(d_ret1)) * 100
    worst_day2 = float(np.min(d_ret2)) * 100

    breach_day1 = int(np.sum(d_ret1 <= -0.05))
    breach_day2 = int(np.sum(d_ret2 <= -0.05))
    ret1 = float(res1.metrics.get("total_return", 0.0)) * 100
    ret2 = float(res2.metrics.get("total_return", 0.0)) * 100

    max_dd1 = float(res1.metrics.get("max_drawdown", 0.0)) * 100
    max_dd2 = float(res2.metrics.get("max_drawdown", 0.0)) * 100

    sr1 = float(d_ret1.mean() / d_ret1.std() * np.sqrt(365.25)) if d_ret1.std() > 0 else 0.0
    sr2 = float(d_ret2.mean() / d_ret2.std() * np.sqrt(365.25)) if d_ret2.std() > 0 else 0.0

    n_trades1 = len(res1.trades)
    n_trades2 = len(res2.trades)
    costs1 = float(res1.metrics.get("costs_total", 0.0))
    costs2 = float(res2.metrics.get("costs_total", 0.0))

    print("\n" + "=" * 75)
    print("=== 2025-2026 HOLDOUT: FULL RISK vs 4% DAILY CIRCUIT BREAKER ===")
    print("=" * 75)
    print(f"{'Metric':<35} | {'Full Risk (No Breaker)':<20} | {'Full Risk + 4% Breaker':<20}")
    print("-" * 75)
    print(f"{'Total Net Return (19m)':<35} | {ret1:>19.2f}% | {ret2:>19.2f}%")
    print(f"{'Max Cumulative Drawdown':<35} | {max_dd1:>19.2f}% | {max_dd2:>19.2f}%")
    print(f"{'Worst Single-Day Return':<35} | {worst_day1:>19.2f}% | {worst_day2:>19.2f}%")
    print(f"{'Daily 5% Limit Breaches':<35} | {breach_day1:>20} | {breach_day2:>20}")
    print(f"{'Daily Sharpe Ratio':<35} | {sr1:>20.2f} | {sr2:>20.2f}")
    print(f"{'Total Trades Executed':<35} | {n_trades1:>20} | {n_trades2:>20}")
    print(f"{'Total Friction Costs':<35} | ${costs1:>19,.2f} | ${costs2:>19,.2f}")
    print(f"{'4% Circuit Breaker Triggers':<35} | {'N/A':>20} | {strat2.circuit_breaker_triggers:>20}")
    print("-" * 75)

    prop_firm_status = "PASSED" if (max_dd2 < 10.0 and breach_day2 == 0) else "FAILED"
    print(f"\nProp Firm Compliance (5% Daily, 10% Max DD): {prop_firm_status}")
    if max_dd2 >= 10.0:
        print(f"-> FAILED on Max Drawdown limit ({max_dd2:.2f}% >= 10.00%)")
    if breach_day2 > 0:
        print(f"-> FAILED on Daily Drawdown limit ({breach_day2} days <= -5.00%)")

    # Save artifact
    with (OUT_DIR / "circuit_breaker_2025_2026_result.json").open("w") as f:
        json.dump({
            "full_risk_unconstrained": {
                "return_pct": ret1,
                "max_dd_pct": max_dd1,
                "worst_day_pct": worst_day1,
                "daily_breaches": breach_day1,
                "sharpe": sr1,
                "trades": n_trades1,
            },
            "full_risk_with_4pct_breaker": {
                "return_pct": ret2,
                "max_dd_pct": max_dd2,
                "worst_day_pct": worst_day2,
                "daily_breaches": breach_day2,
                "sharpe": sr2,
                "trades": n_trades2,
                "breaker_triggers": strat2.circuit_breaker_triggers,
                "prop_firm_passed": prop_firm_status == "PASSED",
            }
        }, f, indent=2)


if __name__ == "__main__":
    run_comparison()
