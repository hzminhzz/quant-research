from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl
import pytest

import scripts.run_one_bar_practical_yearly_20261012 as yearly
from scripts.run_one_bar_practical_yearly_20261012 import (
    add_breakout_features,
    ambiguous_loss_bound,
    chicago_session_day,
    eligible_years,
    next_30m_boundary,
    with_session_day,
)


def test_year_range_covers_2013_through_partial_2026():
    assert eligible_years() == list(range(2013, 2027))


def test_session_assignment_uses_chicago_dst_and_globex_boundary():
    before_winter_open = datetime(2024, 1, 1, 22, 59, tzinfo=timezone.utc)
    at_winter_open = datetime(2024, 1, 1, 23, 0, tzinfo=timezone.utc)
    before_summer_open = datetime(2024, 7, 1, 21, 59, tzinfo=timezone.utc)
    at_summer_open = datetime(2024, 7, 1, 22, 0, tzinfo=timezone.utc)

    assert str(chicago_session_day(before_winter_open)) == "2023-12-31"
    assert str(chicago_session_day(at_winter_open)) == "2024-01-01"
    assert str(chicago_session_day(before_summer_open)) == "2024-06-30"
    assert str(chicago_session_day(at_summer_open)) == "2024-07-01"


def test_polars_session_assignment_does_not_overflow_hour_arithmetic():
    timestamps = [datetime(2024, 1, 1, 22, 59, tzinfo=timezone.utc),
                  datetime(2024, 1, 1, 23, 0, tzinfo=timezone.utc),
                  datetime(2024, 7, 1, 21, 59, tzinfo=timezone.utc),
                  datetime(2024, 7, 1, 22, 0, tzinfo=timezone.utc)]
    assigned = with_session_day(pl.DataFrame({"timestamp": timestamps}))
    assert assigned["session_date"].to_list() == [
        datetime(2023, 12, 31).date(), datetime(2024, 1, 1).date(),
        datetime(2024, 6, 30).date(), datetime(2024, 7, 1).date(),
    ]


def test_ambiguous_event_bound_charges_worst_case_and_round_trip_cost():
    assert ambiguous_loss_bound(500.0,
        ["entry_and_protective_stop_same_candle", "both_entry_stops_filled"],
        2.5, 0.25) == -2545.0


def test_scheduled_exit_advances_to_next_half_hour_boundary():
    entry = datetime(2024, 3, 10, 7, 29, tzinfo=timezone.utc)
    assert next_30m_boundary(entry) == datetime(2024, 3, 10, 7, 30, tzinfo=timezone.utc)


def test_ml4t_donchian_levels_match_the_50_bar_breakout_window():
    bars = pl.DataFrame({
        "bar_start": [
            datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=30 * i)
            for i in range(52)
        ],
        "bar_open": [100.0] * 52,
        "bar_high": [100.0 + i for i in range(52)],
        "bar_low": [50.0 + i for i in range(52)],
        "bar_close": [100.0] * 52,
        "bar_volume": [1.0] * 52,
    })

    enriched = add_breakout_features(bars)

    assert enriched["next_long_stop"].to_list()[48:51] == [None, 149.0, 150.0]
    assert enriched["next_short_stop"].to_list()[48:51] == [None, 50.0, 51.0]



def test_build_year_feed_aggregates_complete_bins_and_releases_levels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    start = datetime(2013, 1, 2, 23, tzinfo=timezone.utc)
    timestamps = [start + timedelta(minutes=i) for i in range(51 * 30 + 2)]
    bar_numbers = [i // 30 for i in range(len(timestamps))]
    source = tmp_path / "minutes.parquet"
    pl.DataFrame({
        "timestamp": timestamps,
        "open": [100.0 + bar for bar in bar_numbers],
        "high": [101.0 + bar for bar in bar_numbers],
        "low": [50.0 + bar for bar in bar_numbers],
        "close": [100.5 + bar for bar in bar_numbers],
        "volume": [1.0] * len(timestamps),
    }).write_parquet(source)

    def files_for_year(_: int) -> list[Path]:
        return [source]

    monkeypatch.setattr(yearly, "files_for_year", files_for_year)

    feed, quality = yearly.build_year_feed(2013)

    assert quality["complete_30m_bars"] == 51
    assert quality["incomplete_30m_bins"] == 1
    assert quality["execution_rows_retained"] == len(timestamps)
    assert feed["timestamp"][1498] == timestamps[1498]
    assert feed["next_long_stop"][1498] is None
    assert feed["timestamp"][1499] == timestamps[1499]
    assert feed["next_long_stop"][1499] == 150.0
    assert feed["next_short_stop"][1499] == 50.0
    assert feed["next_long_stop"][1529] == 151.0
    assert feed["timestamp"][-1] == timestamps[-1]
    assert feed["next_long_stop"][-1] == 151.0

