from datetime import datetime, timedelta, timezone

import polars as pl

from scripts.run_one_bar_execution_remediation_20261012 import (
    gap_price, next_boundary, prepare_execution_feed, run_bounded_native_checks,
    run_native_fixture, run_native_oco_fixture, run_native_market_exit_fixture,
)


def test_native_stop_market_uses_open_when_entry_gaps_through_trigger():
    long = run_native_fixture(side="buy", stop=100, opens=[99, 101], highs=[99.5, 102], lows=[98.5, 100.5])
    short = run_native_fixture(side="sell", stop=100, opens=[101, 99], highs=[101.5, 99.5], lows=[100.5, 98])
    assert long["price"].to_list() == [101.0]
    assert short["price"].to_list() == [99.0]


def test_native_protective_stop_uses_open_when_market_gaps_through_stop():
    long = run_native_fixture(side="buy", stop=100, protective=50,
        opens=[99, 100, 49], highs=[99.5, 101, 50], lows=[98.5, 99, 48])
    short = run_native_fixture(side="sell", stop=100, protective=150,
        opens=[101, 100, 151], highs=[101.5, 101, 152], lows=[100.5, 99, 150])
    assert long["price"].to_list() == [100.0, 49.0]
    assert short["price"].to_list() == [100.0, 151.0]


def test_untriggered_stop_fills_at_trigger_not_open():
    fills = run_native_fixture(side="buy", stop=100, opens=[99.0, 99.75], highs=[99.5, 100.5], lows=[98.5, 99.75])
    assert fills["price"].to_list() == [100.0]


def test_native_gap_fill_matches_independent_adverse_price_oracle():
    assert gap_price("buy", 100, 101) == 101
    assert gap_price("sell", 100, 99) == 99
    assert gap_price("buy", 100, 99) == 100
    assert gap_price("sell", 100, 101) == 100


def test_incomplete_decision_bin_keeps_available_execution_minutes():
    ts = datetime(2024, 1, 8, 17, 0, tzinfo=timezone.utc)
    raw = pl.DataFrame({"timestamp": [ts, ts + timedelta(minutes=2)],
        "open": [100.0, 101.0], "high": [101.0, 102.0], "low": [99.0, 100.0],
        "close": [100.5, 101.5], "volume": [1.0, 1.0]})
    feed, audit = prepare_execution_feed(raw)
    assert feed.height == 2
    assert feed["next_long_stop"].null_count() == 2
    assert audit["execution_minutes_without_released_signal"] == 2
    assert audit["source_open_gaps"] == 1


def test_signal_uses_fifty_complete_prior_bins_and_excludes_current_bin():
    start = datetime(2024, 1, 8, 23, 0, tzinfo=timezone.utc)
    timestamps, highs, lows = [], [], []
    for bar_no in range(52):
        for minute in range(30):
            timestamps.append(start + timedelta(minutes=30 * bar_no + minute))
            highs.append(100.0 + bar_no)
            lows.append(50.0 - bar_no)
    raw = pl.DataFrame({"timestamp": timestamps, "open": highs, "high": highs,
        "low": lows, "close": highs, "volume": [1.0] * len(highs)})
    feed, _ = prepare_execution_feed(raw)
    assert feed.filter(pl.col("timestamp") == start + timedelta(minutes=30 * 49))["next_long_stop"][0] is None
    assert feed.filter(pl.col("timestamp") == start + timedelta(minutes=30 * 50))["next_long_stop"][0] == 149.0
    assert feed.filter(pl.col("timestamp") == start + timedelta(minutes=30 * 51))["next_long_stop"][0] == 150.0


def test_fiftieth_completed_bar_releases_level_at_its_close_to_incomplete_next_bar():
    start = datetime(2024, 1, 8, 23, 0, tzinfo=timezone.utc)
    timestamps, prices = [], []
    for bar_no in range(50):
        for minute in range(30):
            timestamps.append(start + timedelta(minutes=30 * bar_no + minute))
            prices.append(100.0 + bar_no)
    release = start + timedelta(minutes=30 * 50)
    timestamps.append(release)
    prices.append(999.0)
    raw = pl.DataFrame({"timestamp": timestamps, "open": prices, "high": prices,
        "low": prices, "close": prices, "volume": [1.0] * len(prices)})
    feed, _ = prepare_execution_feed(raw)
    opening = feed.filter(pl.col("timestamp") == release)
    assert opening.height == 1
    assert opening["next_long_stop"][0] == 149.0
    assert opening["open"][0] == 999.0


def test_future_bar_mutation_does_not_change_earlier_released_signal():
    start = datetime(2024, 1, 8, 23, 0, tzinfo=timezone.utc)
    timestamps, highs, lows = [], [], []
    for bar_no in range(52):
        for minute in range(30):
            timestamps.append(start + timedelta(minutes=30 * bar_no + minute))
            highs.append(100.0 + bar_no)
            lows.append(50.0 - bar_no)
    raw = pl.DataFrame({"timestamp": timestamps, "open": highs, "high": highs,
        "low": lows, "close": highs, "volume": [1.0] * len(highs)})
    changed = raw.with_columns(
        pl.when(pl.col("timestamp") >= start + timedelta(minutes=30 * 51))
        .then(1_000_000.0).otherwise(pl.col("high")).alias("high")
    )
    original_feed, _ = prepare_execution_feed(raw)
    changed_feed, _ = prepare_execution_feed(changed)
    decision = start + timedelta(minutes=30 * 50)
    original = original_feed.filter(pl.col("timestamp") == decision)["next_long_stop"][0]
    mutated = changed_feed.filter(pl.col("timestamp") == decision)["next_long_stop"][0]
    assert original == mutated == 149.0


def test_session_gap_carries_last_released_level_to_first_real_minute():
    start = datetime(2024, 1, 8, 23, 0, tzinfo=timezone.utc)
    timestamps, values = [], []
    for bar_no in range(50):
        for minute in range(30):
            timestamps.append(start + timedelta(minutes=30 * bar_no + minute))
            values.append(100.0 + bar_no)
    after_gap = datetime(2024, 1, 10, 23, 0, tzinfo=timezone.utc)
    timestamps.append(after_gap)
    values.append(300.0)
    raw = pl.DataFrame({"timestamp": timestamps, "open": values, "high": values,
        "low": values, "close": values, "volume": [1.0] * len(values)})
    feed, _ = prepare_execution_feed(raw)
    first = feed.filter(pl.col("timestamp") == after_gap)
    assert first.height == 1
    assert first["next_long_stop"][0] == 149.0


def test_dst_repeated_hour_has_distinct_utc_exit_boundaries():
    first = datetime(2026, 11, 1, 6, 29, tzinfo=timezone.utc)
    repeated = datetime(2026, 11, 1, 7, 29, tzinfo=timezone.utc)
    assert next_boundary(first) == datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)
    assert next_boundary(repeated) == datetime(2026, 11, 1, 7, 30, tzinfo=timezone.utc)


def test_market_exit_fills_at_available_next_boundary_open_in_incomplete_bin():
    fills = run_native_market_exit_fixture(omit_boundary=False)
    assert fills["timestamp"][-1].replace(tzinfo=timezone.utc) == datetime(2024, 1, 8, 17, 0, tzinfo=timezone.utc)
    assert fills["price"][-1] == 102.0


def test_missing_boundary_open_waits_for_first_real_source_print():
    fills = run_native_market_exit_fixture(omit_boundary=True)
    assert fills["timestamp"][-1].replace(tzinfo=timezone.utc) == datetime(2024, 1, 8, 17, 10, tzinfo=timezone.utc)
    assert fills["price"][-1] == 103.0


def test_bounded_native_report_keeps_oco_blocked():
    report = run_bounded_native_checks()
    assert report["status"] == "VERIFIED"
    assert report["oco_status"].startswith("BLOCKED:")


def test_native_engine_double_fills_opposing_stops_without_oco():
    result = run_native_oco_fixture()
    assert result["both_sides_filled_same_minute"]
    assert len(result["opposing_stop_fills"]) == 2
    assert {row["side"] for row in result["opposing_stop_fills"]} == {"buy", "sell"}
    assert not result["atomic_oco_api_available"]
    assert result["status"] == "BLOCKED"
