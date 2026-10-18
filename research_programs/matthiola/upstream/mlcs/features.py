"""Feature engineering for cross-sectional stock ranking.

Inputs are wide DataFrames (index=date, columns=symbol) of adjusted close and
volume. All feature helpers preserve that shape so they can be stacked into a
long-format feature matrix downstream.

Convention: feature orientation is not standardised here — LightGBM / XGBoost
are invariant to monotone transforms of a single feature, and the linear
baselines get z-scored per-date in the training script. Classic factor signals
keep their "higher = more attractive" orientation (from classic-factors) for
interpretability.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# classic factor signals (inlined — originals live in classic-factors/src)
# ---------------------------------------------------------------------------

def momentum(close: pd.DataFrame, lookback: int = 252, skip: int = 21) -> pd.DataFrame:
    """12-1 momentum: total return over `lookback` days, skipping last `skip`."""
    return close.shift(skip) / close.shift(skip + lookback) - 1


def short_term_reversal(close: pd.DataFrame, lookback: int = 5) -> pd.DataFrame:
    """Negative of recent cumulative return — bets on short-horizon mean reversion."""
    return -(close / close.shift(lookback) - 1)


def low_volatility(close: pd.DataFrame, lookback: int = 60) -> pd.DataFrame:
    """Negative rolling std of daily returns (low-vol anomaly)."""
    return -close.pct_change().rolling(lookback).std()


def size_adv(close: pd.DataFrame, volume: pd.DataFrame, lookback: int = 60) -> pd.DataFrame:
    """Liquidity-proxied size: negative average dollar volume (shares-outstanding unavailable)."""
    adv = (close * volume).rolling(lookback).mean()
    return -adv


# ---------------------------------------------------------------------------
# technical indicators
# ---------------------------------------------------------------------------

def horizon_return(close: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """Plain cumulative return over `lookback` days (no skip)."""
    return close / close.shift(lookback) - 1


def realised_vol(close: pd.DataFrame, lookback: int = 60) -> pd.DataFrame:
    """Rolling std of daily log returns (annualised-free; scale is relative)."""
    return np.log(close / close.shift(1)).rolling(lookback).std()


def rsi(close: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    """Wilder's RSI per symbol. Vectorised across columns."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def macd(close: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD histogram = (EMA_fast − EMA_slow) − signal-EMA-of-that."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    line = ema_fast - ema_slow
    sig = line.ewm(span=signal, adjust=False).mean()
    return line - sig


def volume_zscore(volume: pd.DataFrame, lookback: int = 60) -> pd.DataFrame:
    """Rolling z-score of log(1+volume) per symbol."""
    v = np.log1p(volume.astype("float64"))
    mean = v.rolling(lookback).mean()
    std = v.rolling(lookback).std()
    return (v - mean) / std.replace(0, np.nan)


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------

def build_feature_panel(close: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    """Compute the full feature set and return a long-format DataFrame.

    Returns columns: [date, symbol, <features...>]. No target column — that is
    added by `add_forward_target` after the feature panel is built, so that
    horizon/rank logic stays colocated with target definition.
    """
    features: dict[str, pd.DataFrame] = {
        # classic factor signals
        "mom_12_1": momentum(close, lookback=252, skip=21),
        "reversal_1w": short_term_reversal(close, lookback=5),
        "low_vol_60": low_volatility(close, lookback=60),
        "size_adv_60": size_adv(close, volume, lookback=60),
        # multi-horizon momentum (no skip)
        "ret_21d": horizon_return(close, 21),
        "ret_63d": horizon_return(close, 63),
        "ret_126d": horizon_return(close, 126),
        "ret_252d": horizon_return(close, 252),
        # volatility
        "vol_20d": realised_vol(close, 20),
        "vol_60d": realised_vol(close, 60),
        # momentum/mean-reversion oscillators
        "rsi_14": rsi(close, 14),
        "macd_hist": macd(close),
        # volume
        "volume_z_60": volume_zscore(volume, 60),
    }

    long_frames = []
    for name, wide in features.items():
        s = wide.stack().rename(name)
        s.index.names = ["date", "symbol"]
        long_frames.append(s)

    return pd.concat(long_frames, axis=1).reset_index()


def add_forward_target(
    features_long: pd.DataFrame,
    close: pd.DataFrame,
    horizon: int = 21,
) -> pd.DataFrame:
    """Attach forward `horizon`-day return plus per-date cross-sectional rank."""
    fwd = close.shift(-horizon) / close - 1
    fwd_long = fwd.stack().rename(f"fwd_ret_{horizon}d")
    fwd_long.index.names = ["date", "symbol"]

    out = features_long.merge(fwd_long.reset_index(), on=["date", "symbol"], how="left")

    # per-date cross-sectional rank in [0, 1]; NaN rows are excluded from ranking
    col = f"fwd_ret_{horizon}d"
    out[f"fwd_rank_{horizon}d"] = out.groupby("date")[col].rank(pct=True)
    return out
