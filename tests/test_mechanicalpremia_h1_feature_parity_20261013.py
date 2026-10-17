"""Evidence tests: source H1 signals and exact ML4T Engineer feature discovery.

No strategy optimization or alternative backtest. Independent TA-Lib reference
checks on deterministic OHLC and point-in-time append invariance.
"""
import numpy as np
from datetime import datetime, timezone, timedelta
import polars as pl
import talib

from ml4t.engineer import compute_features, feature_catalog


def _sample() -> pl.DataFrame:
    rng = np.random.default_rng(20261013)
    n = 280
    close = 5000.0 + np.cumsum(rng.normal(0, 9, n))
    opens = close + rng.normal(0, 1, n)
    high = np.maximum(close, opens) + rng.uniform(0.5, 7.0, n)
    low = np.minimum(close, opens) - rng.uniform(0.5, 7.0, n)
    return pl.DataFrame({
        "timestamp": [datetime(2023,1,1,tzinfo=timezone.utc)+timedelta(hours=i) for i in range(n)],
        "open": opens,
        "high": high,
        "low": low,
        "close": close,
        "volume": np.full(n, 1000.0),
    })


def _engineer(frame):
    return compute_features(frame, [
        {"name": "atr", "params": {"period": 14}, "output": "atr14"},
        {"name": "bollinger_bands", "params": {
            "period": 40, "nbdevup": 2, "nbdevdn": 2
        }, "output": "bb40"},
    ])


def test_h1_indicator_registry_and_talib_reference():
    assert "atr" in feature_catalog.list()
    assert "bollinger_bands" in feature_catalog.list()
    assert feature_catalog.describe("atr")["ta_lib_compatible"] is True
    assert feature_catalog.describe("bollinger_bands")["ta_lib_compatible"] is True
    d = _sample()
    got = _engineer(d)
    atr = talib.ATR(d["high"].to_numpy(), d["low"].to_numpy(),
                    d["close"].to_numpy(), timeperiod=14)
    upper, _, lower = talib.BBANDS(d["close"].to_numpy(), timeperiod=40,
                                  nbdevup=2, nbdevdn=2, matype=0)
    np.testing.assert_allclose(got["atr14"].to_numpy(), atr,
                               equal_nan=True, rtol=1e-10, atol=1e-8)
    np.testing.assert_allclose(
        got["bb40"].struct.field("upper").to_numpy(), upper,
        equal_nan=True, rtol=1e-10, atol=1e-8
    )
    np.testing.assert_allclose(
        got["bb40"].struct.field("lower").to_numpy(), lower,
        equal_nan=True, rtol=1e-10, atol=1e-8
    )


def test_100_closed_atr_upper_middle_and_causality():
    d = _sample()
    out = _engineer(d)
    got = out.with_columns(pl.col("atr14").rolling_quantile(
        0.5, interpolation="higher", window_size=100, min_samples=100
    ).alias("median"))
    atr=out["atr14"].to_numpy()
    med=got["median"].to_numpy()
    for i in range(113, len(atr)):
        np.testing.assert_allclose(med[i], np.sort(atr[i-99:i+1])[50],
                                   rtol=0, atol=1e-9)
    cut=220
    prefix = _engineer(d.head(cut))
    np.testing.assert_allclose(prefix["atr14"].to_numpy(),
                               out["atr14"].to_numpy()[:cut],
                               rtol=1e-10, atol=1e-8, equal_nan=True)
    np.testing.assert_allclose(
        prefix["bb40"].struct.field("upper").to_numpy(),
        out["bb40"].struct.field("upper").to_numpy()[:cut],
        rtol=1e-10, atol=1e-8, equal_nan=True
    )
