"""MT5 iATR(14) feature pipeline using ml4t-engineer registry features.

Registered native TRANGE -> registered native SMA(14) -> registered
upper-median extension. No handwritten ATR/trend or backtest loops.
"""
from __future__ import annotations

import numpy as np
import polars as pl
from ml4t.engineer import compute_features
from ml4t.engineer.core.decorators import feature


@feature(
    name="yen_mt5_upper_median",
    category="volatility",
    description="MT5 upper order statistic (sorted[50]) for 100 completed ATR observations.",
    normalized=False,
    ta_lib_compatible=False,
    lookback=lambda period=100: period - 1,
)
def mt5_upper_median(close: str, period: int = 100) -> pl.Expr:
    """Certified extension: Polars vectorized 100-observation upper median.

    The registry has no rolling median feature. This contains no handwritten
    rolling feature algorithm. Use only inside ml4t.engineer.compute_features.
    """
    return pl.col(close).cast(pl.Float64).fill_nan(None).rolling_quantile(
        quantile=0.5, interpolation="higher", window_size=period,
        min_samples=period,
    )


def build_mt5_features(hourly: pl.DataFrame) -> pl.DataFrame:
    """Every H1 feature is computed by the ml4t-engineer registry."""
    hourly = hourly.sort("timestamp")
    base = compute_features(
        hourly,
        [
            {"name": "trange", "output": "mt5_tr"},
            {"name": "donchian_channels", "params": {"period": 20}, "output": "donchian20"},
            {"name": "donchian_channels", "params": {"period": 500}, "output": "donchian500"},
        ],
        timestamp_col="timestamp",
    )
    # Rebind the registry's expected close input to native TRANGE, preserving
    # the original OHLC for the downstream native execution adapter.
    atr = compute_features(
        base.with_columns(pl.col("mt5_tr").alias("close")),
        [{"name": "sma", "params": {"period": 14}, "output": "atr14"}],
        timestamp_col="timestamp",
    )
    median = compute_features(
        atr.with_columns(pl.col("atr14").alias("close")),
        [{"name": "yen_mt5_upper_median", "params": {"period": 100}, "output": "atr100_upper_median"}],
        timestamp_col="timestamp",
    )
    return base.with_columns(
        atr["atr14"], median["atr100_upper_median"],
        (pl.col("timestamp") + pl.duration(hours=1)).alias("available_at"),
    )


def prepare_minute_bars(minutes: pl.DataFrame, *, naive_is_utc: bool = False) -> pl.DataFrame:
    """Use complete H1 bars only; features available next H1 from the registry."""
    from scripts.audit_mechanicalpremia_yen_squeeze_native_20261014 import build_complete_h1
    h1, _ = build_complete_h1(minutes, naive_is_utc=naive_is_utc)
    f = build_mt5_features(h1)
    if minutes.schema["timestamp"].time_zone is None:
        if not naive_is_utc:
            raise ValueError("naive timestamps require explicit UTC provenance")
        minutes = minutes.with_columns(pl.col("timestamp").dt.replace_time_zone("UTC"))
    out = minutes.sort("timestamp").join_asof(
        f.sort("available_at"), left_on="timestamp", right_on="available_at",
        strategy="backward",
    )
    if out.filter(pl.col("available_at") > pl.col("timestamp")).height:
        raise AssertionError("future features reached minute data")
    return out
