"""Integration tests for the Standardized ML4T 4-Stage Pipeline Contract."""

import numpy as np
import polars as pl
from src.pipeline import (
    run_stage1_features,
    run_stage2_diagnostics,
    run_stage3_backtest,
    run_stage4_meta_labeling,
    run_full_pipeline,
)


def make_synthetic_ohlcv(n_bars: int = 300) -> pl.DataFrame:
    """Generate realistic synthetic OHLCV data for pipeline testing."""
    rng = np.random.default_rng(42)
    dt_range = [f"2024-01-01 {i//4:02d}:{(i%4)*15:02d}" for i in range(n_bars)]
    
    returns = rng.normal(loc=0.0002, scale=0.005, size=n_bars)
    prices = 100.0 * np.exp(np.cumsum(returns))
    
    highs = prices * (1.0 + rng.uniform(0.001, 0.004, size=n_bars))
    lows = prices * (1.0 - rng.uniform(0.001, 0.004, size=n_bars))
    opens = prices * (1.0 + rng.normal(0.0, 0.001, size=n_bars))
    volumes = rng.integers(500, 5000, size=n_bars)

    return pl.DataFrame({
        "timestamp": dt_range,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": prices,
        "volume": volumes,
    })


def test_stage1_features():
    df = make_synthetic_ohlcv(250)
    res = run_stage1_features(df)
    assert "atr" in res.data.columns
    assert "rsi" in res.data.columns
    assert "ema_200" in res.data.columns
    assert "fwd_ret_16" in res.data.columns
    assert "tb_label" in res.data.columns
    assert len(res.feature_names) > 0


def test_stage2_diagnostics():
    df = make_synthetic_ohlcv(250)
    s1 = run_stage1_features(df)
    s1_data = s1.data.with_columns(
        (pl.col("rsi") < 45).alias("test_signal")
    )
    s1 = s1.__class__(data=s1_data, feature_names=s1.feature_names, label_names=s1.label_names)
    s2 = run_stage2_diagnostics(s1, signal_col="test_signal", n_bootstrap=50)
    assert len(s2.metrics) > 0
    assert -1.0 <= s2.mean_ic <= 1.0


def test_stage3_backtest():
    df = make_synthetic_ohlcv(250)
    s1 = run_stage1_features(df)
    s1_data = s1.data.with_columns(
        (pl.col("close") > pl.col("open")).alias("test_signal")
    )
    s1 = s1.__class__(data=s1_data, feature_names=s1.feature_names, label_names=s1.label_names)
    s3 = run_stage3_backtest(s1, signal_col="test_signal", holding_bars=8)
    assert s3.total_trades >= 0
    assert "daily_equity" in dir(s3)


def test_full_pipeline_orchestration():
    df = make_synthetic_ohlcv(250)
    
    def signal_fn(data: pl.DataFrame) -> pl.DataFrame:
        return data.with_columns(
            (pl.col("is_bullish_engulfing") & (pl.col("close") > pl.col("ema_200"))).alias("strategy_signal")
        )

    report = run_full_pipeline(df, symbol="TEST/USD", primary_signal_fn=signal_fn, holding_bars=8)
    assert report.symbol == "TEST/USD"
    assert report.stage1 is not None
    assert report.stage2 is not None
    assert report.stage3 is not None
    assert isinstance(report.is_deployable, bool)
