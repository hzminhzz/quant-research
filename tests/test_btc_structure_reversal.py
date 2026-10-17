from datetime import datetime, timedelta, timezone

import numpy as np
import polars as pl

from src.btc_structure_reversal import (
    detect_fractal_pivots,
    first_crossing,
    simulate_period,
)


def _times(n: int):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(hours=i) for i in range(n)]


def _empty_funding() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "timestamp": pl.Datetime("us", "UTC"),
            "funding_rate": pl.Float64,
        }
    )


def test_fractal_pivot_is_not_available_until_right_bars_confirm():
    frame = pl.DataFrame(
        {
            "timestamp": _times(5),
            "open": [1.0] * 5,
            "high": [1.0, 2.0, 5.0, 4.0, 3.0],
            "low": [0.0] * 5,
            "close": [1.0] * 5,
        }
    )
    highs = [p for p in detect_fractal_pivots(frame) if p.kind == "H"]
    assert len(highs) == 1
    assert highs[0].pivot_index == 2
    assert highs[0].confirmation_index == 4


def test_first_crossing_requires_prior_bar_below_or_at_prior_threshold():
    bearish = np.array([True, True, True, True])
    close = np.array([9.0, 10.0, 11.0, 12.0])
    threshold = np.array([10.0, 10.0, 10.0, 12.0])
    signal = first_crossing(bearish, close, threshold)
    assert signal.tolist() == [False, False, True, False]


def test_entry_signal_fills_at_next_bar_open():
    times = _times(5)
    signals = pl.DataFrame(
        {
            "timestamp": times,
            "open": [99.0, 100.0, 101.0, 102.0, 103.0],
            "high": [100.0, 101.0, 102.0, 103.0, 104.0],
            "low": [98.0, 99.0, 100.0, 101.0, 102.0],
            "close": [99.5, 100.5, 101.5, 102.5, 103.5],
            "entry_signal": [False, True, False, False, False],
            "latest_confirmed_swing_low": [90.0] * 5,
        }
    )
    _, trades, _ = simulate_period(
        signals,
        _empty_funding(),
        start=times[0],
        end_exclusive=times[-1] + timedelta(hours=1),
        max_holding_bars=1,
    )
    assert trades.height == 1
    trade = trades.row(0, named=True)
    assert trade["signal_time"] == times[1]
    assert trade["entry_time"] == times[2]
    assert trade["entry_price"] == 101.0


def test_same_bar_stop_target_tie_resolves_to_stop():
    times = _times(4)
    signals = pl.DataFrame(
        {
            "timestamp": times,
            "open": [100.0, 100.0, 100.0, 100.0],
            "high": [100.0, 121.0, 100.0, 100.0],
            "low": [100.0, 89.0, 100.0, 100.0],
            "close": [100.0, 100.0, 100.0, 100.0],
            "entry_signal": [True, False, False, False],
            "latest_confirmed_swing_low": [90.0] * 4,
        }
    )
    _, trades, _ = simulate_period(
        signals,
        _empty_funding(),
        start=times[0],
        end_exclusive=times[-1] + timedelta(hours=1),
        target_r=2.0,
        max_holding_bars=120,
    )
    assert trades.height == 1
    trade = trades.row(0, named=True)
    assert trade["exit_reason"] == "stop"
    assert trade["exit_price"] == 90.0
