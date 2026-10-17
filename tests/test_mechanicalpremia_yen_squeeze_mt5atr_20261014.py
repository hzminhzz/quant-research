"""Numerical MT5-style ATR feature parity and causal feature-clock checks."""
from datetime import datetime, timedelta, timezone

import numpy as np
import polars as pl
import pytest

from scripts.mechanicalpremia_yen_squeeze_mt5atr_features_20261014 import (
    build_mt5_features,
)


def _h1(n=700):
    # Alternating true-range regime exposes SMA-versus-Wilder differences.
    t = [datetime(2023, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i) for i in range(n)]
    p = [120.0 + (i % 31) * 0.13 + (i // 31) * 0.019 for i in range(n)]
    width = [0.12 + 0.07 * (i % 11) for i in range(n)]
    return pl.DataFrame({
        "timestamp": t, "open": p,
        "high": [x + w for x, w in zip(p, width)],
        "low": [x - w / 2 for x, w in zip(p, width)],
        "close": [x + w / 5 for x, w in zip(p, width)],
        "volume": [1.0] * n,
    })


def test_registered_mt5_sma_tr_matches_independent_oracle():
    h = _h1()
    f = build_mt5_features(h)
    highs, lows, closes = (h[x].to_list() for x in ("high", "low", "close"))
    # This small independent reference lives only in the unit test.
    for i in (20, 30, 110, 300, 650):
        ranges = [
            max(highs[j] - lows[j], abs(highs[j] - closes[j-1]), abs(lows[j] - closes[j-1]))
            for j in range(i-13, i+1)
        ]
        assert f["atr14"][i] == pytest.approx(sum(ranges) / 14, abs=1e-10)
    assert f["atr14"][13] is None
    assert f["atr14"][14] is not None


def test_median_upper_order_statistic_exact():
    f = build_mt5_features(_h1())
    i = 300
    previous_100 = sorted(f["atr14"].slice(i-99, 100).to_list())
    assert f["atr100_upper_median"][i] == pytest.approx(previous_100[50], abs=1e-12)
    assert f["atr100_upper_median"][112] is None
    assert f["atr100_upper_median"][113] is not None


def test_features_are_append_invariant_and_available_after_h1():
    src = _h1()
    earlier = build_mt5_features(src.head(610))
    later = build_mt5_features(src)
    for c in ("atr14", "atr100_upper_median", "donchian20_0", "donchian500_0"):
        np.testing.assert_allclose(
            earlier[c].to_numpy(), later[c].head(610).to_numpy(),
            rtol=0, atol=1e-10, equal_nan=True,
        )
    assert earlier["available_at"][500] == src["timestamp"][500] + timedelta(hours=1)


def test_sma_and_wilder_are_not_interchangeable():
    from scripts.mechanicalpremia_yen_squeeze_native_strategy_20261014 import build_features
    h = _h1()
    correct, old = build_mt5_features(h), build_features(h)
    assert abs(correct["atr14"][650] - old["atr14"][650]) > 1e-5
