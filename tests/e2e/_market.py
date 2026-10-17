"""Deterministic synthetic markets for end-to-end harness tests.

The generators answer one question: does the data contain an edge, and if so,
where? An end-to-end test can then assert that ``src.backtest`` reports the
edge that is actually present, in the correct direction and magnitude.

Nothing here reads gitignored artifacts, so every test built on these helpers
runs in the fast lane.
"""

from __future__ import annotations

import numpy as np
import polars as pl

__all__ = [
    "ohlcv",
    "random_walk",
    "momentum_signal",
    "periodic_signal",
    "drift_during_holding",
]

BARS_PER_DAY = 96  # 15-minute bars
DEFAULT_HOLDING_BARS = 6


def _timestamps(n: int) -> list[str]:
    """ISO bar stamps at a 15-minute step, so the daily downsample stays meaningful."""
    start = np.datetime64("2024-01-01T00:00:00")
    stamps = start + np.arange(n) * np.timedelta64(15, "m")
    return [str(stamp) for stamp in stamps]


def ohlcv(closes: np.ndarray, signal: np.ndarray) -> pl.DataFrame:
    """Wrap closes and a boolean entry signal into the frame the engine reads."""
    closes = np.asarray(closes, dtype=float)
    signal = np.asarray(signal, dtype=bool)
    if closes.shape != signal.shape:
        raise ValueError(f"shape mismatch: {closes.shape} vs {signal.shape}")

    n = closes.size
    return pl.DataFrame(
        {
            "timestamp": _timestamps(n),
            "open": closes,
            "high": closes * 1.0005,
            "low": closes * 0.9995,
            "close": closes,
            "volume": np.full(n, 1_000.0),
            "signal": signal,
        }
    )


def random_walk(
    n: int,
    seed: int,
    sigma: float = 0.001,
    start: float = 100.0,
) -> np.ndarray:
    """Positive, seeded geometric random walk with no exploitable structure."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0, sigma, n)
    return start * np.exp(np.cumsum(returns))


def momentum_signal(closes: np.ndarray, lookback: int = 20) -> np.ndarray:
    """Causal signal: close above its own value ``lookback`` bars ago."""
    closes = np.asarray(closes, dtype=float)
    signal = np.zeros(closes.size, dtype=bool)
    signal[lookback:] = closes[lookback:] > closes[:-lookback]
    return signal


def periodic_signal(n: int, every: int) -> np.ndarray:
    """Exogenous signal at fixed bar indices, never at bar 0.

    Index 0 stays ``False`` because the generator replays engine state starting
    from bar 1; the engine processes bar 0 first. Keeping both aligned makes
    holding windows match between generator and backtest.
    """
    signal = np.zeros(n, dtype=bool)
    signal[every:n:every] = True
    return signal


def drift_during_holding(
    n: int,
    seed: int,
    signal: np.ndarray,
    holding_bars: int = DEFAULT_HOLDING_BARS,
    per_bar_drift: float = 0.001,
    sigma: float = 0.001,
    start: float = 100.0,
) -> np.ndarray:
    """Closes that carry ``per_bar_drift`` exactly while the engine holds a position.

    The replay mirrors ``src.backtest.run_intraday_backtest``: exit check first,
    then entry check, both at the same bar. Bar 0 opens flat, so the first drift
    bar is the bar after the first entry.
    """
    signal = np.asarray(signal, dtype=bool)
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, sigma, n)

    closes = np.empty(n)
    closes[0] = start

    position = 0
    bars_held = 0
    in_position = False

    for t in range(1, n):
        excess = per_bar_drift if in_position else 0.0
        closes[t] = closes[t - 1] * (1.0 + noise[t] + excess)

        if position == 1:
            bars_held += 1
            if bars_held >= holding_bars:
                position = 0
                bars_held = 0
        if position == 0 and signal[t]:
            position = 1
            bars_held = 0
        in_position = position == 1

    return closes
