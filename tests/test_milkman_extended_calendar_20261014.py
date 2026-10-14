"""Calendar and holdout gates for 2015-2024 Milkman native extension."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from scripts.run_milkman_extended_2015_2024 import _rth_15m, _time


def minute_day(date: datetime) -> pl.DataFrame:
    # NYC RTH has exactly 390 minutes on normal days.
    t=[date+timedelta(minutes=i) for i in range(390)]
    return pl.DataFrame({
        "timestamp":t,"open":[100.] * 390,"high":[101.] * 390,
        "low":[99.] * 390,"close":[100.] * 390,"volume":[1000.] * 390,
    })


@pytest.mark.parametrize("day",[
    datetime(2022,1,4,14,30,tzinfo=UTC),  # EST
    datetime(2022,6,6,13,30,tzinfo=UTC),  # EDT
])
def test_exact_26_rth_15min_bars(day):
    raw=minute_day(day)
    bars=_rth_15m(raw)
    assert bars.height==26
    assert all(bars["session_date"]==bars["session_date"][0])
    assert bars["timestamp"][0]==day+timedelta(minutes=15)
    assert bars["timestamp"][-1]==day+timedelta(minutes=390)


def test_protected_year_cutoff():
    assert _time(2015)[0]==datetime(2015,1,1,tzinfo=UTC)
    assert _time(2024)[1]==datetime(2025,1,1,tzinfo=UTC)
    with pytest.raises(ValueError):
        _time(2025)
    with pytest.raises(ValueError):
        _time(2014)
