from __future__ import annotations

from datetime import datetime, timedelta, timezone

import polars as pl

from scripts.run_crypto_high_momentum import make_weekly_factor_frame


def synthetic_panel(hours: int = 2400) -> pl.DataFrame:
    start = datetime(2020, 1, 6, tzinfo=timezone.utc)
    rows = []
    for j in range(12):
        price = 100.0 + j
        for i in range(hours):
            ts = start + timedelta(hours=i)
            price *= 1.0 + (j + 1) * 1e-6
            rows.append({"timestamp": ts, "symbol": f"S{j}", "open": price, "high": price, "low": price, "close": price, "volume": 1000.0 + j})
    return pl.DataFrame(rows)


def test_factor_uses_prior_close_not_current_close() -> None:
    df = synthetic_panel()
    frame = make_weekly_factor_frame(df, 168)
    assert frame.height > 0
    row = frame.row(0, named=True)
    source = df.filter((pl.col("symbol") == row["symbol"]) & (pl.col("timestamp") < row["timestamp"])).sort("timestamp")
    expected_prior = source["close"][-1]
    expected_high = source["close"].tail(168).max()
    assert abs(row["prior_close"] - expected_prior) < 1e-12
    assert abs(row["signal"] - (expected_prior / expected_high - 1.0)) < 1e-12


def test_liquidity_filter_keeps_cross_section_causal() -> None:
    frame = make_weekly_factor_frame(synthetic_panel(), 168)
    counts = frame.group_by("timestamp").len()["len"]
    assert counts.min() >= 8
    assert counts.max() <= 12
