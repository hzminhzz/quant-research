from datetime import date, datetime, time, timedelta, timezone

import polars as pl
import pytest

from src.market_time import (
    BarTimestampSpec,
    SessionSpec,
    TimestampContractError,
    available_at,
    canonicalize_utc_timestamp,
    localize_strict,
    session_window,
)


def test_berlin_cash_open_follows_dst():
    spec = SessionSpec("DE30_cash_open", "Europe/Berlin", time(9))
    winter, _, _ = session_window(date(2026, 1, 15), spec)
    summer, _, _ = session_window(date(2026, 7, 15), spec)
    assert winter == datetime(2026, 1, 15, 8, tzinfo=timezone.utc)
    assert summer == datetime(2026, 7, 15, 7, tzinfo=timezone.utc)


def test_de30_new_york_overlap_moves_in_winter():
    spec = SessionSpec(
        "DE30_new_york_overlap",
        "America/New_York",
        time(9),
        calendar_timezone="Europe/Berlin",
    )
    summer, _, _ = session_window(date(2026, 7, 15), spec)
    winter, _, _ = session_window(date(2026, 1, 15), spec)
    assert summer == datetime(2026, 7, 15, 13, tzinfo=timezone.utc)
    assert winter == datetime(2026, 1, 15, 14, tzinfo=timezone.utc)


def test_de30_new_york_overlap_uses_us_not_eu_dst_in_mismatch_week():
    spec = SessionSpec(
        "DE30_new_york_overlap",
        "America/New_York",
        time(9),
        calendar_timezone="Europe/Berlin",
    )
    before_us_dst, _, _ = session_window(date(2026, 3, 6), spec)
    after_us_before_eu, _, _ = session_window(date(2026, 3, 9), spec)
    assert before_us_dst == datetime(2026, 3, 6, 14, tzinfo=timezone.utc)
    assert after_us_before_eu == datetime(2026, 3, 9, 13, tzinfo=timezone.utc)


def test_new_york_half_hour_open_follows_dst_and_mismatch_week():
    spec = SessionSpec("NAS100_cash_open", "America/New_York", time(9, 30))
    before_us_dst, _, _ = session_window(date(2026, 3, 6), spec)
    mismatch, _, _ = session_window(date(2026, 3, 9), spec)
    after_eu_dst, _, _ = session_window(date(2026, 3, 30), spec)
    assert before_us_dst.hour == 14
    assert mismatch == datetime(2026, 3, 9, 13, 30, tzinfo=timezone.utc)
    assert after_eu_dst == datetime(2026, 3, 30, 13, 30, tzinfo=timezone.utc)


def test_strict_localization_rejects_nonexistent_and_ambiguous_times():
    with pytest.raises(TimestampContractError, match="nonexistent"):
        localize_strict(datetime(2026, 3, 8, 2, 30), "America/New_York")
    with pytest.raises(TimestampContractError, match="ambiguous"):
        localize_strict(datetime(2026, 11, 1, 1, 30), "America/New_York")
    first = localize_strict(datetime(2026, 11, 1, 1, 30), "America/New_York", fold=0)
    second = localize_strict(datetime(2026, 11, 1, 1, 30), "America/New_York", fold=1)
    assert first.utcoffset() != second.utcoffset()


def test_open_and_close_bar_availability_differ():
    ts = datetime(2026, 1, 2, 9, tzinfo=timezone.utc)
    duration = timedelta(minutes=5)
    assert available_at(ts, BarTimestampSpec("open", duration)) == ts + duration
    assert available_at(ts, BarTimestampSpec("close", duration)) == ts


def test_unknown_semantics_fail_closed():
    with pytest.raises(TimestampContractError):
        BarTimestampSpec("unknown", timedelta(minutes=5))  # type: ignore[arg-type]


def test_naive_input_requires_explicit_source_timezone():
    df = pl.DataFrame({"timestamp": ["2026-01-01 09:00:00"]})
    with pytest.raises(TimestampContractError):
        canonicalize_utc_timestamp(df)
    result = canonicalize_utc_timestamp(df, source_timezone="Europe/Berlin")
    assert result["timestamp"][0] == datetime(2026, 1, 1, 8, tzinfo=timezone.utc)


def test_unsorted_and_duplicate_timestamps_fail():
    unsorted = pl.DataFrame(
        {"timestamp": [datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, 0, tzinfo=timezone.utc)]}
    )
    duplicate = pl.DataFrame(
        {"timestamp": [datetime(2026, 1, 1, 0, tzinfo=timezone.utc)] * 2}
    )
    with pytest.raises(TimestampContractError, match="sorted"):
        canonicalize_utc_timestamp(unsorted)
    with pytest.raises(TimestampContractError, match="duplicate"):
        canonicalize_utc_timestamp(duplicate)
