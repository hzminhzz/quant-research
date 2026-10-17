"""Portfolio-analysis invariants for five existing native-backtest sleeves."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.analyze_independent_five_portfolio_20261014 import (
    CASES, START, CUTOFF, TRAIN_END,
    align_business_days, align_calendar_days, inverse_vol_group_weights,
    inverse_vol_between_market_groups, load_native_sleeves,
    portfolio_daily_rebalanced, portfolio_static_initial_capital,
)


def _toy():
    fri = pd.Timestamp("2024-01-05", tz="UTC")
    sat = fri + pd.Timedelta(days=1)
    sun = sat + pd.Timedelta(days=1)
    mon = sun + pd.Timedelta(days=1)
    es = pd.Series([0.0, 0.0], index=[fri, mon])
    btc = pd.Series([0.0, 0.10, -0.10, 0.05], index=[fri, sat, sun, mon])
    return {name:(btc if "btc" in name else es).rename(name) for name in CASES},fri,mon


def test_weekend_returns_compound_in_monday_not_summed_or_dropped():
    data, fri, mon = _toy()
    sample = align_business_days(data, start=fri, end=mon)
    assert len(sample) == 2
    assert sample.loc[mon, "pivot-breakout-btc"] == pytest.approx(1.1*.9*1.05 - 1)
    assert sample.loc[mon, "donchian-btc"] == pytest.approx(1.1*.9*1.05 - 1)
    assert (sample[["three-red-spy","slope-hook","rsi-30-50"]] == 0).all().all()
    separate_calendar = align_calendar_days(data, start=fri, end=mon)
    sat, sun = fri + pd.Timedelta(days=1), fri + pd.Timedelta(days=2)
    assert separate_calendar.loc[sat,"pivot-breakout-btc"] == pytest.approx(0.10)
    assert separate_calendar.loc[sun,"pivot-breakout-btc"] == pytest.approx(-0.10)
    assert separate_calendar.loc[sat,"rsi-30-50"] == pytest.approx(0.0)


def test_weight_rules_do_not_read_after_train_and_honor_caps():
    n=800
    index = pd.bdate_range("2020-01-01", periods=n, tz="UTC")
    x = pd.DataFrame({
        name: (np.sin(np.arange(n)*(.08+i*.013)) *(.0008 + i*.0005)
               +np.sin(np.arange(n)*(.23+i*.01))*.0004)
        for i,name in enumerate(CASES)
    },index=index)
    trained = x.loc[x.index < TRAIN_END]
    altered=x.copy()
    altered.loc[altered.index>=TRAIN_END] *= 1000
    for fn in (inverse_vol_group_weights, inverse_vol_between_market_groups):
        w = fn(trained)
        w_changed = fn(altered.loc[altered.index<TRAIN_END])
        assert np.allclose(w, w_changed)
        assert sum(w) == pytest.approx(1)
        assert w.min() >= 0
        assert w.max() <= .35 + 1e-10


def test_native_equity_common_window_and_overlay_reconcile():
    sources=load_native_sleeves()
    data=align_business_days(sources)
    assert data.columns.to_list() == list(CASES)
    assert data.index[0] == START and data.index[-1] < CUTOFF
    assert data.index.is_monotonic_increasing
    assert not data.isnull().any().any()
    corr=data.corr()
    assert np.allclose(corr,corr.T)
    assert np.allclose(np.diag(corr), np.ones(len(CASES)))
    w = pd.Series(.2,index=CASES)
    r=portfolio_daily_rebalanced(data,w)
    assert np.allclose(r.to_numpy(),np.mean(data.to_numpy(),axis=1))
    r_static=portfolio_static_initial_capital(data,w)
    assert len(r_static)==len(r)
    assert np.isfinite(r_static).all()
    assert not np.allclose(r_static.to_numpy(),r.to_numpy())
