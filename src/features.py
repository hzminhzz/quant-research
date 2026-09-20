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


def compute_garman_klass_volatility(
    df: pl.DataFrame,
    lookback: int = 20,
    group_col: Optional[str] = None,
    alias: Optional[str] = None,
) -> pl.DataFrame:
    """Compute Garman-Klass continuous diffusion volatility estimator.
    
    GK_t = 0.5 * (ln(H/L))^2 - (2*ln(2) - 1) * (ln(C/O))^2
    More efficient and continuous than Parkinson or close-to-close variance.
    """
    col_name = alias or f"garman_klass_{lookback}"
    log_hl = (pl.col("high") / pl.col("low")).log()
    log_co = (pl.col("close") / pl.col("open")).log()
    
    gk_var = 0.5 * (log_hl ** 2) - (2.0 * np.log(2.0) - 1.0) * (log_co ** 2)
    rolling_gk = gk_var.rolling_mean(window_size=lookback)
    if group_col and group_col in df.columns:
        rolling_gk = rolling_gk.over(group_col)
    
    gk_vol = (rolling_gk.clip(lower_bound=0.0)).sqrt()
    return df.with_columns(gk_vol.alias(col_name))



def compute_nr7(
    df: pl.DataFrame,
    high_col: str = "high",
    low_col: str = "low",
    group_col: Optional[str] = None,
    alias: str = "nr7",
) -> pl.DataFrame:
    """Identify Toby Crabel's Narrow Range 7 (NR7) compression days.
    
    True if the current bar/day range is narrower than the prior 6 bars/days.
    """
    range_expr = pl.col(high_col) - pl.col(low_col)
    min_prior_range = range_expr.shift(1).rolling_min(window_size=6)
    if group_col and group_col in df.columns:
        min_prior_range = min_prior_range.over(group_col)
    
    nr7_expr = range_expr < min_prior_range
    return df.with_columns(nr7_expr.fill_null(False).alias(alias))


def extract_breakout_feature_vector(
    or_df: pl.DataFrame,
    current_bar: pl.DataFrame,
    or_high: float,
    or_low: float,
    or_range: float,
    atr20: float,
    direction: int = 1,
    baseline_volume_1h: float = 1.0,
    gk_vol: float = 0.0,
    is_nr7: bool = False,
    spx_c: Optional[float] = None,
    spx_v: Optional[float] = None,
    is_crypto: bool = False,
) -> dict:
    """Extract stationary, zero-lookahead feature vector at breakout bar confirmation.

    Features:
    1. rvol_1h: Opening 1H volume / baseline average 1H volume (>1.0 = institutional presence)
    2. vwap_loc_1h: 1H Volume-Weighted Price location inside opening range [0.0, 1.0]
    3. vwap_alignment: Volume concentration aligned with breakout direction (>0.5 = aligned)
    4. wick_exhaustion: Counter-directional shadow rejection ratio (upper for long, lower for short)
    5. range_to_atr20: Opening range width normalized by daily ATR20
    6. garman_klass_norm: Intraday continuous diffusion volatility proxy
    7. spx_vwap_dist: Macro market alignment (S&P 500 distance to VWAP in %)
    8. spx_alignment: Macro market distance aligned with breakout direction
    9. nr7_flag: Multi-day volatility compression preceding breakout (0.0 or 1.0)
    10. breakout_bar_range_ratio: Breakout bar range vs median 5m bar range
    """
    or_vols = or_df["volume"].to_numpy() if "volume" in or_df.columns else np.ones(len(or_df))
    or_closes = or_df["close"].to_numpy()
    or_opens = or_df["open"].to_numpy()
    total_or_vol = float(np.sum(or_vols)) if len(or_vols) > 0 else 1.0

    # 1. Relative Volume (RVOL_1H)
    rvol_1h = total_or_vol / baseline_volume_1h if baseline_volume_1h > 0 else 1.0

    # 2. VWAP Location inside 1H range (0.0 = low, 1.0 = high)
    if total_or_vol > 0:
        vwap_1h = float(np.sum(or_closes * or_vols) / total_or_vol)
    else:
        vwap_1h = float(np.mean(or_closes))
    vwap_loc_1h = (vwap_1h - or_low) / or_range if or_range > 0 else 0.5
    vwap_alignment = vwap_loc_1h if direction == 1 else (1.0 - vwap_loc_1h)

    # 3. Wick Exhaustion of 1H candle
    c_1h = or_closes[-1]
    o_1h = or_opens[0]
    wick_upper = (or_high - max(o_1h, c_1h)) / or_range if or_range > 0 else 0.0
    wick_lower = (min(o_1h, c_1h) - or_low) / or_range if or_range > 0 else 0.0
    wick_exhaustion = wick_upper if direction == 1 else wick_lower

    # 4. Range to ATR20 ratio (Compression vs Saturation)
    range_to_atr20 = or_range / atr20 if atr20 > 0 else 1.0

    # 5. SPX Macro Distance to VWAP
    if not is_crypto and spx_c is not None and spx_v is not None and spx_v > 0:
        spx_dist = (spx_c - spx_v) / spx_v * 100.0
    else:
        spx_dist = 0.0
    spx_alignment = spx_dist * direction

    # 6. Breakout bar range ratio vs average bar range in 1H
    curr_h = float(current_bar["high"][0])
    curr_l = float(current_bar["low"][0])
    curr_bar_range = max(1e-6, curr_h - curr_l)
    bar_range_ratio = curr_bar_range / (or_range / 12.0) if or_range > 0 else 1.0

    return {
        "rvol_1h": float(np.clip(rvol_1h, 0.1, 10.0)),
        "vwap_loc_1h": float(np.clip(vwap_loc_1h, 0.0, 1.0)),
        "vwap_alignment": float(np.clip(vwap_alignment, 0.0, 1.0)),
        "wick_upper_ratio": float(np.clip(wick_upper, 0.0, 1.0)),
        "wick_lower_ratio": float(np.clip(wick_lower, 0.0, 1.0)),
        "wick_exhaustion": float(np.clip(wick_exhaustion, 0.0, 1.0)),
        "range_to_atr20": float(range_to_atr20),
        "garman_klass_norm": float(np.clip(gk_vol * 100.0, 0.0, 50.0)),
        "spx_vwap_dist": float(spx_dist),
        "spx_alignment": float(spx_alignment),
        "nr7_flag": 1.0 if is_nr7 else 0.0,
        "breakout_bar_range_ratio": float(np.clip(bar_range_ratio, 0.2, 5.0)),
    }


