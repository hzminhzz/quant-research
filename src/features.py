"""Systematic Quantitative Feature Engineering Engine.

Provides vectorized, high-performance Polars feature transformers with strict
zero-lookahead guarantees. Supports single asset series and multi-asset panels
with group-aware expressions.
"""

from typing import List, Optional
import polars as pl
import numpy as np


def compute_ema(
    df: pl.DataFrame,
    span: int = 200,
    price_col: str = "close",
    group_col: Optional[str] = None,
    alias: Optional[str] = None,
) -> pl.DataFrame:
    """Calculate Exponential Moving Average (EMA)."""
    col_name = alias or f"ema_{span}"
    expr = pl.col(price_col).ewm_mean(span=span, adjust=False)
    if group_col and group_col in df.columns:
        expr = expr.over(group_col)
    return df.with_columns(expr.alias(col_name))


def compute_rsi(
    df: pl.DataFrame,
    period: int = 14,
    price_col: str = "close",
    group_col: Optional[str] = None,
    alias: Optional[str] = None,
) -> pl.DataFrame:
    """Calculate Relative Strength Index (RSI) with Wilder's smoothing."""
    col_name = alias or f"rsi_{period}"
    
    # Price difference
    diff_expr = pl.col(price_col).diff()
    if group_col and group_col in df.columns:
        diff_expr = diff_expr.over(group_col)

    up_expr = pl.when(diff_expr > 0).then(diff_expr).otherwise(0.0)
    down_expr = pl.when(diff_expr < 0).then(-diff_expr).otherwise(0.0)

    # Wilder's smoothing via ewm_mean with alpha = 1 / period
    avg_gain = up_expr.ewm_mean(alpha=1.0 / period, adjust=False)
    avg_loss = down_expr.ewm_mean(alpha=1.0 / period, adjust=False)

    if group_col and group_col in df.columns:
        avg_gain = avg_gain.over(group_col)
        avg_loss = avg_loss.over(group_col)

    rs = avg_gain / (avg_loss + 1e-12)
    rsi_expr = 100.0 - (100.0 / (1.0 + rs))

    return df.with_columns(rsi_expr.fill_null(50.0).alias(col_name))


def compute_atr(
    df: pl.DataFrame,
    period: int = 14,
    group_col: Optional[str] = None,
    alias: Optional[str] = None,
) -> pl.DataFrame:
    """Calculate Average True Range (ATR) with zero lookahead."""
    col_name = alias or f"atr_{period}"

    prev_close = pl.col("close").shift(1)
    if group_col and group_col in df.columns:
        prev_close = prev_close.over(group_col)

    tr1 = pl.col("high") - pl.col("low")
    tr2 = (pl.col("high") - prev_close).abs()
    tr3 = (pl.col("low") - prev_close).abs()

    tr = pl.max_horizontal(tr1, tr2, tr3)
    atr_expr = tr.ewm_mean(alpha=1.0 / period, adjust=False)
    if group_col and group_col in df.columns:
        atr_expr = atr_expr.over(group_col)

    return df.with_columns(atr_expr.alias(col_name))


def compute_realized_volatility(
    df: pl.DataFrame,
    lookback: int = 20,
    price_col: str = "close",
    group_col: Optional[str] = None,
    alias: Optional[str] = None,
) -> pl.DataFrame:
    """Compute rolling realized volatility of log returns."""
    col_name = alias or f"realized_vol_{lookback}"
    
    ret_expr = (pl.col(price_col) / pl.col(price_col).shift(1)).log()
    if group_col and group_col in df.columns:
        ret_expr = ret_expr.over(group_col)

    vol_expr = ret_expr.rolling_std(window_size=lookback)
    if group_col and group_col in df.columns:
        vol_expr = vol_expr.over(group_col)

    return df.with_columns(vol_expr.alias(col_name))


def compute_bollinger_bands(
    df: pl.DataFrame,
    period: int = 20,
    num_std: float = 2.0,
    price_col: str = "close",
    group_col: Optional[str] = None,
) -> pl.DataFrame:
    """Compute Bollinger Bands (middle, upper, lower, %B, and bandwidth)."""
    mean_expr = pl.col(price_col).rolling_mean(window_size=period)
    std_expr = pl.col(price_col).rolling_std(window_size=period)

    if group_col and group_col in df.columns:
        mean_expr = mean_expr.over(group_col)
        std_expr = std_expr.over(group_col)

    upper_expr = mean_expr + (std_expr * num_std)
    lower_expr = mean_expr - (std_expr * num_std)
    pct_b = (pl.col(price_col) - lower_expr) / (upper_expr - lower_expr + 1e-12)
    bandwidth = (upper_expr - lower_expr) / (mean_expr + 1e-12)

    return df.with_columns([
        mean_expr.alias(f"bb_mid_{period}"),
        upper_expr.alias(f"bb_upper_{period}"),
        lower_expr.alias(f"bb_lower_{period}"),
        pct_b.alias(f"bb_pct_b_{period}"),
        bandwidth.alias(f"bb_bandwidth_{period}"),
    ])


def compute_momentum_panel(
    df: pl.DataFrame,
    lookbacks: List[int] = [5, 10, 21, 63],
    price_col: str = "close",
    group_col: Optional[str] = None,
) -> pl.DataFrame:
    """Compute multi-horizon momentum (percentage return) features."""
    cols = []
    for lb in lookbacks:
        expr = pl.col(price_col).pct_change(lb)
        if group_col and group_col in df.columns:
            expr = expr.over(group_col)
        cols.append(expr.alias(f"mom_{lb}"))
    return df.with_columns(cols)
