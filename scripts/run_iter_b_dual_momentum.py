"""Phase 3 diagnostics and maker backtest for dual-momentum leaders."""

import json
from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats
from ml4t.backtest import BacktestConfig, DataFeed, Engine, Strategy
from ml4t.backtest.config import CommissionType, ShareType, SlippageType

FEATURES_PATH = Path("data/features/crypto_tsmom_two_stage_funnel_features.parquet")
OUTPUT_PATH = Path("run_log/iterations/iteration_b_dual_momentum.json")
START = pl.datetime(2021, 1, 1, 0, 0, 0, time_zone="UTC")
END = pl.datetime(2024, 12, 31, 23, 59, 59, time_zone="UTC")
HORIZONS = {"1h": "fwd_ret_1h", "4h": "fwd_ret_4h", "24h": "fwd_ret_24h", "72h": "fwd_ret_72h"}


class TopFiveDualMomentum(Strategy):
    def on_data(self, timestamp, data, context, broker):
        desired = {
            sym for sym, bar in data.items()
            if bar["signals"].get("selected", 0.0) == 1.0
            and bar["signals"].get("trend_ok", 0.0) == 1.0
        }
        for sym in set(data) | desired:
            pos = broker.get_position(sym)
            is_long = pos is not None and pos.quantity > 0
            if sym in desired and not is_long:
                broker.order_target_percent(sym, 0.20)
            elif sym not in desired and is_long:
                broker.order_target_percent(sym, 0.0)


def diagnose(df, factor, ret_col):
    clean = df.select(["timestamp", factor, ret_col]).drop_nulls()
    if clean.height < 3:
        return {"rank_ic": None, "p_value": None, "ic_ir": None, "quintile_spread": None, "observations": clean.height}
    values, returns = clean[factor].to_numpy(), clean[ret_col].to_numpy()
    ic, p_value = stats.spearmanr(values, returns)
    ranks = pl.Series(stats.rankdata(values))
    quintile = (ranks / len(ranks) * 5).ceil().clip(1, 5).cast(pl.Int8)
    buckets = clean.with_columns(quintile.alias("quintile")).group_by("quintile").agg(pl.col(ret_col).mean()).sort("quintile")
    means = {row["quintile"]: row[ret_col] for row in buckets.iter_rows(named=True)}
    daily_ic = []
    for group in clean.partition_by("timestamp"):
        if group.height >= 3:
            r, _ = stats.spearmanr(group[factor].to_numpy(), group[ret_col].to_numpy())
            if np.isfinite(r):
                daily_ic.append(float(r))
    ir = float(np.mean(daily_ic) / np.std(daily_ic, ddof=1) * np.sqrt(365.25)) if len(daily_ic) > 1 and np.std(daily_ic, ddof=1) else None
    return {"rank_ic": float(ic), "p_value": float(p_value), "ic_ir": ir,
            "quintile_spread": float(means.get(5, float("nan")) - means.get(1, float("nan"))),
            "observations": clean.height}


def main():
    df = pl.read_parquet(FEATURES_PATH).sort(["symbol", "timestamp"])
    df = df.with_columns([
        pl.col("close").ewm_mean(span=12, adjust=False).over("symbol").alias("macd_fast"),
        pl.col("close").ewm_mean(span=26, adjust=False).over("symbol").alias("macd_slow"),
        pl.col("close").ewm_mean(span=72, adjust=False).over("symbol").alias("ema_72"),
        pl.col("close").diff().over("symbol").alias("price_change"),
    ]).with_columns((pl.col("macd_fast") - pl.col("macd_slow")).alias("macd_line"))
    df = df.with_columns((pl.col("macd_line") - pl.col("macd_line").ewm_mean(span=9, adjust=False).over("symbol")).alias("macd_hist"))
    df = df.with_columns([
        pl.col("price_change").clip(lower_bound=0).rolling_mean(14).over("symbol").alias("avg_gain"),
        (-pl.col("price_change").clip(upper_bound=0)).rolling_mean(14).over("symbol").alias("avg_loss"),
    ]).with_columns((100 - 100 / (1 + pl.col("avg_gain") / pl.col("avg_loss"))).alias("rsi_14"))
    df = df.with_columns((pl.col("close").shift(-1).over("symbol") / pl.col("close") - 1).alias("fwd_ret_1h"),
                         (pl.col("close").shift(-4).over("symbol") / pl.col("close") - 1).alias("fwd_ret_4h"))
    df = df.with_columns([
        (pl.col("roc_168") / (pl.col("realized_vol_168") + 0.05)).rank(method="average").over("timestamp").alias("mom_rank"),
        pl.col("macd_hist").rank(method="average").over("timestamp").alias("macd_rank"),
        pl.len().over("timestamp").alias("cross_section_n"),
    ]).with_columns((0.6 * pl.col("mom_rank") / pl.col("cross_section_n") + 0.4 * pl.col("macd_rank") / pl.col("cross_section_n")).alias("composite_mom"))
    df = df.with_columns(pl.col("composite_mom").rank(method="ordinal", descending=True).over("timestamp").alias("composite_rank"))
    dev = df.filter((pl.col("timestamp") >= START) & (pl.col("timestamp") <= END)).with_columns([
        (pl.col("composite_rank") <= 5).cast(pl.Float64).alias("selected"),
        (pl.col("close") > pl.col("ema_72")).cast(pl.Float64).alias("trend_ok"),
    ])

    diagnostics = {}
    for horizon, ret_col in HORIZONS.items():
        diagnostics[horizon] = {
            "composite_mom": diagnose(dev, "composite_mom", ret_col),
            "roc_168": diagnose(dev, "roc_168", ret_col),
        }

    prices = dev.select(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
    signals = dev.select(["timestamp", "symbol", "selected", "trend_ok"])
    config = BacktestConfig(initial_cash=10000.0, share_type=ShareType.FRACTIONAL,
                            commission_type=CommissionType.PERCENTAGE, commission_rate=0.00018,
                            slippage_type=SlippageType.PERCENTAGE, slippage_rate=0.0)
    result = Engine(DataFeed(prices_df=prices, signals_df=signals), TopFiveDualMomentum(), config).run()
    daily = result.to_daily_returns()
    sr = float(daily.mean() / daily.std() * np.sqrt(365.25)) if daily.std() else 0.0
    metrics = result.metrics
    backtest = {"daily_sharpe": sr, "total_return": float(metrics.get("total_return", 0.0)),
                "max_drawdown": float(metrics.get("max_drawdown", 0.0)), "trades": len(result.trades),
                "costs": float(metrics.get("total_costs", 0.0)), "commission_rate": 0.00018,
                "slippage_rate": 0.0, "initial_cash": 10000.0}
    artifact = {"iteration": "B_dual_momentum", "period": {"start": "2021-01-01", "end": "2024-12-31"},
                "universe": "dynamic Binance perpetuals, as represented in input feature panel",
                "composite_definition": "0.6 * cross-sectional rank(roc_168 / (realized_vol_168 + 0.05)) + 0.4 * cross-sectional rank(macd_hist)",
                "indicators": {"macd": [12, 26, 9], "rsi": 14},
                "factor_diagnostics": diagnostics, "backtest": backtest}
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(artifact, indent=2, allow_nan=False) + "\n")
    print(json.dumps(artifact, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
