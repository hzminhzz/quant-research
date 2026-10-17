"""Compare Buy & Hold vs Iteration 2 & 3 in Development (2021-2024) and Out-Of-Sample (2025-2026)."""

from pathlib import Path
import numpy as np
import polars as pl
from scipy import stats

from ml4t.backtest import Strategy, Engine, DataFeed, BacktestConfig
from ml4t.backtest.config import ShareType, CommissionType, SlippageType

df = pl.read_parquet("data/features/crypto_tsmom_features.parquet").sort(["symbol", "timestamp"])


class BnH(Strategy):
    def on_data(self, timestamp, data, context, broker):
        for sym in data:
            pos = broker.get_position(sym)
            if pos is None or pos.quantity == 0:
                broker.order_target_percent(sym, 0.33)


class Iter2VolTarget(Strategy):
    def on_data(self, timestamp, data, context, broker):
        for sym, bar in data.items():
            sig = bar["signals"].get("roc_168")
            vol_w = bar["signals"].get("vol_scaled_weight", 0.20)
            if sig is None or vol_w is None:
                continue
            pos = broker.get_position(sym)
            is_l = pos is not None and pos.quantity > 0
            if sig > 0 and not is_l:
                broker.order_target_percent(sym, float(vol_w))
            elif sig <= 0 and is_l:
                broker.order_target_percent(sym, 0.0)


class Iter3RegimeMaker(Strategy):
    def on_data(self, timestamp, data, context, broker):
        for sym, bar in data.items():
            sig = bar["signals"].get("roc_168")
            regime_w = bar["signals"].get("regime_scaled_weight", 0.20)
            if sig is None or regime_w is None:
                continue
            pos = broker.get_position(sym)
            is_l = pos is not None and pos.quantity > 0
            if sig > 0 and not is_l:
                broker.order_target_percent(sym, float(regime_w))
            elif sig <= 0 and is_l:
                broker.order_target_percent(sym, 0.0)


def evaluate_period(start_str, end_str, label):
    sub = df.filter(
        (pl.col("timestamp") >= pl.datetime(int(start_str[:4]), int(start_str[5:7]), int(start_str[8:10]), time_zone="UTC")) &
        (pl.col("timestamp") <= pl.datetime(int(end_str[:4]), int(end_str[5:7]), int(end_str[8:10]), 23, 59, 59, time_zone="UTC"))
    )
    prices_df = sub.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
    signals_df = sub.select(["timestamp", "symbol", "roc_168", "vol_scaled_weight", "regime_scaled_weight"])
    
    # Factor Rank IC in this period
    labels = (
        sub.select(["timestamp", "symbol", "roc_168", "fwd_ret_72h"])
        .drop_nulls()
    )
    r_ic, p_ic = stats.spearmanr(labels["roc_168"].to_numpy(), labels["fwd_ret_72h"].to_numpy())

    # 1. Buy and hold
    feed1 = DataFeed(prices_df=prices_df, signals_df=signals_df)
    cfg1 = BacktestConfig(initial_cash=10000.0, share_type=ShareType.FRACTIONAL)
    res_bnh = Engine(feed1, BnH(), cfg1).run()
    d_bnh = res_bnh.to_daily_returns()
    sr_bnh = float(d_bnh.mean() / d_bnh.std() * np.sqrt(365.25)) if d_bnh.std() > 0 else 0.0

    # 2. Iteration 2 (Taker)
    feed2 = DataFeed(prices_df=prices_df, signals_df=signals_df)
    cfg2 = BacktestConfig(
        initial_cash=10000.0,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=0.00045,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=0.00015,
    )
    res_it2 = Engine(feed2, Iter2VolTarget(), cfg2).run()
    d_it2 = res_it2.to_daily_returns()
    sr_it2 = float(d_it2.mean() / d_it2.std() * np.sqrt(365.25)) if d_it2.std() > 0 else 0.0

    # 3. Iteration 3 (Maker)
    feed3 = DataFeed(prices_df=prices_df, signals_df=signals_df)
    cfg3 = BacktestConfig(
        initial_cash=10000.0,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=0.00018,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=0.0,
    )
    res_it3 = Engine(feed3, Iter3RegimeMaker(), cfg3).run()
    d_it3 = res_it3.to_daily_returns()
    sr_it3 = float(d_it3.mean() / d_it3.std() * np.sqrt(365.25)) if d_it3.std() > 0 else 0.0

    ret_bnh = res_bnh.metrics.get("total_return", 0.0)
    dd_bnh = res_bnh.metrics.get("max_drawdown", 0.0)

    ret_it2 = res_it2.metrics.get("total_return", 0.0)
    dd_it2 = res_it2.metrics.get("max_drawdown", 0.0)

    ret_it3 = res_it3.metrics.get("total_return", 0.0)
    dd_it3 = res_it3.metrics.get("max_drawdown", 0.0)

    print("\n" + "=" * 65)
    print(f"=== {label} ({start_str} to {end_str}) ===")
    print("=" * 65)
    print(f"  72h Factor Rank IC: {r_ic:+.4f} (p={p_ic:.3e})")
    print(f"  Buy & Hold:     Return: {ret_bnh*100:+7.2f}% | MaxDD: {dd_bnh*100:5.2f}% | Daily Sharpe: {sr_bnh:5.2f}")
    print(f"  Iter 2 (Taker): Return: {ret_it2*100:+7.2f}% | MaxDD: {dd_it2*100:5.2f}% | Daily Sharpe: {sr_it2:5.2f}")
    print(f"  Iter 3 (Maker): Return: {ret_it3*100:+7.2f}% | MaxDD: {dd_it3*100:5.2f}% | Daily Sharpe: {sr_it3:5.2f}")


if __name__ == "__main__":
    evaluate_period("2021-01-01", "2024-12-31", "Development Window (4 Years)")
    evaluate_period("2025-01-01", "2025-12-31", "Out-Of-Sample 2025 (Full Year)")
    evaluate_period("2026-01-01", "2026-07-31", "Out-Of-Sample 2026 (Jan - Jul 2026)")
    evaluate_period("2025-01-01", "2026-07-31", "Total Frozen Holdout (19 Months)")
