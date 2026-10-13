from datetime import UTC, datetime, timedelta

import polars as pl

from scripts.prepare_m8_n8_data import aggregate_30m


def source_minutes(*, gap: int | None = None) -> pl.DataFrame:
    start = datetime(2024, 1, 2, tzinfo=UTC)
    rows = []
    for index in range(70):
        if index == gap:
            continue
        price = 100.0 + index
        rows.append(
            {
                "timestamp": start + timedelta(minutes=index),
                "symbol": "NQ",
                "open": price,
                "high": price + 2,
                "low": price - 1,
                "close": price + 1,
                "volume": 10.0,
            }
        )
    return pl.DataFrame(rows)


def test_30m_ohlcv_aggregation_keeps_complete_bins_and_matches_fields():
    bars = aggregate_30m(source_minutes())
    assert bars.height == 2
    first, second = bars.to_dicts()
    assert first["timestamp"] == datetime(2024, 1, 2, tzinfo=UTC)
    assert (
        first["open"],
        first["high"],
        first["low"],
        first["close"],
        first["volume"],
    ) == (100.0, 131.0, 99.0, 130.0, 300.0)
    assert second["timestamp"] == datetime(2024, 1, 2, 0, 30, tzinfo=UTC)
    assert (
        second["open"],
        second["high"],
        second["low"],
        second["close"],
        second["volume"],
    ) == (130.0, 161.0, 129.0, 160.0, 300.0)


def test_30m_aggregation_rejects_bins_with_a_missing_minute():
    bars = aggregate_30m(source_minutes(gap=35))
    assert bars.height == 1
    assert bars["timestamp"][0] == datetime(2024, 1, 2, tzinfo=UTC)
