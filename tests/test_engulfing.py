"""Unit tests for Candlestick Pattern Engine and ML4T pipeline components."""

import polars as pl
from src.patterns import detect_engulfing


def test_bullish_engulfing_detection():
    # Bar 0: Prior red candle (Open: 105, Close: 100)
    # Bar 1: Current green candle engulfing prior body (Open: 99, Close: 106)
    data = pl.DataFrame({
        "timestamp": ["2024-01-01 09:30", "2024-01-01 09:45"],
        "open": [105.0, 99.0],
        "high": [106.0, 107.0],
        "low": [98.0, 98.0],
        "close": [100.0, 106.0],
        "volume": [1000, 1500],
    })
    result = detect_engulfing(data)
    assert "is_bullish_engulfing" in result.columns
    assert "is_bearish_engulfing" in result.columns
    assert result["is_bullish_engulfing"].to_list() == [False, True]
    assert result["is_bearish_engulfing"].to_list() == [False, False]


def test_bearish_engulfing_detection():
    # Bar 0: Prior green candle (Open: 100, Close: 105)
    # Bar 1: Current red candle engulfing prior body (Open: 106, Close: 99)
    data = pl.DataFrame({
        "timestamp": ["2024-01-01 09:30", "2024-01-01 09:45"],
        "open": [100.0, 106.0],
        "high": [106.0, 107.0],
        "low": [99.0, 98.0],
        "close": [105.0, 99.0],
        "volume": [1000, 1500],
    })
    result = detect_engulfing(data)
    assert result["is_bullish_engulfing"].to_list() == [False, False]
    assert result["is_bearish_engulfing"].to_list() == [False, True]


def test_non_engulfing_candles():
    # Both candles green (trend continuation, no engulfing)
    data = pl.DataFrame({
        "timestamp": ["2024-01-01 09:30", "2024-01-01 09:45"],
        "open": [100.0, 102.0],
        "high": [103.0, 105.0],
        "low": [99.0, 101.0],
        "close": [102.0, 104.0],
        "volume": [1000, 1200],
    })
    result = detect_engulfing(data)
    assert result["is_bullish_engulfing"].to_list() == [False, False]
    assert result["is_bearish_engulfing"].to_list() == [False, False]
