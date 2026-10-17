"""Native ML4T Shannon strategy feature smoke and causality tests."""
from datetime import datetime, timedelta
import math

import polars as pl
import pytest

from src.strategies.independent_seven_native_features import FEATURE_BUILDERS, fx_timing


@pytest.fixture
def bars():
    n = 340
    close = [100.0 + .03 * i + 4 * math.sin(i * .21) for i in range(n)]
    return pl.DataFrame({
        "timestamp": [datetime(2020, 1, 1) + timedelta(days=i) for i in range(n)],
        "open": [v + .12 for v in close],
        "high": [v + 1.0 for v in close],
        "low": [v - 1.0 for v in close],
        "close": close,
        "volume": [1000.0] * n,
    })


@pytest.mark.parametrize("name", sorted(FEATURE_BUILDERS))
def test_feature_builder_has_full_timeline_and_causal_prefix(name, bars):
    builder = FEATURE_BUILDERS[name]
    if name == "fx-timing":
        def call(frame):
            return fx_timing({s: frame for s in ("FXE", "UUP", "SPY", "BIL")})
        columns = ["roc_fxe", "roc_uup", "fxe_leads"]
    else:
        call = builder
        columns = {
            "pivot-breakout-btc": ["confirmed_pivot_high", "confirmed_pivot_low", "breakout_observed"],
            "donchian-btc": ["average_direction", "target_exposure"],
            "three-red-spy": ["entry_signal", "exit_signal"],
            "gold-macd-hook": ["macd_line", "histogram", "hull_proxy", "entry_signal", "exit_signal"],
            "slope-hook": ["slope3", "entry_signal", "exit_signal"],
            "rsi-30-50": ["rsi5", "entry_signal", "exit_signal"],
        }[name]
    full = call(bars)
    shorter = call(bars.head(310))
    assert full.height == bars.height
    assert shorter.height == 310
    assert all(c in full.columns for c in columns)
    for c in columns:
        a = full[c][:310].to_list()
        b = shorter[c].to_list()
        for x, y in zip(a, b):
            if isinstance(x, float) and isinstance(y, float) and math.isnan(x) and math.isnan(y):
                continue
            if isinstance(x, float) and isinstance(y, float):
                assert x == pytest.approx(y, abs=1e-8)
            else:
                assert x == y


def test_fx_week_end_only(bars):
    r = fx_timing({s: bars for s in ("FXE", "UUP", "SPY", "BIL")})
    # No more than one rebalance event in any seven consecutive calendar days.
    dates = r.filter(pl.col("week_last_session"))["timestamp"].to_list()
    assert all((b - a).days >= 6 for a, b in zip(dates, dates[1:]))
