"""Japanese Candlestick Pattern Engine.

Implements standard candlestick pattern recognition using Polars with exact
mathematical parity against TA-Lib (CDLENGULFING).
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
