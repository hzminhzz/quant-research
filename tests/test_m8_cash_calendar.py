from datetime import UTC, datetime, timedelta

import pytest

from src.research_control.m8_cash_calendar import (
    assert_planned_fill_bars_present,
    cash_session_dates,
    cash_session_signal_eligible,
)


@pytest.mark.parametrize(
    ("signal", "expected"),
    [
        (datetime(2024, 3, 8, 15, 0, tzinfo=UTC), True),  # EST close: 21:00Z
        (datetime(2024, 3, 11, 13, 30, tzinfo=UTC), True),  # EDT open: 13:30Z
        (datetime(2024, 11, 1, 13, 30, tzinfo=UTC), True),  # EDT
        (datetime(2024, 11, 4, 14, 30, tzinfo=UTC), True),  # EST
        (datetime(2024, 3, 11, 13, 0, tzinfo=UTC), False),  # before open
        (datetime(2024, 3, 11, 19, 0, tzinfo=UTC), False),  # exit at close
    ],
)
def test_cash_session_dst_and_regular_boundaries(signal, expected):
    assert cash_session_signal_eligible(signal) is expected


@pytest.mark.parametrize(
    ("signal", "expected"),
    [
        (datetime(2024, 7, 3, 15, 30, tzinfo=UTC), True),  # close 17:00Z
        (datetime(2024, 7, 3, 16, 0, tzinfo=UTC), False),
        (datetime(2024, 12, 24, 16, 30, tzinfo=UTC), True),  # close 18:00Z
        (datetime(2024, 12, 24, 17, 0, tzinfo=UTC), False),
    ],
)
def test_cash_session_early_closes(signal, expected):
    assert cash_session_signal_eligible(signal) is expected


def test_cash_session_filter_does_not_accept_holdout_crossing():
    assert not cash_session_signal_eligible(
        datetime(2024, 12, 31, 23, 0, tzinfo=UTC)
    )
    assert not cash_session_signal_eligible(
        datetime(2025, 1, 2, 15, 0, tzinfo=UTC)
    )


def test_calendar_eligibility_has_no_provider_rows_and_missing_fill_fails_whole_set():
    signal = datetime(2024, 3, 11, 13, 30, tzinfo=UTC)
    assert cash_session_signal_eligible(signal)
    observed = {signal, signal + timedelta(minutes=30)}
    with pytest.raises(RuntimeError, match="EXECUTION_EXCEPTION"):
        assert_planned_fill_bars_present(observed, [signal])


def test_daily_calendar_clips_half_open_evaluation_bounds_to_available_sessions():
    days = cash_session_dates(
        datetime(2020, 1, 1, tzinfo=UTC),
        datetime(2025, 1, 1, tzinfo=UTC),
    )
    assert days[0].isoformat() == "2020-01-02"
    assert days[-1].isoformat() == "2024-12-31"
    assert "2024-07-03" in {day.isoformat() for day in days}
