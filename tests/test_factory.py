"""Unit tests for ML4T Strategy Factory and systematic signal engines."""

from pathlib import Path
import polars as pl
import pytest
from src.factory import (
    compute_factory_features,
    get_breakout_strategies,
    get_mean_reversion_strategies,
    run_strategy_backtest,
)


@pytest.fixture
def sample_15m_data():
    """Create synthetic 15m OHLCV bar series for unit testing."""
    from datetime import datetime
    n = 300
    ts = pl.datetime_range(
        datetime(2024, 1, 1, 0, 0),
        datetime(2024, 1, 5, 0, 0),
        interval="15m",
        eager=True,
    ).slice(0, n)
    prices = [100.0 + i * 0.1 for i in range(len(ts))]
    return pl.DataFrame({
        "timestamp": ts,
        "open": prices,
        "high": [p + 0.5 for p in prices],
        "low": [p - 0.5 for p in prices],
        "close": [p + 0.2 for p in prices],
        "volume": [1000] * len(ts),
        "symbol": ["TEST/USD"] * len(ts),
    })


def test_factory_feature_computation(sample_15m_data):
    df_feat = compute_factory_features(sample_15m_data)
    expected_cols = [
        "rsi_2",
        "rsi_14",
        "atr_14",
        "adx_14",
        "ema_20",
        "ema_50",
        "ema_200",
        "donchian_high_10",
        "donchian_high_20",
        "candle_range",
        "candle_body",
        "lower_wick",
        "bull_engulf",
        "bear_engulf",
        "ema50_stretch",
        "fwd_ret_20",
    ]
    for col in expected_cols:
        assert col in df_feat.columns, f"Missing feature column: {col}"
    assert len(df_feat) > 0


def test_breakout_strategy_definitions():
    strats = get_breakout_strategies()
    assert len(strats) == 3
    for name, info in strats.items():
        assert info["family"] == "Breakout"
        assert info["hold_bars"] <= 48, (
            f"Hold period exceeds 2-3 days max: {info['hold_bars']}h"
        )
        assert isinstance(info["expr"], pl.Expr)


def test_mean_reversion_strategy_definitions():
    strats = get_mean_reversion_strategies()
    assert len(strats) == 3
    for name, info in strats.items():
        assert info["family"] == "Mean Reversion"
        assert info["hold_bars"] <= 48, (
            f"Hold period exceeds 2-3 days max: {info['hold_bars']}h"
        )
        assert isinstance(info["expr"], pl.Expr)


def test_factory_backtest_execution():
    parquet_path = Path("data/processed/DE30_EUR_15m_2019_2026.parquet")
    if not parquet_path.exists():
        parquet_path = Path("/tmp/lse_15m_cache/DE30_EUR_15m_2019_2026.parquet")
    if not parquet_path.exists():
        pytest.skip("Local test parquet data not available")

    df_raw = pl.read_parquet(parquet_path).slice(0, 1500)
    df_feat = compute_factory_features(df_raw)
    strats = get_breakout_strategies()
    first_strat = list(strats.values())[0]

    res = run_strategy_backtest(
        df_feat, first_strat["expr"], hold_bars=first_strat["hold_bars"]
    )
    assert "sharpe" in res
    assert "win_rate_pct" in res
    assert "dsr_probability" in res
    assert "equity_dataframe" in res
