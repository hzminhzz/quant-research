"""Unit tests for Strategy 2 Phase 3 (signal study, not a backtest)."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl

from scripts.run_vwap_pullback_adx_phase3_20261012 import (
    detected_events, forward_outcome
)


def make_day(*, adx_reclaim=23.0, adx_breakout=22.0, adx_next=23.0):
    ct = ZoneInfo("America/Chicago")
    start = datetime(2026, 1, 7, 8, 30, tzinfo=ct)
    rows = []
    for i in range(41):
        stamp = start + timedelta(minutes=i)
        high, low, close = 100.0, 99.0, 99.5
        adx = 22.0
        if i == 30:
            high, low, close, adx = 101.0, 99.6, 100.5, adx_breakout
        if i == 31:
            high, low, close, adx = 100.8, 98.0, 100.25, adx_reclaim
        if i == 32:
            high, low, close, adx = 101.0, 99.5, 100.75, adx_next
        rows.append(dict(timestamp=stamp.astimezone(ZoneInfo("UTC")),
                         ct=stamp, high=high, low=low, close=close,
                         open=close-0.125, vwap=99.0, adx=adx))
    return pl.DataFrame(rows)


def test_same_candle_touch_reclaim_adx_gate():
    bars = make_day(adx_reclaim=21.5, adx_breakout=22.0)
    r = detected_events(bars)
    assert r["b1"] == 30
    assert r["b2"] == 31
    assert r["b3"] == 31
    assert r["adx_wait_minutes"] == 0


def test_lagged_adx_wait():
    bars = make_day(adx_reclaim=23.0, adx_breakout=22.0, adx_next=23.0)
    r = detected_events(bars)
    assert r["b1"] == 30
    assert r["b2"] == 31
    assert r["b3"] == 32
    assert r["adx_wait_minutes"] == 1


def test_next_open_forward_label_not_signal_close():
    bars = make_day()
    label = forward_outcome(bars, 31, 1)
    assert label is not None
    assert abs(label["points"] - (bars["close"][32] - bars["open"][32])) < 1e-10


def test_missing_future_minute_invalidates_label():
    bars = make_day().filter(pl.col("ct").dt.strftime("%H:%M") != pl.lit("09:02"))
    assert forward_outcome(bars, 31, 1) is None
