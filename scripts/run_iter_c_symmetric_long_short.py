"""Iteration C: Symmetric Long/Short Trend Following across Dynamic Crypto Universe."""

import json
from pathlib import Path
import numpy as np
import polars as pl

from ml4t.backtest import Strategy, Engine, DataFeed, BacktestConfig
from ml4t.backtest.config import ShareType, CommissionType, SlippageType

FEATURES_PATH = Path("data/features/crypto_tsmom_two_stage_funnel_features.parquet")
OUT_DIR = Path("run_log/iterations")
OUT_DIR.mkdir(parents=True, exist_ok=True)

DEV_START = pl.datetime(2021, 1, 1, 0, 0, 0, time_zone="UTC")
DEV_END = pl.datetime(2024, 12, 31, 23, 59, 59, time_zone="UTC")

INITIAL_CASH = 10000.0
MAKER_FEE = 0.00018  # 1.8 bps maker fee
MAKER_SLIP = 0.00000

df = pl.read_parquet(FEATURES_PATH).sort(["symbol", "timestamp"])

# Compute EMA 120 for optimal trend responsiveness
df = df.with_columns([
    pl.col("close").ewm_mean(span=120).over("symbol").alias("ema_120")
])


class LongOnlyTSMOM120(Strategy):
    """Benchmark: Long-Only TSMOM with EMA 120 trend gate."""
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
            is_l = pos is not None and pos.quantity > 0

            # Exit if not in universe or broken below EMA120
            if (not in_univ or close_p <= ema120 or sig <= 0.015) and is_l:
                broker.order_target_percent(sym, 0.0)
            # Long entry
            elif in_univ and close_p > ema120 and sig > 0.015 and not is_l:
                broker.order_target_percent(sym, min(float(vol_w), 0.20))


class SymmetricLongShortTSMOM120(Strategy):
    """Iteration C: Symmetric Long/Short TSMOM with EMA 120 trend filter."""
    def on_data(self, timestamp, data, context, broker):
        for sym, bar in data.items():
            in_univ = bar["signals"].get("is_in_top10_universe", 0.0) == 1.0
            sig = bar["signals"].get("roc_168")
            ema120 = bar["signals"].get("ema_120")
            vol_w = bar["signals"].get("vol_scaled_weight", 0.10)
            close_p = bar.get("close", 0.0)

            if sig is None or ema120 is None or vol_w is None:
                continue

            pos = broker.get_position(sym)
            current_qty = pos.quantity if pos is not None else 0.0

            # Rule 1: Exited from universe -> Close position
            if not in_univ and current_qty != 0:
                broker.order_target_percent(sym, 0.0)
                continue

            if in_univ:
                target_w = float(np.clip(float(vol_w), 0.03, 0.20))
                
                # Bullish regime: Close > EMA120 and positive weekly momentum -> Go Long
                if close_p > ema120 and sig > 0.015:
                    if current_qty <= 0:
                        broker.order_target_percent(sym, target_w)
                # Bearish regime: Close < EMA120 and negative weekly momentum -> Go Short
                elif close_p < ema120 and sig < -0.015:
                    if current_qty >= 0:
                        broker.order_target_percent(sym, -target_w)
                # Neutral dead-band: Exit to cash
                else:
                    if current_qty != 0:
                        broker.order_target_percent(sym, 0.0)


def run_iteration_c():
    print("Filtering development data (2021-2024)...")
    dev = df.filter((pl.col("timestamp") >= DEV_START) & (pl.col("timestamp") <= DEV_END))
    active_syms = dev.filter(pl.col("is_in_top10_universe") == 1.0)["symbol"].unique().to_list()
    dev_sub = dev.filter(pl.col("symbol").is_in(active_syms))

    prices_df = dev_sub.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
    signals_df = dev_sub.select(["timestamp", "symbol", "roc_168", "ema_120", "vol_scaled_weight", "is_in_top10_universe"])

    # 1. Run Long-Only Benchmark
    print("\nRunning Benchmark: Long-Only TSMOM with EMA 120...")
    f1 = DataFeed(prices_df=prices_df, signals_df=signals_df)
    cfg1 = BacktestConfig(
        initial_cash=INITIAL_CASH, share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE, commission_rate=MAKER_FEE,
        slippage_type=SlippageType.PERCENTAGE, slippage_rate=MAKER_SLIP,
    )
    r1 = Engine(f1, LongOnlyTSMOM120(), cfg1).run()
    d1 = r1.to_daily_returns()
    sr1 = float(d1.mean() / d1.std() * np.sqrt(365.25)) if d1.std() > 0 else 0.0
    ret1 = float(r1.metrics.get("total_return", 0.0))
    dd1 = float(r1.metrics.get("max_drawdown", 0.0))
    trades1 = len(r1.trades)
    costs1 = float(r1.metrics.get("total_costs", 0.0))

    # 2. Run Symmetric Long/Short Strategy
    print("Running Iteration C: Symmetric Long/Short TSMOM with EMA 120...")
    f2 = DataFeed(prices_df=prices_df, signals_df=signals_df)
    cfg2 = BacktestConfig(
        initial_cash=INITIAL_CASH, allow_short_selling=True,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE, commission_rate=MAKER_FEE,
        slippage_type=SlippageType.PERCENTAGE, slippage_rate=MAKER_SLIP,
    )
    r2 = Engine(f2, SymmetricLongShortTSMOM120(), cfg2).run()
    d2 = r2.to_daily_returns()
    sr2 = float(d2.mean() / d2.std() * np.sqrt(365.25)) if d2.std() > 0 else 0.0
    ret2 = float(r2.metrics.get("total_return", 0.0))
    dd2 = float(r2.metrics.get("max_drawdown", 0.0))
    trades2 = len(r2.trades)
    costs2 = float(r2.metrics.get("total_costs", 0.0))

    print("\n" + "=" * 65)
    print("=== ITERATION C RESULTS: LONG-ONLY vs SYMMETRIC LONG/SHORT ===")
    print("=" * 65)
    print(f"Long-Only Benchmark: Return: {ret1*100:+7.2f}% | MaxDD: {dd1*100:5.2f}% | Daily Sharpe: {sr1:5.3f} | Trades: {trades1} | Costs: ${costs1:,.2f}")
    print(f"Symmetric Long/Short: Return: {ret2*100:+7.2f}% | MaxDD: {dd2*100:5.2f}% | Daily Sharpe: {sr2:5.3f} | Trades: {trades2} | Costs: ${costs2:,.2f}")

    results = {
        "iteration": "C_symmetric_long_short",
        "period": "2021-01-01 to 2024-12-31",
        "long_only_benchmark": {
            "total_return_pct": round(ret1 * 100, 2),
            "max_drawdown_pct": round(dd1 * 100, 2),
            "daily_sharpe": round(sr1, 3),
            "trades": trades1,
            "costs": costs1,
        },
        "symmetric_long_short": {
            "total_return_pct": round(ret2 * 100, 2),
            "max_drawdown_pct": round(dd2 * 100, 2),
            "daily_sharpe": round(sr2, 3),
            "trades": trades2,
            "costs": costs2,
        }
    }
    with (OUT_DIR / "iteration_c_symmetric_long_short.json").open("w") as f:
        json.dump(results, f, indent=2)
    print(f"Saved Iteration C report to {OUT_DIR / 'iteration_c_symmetric_long_short.json'}")


if __name__ == "__main__":
    run_iteration_c()
