#!/usr/bin/env python3
"""Native Phase5 chronological B1/B2/B3 validation; frozen v4 rules."""
from __future__ import annotations
import hashlib,json,sys
from datetime import date, timedelta
from pathlib import Path
import exchange_calendars as xc
import polars as pl

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import run_vwap_pullback_adx_phase4_20261012 as original
from scripts.run_vwap_pullback_adx_execfix_v3_20261012 import LegalLimitsEngine
SID="vwap_pullback_adx_nq_20261012_proxy_v4_phase56"
FILE=ROOT/"data/processed/vwap_adx_nqf_2026h2_validation_1m.parquet"
OUT=ROOT/"run_log"/SID/"phase5"
SHA="21bd6e367df44b934386e59e831c7e8090116de9d5fd9ac82ca8a8ff9d7c4839"


def build(start:date=date(2026,7,1),end:date=date(2026,9,30)):
    assert hashlib.sha256(FILE.read_bytes()).hexdigest()==SHA
    a=pl.read_parquet(FILE).sort("timestamp")
    assert a["timestamp"].n_unique()==a.height
    a=original.compute_features(a,[{"name":"adx","params":{"period":14}}])
    a=a.with_columns(pl.col("timestamp").dt.convert_time_zone("America/Chicago").alias("ct"))
    a=a.with_columns(pl.col("ct").dt.date().alias("day"),pl.col("ct").dt.strftime("%H:%M").alias("clock"))
    cash=pl.col("clock")>=pl.lit("08:30")
    a=a.with_columns(
        pl.when(cash).then(((pl.col("high")+pl.col("low")+pl.col("close"))/3)*pl.col("volume")).otherwise(0).cum_sum().over("day").alias("pv"),
        pl.when(cash).then(pl.col("volume")).otherwise(0).cum_sum().over("day").alias("vv"),
        pl.col("high").rolling_max(5).alias("next_tp"),
        pl.col("low").rolling_min(20).alias("next_sl"),
        pl.col("close").shift(1).alias("prior_close"),
        pl.col("adx").shift(1).alias("prior_adx"),
    ).with_columns(
        pl.when(pl.col("vv")>0).then(pl.col("pv")/pl.col("vv")).otherwise(None).alias("vwap")
    )
    or_high=a.filter(pl.col("clock").is_between(pl.lit("08:30"),pl.lit("08:59"))).group_by("day").agg(
        pl.col("high").max().alias("or_high"),pl.len().alias("or_count"))
    a=a.join(or_high,on="day",how="left")
    cal=xc.get_calendar("XNYS")
    valid={d.date() for d in cal.sessions_in_range(str(start),str(end))}
    early={d.date() for d in cal.early_closes if start<=d.date()<=end}
    dates=sorted(valid-early)
    days=a.filter((pl.col("day")>=start)&(pl.col("day")<=end)).partition_by("day",as_dict=True)
    accepted=[];problems={}
    for d in dates:
        b=days.get((d,))
        if b is None:
            problems[str(d)]="MISSING_DAY";continue
        cash=b.filter(pl.col("clock").is_between(pl.lit("08:30"),pl.lit("15:55")))
        opens=cash["clock"].to_list()
        if cash.height!=446 or len(set(opens))!=446 or opens[0]!="08:30" or opens[-1]!="15:55":
            problems[str(d)]=f"INCOMPLETE_GRID_{cash.height}";continue
        if cash["timestamp"].diff().drop_nulls().to_list().count(timedelta(minutes=1))!=445:
            problems[str(d)]="MISSING_MINUTE";continue
        if b.filter(pl.col("clock").is_between(pl.lit("08:30"),pl.lit("08:59"))).height!=30 or cash["volume"].min()<=0:
            problems[str(d)]="INVALID_OR_OR_VOLUME";continue
        accepted.append(d)
    feed=a.filter(pl.col("day").is_in(accepted)&pl.col("clock").is_between(pl.lit("08:30"),pl.lit("15:55"))).with_columns(pl.lit("NQ.F").alias("asset"))
    assert feed.height==len(accepted)*446 and feed["day"].n_unique()==len(accepted)
    assert feed.select("vwap","adx","or_high","next_sl","next_tp","prior_close","prior_adx").null_count().sum_horizontal().sum()==0
    qa={
        "source_sha256":SHA,"requested_start":str(start),"requested_end":str(end),
        "calendar_valid_sessions":len(dates),"early_close_days_excluded":sorted(map(str,early)),
        "accepted_count":len(accepted),"accepted_dates":list(map(str,accepted)),
        "excluded_due_to_quality":problems,"datetime_zone":"America/Chicago",
        "cash_bar_count":feed.height,"observed_final_bar":str(feed["timestamp"].max()) if feed.height else None,
        "proxy_not_actual_CME":True,
        "timestamp_gap_in_accepted_cash_days":0,
        "same_registered_signals_and_costs":True
    }
    return feed,qa


def main():
    dest=OUT
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError("Do not overwrite trial evidence")
    frozen=ROOT/"run_log/research_sessions"/SID/"frozen_spec.json"
    if not frozen.exists():raise RuntimeError("Spec not registered and frozen")
    feed,qa=build()
    if len(qa["accepted_dates"])<45:raise RuntimeError(f"too few validated days {qa}")
    dest.mkdir(parents=True,exist_ok=True)
    (dest/"source_qa.json").write_text(json.dumps(qa,indent=2)+"\n")
    original.OUT=dest
    original.Engine=LegalLimitsEngine
    results=[]
    for mode in ("B1","B2","B3"):
        for label,fee,slip in (("gross",0.,0.),("cost",2.5,.25),("stress",2.5,.5)):
            print("START",mode,label,flush=True)
            r=original.run_mode(feed,mode,label,fee,slip)
            results.append(r)
            print("DONE",mode,label,r["trades"],round(r["net_account_pnl_usd"],2),flush=True)
    (dest/"all_trials.json").write_text(json.dumps(results,indent=2,default=str)+"\n")
    print("PHASE5_NATIVE_COMPLETE")
if __name__=="__main__":main()
