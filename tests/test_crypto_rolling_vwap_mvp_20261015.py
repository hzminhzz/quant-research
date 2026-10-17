"""Adversarial causal/indicator tests for the frozen Gemini Cycle 9 MVP."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest
from ml4t.backtest import DataFeed, Engine

from scripts.run_crypto_rolling_vwap_mvp_20261015 import (
    FEATURE_COLUMNS,
    VwapPullbackStrategy,
    config,
    feature_frame,
)


def bars(*, n=260, fixed_volume=False):
    start = datetime(2020, 1, 1, tzinfo=UTC)
    close = np.arange(n, dtype=float) * .1 + 100.
    high = close + .35
    low = close - .35
    low[200] = close[200] - 3.0  # specific retest candle, no future information
    volume = np.ones(n)*10 if fixed_volume else (5+np.arange(n)%17).astype(float)
    return pl.DataFrame({
        "timestamp": [start+timedelta(hours=i) for i in range(n)],
        "symbol": ["BTCUSDT"]*n,
        "open": close-.1,
        "high": high, "low": low, "close": close, "volume": volume,
    })


def test_native_features_and_weighted_sum_reference():
    raw = bars()
    feat = feature_frame(raw)
    c = raw["close"].to_numpy()
    v = raw["volume"].to_numpy()
    assert feat["trend168"][167] is None
    assert feat["trend168"][168] == pytest.approx(c[168]/c[0]-1)
    for i in (23, 24, 100, 168, 200, 259):
        expected = np.dot(c[i-23:i+1],v[i-23:i+1])/v[i-23:i+1].sum()
        assert feat["vwap24"][i] == pytest.approx(expected, abs=1e-10)
    assert np.isnan(feat["atr24"][0])
    assert feat["atr24"][24] > 0


def test_future_changes_cannot_alter_past_vwap_or_signals():
    raw = bars()
    first = feature_frame(raw)
    revised = raw.with_columns(
        pl.when(pl.int_range(pl.len())>=210).then(pl.col("close")*4).otherwise(pl.col("close")).alias("close"),
        pl.when(pl.int_range(pl.len())>=210).then(pl.col("volume")*20).otherwise(pl.col("volume")).alias("volume"),
    )
    second = feature_frame(revised)
    for column in FEATURE_COLUMNS:
        x = first[column].to_numpy()[:210]
        y = second[column].to_numpy()[:210]
        np.testing.assert_allclose(x,y,equal_nan=True,rtol=0,atol=1e-9)


def test_vwap_does_not_reuse_previous_valid_when_24_volumes_are_zero():
    raw = bars().with_columns(
        pl.when(pl.int_range(pl.len())>=236).then(0.0).otherwise(pl.col("volume")).alias("volume")
    )
    f = feature_frame(raw)
    assert f["vwap24"][259] is None
    assert f["signal_vwap"][259] == 0


def test_symbol_isolation_required():
    raw = bars().with_columns(
        pl.when(pl.int_range(pl.len())==0).then(pl.lit("ETHUSDT")).otherwise(pl.col("symbol")).alias("symbol")
    )
    with pytest.raises(ValueError, match="separately"):
        feature_frame(raw)


def test_native_next_bar_fill_and_atr_frozen_for_trade():
    f = feature_frame(bars(n=265, fixed_volume=True))
    s = VwapPullbackStrategy("BTCUSDT", "vwap24", "signal_vwap")
    feed = DataFeed(
        prices_df=f.select("timestamp","symbol","open","high","low","close","volume"),
        signals_df=f.select("timestamp","symbol",*FEATURE_COLUMNS),
    )
    result = Engine(feed,s,config(1.0)).run()
    fills = result.to_fills_dataframe()
    intents = [e for e in s.events if e["kind"] in ("entry_intent","exit_intent")]
    assert fills.height == len(intents) and fills.height > 0
    assert sorted(fills["timestamp"].to_list()) == sorted(
        (datetime.fromisoformat(e["timestamp"]) + timedelta(hours=1)).replace(tzinfo=None)
        if fills["timestamp"].dtype.time_zone is None else datetime.fromisoformat(e["timestamp"])+timedelta(hours=1)
        for e in intents
    )
    initial = [e for e in s.events if e["kind"] == "entry_intent"]
    closing = [e for e in s.events if e["kind"] == "exit_intent"]
    assert initial and closing
    assert closing[0]["frozen_atr"] == initial[0]["frozen_atr"]
    assert result.metrics["num_rejected_orders"] == 0
