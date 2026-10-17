"""Regression tests for the frozen Mechanical Premia native research adapter."""
from datetime import datetime, timedelta, timezone

import polars as pl
import pytest

from scripts.mechanicalpremia_native_20261013 import (
    HOLDOUT, build_signals, load_development, run_native,
)


def test_protected_holdout_is_inaccessible():
    with pytest.raises(ValueError, match="Protected"):
        load_development("ES_PROXY", until=HOLDOUT + timedelta(minutes=1))


def test_engineer_features_are_bounded_to_completed_h1_and_d1():
    end = datetime(2024, 4, 1, tzinfo=timezone.utc)
    result = build_signals(load_development("ES_PROXY", until=end))
    assert result["timestamp"].max() < HOLDOUT
    assert result.filter(pl.col("h_enter")).height > 0
    # The completed hourly bar's final minute is 59; native NEXT_BAR is later.
    assert result.filter(pl.col("h_enter")).select(
        (pl.col("timestamp").dt.minute() == 59).all()).item()
    assert result.select(pl.col("last_h_atr").is_not_null().sum()).item() > 0
    # At least some daily Bollinger exits, even before D1 ATR100 warmup.
    assert result.filter(pl.col("d_exit")).height > 0


def test_native_engine_independent_h1_and_d1_positions():
    start = datetime(2024, 1, 2, tzinfo=timezone.utc)
    frame = pl.DataFrame({
        "timestamp": [start + timedelta(minutes=i) for i in range(8)],
        "asset": ["ES_PROXY"] * 8,
        "open": [100.0] * 8,
        "high": [100.5] * 8,
        "low": [99.5] * 8,
        "close": [100.0] * 8,
        "volume": [10.0] * 8,
        "h_enter": [True] + [False] * 7,
        "d_enter": [True] + [False] * 7,
        "d_exit": [False] * 3 + [True] + [False] * 4,
        "last_h_atr": [1.0] * 8,
        "last_d_atr": [1.0] * 8,
    })
    strategy, result = run_native(frame, "PORTFOLIO-SOURCE-RISK")
    fills = result.to_fills_dataframe()
    # Two distinct logical instruments permit concurrent D1 and H1 entries.
    buys = fills.filter(pl.col("side") == "buy")
    assert set(buys["asset"].to_list()) == {"ES_PROXY_H", "ES_PROXY_D"}
    assert result.metrics["num_rejected_orders"] == 0
    assert result.metrics["num_fills"] >= 3
    assert strategy.h_entry_count == 1
    assert strategy.d_entry_count == 1
    assert result.metrics["total_commission"] > 0
    assert result.metrics["final_value"] > 0


def test_native_h1_entry_next_minute_not_signal_candle():
    start = datetime(2024, 1, 2, tzinfo=timezone.utc)
    frame = pl.DataFrame({
        "timestamp": [start + timedelta(minutes=i) for i in range(5)],
        "asset": ["NQ_PROXY"] * 5,
        "open": [100.0] * 5, "high": [101.0] * 5,
        "low": [99.0] * 5, "close": [100.0] * 5,
        "volume": [100.0] * 5,
        "h_enter": [True, False, False, False, False],
        "d_enter": [False] * 5,
        "d_exit": [False] * 5,
        "last_h_atr": [1.0] * 5,
        "last_d_atr": [1.0] * 5,
    })
    _, result = run_native(frame, "H1-ONLY")
    fills = result.to_fills_dataframe()
    assert fills.height >= 1
    entry = fills.filter(pl.col("side") == "buy").row(0, named=True)
    assert entry["timestamp"].replace(tzinfo=timezone.utc) == start + timedelta(minutes=1)
