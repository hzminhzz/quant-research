"""Causality and event-outcome checks for the frozen structural FX diagnostic."""

from datetime import datetime, timedelta, timezone

import numpy as np
import polars as pl

from scripts.run_fx_support_newhigh_d0 import (
    _candidate_pivots,
    _select_first_retests,
)


def _fixture(*, retest_bar=105, retest_close=100.4, future_high=True):
    n = 1_200
    highs = np.full(n, 101.0)
    lows = np.full(n, 99.7)
    closes = np.full(n, 100.3)
    highs[100] = 105.0
    highs[101:104] = 104.0
    lows[retest_bar] = 99.1
    closes[retest_bar] = retest_close
    if future_high:
        highs[150] = 105.2

    ts = [
        datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=30 * i)
        for i in range(n)
    ]
    return pl.DataFrame(
        {
            "timestamp": ts,
            "high": highs,
            "low": lows,
            "close": closes,
            "support": np.full(n, 99.0),
            "atr20": np.full(n, 1.0),
            "prior_40_high": np.full(n, 101.0),
        }
    )


def test_significant_high_is_not_signal_before_three_confirmation_bars():
    bars = _fixture(retest_bar=102)
    pivots = _candidate_pivots(bars)
    assert 100 in pivots
    events = _select_first_retests(bars)
    assert events.is_empty()


def test_hold_and_future_high_are_labeled_only_after_signal():
    events = _select_first_retests(_fixture())
    assert events.height == 1
    row = events.row(0, named=True)
    assert row["support_held"] is True
    assert row["within_48_bars"] is True
    assert row["within_240_bars"] is True
    assert row["target_before_support_invalidation_240"] is True
    assert row["first_new_high_bars"] == 45


def test_support_break_close_is_control_not_hold():
    events = _select_first_retests(_fixture(retest_close=98.9))
    assert events.height == 1
    assert events["support_held"][0] is False


def test_no_new_high_does_not_count_as_success():
    events = _select_first_retests(_fixture(future_high=False))
    assert events.height == 1
    assert events["within_48_bars"][0] is False
    assert events["within_240_bars"][0] is False
    assert events["within_960_bars"][0] is False
