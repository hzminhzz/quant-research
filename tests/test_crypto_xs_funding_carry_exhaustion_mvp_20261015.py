"""Causal tests for the frozen cross-sectional funding-carry MVP."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from scripts.run_crypto_xs_funding_carry_exhaustion_mvp_20261015 import (
    MIN_HISTORY,
    funding_features,
    native_price_features,
)


def sample_prices(n: int = 760) -> pl.DataFrame:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    rows = []
    for j, symbol in enumerate(("AAAUSDT", "BBBUSDT")):
        base = 100.0 + 20 * j
        for i in range(n):
            close = base + 0.05 * i + np.sin(i / 13)
            rows.append({
                "timestamp": start + timedelta(hours=i),
                "symbol": symbol,
                "open": close - 0.1,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 10.0 + (i % 11),
            })
    return pl.DataFrame(rows).sort("symbol", "timestamp")


def sample_funding() -> pl.DataFrame:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    rows = []
    for symbol, sign in (("AAAUSDT", 1.0), ("BBBUSDT", -1.0)):
        for i in range(8):
            rows.append({
                "timestamp": start + timedelta(hours=8*i, milliseconds=i % 3),
                "symbol": symbol,
                "funding_interval_hours": 8,
                "funding_rate": sign * (0.0001 + i * 0.00001),
                "mark_price": 100.0,
            })
    return pl.DataFrame(rows)


def test_native_grouped_features_are_symbol_isolated_and_have_expected_warmup():
    raw = sample_prices()
    f = native_price_features(raw)
    for symbol in ("AAAUSDT", "BBBUSDT"):
        one = f.filter(pl.col("symbol") == symbol).sort("timestamp")
        assert one["ret24"][23] is None
        assert one["ret24"][24] == pytest.approx(one["close"][24] / one["close"][0] - 1)
        assert one["dollar_volume_720h"][MIN_HISTORY - 2] is None
        expected = float((one["close"][:MIN_HISTORY] * one["volume"][:MIN_HISTORY]).sum())
        assert one["dollar_volume_720h"][MIN_HISTORY - 1] == pytest.approx(expected)


def test_future_price_changes_do_not_change_past_features():
    raw = sample_prices()
    first = native_price_features(raw)
    cutoff = datetime(2020, 1, 26, tzinfo=UTC)
    revised = raw.with_columns(
        pl.when(pl.col("timestamp") >= cutoff)
        .then(pl.col("close") * 7)
        .otherwise(pl.col("close"))
        .alias("close"),
        pl.when(pl.col("timestamp") >= cutoff)
        .then(pl.col("volume") * 9)
        .otherwise(pl.col("volume"))
        .alias("volume"),
    )
    second = native_price_features(revised)
    for col in ("ret24", "atr24", "dollar_volume_720h"):
        a = first.filter(pl.col("timestamp") < cutoff)[col].to_numpy()
        b = second.filter(pl.col("timestamp") < cutoff)[col].to_numpy()
        np.testing.assert_allclose(a, b, rtol=0, atol=1e-10, equal_nan=True)


def test_funding_24h_sum_uses_all_actual_settlements_in_window():
    f = funding_features(sample_funding())
    one = f.filter(pl.col("symbol") == "AAAUSDT").sort("timestamp")
    assert one["cum_funding_24h"][0] == pytest.approx(0.0001)
    assert one["cum_funding_24h"][2] == pytest.approx(0.0001 + 0.00011 + 0.00012)
    # At +24h the left endpoint is excluded: 0h drops out.
    assert one["cum_funding_24h"][3] == pytest.approx(0.00011 + 0.00012 + 0.00013)
    assert one["funding_events_24h"][3] == 3


def test_duplicate_exact_funding_timestamp_fails_closed():
    f = sample_funding()
    dup = pl.concat([f, f.head(1)])
    with pytest.raises(ValueError, match="Duplicate exact funding timestamps"):
        funding_features(dup)
