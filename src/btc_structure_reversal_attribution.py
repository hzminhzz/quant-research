"""Causal attribution features for the frozen BTC structure-reversal baseline."""

from __future__ import annotations

import numpy as np
import polars as pl

from src.btc_structure_reversal import Pivot


def ema(values: np.ndarray, period: int) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    out = np.empty(len(values), dtype=float)
    if len(values) == 0:
        return out
    alpha = 2.0 / (period + 1.0)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
    return out


def wilder_adx(frame: pl.DataFrame, period: int = 14) -> np.ndarray:
    """Causal Wilder-style ADX using only data through each completed bar."""
    n = frame.height
    high = frame["high"].to_numpy().astype(float)
    low = frame["low"].to_numpy().astype(float)
    close = frame["close"].to_numpy().astype(float)
    tr = np.zeros(n, dtype=float)
    plus_dm = np.zeros(n, dtype=float)
    minus_dm = np.zeros(n, dtype=float)
    for i in range(n):
        prev_close = close[i - 1] if i else close[i]
        tr[i] = max(high[i] - low[i], abs(high[i] - prev_close), abs(low[i] - prev_close))
        if i:
            up = high[i] - high[i - 1]
            down = low[i - 1] - low[i]
            plus_dm[i] = up if up > down and up > 0 else 0.0
            minus_dm[i] = down if down > up and down > 0 else 0.0

    atr = np.zeros(n, dtype=float)
    p_dm = np.zeros(n, dtype=float)
    m_dm = np.zeros(n, dtype=float)
    dx = np.full(n, np.nan, dtype=float)
    adx = np.full(n, np.nan, dtype=float)
    if n == 0:
        return adx

    atr[0], p_dm[0], m_dm[0] = tr[0], plus_dm[0], minus_dm[0]
    for i in range(1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
        p_dm[i] = (p_dm[i - 1] * (period - 1) + plus_dm[i]) / period
        m_dm[i] = (m_dm[i - 1] * (period - 1) + minus_dm[i]) / period
        if atr[i] > 0:
            plus_di = 100.0 * p_dm[i] / atr[i]
            minus_di = 100.0 * m_dm[i] / atr[i]
            denom = plus_di + minus_di
            if denom > 0:
                dx[i] = 100.0 * abs(plus_di - minus_di) / denom

    first = next((i for i, x in enumerate(dx) if np.isfinite(x)), None)
    if first is None:
        return adx
    adx[first] = dx[first]
    for i in range(first + 1, n):
        if np.isfinite(dx[i]):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period
        else:
            adx[i] = adx[i - 1]
    return adx


def latest_confirmed_low_anchor_indices(n: int, pivots: list[Pivot]) -> np.ndarray:
    anchors = np.full(n, -1, dtype=int)
    by_confirmation: dict[int, list[Pivot]] = {}
    for pivot in pivots:
        by_confirmation.setdefault(pivot.confirmation_index, []).append(pivot)
    current = -1
    for i in range(n):
        for pivot in by_confirmation.get(i, []):
            if pivot.kind == "L":
                current = pivot.pivot_index
        anchors[i] = current
    return anchors


def anchored_vwap(frame: pl.DataFrame, anchors: np.ndarray) -> np.ndarray:
    """Quote-volume/base-volume VWAP from the latest confirmed low pivot."""
    volume = frame["volume"].to_numpy().astype(float)
    quote = frame["quote_volume"].to_numpy().astype(float)
    cum_v = np.cumsum(np.nan_to_num(volume, nan=0.0))
    cum_q = np.cumsum(np.nan_to_num(quote, nan=0.0))
    out = np.full(frame.height, np.nan, dtype=float)
    for i, anchor in enumerate(anchors):
        if anchor < 0 or anchor > i:
            continue
        v0 = cum_v[anchor - 1] if anchor else 0.0
        q0 = cum_q[anchor - 1] if anchor else 0.0
        dv = cum_v[i] - v0
        dq = cum_q[i] - q0
        if dv > 0:
            out[i] = dq / dv
    return out


def add_attribution_features(
    signal_frame: pl.DataFrame,
    pivots: list[Pivot],
) -> pl.DataFrame:
    close = signal_frame["close"].to_numpy().astype(float)
    ema20 = ema(close, 20)
    ema_slope3 = np.full(signal_frame.height, np.nan, dtype=float)
    if signal_frame.height > 3:
        ema_slope3[3:] = ema20[3:] - ema20[:-3]

    anchors = latest_confirmed_low_anchor_indices(signal_frame.height, pivots)
    avwap = anchored_vwap(signal_frame, anchors)
    adx14 = wilder_adx(signal_frame, 14)
    adx_delta3 = np.full(signal_frame.height, np.nan, dtype=float)
    if signal_frame.height > 3:
        adx_delta3[3:] = adx14[3:] - adx14[:-3]

    base = signal_frame["entry_signal"].to_numpy().astype(bool)
    r1 = base & np.isfinite(ema_slope3) & (ema_slope3 > 0)
    r2 = base & np.isfinite(avwap) & (close > avwap)
    r3 = (
        base
        & np.isfinite(adx14)
        & np.isfinite(adx_delta3)
        & (adx14 >= 20.0)
        & (adx_delta3 < 0)
    )

    return signal_frame.with_columns(
        pl.Series("ema20", ema20),
        pl.Series("ema20_slope3", ema_slope3),
        pl.Series("latest_confirmed_low_anchor_index", anchors),
        pl.Series("anchored_vwap", avwap),
        pl.Series("adx14", adx14),
        pl.Series("adx14_delta3", adx_delta3),
        pl.Series("r1_ema_signal", r1),
        pl.Series("r2_avwap_signal", r2),
        pl.Series("r3_regime_signal", r3),
    )


def with_trial_signal(frame: pl.DataFrame, signal_column: str) -> pl.DataFrame:
    return frame.with_columns(pl.col(signal_column).alias("entry_signal"))
