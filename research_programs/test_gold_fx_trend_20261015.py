"""Adversarial frozen signal/next-open integration tests for Gold/FX MVP."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest
from ml4t.backtest import DataFeed, Engine
from ml4t.engineer import compute_features

from research_programs.gold_fx_trend_20261015 import (
    MonthlyTrend60,
    config,
    features_and_feed,
)


@pytest.mark.parametrize("symbol", ["XAUUSD", "EURUSD", "AUDUSD"])
def test_scheduled_monthly_signals_have_native_roc_and_no_future_bars(symbol):
    prices, signals, report = features_and_feed(symbol)
    assert prices.height > 1600
    assert signals.height == 84
    assert len(signals["timestamp"].unique()) == 84
    assert signals["timestamp"].max() < datetime(2022,1,1,tzinfo=UTC)
    assert all(v in (-1,0,1) for v in signals["target_side"].to_list())
    assert report["source_clock"].startswith("NY")
    # First eligible day of each month only.
    months = signals["timestamp"].dt.convert_time_zone("America/New_York").dt.strftime("%Y-%m")
    assert months.n_unique() == 84


def test_independent_native_roc60_math():
    t = datetime(2014,1,1,22,tzinfo=UTC)
    rows = 200
    prices = pl.DataFrame({
        "timestamp":[t + timedelta(days=i) for i in range(rows)],
        "open":[100+i*.05 for i in range(rows)],
        "high":[101+i*.05 for i in range(rows)],
        "low":[99+i*.05 for i in range(rows)],
        "close":[100+i*.05 for i in range(rows)],
        "volume":[100.] * rows,
    })
    f = compute_features(prices,[{"name":"roc","params":{"period":60},"output":"roc60"}],timestamp_col="timestamp")
    assert f["roc60"][59] is None or f["roc60"][59] != f["roc60"][59]
    # ROC may be expressed as percentage or fraction; verify ratio scale empirically.
    expected_fraction=prices["close"][100]/prices["close"][40]-1
    observed=f["roc60"][100]
    assert min(abs(observed-expected_fraction), abs(observed-100*expected_fraction))<1e-9


def test_native_engine_next_bar_fill_not_signal_bar():
    t = datetime(2016,1,4,22,tzinfo=UTC)
    rows=[(t+timedelta(days=i), 100+i) for i in range(5)]
    prices=pl.DataFrame({
        "timestamp":[x[0] for x in rows], "open":[float(x[1]) for x in rows],
        "high":[float(x[1]+1) for x in rows], "low":[float(x[1]-1) for x in rows],
        "close":[float(x[1]) for x in rows], "volume":[1000.] * len(rows),
        "asset":["EURUSD"] * len(rows),
    })
    signals=pl.DataFrame({
        "timestamp":[rows[1][0]],"asset":["EURUSD"],"target_side":[1],
        "roc60":[1.0],
    })
    model=MonthlyTrend60("EURUSD")
    r=Engine(DataFeed(prices_df=prices,signals_df=signals),model,config()).run()
    assert len(r.fills)==1
    assert r.fills[0].timestamp == rows[2][0]
    assert r.fills[0].price > rows[2][1]  # cost slippage on long fill
    assert model.orders==1


def test_development_cutoff_disallows_post_2021_and_preserves_symbol_isolation():
    a, sa, _ = features_and_feed("XAUUSD")
    b, sb, _ = features_and_feed("EURUSD")
    assert a["timestamp"].max() < datetime(2022,1,1,tzinfo=UTC)
    assert b["timestamp"].max() < datetime(2022,1,1,tzinfo=UTC)
    assert sa["timestamp"].n_unique()==sa.height
    assert sb["timestamp"].n_unique()==sb.height
    assert sa["roc60"].to_list()!=sb["roc60"].to_list()
