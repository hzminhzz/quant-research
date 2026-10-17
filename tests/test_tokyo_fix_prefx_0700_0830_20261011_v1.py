"""Program 4A immutable evidence and native-timing regression checks."""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import polars as pl

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"run_log/tokyo_fix_prefx_0700_0830_20261011_v1"

def read(rel):
    return json.loads((OUT/rel).read_text())

def test_source_holdout_and_complete_case():
    g=read("T0_data_gate/result.json")
    assert g["bank_dates"]==1627
    assert g["new_eligible"]<=g["old91min_eligible"]<g["bank_dates"]
    assert g["interpolation"] is False
    assert g["holdout_read"] is False
    assert g["duplicate_timestamps"]==0
    m=read("source_manifest.json")
    assert m["holdout_read"] is False
    f=pl.read_parquet(OUT/"window_gates.parquet")
    assert f["session"].max().year==2026
    assert str(f["session"].max())=="2026-08-31"
    assert int(f["execution_complete"].sum())==g["new_eligible"]

def test_native_order_lifecycle_all_runs():
    folders=sorted((OUT/"runs").glob("*/result.json"))
    assert len(folders)==11
    for p in folders:
        x=json.loads(p.read_text())
        orders=pl.read_parquet(p.parent/"orders.parquet")
        trades=pl.read_parquet(p.parent/"trades.parquet")
        assert orders.height==trades.height*2
        assert orders.filter(pl.col("status")!="filled").is_empty()
        assert x["orders"]==orders.height
        assert x["no_carry"] is True
        assert abs(x["native_pnl_jpy"]-float(trades["pnl_jpy"].sum()))<2e-5
        a=orders.filter(pl.col("role")=="entry").sort("session")
        z=orders.filter(pl.col("role")=="exit").sort("session")
        assert a.height==z.height==trades.height
        assert (a["filled_at"]-a["submitted_at"]).unique().to_list()==[timedelta(minutes=1)]
        assert (z["filled_at"]-z["submitted_at"]).unique().to_list()==[timedelta(minutes=1)]
        assert all(x["status"]=="filled" for x in orders.to_dicts())
        assert all(t.year<=2026 and (t.year<2026 or t.month<=8) for t in trades["session"])
        assert abs(x["metrics"]["net_usd"]-float(trades["pnl_usd"].sum()))<1e-7

def test_fixed_qualification_rules_and_no_selected_filter():
    g=read("T1_native_gotobi/result.json")
    ordinary=read("T2_native_ordinary/result.json")
    assert g["metrics"]["n"]+ordinary["metrics"]["n"]==read("T0_data_gate/result.json")["new_eligible"]
    assert g["entry_minute"]==420 and g["exit_minute"]==510
    assert g["cost_pips"]==ordinary["cost_pips"]==1
    v=read("T4_regimes/result.json")
    assert v["no_filter_strategy"] is True
    assert v["cutoffs"]["fit_scope"].startswith("All complete prior-feature bank dates2020-23")
    assert len(v["risk_shift"])==3
    h=read("T5_refutation/result.json")
    assert len(h["tests"])==8
    assert all(0<=x["holm8_p"]<=1 for x in h["tests"])
    assert all(0<=x["p"]<=1 for x in h["tests"])

def test_cost_stress_and_delay_are_not_optimized():
    z=read("T3_cost_sensitivity/result.json")
    assert len(z["native_cost_runs"])==6
    assert len(z["native_delay_stress"])==2
    assert [x["entry_minute"] for x in z["native_delay_stress"]]==[421,422]
    for x in z["native_cost_runs"]:
        assert x["metrics"]["n"]==read("T1_native_gotobi/result.json")["metrics"]["n"]
    assert z["usd_breakeven_roundtrip_pips"]>0

def test_independent_oracle():
    r=read("T6_independent_oracle/result.json")
    assert r["status"]=="PASS"
    assert r["native_runs"]==11
    assert r["fills_verified"]==2*r["trades_verified"]
    assert r["source_identity_verified"] is True
    assert r["protected_holdout_read"] is False
    assert r["features_timestamp_verified"]>0
    assert all(a["pass"] for a in r["scenarios"])
