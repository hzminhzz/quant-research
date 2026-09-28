#!/usr/bin/env python3
"""Pre-registered weekly crypto MAX-effect factor research."""

from __future__ import annotations
import argparse, json, math
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np
import polars as pl
from scipy import stats

from scripts.run_crypto_high_momentum import hac_mean_test, simulate, validate_panel
from src.experiment import compute_deflated_sharpe

DAYS=(14,30,60)
CANONICAL=30
LIQ_WINDOW=720
LIQUID_FRACTION=0.80
MIN_XS=8
COST=3.0
DEV0=datetime(2021,1,1,tzinfo=timezone.utc)
DEV1=datetime(2024,1,1,tzinfo=timezone.utc)
OOS0=datetime(2024,1,1,tzinfo=timezone.utc)
OOS1=datetime(2026,1,1,tzinfo=timezone.utc)


def factor_frame(df:pl.DataFrame, days:int)->pl.DataFrame:
    hours=days*24
    history=max(LIQ_WINDOW,hours+25)
    ordered=df.sort(["symbol","timestamp"]).with_columns(
        (pl.col("close")*pl.col("volume")).alias("_dv"),
        pl.when(pl.col("timestamp").dt.hour()==0)
        .then(pl.col("close").shift(1).over("symbol")/pl.col("close").shift(25).over("symbol")-1.0)
        .otherwise(None).alias("_daily_ret"),
    )
    frame=ordered.with_columns(
        pl.col("_daily_ret").rolling_max(hours, min_samples=days).over("symbol").alias("signal"),
        pl.col("_dv").shift(1).rolling_mean(LIQ_WINDOW).over("symbol").alias("_liq"),
        pl.col("timestamp").shift(history).over("symbol").alias("_anchor"),
        pl.col("timestamp").shift(-168).over("symbol").alias("_next_ts"),
        pl.col("open").shift(-168).over("symbol").alias("_next_open"),
    ).with_columns(
        (pl.col("_next_open")/pl.col("open")-1.0).alias("forward_return")
    )
    weekly=frame.filter(
        (pl.col("timestamp").dt.weekday()==1)
        &(pl.col("timestamp").dt.hour()==0)
        &pl.col("signal").is_finite()
        &pl.col("_liq").is_finite()
        &(pl.col("_anchor")==pl.col("timestamp")-pl.duration(hours=history))
        &(pl.col("_next_ts")==pl.col("timestamp")+pl.duration(hours=168))
    ).with_columns(
        pl.col("_liq").rank(method="ordinal",descending=True).over("timestamp").alias("_lr"),
        pl.len().over("timestamp").alias("_n"),
    ).filter(pl.col("_lr")<=(pl.col("_n").cast(pl.Float64)*LIQUID_FRACTION).ceil())
    return weekly.filter(pl.len().over("timestamp")>=MIN_XS).sort(["timestamp","symbol"])


def diagnostic(frame:pl.DataFrame)->dict:
    d=frame.filter((pl.col("timestamp")>=DEV0)&(pl.col("timestamp")<DEV1))
    ics=[]; spreads=[]; counts=[]; buckets={q:[] for q in range(1,5)}
    for p in d.partition_by("timestamp",maintain_order=True):
        n=p.height
        if n<MIN_XS: continue
        s=p["signal"].to_numpy(); f=p["forward_return"].to_numpy()
        ic=stats.spearmanr(s,f).statistic
        if np.isfinite(ic):
            ics.append(float(ic)); counts.append(n)
        rows=sorted(zip(s.tolist(),f.tolist()),key=lambda z:z[0])
        k=max(1,math.ceil(n*.25))
        spreads.append(float(np.mean([r for _,r in rows[-k:]])-np.mean([r for _,r in rows[:k]])))
        for i,(_,ret) in enumerate(rows):
            q=min(4,int(i*4/n)+1); buckets[q].append(float(ret))
    a=np.asarray(ics,float); t,pv=hac_mean_test(a,max_lag=4)
    return {
        "n_weeks":len(ics),
        "mean_ic":float(np.mean(a)) if len(a) else math.nan,
        "ic_ir":float(np.mean(a)/np.std(a,ddof=1)) if len(a)>1 and np.std(a,ddof=1)>0 else 0.0,
        "hac_t":t,"hac_p":pv,
        "high_minus_low":float(np.mean(spreads)) if spreads else math.nan,
        "quartile_returns":[float(np.mean(buckets[q])) if buckets[q] else math.nan for q in range(1,5)],
        "mean_assets":float(np.mean(counts)) if counts else 0.0,
    }


def build_targets(frame,start,end,exclude=None,delay=0):
    ex=exclude or set()
    z=frame.filter((pl.col("timestamp")>=start)&(pl.col("timestamp")<end)&(~pl.col("symbol").is_in(sorted(ex))))
    out={}
    for p in z.partition_by("timestamp",maintain_order=True):
        rows=sorted([(r["symbol"],float(r["signal"])) for r in p.iter_rows(named=True)],key=lambda z:z[1])
        if len(rows)<MIN_XS: continue
        k=max(1,math.ceil(len(rows)*.25)); w={}
        for sym,_ in rows[-k:]: w[sym]=.5/k
        for sym,_ in rows[:k]: w[sym]=-.5/k
        out[p["timestamp"][0]+timedelta(hours=delay)]=w
    return out


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--data",type=Path,required=True); a=ap.parse_args()
    prices=pl.read_parquet(a.data).sort(["symbol","timestamp"]); integrity=validate_panel(prices)
    dev=prices.filter(pl.col("timestamp")<DEV1)
    frames={d:factor_frame(dev,d) for d in DAYS}
    diag={d:diagnostic(frames[d]) for d in DAYS}
    c=diag[CANONICAL]
    gate=c["n_weeks"]>=100 and c["mean_ic"]>=.02 and c["hac_p"]<.05 and c["high_minus_low"]>0
    out={"schema_version":1,"run_id":"20260928-monthly-max-effect-weekly","data_integrity":integrity,
         "diagnostics":{str(d):diag[d] for d in DAYS},"development_gate_passed":gate,"oos_consumed":False,
         "trial_accounting":{"previous_parameter_trials":33,"new_parameter_trials":3,"cumulative_parameter_trials":36}}
    if not gate:
        out["classification"]="REJECT"; out["conclusion"]="Development MAX-effect gate failed; OOS was not consumed."
        print(json.dumps(out,indent=2,default=str)); return 0

    frames={d:factor_frame(prices,d) for d in DAYS}; res={}; sharpes=[]
    for d in DAYS:
        res[str(d)]={}
        tg=build_targets(frames[d],OOS0,OOS1)
        for m in (1.0,2.0,3.0): res[str(d)][str(m)]=simulate(prices,tg,COST*m,OOS0,OOS1)
        sharpes.append(float(res[str(d)]["1.0"]["metrics"]["annualized_sharpe"]))
    can=res[str(CANONICAL)]["1.0"]; contrib=can["asset_contribution"]; strong=max(contrib,key=contrib.get) if contrib else None
    abl={
        "exclude_btc_eth":simulate(prices,build_targets(frames[CANONICAL],OOS0,OOS1,{"BTCUSDT","ETHUSDT"}),COST,OOS0,OOS1),
        "delay_one_hour":simulate(prices,build_targets(frames[CANONICAL],OOS0,OOS1,delay=1),COST,OOS0,OOS1),
    }
    if strong:
        abl["exclude_strongest"]={"asset":strong,"result":simulate(prices,build_targets(frames[CANONICAL],OOS0,OOS1,{strong}),COST,OOS0,OOS1)}
    dsr=compute_deflated_sharpe(float(can["metrics"]["annualized_sharpe"]),sharpes,n_obs_days=int(can["metrics"]["n_days"]))
    base=can["metrics"]; two=res[str(CANONICAL)]["2.0"]["metrics"]
    stable=sum(res[str(d)]["1.0"]["metrics"]["total_return"]>0 for d in DAYS)>=2
    years=all(can["by_year"][str(y)]["total_return"]>=0 for y in (2024,2025))
    breadth=abl["exclude_btc_eth"]["metrics"]["total_return"]>0 and abl["delay_one_hour"]["metrics"]["total_return"]>0 and (not strong or abl["exclude_strongest"]["result"]["metrics"]["total_return"]>0)
    qual=base["annualized_sharpe"]>1 and base["total_return"]>0 and two["total_return"]>0 and stable and years and breadth and dsr["dsr_probability"]>=.95
    out.update({"oos_consumed":True,"oos_results":res,"ablations":abl,
                "multiple_testing":{"base_cost_sharpes":sharpes,"dsr":dsr,"pbo":"N/A: three preregistered MAX windows","global_cumulative_parameter_trials":36},
                "funding_treatment":"not modeled","success_gate_candidate":qual,
                "classification":"EXPLORATORY_PASS" if qual else "REJECT"})
    print(json.dumps(out,indent=2,default=str)); return 0

if __name__=="__main__": raise SystemExit(main())
