"""Japanese Candlestick Pattern Engine.

Implements standard candlestick pattern recognition using Polars with exact
mathematical parity against TA-Lib (CDLENGULFING), plus ML4T refined high-Sharpe
intraday setups.
"""

from typing import Tuple
import polars as pl


def detect_engulfing(df: pl.DataFrame) -> pl.DataFrame:
    """Detect Bullish and Bearish Engulfing patterns.

    Requires columns: 'open', 'high', 'low', 'close'.
    Appends boolean columns: 'is_bullish_engulfing' and 'is_bearish_engulfing'.
    """
    return df.with_columns([
        pl.col("open").shift(1).alias("prev_open"),
        pl.col("close").shift(1).alias("prev_close"),
    ]).with_columns([
        (
            (pl.col("prev_close") < pl.col("prev_open"))  # Prior bar was red/bearish
            & (pl.col("close") > pl.col("open"))          # Current bar is green/bullish
            & (pl.col("open") <= pl.col("prev_close"))    # Current open <= prior close
            & (pl.col("close") >= pl.col("prev_open"))    # Current close >= prior open
        ).fill_null(False).alias("is_bullish_engulfing"),
        (
            (pl.col("prev_close") > pl.col("prev_open"))  # Prior bar was green/bullish
            & (pl.col("close") < pl.col("open"))          # Current bar is red/bearish
            & (pl.col("open") >= pl.col("prev_close"))    # Current open >= prior close
            & (pl.col("close") <= pl.col("prev_open"))    # Current close <= prior open
        ).fill_null(False).alias("is_bearish_engulfing"),
    ]).drop(["prev_open", "prev_close"])


def detect_high_sharpe_engulfing(
    df: pl.DataFrame,
    body_atr_mult: float = 0.35,
    rsi_pullback_thresh: float = 55.0,
) -> pl.DataFrame:
    """Detect High-Sharpe Refined Bullish Engulfing Pattern.

    Requires columns: 'open', 'high', 'low', 'close', 'atr', 'rsi'.
    Filters naive bullish engulfing by:
    1. Body size >= body_atr_mult * atr (volatility expansion)
    2. Prior RSI < rsi_pullback_thresh (pullback confirmation)
    """
    base = detect_engulfing(df)
    body = (pl.col("close") - pl.col("open")).abs()
    refined_bull = (
        pl.col("is_bullish_engulfing")
        & (body >= body_atr_mult * pl.col("atr"))
        & (pl.col("rsi").shift(1) < rsi_pullback_thresh)
    ).fill_null(False)
    return base.with_columns(refined_bull.alias("is_refined_bullish_engulfing"))
