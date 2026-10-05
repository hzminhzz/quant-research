from datetime import datetime, timedelta, timezone, time

import polars as pl

from src.labeling import MetaLabelingORBDatasetBuilder
from src.market_time import BarTimestampSpec, SessionSpec

UTC = timezone.utc


def test_timestamp_window_builder_uses_next_bar_execution_and_decision_time():
    rows = []
    start = datetime(2026, 1, 15, 7, 55, tzinfo=UTC)
    for i in range(30):
        ts = start + timedelta(minutes=5 * i)
        if i < 12:
            close = 100.0 + (i % 2) * 0.05
            high = 101.0
            low = 99.0
        elif i == 12:
            close = 102.0
            high = 102.2
            low = 101.8
        else:
            close = 102.0 + min(i - 12, 3) * 0.1
            high = close + 0.1
            low = close - 0.1
        rows.append(
            {
                "timestamp": ts,
                "open": close - 0.2,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1000.0,
                "atr20_bar": 0.5,
                "ema_200": 95.0,
            }
        )
    events = MetaLabelingORBDatasetBuilder(stretch_k=0.05).extract_events_and_labels(
        pl.DataFrame(rows),
        symbol="DE30/EUR",
        sessions=[SessionSpec("DE30_cash_open", "Europe/Berlin", time(9))],
        bar_spec=BarTimestampSpec("open", timedelta(minutes=5)),
    )
    assert len(events) == 1
    event = events[0]
    assert event.decision_time == "2026-01-15T09:00:00+00:00"
    assert event.entry_time == "2026-01-15T09:00:00+00:00"
    assert event.entry_price == rows[13]["open"]
    assert event.entry_time >= event.decision_time
