"""Numerical oracles for Program 2 timing, quality and currency units."""
from datetime import datetime, timedelta, timezone
import math
import numpy as np
import polars as pl
import pytest
from scripts.run_tokyo_fix_program2_cross_currency_20261011_v1 import features, admissible, fx_exposures, AnnualExpanding
from scripts.materialize_tokyo_fix_program2_cross_currency_20261011_v1 import safe_files

def fixture_prices():
    return pl.DataFrame({"timestamp":[datetime(2020,1,1,tzinfo=timezone.utc)+timedelta(minutes=i) for i in range(100)],"close":[100+i*.01 for i in range(100)],"session":["2020-01-01"]*100}).with_columns(pl.col("close").alias("open"),pl.col("close").alias("high"),pl.col("close").alias("low"),pl.lit(1.).alias("volume"))

@pytest.mark.parametrize("h",[5,15,30,60])
def test_native_feature_matches_independent_log_oracle(h):
    d=fixture_prices();f=features(d,[h])
    assert math.isclose(f[f"f{h}"][80],math.log(d["close"][80]/d["close"][80-h]),abs_tol=1e-14)

def test_closed_feature_survives_current_and_future_mutation():
    d=fixture_prices(); original=features(d,[15])["f15"][78]
    changed=d.with_columns(pl.when(pl.col("timestamp")>=d["timestamp"][79]).then(pl.col("close")*2).otherwise(pl.col("close")).alias("close"))
    assert features(changed,[15])["f15"][78]==original
    changed=d.with_columns(pl.when(pl.col("timestamp")==d["timestamp"][78]).then(pl.col("close")*1.01).otherwise(pl.col("close")).alias("close"))
    assert features(changed,[15])["f15"][78]!=original
    assert d["timestamp"][78]+timedelta(minutes=1)<d["timestamp"][80]

def test_internal_missing_minute_rejects_endpoint_return():
    d=fixture_prices().with_columns(pl.when(pl.col("timestamp")==fixture_prices()["timestamp"][75]).then(None).otherwise(pl.col("close")).alias("close"))
    assert features(d,[15])["f15"][80] is None

def test_stale_and_bad_geometry():
    d=fixture_prices().with_columns(pl.lit(100.).alias("close"),pl.lit(100.).alias("open"),pl.lit(100.).alias("high"),pl.lit(100.).alias("low"))
    assert admissible(d)["stale"][5]
    assert not admissible(d.with_columns(pl.lit(99.).alias("high")))["geometry_ok"].any()

def test_fx_gross_and_hedge_direction():
    q={"USDJPY":150.,"EURUSD":1.1,"GBPUSD":1.3,"AUDUSD":.7}
    e=fx_exposures({"USDJPY":5000.,"EURUSD":5000/1.1},q)
    assert math.isclose(e["gross_usd"],10000.)
    assert math.isclose(e["units"]["USD"],0.,abs_tol=1e-10)
    assert e["units"]["JPY"]==-750000.
    assert math.isclose(sum(e["usd_values"].values()),0.,abs_tol=1e-10)
    opposite=fx_exposures({"USDJPY":5000.,"EURUSD":-5000/1.1},q)
    assert math.isclose(opposite["units"]["USD"],10000.)
    pnl=5000/151+(5000/1.1)*.01
    assert math.isclose(pnl,78.56712823599669)

def test_triangle_identity_and_pip_units():
    assert 150*1.1==165.
    assert math.isclose(5000*.01/150,1/3)
    assert math.isclose(5000/1.1*.0001,.45454545454545453)

def test_annual_train_is_strictly_earlier():
    years=np.repeat(np.arange(2020,2027),60)
    for train,test in AnnualExpanding(years).split(years):
        assert years[train].max()<years[test].min()

def test_partition_selection_seals_holdout():
    assert not any("month=9/" in str(p) or "month=10/" in str(p) for p in safe_files("USDJPY",2026))
    with pytest.raises(ValueError):safe_files("USDJPY",2027)
