"""Sweep sizing and daily circuit breaker thresholds for prop firm compliance (2025-2026)."""

import json
from pathlib import Path
import numpy as np
import polars as pl

from ml4t.backtest import Strategy, Engine, DataFeed, BacktestConfig
from ml4t.backtest.config import ShareType, CommissionType, SlippageType

FEATURES_PATH = Path("data/features/crypto_tsmom_two_stage_funnel_features.parquet")
df = pl.read_parquet(FEATURES_PATH).sort(["symbol", "timestamp"])
df = df.with_columns([
    pl.col("close").ewm_mean(span=120).over("symbol").alias("ema_120")
])

df_holdout = df.filter(
    (pl.col("timestamp") >= pl.datetime(2025, 1, 1, time_zone="UTC")) &
    (pl.col("timestamp") <= pl.datetime(2026, 7, 31, 23, 59, 59, time_zone="UTC"))
)

active_syms = df_holdout.filter(pl.col("is_in_top10_universe") == 1.0)["symbol"].unique().to_list()
df_sub = df_holdout.filter(pl.col("symbol").is_in(active_syms))

prices_df = df_sub.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
signals_df = df_sub.select(["timestamp", "symbol", "roc_168", "ema_120", "vol_scaled_weight", "is_in_top10_universe"])

INITIAL_CASH = 100000.0


class ConfigurablePropFirmStrategy(Strategy):
    def __init__(self, risk_multiplier: float = 1.0, daily_limit_pct: float = 0.03):
        super().__init__()
        self.risk_mult = risk_multiplier
        self.daily_limit_pct = daily_limit_pct
        self.current_date = None
        self.day_start_equity = INITIAL_CASH
        self.circuit_breaker_active = False
        self.triggers = 0

    def on_data(self, timestamp, data, context, broker):
        bar_date = timestamp.strftime("%Y-%m-%d")
        equity = float(broker.equity())

        if self.current_date != bar_date:
            self.current_date = bar_date
            self.day_start_equity = equity
            self.circuit_breaker_active = False

        dd = (equity - self.day_start_equity) / self.day_start_equity

        if not self.circuit_breaker_active and dd <= -self.daily_limit_pct:
            self.circuit_breaker_active = True
            self.triggers += 1
            for sym in data.keys():
                pos = broker.get_position(sym)
                if pos is not None and pos.quantity != 0:
                    broker.order_target_percent(sym, 0.0)
            return

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
                base_w = float(np.clip(float(vol_w), 0.03, 0.20))
                target_w = base_w * self.risk_mult

                if close_p > ema120 and sig > 0.015:
                    if current_qty <= 0:
                        broker.order_target_percent(sym, target_w)
                elif close_p < ema120 and sig < -0.015:
                    if current_qty >= 0:
                        broker.order_target_percent(sym, -target_w)
                else:
                    if current_qty != 0:
                        broker.order_target_percent(sym, 0.0)


def sweep():
    grid = [
        (1.0, 0.04),
        (0.7, 0.03),
        (0.5, 0.025),
        (0.5, 0.03),
        (0.4, 0.025),
    ]

    cfg = BacktestConfig(
        initial_cash=INITIAL_CASH, allow_short_selling=True,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE, commission_rate=0.00018,
        slippage_type=SlippageType.PERCENTAGE, slippage_rate=0.0,
    )

    print("\n" + "=" * 95)
    print("=== PROP FIRM COMPLIANCE SWEEP (2025-2026 HOLDOUT: 577 DAYS) ===")
    print("=" * 95)
    print(f"{'Risk Mult':<10} | {'Breaker':<10} | {'Total Ret':<11} | {'Max DD':<9} | {'Worst Day':<10} | {'Breaches':<9} | {'Sharpe':<7} | {'Triggers':<8} | {'Status'}")
    print("-" * 95)

    for r_mult, breaker_pct in grid:
        feed = DataFeed(prices_df=prices_df, signals_df=signals_df)
        strat = ConfigurablePropFirmStrategy(risk_multiplier=r_mult, daily_limit_pct=breaker_pct)
        res = Engine(feed, strat, cfg).run()

        d_ret = np.array(res.to_daily_returns().drop_nulls().to_list())
        tot_ret = float(res.metrics.get("total_return", 0.0)) * 100
        max_dd = float(res.metrics.get("max_drawdown", 0.0)) * 100
        worst_d = float(np.min(d_ret)) * 100
        breaches = int(np.sum(d_ret <= -0.05))
        sr = float(d_ret.mean() / d_ret.std() * np.sqrt(365.25)) if d_ret.std() > 0 else 0.0

        compliant = (max_dd < 10.0) and (breaches == 0) and (worst_d > -5.0)
        status = "PASSED" if compliant else "FAILED"

        print(f"{r_mult:<10.2f} | {breaker_pct*100:<9.1f}% | {tot_ret:>9.2f}% | {max_dd:>7.2f}% | {worst_d:>8.2f}% | {breaches:>9} | {sr:>7.2f} | {strat.triggers:>8} | {status}")
    print("-" * 95)


if __name__ == "__main__":
    sweep()
