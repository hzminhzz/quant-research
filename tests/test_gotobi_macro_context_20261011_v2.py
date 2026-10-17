"""Regression gates for Gotobi macro context retrospective research."""
from datetime import date,timedelta
from pathlib import Path
import json
import polars as pl
import pytest

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"run_log/gotobi_macro_context_20261011_v2"
SRC=ROOT/"data/processed/gotobi_macro_context_20261011_v1"

def test_source_dates_are_assumed_lagged_not_claimed_PIT():
    feature=pl.read_parquet(OUT/"feature_panel.parquet")
    assert feature.height==370
    for prefix in ("us_yield","jp_yield"):
        dtcol=f"{prefix}_date"
        f=feature.filter(pl.col(dtcol).is_not_null())
        check=f.select(((pl.col(dtcol).cast(pl.Datetime("us","UTC"))+
                         pl.duration(days=3))<=pl.col("decision_at")).all()).item()
        assert check
    assert feature["entry_at"].max().year==2025
    manifest=json.loads((SRC/"source_manifest.json").read_text())
    assert all(not x.get("historical_vintage_verified",False) for x in manifest["data"][:2])

def test_historical_policy_archive_cannot_be_model_input():
    events=pl.read_parquet(SRC/"rate_events.parquet")
    assert events.height==100
    assert events.filter(pl.col("archive_created_at_utc")>pl.col("event_at_utc")).height==99
    pred=pl.read_parquet(OUT/"walkforward_predictions.parquet")
    assert "near_rate_event_expost" not in pred.columns
    m=json.loads((OUT/"T3_walkforward/result.json").read_text())
    assert not m["policy_event_archive_used_as_model_feature"]

def test_expanding_folds_no_same_year_training():
    folds=json.loads((OUT/"T3_walkforward/result.json").read_text())["folds"]
    assert [f["year"] for f in folds]==[2023,2024,2025]
    for f in folds:
        assert f["train_through"] < f"{f['year']}-01-01"
        assert f["test_from"] >= f"{f['year']}-01-01"
        assert f["train_n"]>=185
    pred=pl.read_parquet(OUT/"walkforward_predictions.parquet")
    assert pred.height==185
    assert pred["session"].is_duplicated().sum()==0

def test_native_baseline_ledger_matches_independent_prior_run():
    original=pl.read_parquet(ROOT/"run_log/gotobi_exact_paper_bridge_20261011_v1/native/trades.parquet")
    dates=pl.read_parquet(OUT/"walkforward_predictions.parquet")["session"].to_list()
    original=original.filter(pl.col("session").is_in(dates)).sort("session")
    backtest=pl.read_parquet(OUT/"runs/always_long_1p0/trades.parquet").sort("session")
    assert original.height==backtest.height==185
    assert original["session"].to_list()==backtest["session"].to_list()
    assert max(abs(a-b) for a,b in zip(original["pnl_usd"],backtest["pnl_usd"]))<1e-7
    assert all(x.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Tokyo")).strftime("%H:%M")=="09:56"
               for x in backtest["exit_at"])

def test_raised_costs_reduce_pnl_all_arms():
    results={}
    for arm in ("always_long","ridge_calendar_only","ridge_with_yield"):
        paths=[OUT/"runs"/f"{arm}_{c}/result.json" for c in ("1p0","1p5","2p0")]
        vals=[json.loads(p.read_text()) for p in paths]
        assert len({v["n"] for v in vals})==1
        assert vals[0]["net_usd"]>vals[1]["net_usd"]>vals[2]["net_usd"]
        assert max(x["engine_cash_reconciliation_jpy"] for x in vals)<1e-5
        assert all(not x["holdout_read"] for x in vals)
