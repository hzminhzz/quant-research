"""Compare 3-Coin vs 10-Coin in 2026 Out-Of-Sample."""

from pathlib import Path
import numpy as np
import polars as pl
from scipy import stats

from ml4t.backtest import Strategy, Engine, DataFeed, BacktestConfig
from ml4t.backtest.config import ShareType, CommissionType, SlippageType

df3 = pl.read_parquet("data/features/crypto_tsmom_features.parquet").filter(
    (pl.col("timestamp") >= pl.datetime(2026, 1, 1, time_zone="UTC")) &
    (pl.col("timestamp") <= pl.datetime(2026, 7, 31, 23, 59, 59, time_zone="UTC"))
).sort(["symbol", "timestamp"])

df10 = pl.read_parquet("data/features/crypto_tsmom_top10_features.parquet").filter(
    (pl.col("timestamp") >= pl.datetime(2026, 1, 1, time_zone="UTC")) &
    (pl.col("timestamp") <= pl.datetime(2026, 7, 31, 23, 59, 59, time_zone="UTC"))
).sort(["symbol", "timestamp"])

# 1. 2026 Rank IC
r_ic3, p_ic3 = stats.spearmanr(df3["roc_168"].to_numpy(), df3["fwd_ret_72h"].to_numpy())
r_ic10, p_ic10 = stats.spearmanr(df10["roc_168"].to_numpy(), df10["fwd_ret_72h"].to_numpy())


class BnH(Strategy):
    def on_data(self, timestamp, data, context, broker):
        n = len(data)
        for sym in data:
            pos = broker.get_position(sym)
            if pos is None or pos.quantity == 0:
                broker.order_target_percent(sym, 1.0 / n)


class StratVol(Strategy):
    def on_data(self, timestamp, data, context, broker):
        for sym, bar in data.items():
            sig = bar["signals"].get("roc_168")
            vol_w = bar["signals"].get("vol_scaled_weight")
            if sig is None or vol_w is None:
                continue
            pos = broker.get_position(sym)
            is_l = pos is not None and pos.quantity > 0
            if sig > 0 and not is_l:
                broker.order_target_percent(sym, float(vol_w))
            elif sig <= 0 and is_l:
                broker.order_target_percent(sym, 0.0)


def run_comparison():
    cfg = BacktestConfig(
        initial_cash=10000.0,
        share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=0.00018,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=0.0,
    )

    # 3-coin
    f3_bnh = DataFeed(prices_df=df3.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"]))
    r3_bnh = Engine(f3_bnh, BnH(), cfg).run()
    d3_bnh = r3_bnh.to_daily_returns()
    sr3_bnh = float(d3_bnh.mean() / d3_bnh.std() * np.sqrt(365.25)) if d3_bnh.std() > 0 else 0.0

    f3_strat = DataFeed(
        prices_df=df3.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"]),
        signals_df=df3.select(["timestamp", "symbol", "roc_168", "vol_scaled_weight"]),
    )
    r3_strat = Engine(f3_strat, StratVol(), cfg).run()
    d3_strat = r3_strat.to_daily_returns()
    sr3_strat = float(d3_strat.mean() / d3_strat.std() * np.sqrt(365.25)) if d3_strat.std() > 0 else 0.0

    # 10-coin
    f10_bnh = DataFeed(prices_df=df10.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"]))
    r10_bnh = Engine(f10_bnh, BnH(), cfg).run()
    d10_bnh = r10_bnh.to_daily_returns()
    sr10_bnh = float(d10_bnh.mean() / d10_bnh.std() * np.sqrt(365.25)) if d10_bnh.std() > 0 else 0.0

    f10_strat = DataFeed(
        prices_df=df10.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"]),
        signals_df=df10.select(["timestamp", "symbol", "roc_168", "vol_scaled_weight"]),
    )
    r10_strat = Engine(f10_strat, StratVol(), cfg).run()
    d10_strat = r10_strat.to_daily_returns()
    sr10_strat = float(d10_strat.mean() / d10_strat.std() * np.sqrt(365.25)) if d10_strat.std() > 0 else 0.0

    ret3_b = float(r3_bnh.metrics.get("total_return", 0.0))
    dd3_b = float(r3_bnh.metrics.get("max_drawdown", 0.0))
    ret3_s = float(r3_strat.metrics.get("total_return", 0.0))
    dd3_s = float(r3_strat.metrics.get("max_drawdown", 0.0))

    ret10_b = float(r10_bnh.metrics.get("total_return", 0.0))
    dd10_b = float(r10_bnh.metrics.get("max_drawdown", 0.0))
    ret10_s = float(r10_strat.metrics.get("total_return", 0.0))
    dd10_s = float(r10_strat.metrics.get("max_drawdown", 0.0))

    print("=================================================================")
    print("=== 2026 OUT-OF-SAMPLE COMPARISON: 3 COINS vs 10 COINS ===")
    print("=================================================================")
    print(f"  3-Coin 72h Rank IC:   {r_ic3:+.4f} (p={p_ic3:.2e})")
    print(f"  10-Coin 72h Rank IC:  {r_ic10:+.4f} (p={p_ic10:.2e})")
    print("\n--- 3-Coin Trio in 2026 (BTC, ETH, SOL) ---")
    print(f"  Buy & Hold Drop:      {ret3_b*100:+6.2f}% | MaxDD: {dd3_b*100:5.2f}% | Sharpe: {sr3_bnh:5.2f}")
    print(f"  TSMOM Strategy Loss:  {ret3_s*100:+6.2f}% | MaxDD: {dd3_s*100:5.2f}% | Sharpe: {sr3_strat:5.2f}")
    print(f"  Net Alpha over Market: {ret3_s*100 - ret3_b*100:+6.2f}%")

    print("\n--- 10-Coin Universe in 2026 (Top 10 Liquid Binance Futures) ---")
    print(f"  Buy & Hold Drop:      {ret10_b*100:+6.2f}% | MaxDD: {dd10_b*100:5.2f}% | Sharpe: {sr10_bnh:5.2f}")
    print(f"  TSMOM Strategy Loss:  {ret10_s*100:+6.2f}% | MaxDD: {dd10_s*100:5.2f}% | Sharpe: {sr10_strat:5.2f}")
    print(f"  Net Alpha over Market: {ret10_s*100 - ret10_b*100:+6.2f}%")


if __name__ == "__main__":
    run_comparison()
