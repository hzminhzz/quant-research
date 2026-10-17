from datetime import date, datetime, timedelta, timezone

import polars as pl

from scripts.run_one_bar_dukascopy_2013_2026_20261011 import exchange_day, input_files, load_and_prepare, mark_utc_timestamps


def test_source_partitions_exclude_protected_august_2026():
    paths = input_files()
    assert paths
    assert all(int(p.parent.parent.name.split("=")[1]) < 2026 or int(p.parent.name.split("=")[1]) <= 7 for p in paths)
    assert not any("year=2026/month=8/" in p.as_posix() for p in paths)


def test_globex_session_day_rolls_at_1700_chicago():
    assert exchange_day(datetime(2026, 7, 1, 20, 59, tzinfo=timezone.utc)) == date(2026, 6, 30)
    assert exchange_day(datetime(2026, 7, 1, 22, 0, tzinfo=timezone.utc)) == date(2026, 7, 1)


def test_engine_ledger_timestamps_are_explicitly_utc():
    frame = pl.DataFrame({"timestamp": [datetime(2026, 1, 1, 12, 0)]})
    marked = mark_utc_timestamps(frame, ("timestamp",))
    assert marked.schema["timestamp"].time_zone == "UTC"


def test_only_complete_bars_and_prior_50_bar_levels_are_used(tmp_path):
    start = datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc)  # 17:00 CST session open
    rows = []
    for bar in range(53):
        for minute in range(30):
            ts = start + timedelta(minutes=bar * 30 + minute)
            rows.append({
                "timestamp": ts.replace(tzinfo=None), "open": 100.0,
                "high": 200.0 if bar == 0 else 101.0, "low": 99.0,
                "close": 100.0, "volume": 1.0,
            })
    # Remove one expected minute from bar 52. It cannot qualify as a complete bar.
    rows.pop()
    path = tmp_path / "data.parquet"
    pl.DataFrame(rows).write_parquet(path)

    feed, quality = load_and_prepare([path])

    assert quality["complete_30m_bars"] == 52
    assert quality["incomplete_30m_bars"] == 1
    assert feed.filter((pl.col("session_date") == date(2026, 1, 2)) & (pl.col("bar_no") == 4)).is_empty()
    # At the end of the 50th complete bar, the next entry level uses bars 0..49.
    expected_last_time = start + timedelta(minutes=24 * 60 + 59)
    level = feed.filter(pl.col("timestamp") == expected_last_time).get_column("next_long_stop").item()
    assert level == 200.0


def test_fall_dst_session_keeps_elapsed_30_minute_bars_distinct(tmp_path):
    start = datetime(2025, 11, 1, 22, 0, tzinfo=timezone.utc)  # 17:00 CDT
    rows = []
    for i in range(25 * 60):
        rows.append({
            "timestamp": (start + timedelta(minutes=i)).replace(tzinfo=None),
            "open": 100.0, "high": 101.0, "low": 99.0,
            "close": 100.0, "volume": 1.0,
        })
    path = tmp_path / "dst.parquet"
    pl.DataFrame(rows).write_parquet(path)

    feed, quality = load_and_prepare([path])

    assert quality["complete_30m_bars"] == 50
    assert quality["incomplete_30m_bars"] == 0
    assert feed.get_column("session_date").unique().to_list() == [date(2025, 11, 1)]
    assert feed.get_column("bar_no").min() == 0
    assert feed.get_column("bar_no").max() == 49

