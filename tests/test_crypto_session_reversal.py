from __future__ import annotations

from datetime import datetime, timedelta, timezone

import polars as pl

from scripts.run_crypto_session_reversal import make_sessions, run_variant


def synthetic_bars(days: int = 5) -> pl.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    price = 100.0
    for i in range(days * 24 * 12):
        ts = start + timedelta(minutes=5 * i)
        price *= 1.00001
        rows.append({
            "timestamp": ts,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": 1.0,
        })
    return pl.DataFrame(rows)


def test_same_session_signal_is_lagged_and_reversed() -> None:
    sessions = make_sessions(synthetic_bars(), 8)
    realized = sessions.filter(pl.col("lag_same_session").is_not_null())
    assert realized.height > 0
    assert realized.filter(
        pl.col("position") != -pl.col("lag_same_session").sign()
    ).height == 0


def test_costs_reduce_returns_and_count_turnover() -> None:
    sessions = make_sessions(synthetic_bars(), 8)
    zero = run_variant(sessions, 0.0)
    costly = run_variant(sessions, 3.0)
    assert costly["cost_drag_sum"] >= 0
    assert costly["all"]["total_return"] <= zero["all"]["total_return"]
    assert costly["trade_events"] >= 1
