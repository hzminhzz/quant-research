from __future__ import annotations

from datetime import UTC, datetime

import polars as pl

from scripts.run_crypto_xs_plain_funding_decay_validation_execution_fix1_20261015 import (
    validation_funding_events_by_hour,
)


def test_validation_funding_helper_keeps_2024_and_excludes_2026():
    frame = pl.DataFrame({
        "timestamp": [
            datetime(2023, 12, 31, 20, tzinfo=UTC),
            datetime(2024, 1, 1, 0, 0, 0, 1000, tzinfo=UTC),
            datetime(2025, 12, 31, 20, tzinfo=UTC),
            datetime(2026, 1, 1, 0, tzinfo=UTC),
        ],
        "symbol": ["BTCUSDT"] * 4,
        "funding_rate": [0.1, 0.2, 0.3, 0.4],
        "mark_price": [100.0] * 4,
    })
    result = validation_funding_events_by_hour(frame, {"BTCUSDT"})
    events = [item for rows in result.values() for item in rows]
    assert [item["funding_rate"] for item in events] == [0.2, 0.3]
