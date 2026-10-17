"""Offline execution and causality tests for the Lighter paired-grid prototype."""

from datetime import UTC, datetime, timedelta

import polars as pl
import yaml

from scripts.run_lighter_spy_qqq_grid_comparison import (
    CONFIG_PATH,
    add_causal_signals,
    run_one,
)


def synthetic_feed(zvalues):
    start = datetime(2026, 2, 22, tzinfo=UTC)
    stamps = [start + timedelta(minutes=i) for i in range(len(zvalues))]
    price_bars = []
    for sym in ("SPY", "QQQ"):
        price_bars.append(pl.DataFrame({
            "timestamp": stamps,
            "symbol": [sym] * len(zvalues),
            "open": [100.0] * len(zvalues),
            "high": [100.0] * len(zvalues),
            "low": [100.0] * len(zvalues),
            "close": [100.0] * len(zvalues),
            "volume": [1000.0] * len(zvalues),
        }))
    prices = pl.concat(price_bars).sort("timestamp", "symbol")
    context = pl.DataFrame({
        "timestamp": stamps,
        "spy_prev": [100.0] * len(zvalues),
        "qqq_prev": [100.0] * len(zvalues),
        "zscore": zvalues,
    })
    return prices, context


def test_previous_bar_signal_never_uses_current_close():
    start = datetime(2026, 1, 22, 16, tzinfo=UTC)
    panel = pl.DataFrame({
        "timestamp": [start + timedelta(minutes=i) for i in range(6)],
        "close_spy": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
        "close_qqq": [100.0] * 6,
    })
    out = add_causal_signals(panel, beta=0.3, lookback=3)
    assert out["spy_prev"][5] == 104.0
    assert out["zscore"][3] is not None
    assert out["spread_mean"][3] != out["spread"][3]


def test_two_independent_bots_do_not_create_beta_neutral_positions():
    params = yaml.safe_load(CONFIG_PATH.read_text())
    prices, context = synthetic_feed([-1.6] * 15)
    result = run_one("independent", prices, context, params["execution"], params["costs"], beta=0.3)
    assert result["fill_count"] == 2
    assert result["layer_entries"] == 2
    assert result["max_beta_residual_usdc"] > 50
    assert result["orphan_events"] == 0


def test_coordinated_pair_creates_neutral_opposing_legs_and_exits():
    params = yaml.safe_load(CONFIG_PATH.read_text())
    prices, context = synthetic_feed([-1.6] * 5 + [0.0] * 12)
    result = run_one("paired", prices, context, params["execution"], params["costs"], beta=0.3)
    assert result["fill_count"] == 4
    assert result["pair_entries"] == 1
    assert result["pair_exits"] == 1
    assert result["max_beta_residual_usdc"] < 1.0
    assert result["end_open_positions"] == {}
    assert result["orphan_events"] == 0
