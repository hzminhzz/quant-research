"""Sweep fast EMA trend gates on the dynamic crypto universe."""

import json
from pathlib import Path

import numpy as np
import polars as pl

from ml4t.backtest import BacktestConfig, DataFeed, Engine, Strategy
from ml4t.backtest.config import CommissionType, ShareType, SlippageType

FEATURES_PATH = Path("data/features/crypto_tsmom_two_stage_funnel_features.parquet")
OUTPUT_PATH = Path("run_log/iterations/iteration_a_fast_ema_sweep.json")
SPANS = (48, 72, 96, 120, 200)
INITIAL_CASH = 10000.0


class FastEmaLeaders(Strategy):
    def __init__(self):
        self.cash_observations = 0
        self.observations = 0

    def on_data(self, timestamp, data, context, broker):
        leaders = [sym for sym, bar in data.items() if bar["signals"].get("is_leader") == 1.0]
        n = len(leaders)
        weight = min(0.95 / n, 0.35) if n else 0.0
        leader_set = set(leaders)
        for sym in data:
            broker.order_target_percent(sym, weight if sym in leader_set else 0.0)
        self.observations += 1
        self.cash_observations += n == 0


def main():
    df = pl.read_parquet(FEATURES_PATH).sort(["symbol", "timestamp"])
    results = []
    for span in SPANS:
        ranked = (
            df.with_columns(pl.col("close").ewm_mean(span=span).over("symbol").alias("ema"))
            .with_columns(
                ((pl.col("close") > pl.col("ema")) & (pl.col("roc_168") > 0.015)
                 & (pl.col("is_in_top10_universe") == 1.0)).alias("passes"),
                (pl.col("roc_168") / (pl.col("realized_vol_168") + 0.05)).alias("risk_adj_mom"),
            )
            .with_columns(
                pl.when(pl.col("passes"))
                .then(pl.col("risk_adj_mom").rank(method="ordinal", descending=True).over("timestamp"))
                .otherwise(None).alias("leader_rank")
            )
            .with_columns((pl.col("leader_rank") <= 5).cast(pl.Float64).alias("is_leader"))
            .filter((pl.col("timestamp") >= pl.datetime(2021, 1, 1, time_zone="UTC"))
                    & (pl.col("timestamp") <= pl.datetime(2024, 12, 31, 23, 59, 59, time_zone="UTC")))
        )
        prices = ranked.select("timestamp", "symbol", "open", "high", "low", "close", "volume")
        signals = ranked.select("timestamp", "symbol", "is_leader")
        config = BacktestConfig(
            initial_cash=INITIAL_CASH,
            share_type=ShareType.FRACTIONAL,
            commission_type=CommissionType.PERCENTAGE,
            commission_rate=0.00018,
            slippage_type=SlippageType.PERCENTAGE,
            slippage_rate=0.0,
        )
        strategy = FastEmaLeaders()
        res = Engine(DataFeed(prices_df=prices, signals_df=signals), strategy, config).run()
        daily = res.to_daily_returns()
        daily_std = daily.std()
        metrics = res.metrics
        results.append({
            "span": span,
            "daily_sharpe": float(daily.mean() / daily_std * np.sqrt(365.25)) if daily_std > 0 else 0.0,
            "total_return_pct": float(metrics.get("total_return", 0.0)) * 100,
            "max_drawdown_pct": float(metrics.get("max_drawdown", 0.0)) * 100,
            "trades": int(metrics.get("num_trades", 0)),
            "total_costs": float(metrics.get("total_costs", 0.0)),
            "time_in_cash_pct": strategy.cash_observations / strategy.observations * 100 if strategy.observations else 0.0,
        })

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(results, indent=2) + "\n")
    print("span  daily_sharpe  total_return_pct  max_drawdown_pct  trades  total_costs  time_in_cash_pct")
    for row in results:
        print(f"{row['span']:>4}  {row['daily_sharpe']:>12.3f}  {row['total_return_pct']:>16.2f}  {row['max_drawdown_pct']:>16.2f}  {row['trades']:>6}  {row['total_costs']:>12.2f}  {row['time_in_cash_pct']:>16.2f}")


if __name__ == "__main__":
    main()
