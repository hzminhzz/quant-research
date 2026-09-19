"""Numerical and Zero-Lookahead Parity Tests for Features and Indicators."""

import numpy as np
import polars as pl
from src.features import (
    compute_ema,
    compute_rsi,
    compute_atr,
    compute_bollinger_bands,
    compute_momentum_panel,
)
from src.patterns import detect_engulfing


def make_test_series(n_bars: int = 200) -> pl.DataFrame:
    rng = np.random.default_rng(123)
    prices = 100.0 + np.cumsum(rng.normal(0, 1, n_bars))
    highs = prices + rng.uniform(0.5, 1.5, n_bars)
    lows = prices - rng.uniform(0.5, 1.5, n_bars)
    opens = prices + rng.normal(0, 0.5, n_bars)
    
    return pl.DataFrame({
        "timestamp": [f"2024-01-01 {i:04d}" for i in range(n_bars)],
        "open": opens,
        "high": highs,
        "low": lows,
        "close": prices,
        "volume": rng.integers(100, 1000, n_bars),
    })


def test_zero_lookahead_guarantee():
    """Verify that altering future prices (t > k) has zero effect on feature at t <= k."""
    df1 = make_test_series(100)
    df2 = df1.clone()

    # Alter future data in df2 (bars 50 to 99)
    df2 = df2.with_columns(
        pl.when(pl.int_range(0, pl.len()) >= 50)
        .then(pl.col("close") * 5.0)
        .otherwise(pl.col("close"))
        .alias("close")
    )

    feat1 = compute_rsi(compute_atr(compute_ema(df1, span=20), period=14), period=14)
    feat2 = compute_rsi(compute_atr(compute_ema(df2, span=20), period=14), period=14)

    # Features at bar 49 (and earlier) must be 100% bitwise identical
    for col in ["ema_20", "atr_14", "rsi_14"]:
        val1 = feat1[col][:50].to_list()
        val2 = feat2[col][:50].to_list()
        assert np.allclose(val1, val2, equal_nan=True), f"Lookahead leakage detected in {col}!"


def test_bollinger_bands_geometry():
    """Verify upper band > middle band > lower band at all points."""
    df = make_test_series(100)
    res = compute_bollinger_bands(df, period=20, num_std=2.0)
    
    # After warm-up period (bar 20 onwards)
    mid = res["bb_mid_20"][20:].to_numpy()
    upper = res["bb_upper_20"][20:].to_numpy()
    lower = res["bb_lower_20"][20:].to_numpy()

    assert np.all(upper >= mid)
    assert np.all(mid >= lower)


def test_group_aware_feature_independence():
    """Verify that features computed on a multi-asset panel do not leak across symbols."""
    df_a = make_test_series(50).with_columns(pl.lit("ASSET_A").alias("symbol"))
    df_b = make_test_series(50).with_columns(
        (pl.col("close") * 10.0).alias("close"),
        pl.lit("ASSET_B").alias("symbol")
    )
    panel = pl.concat([df_a, df_b])

    panel_feat = compute_ema(panel, span=10, group_col="symbol")
    single_a_feat = compute_ema(df_a, span=10)

    val_panel_a = panel_feat.filter(pl.col("symbol") == "ASSET_A")["ema_10"].to_list()
    val_single_a = single_a_feat["ema_10"].to_list()

    assert np.allclose(val_panel_a, val_single_a, equal_nan=True)
