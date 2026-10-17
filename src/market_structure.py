"""Causal ATR-reversal pivots and a frozen long-only structure setup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl


@dataclass(frozen=True)
class Pivot:
    kind: str
    extremum_index: int
    confirmation_index: int
    price: float
    classification: str | None


def _wilder_atr(frame: pl.DataFrame, period: int = 14) -> np.ndarray:
    high, low, close = (frame[name].to_numpy() for name in ("high", "low", "close"))
    atr = np.empty(len(frame), dtype=float)
    previous_close = close[0]
    for i in range(len(frame)):
        tr = max(high[i] - low[i], abs(high[i] - previous_close), abs(low[i] - previous_close))
        atr[i] = tr if i == 0 else (atr[i - 1] * (period - 1) + tr) / period
        previous_close = close[i]
    return atr


def detect_pivots(frame: pl.DataFrame, atr_period: int = 14, reversal_atr: float = 1.0) -> tuple[np.ndarray, list[Pivot]]:
    """Confirm pivots from close reversals; expose each pivot only at confirmation."""
    if frame.height == 0:
        return np.array([], dtype=float), []
    atr = _wilder_atr(frame, atr_period)
    high, low, close = (frame[name].to_numpy() for name in ("high", "low", "close"))
    pivots: list[Pivot] = []
    direction = 0  # +1 tracks a peak; -1 tracks a trough
    trough_i = peak_i = 0
    trough, peak = float(low[0]), float(high[0])
    trough_atr = peak_atr = float(atr[0])
    previous_low: float | None = None
    previous_high: float | None = None

    def append(kind: str, extremum: int, confirmation: int, price: float) -> None:
        nonlocal previous_low, previous_high
        prev = previous_low if kind == "L" else previous_high
        code = None
        if prev is not None:
            code = ("HL" if price > prev else "LL") if kind == "L" else ("HH" if price > prev else "LH")
        pivots.append(Pivot(kind, extremum, confirmation, price, code))
        if kind == "L":
            previous_low = price
        else:
            previous_high = price

    for i in range(1, len(frame)):
        if direction == 0:
            if low[i] < trough:
                trough_i, trough, trough_atr = i, float(low[i]), float(atr[i])
            if high[i] > peak:
                peak_i, peak, peak_atr = i, float(high[i]), float(atr[i])
            if close[i] >= trough + reversal_atr * trough_atr:
                append("L", trough_i, i, trough)
                direction = 1
                peak_i, peak, peak_atr = i, float(high[i]), float(atr[i])
            elif close[i] <= peak - reversal_atr * peak_atr:
                append("H", peak_i, i, peak)
                direction = -1
                trough_i, trough, trough_atr = i, float(low[i]), float(atr[i])
        elif direction == 1:
            if high[i] > peak:
                peak_i, peak, peak_atr = i, float(high[i]), float(atr[i])
            if close[i] <= peak - reversal_atr * peak_atr:
                append("H", peak_i, i, peak)
                direction = -1
                trough_i, trough, trough_atr = i, float(low[i]), float(atr[i])
        else:
            if low[i] < trough:
                trough_i, trough, trough_atr = i, float(low[i]), float(atr[i])
            if close[i] >= trough + reversal_atr * trough_atr:
                append("L", trough_i, i, trough)
                direction = 1
                peak_i, peak, peak_atr = i, float(high[i]), float(atr[i])
    return atr, pivots


def build_signals(frame: pl.DataFrame) -> tuple[pl.DataFrame, list[dict[str, Any]]]:
    """Create entry and structure-exit flags using only confirmed pivots."""
    atr, pivots = detect_pivots(frame)
    entries = np.zeros(frame.height, dtype=bool)
    entry_invalidation_level = np.full(frame.height, np.nan, dtype=float)
    confirmed_swing_low = np.full(frame.height, np.nan, dtype=float)
    pivot_records = [
        {"type": p.kind, "classification": p.classification, "extremum_index": p.extremum_index,
         "confirmation_index": p.confirmation_index, "price": p.price}
        for p in pivots
    ]
    # Match the fixed event grammar LL, LL..., HL, HH, HL, HH.
    state = 0
    ll_count = 0
    setup_hl: float | None = None
    second_hl: float | None = None
    for p in pivots:
        if p.kind == "L":
            confirmed_swing_low[p.confirmation_index] = p.price
        c = p.classification
        if state == 0:
            if p.kind == "L" and c == "LL":
                ll_count += 1
                if ll_count >= 2:
                    state = 1
            elif p.kind == "L":
                ll_count = 0
        elif state == 1:  # wait for first HL; another LL keeps bearish sequence alive
            if p.kind == "L" and c == "HL":
                setup_hl = p.price
                state = 2
            elif p.kind == "L" and c != "LL":
                state, ll_count = 0, 0
        elif state == 2:
            if p.kind == "H" and c == "HH":
                state = 3
            elif p.kind == "L" and c == "LL":
                state, ll_count = 1, 0
        elif state == 3:
            if p.kind == "L" and c == "HL":
                second_hl = p.price
                state = 4
            elif p.kind == "L" and c == "LL":
                state, ll_count = 1, 0
        elif state == 4:
            if p.kind == "H" and c == "HH":
                entries[p.confirmation_index] = True
                entry_invalidation_level[p.confirmation_index] = float(second_hl)
                state, ll_count = 0, 0
                setup_hl = None
                second_hl = None
            elif p.kind == "L" and c == "LL":
                state, ll_count = 1, 0
    return frame.with_columns(
        pl.Series("atr14", atr),
        pl.Series("entry_signal", entries),
        pl.Series("entry_invalidation_level", entry_invalidation_level),
        pl.Series("confirmed_swing_low", confirmed_swing_low),
    ), pivot_records

