#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats
from scipy.stats import spearmanr

from scripts.run_crypto_risk_managed_xs_momentum import load_daily, week_ret_map
from src.experiment import compute_deflated_sharpe

WINDOWS=(14,30,60)
CAN=30
COST=10.0
TOPN=50
MIN_XS=10
DEV0=date(2022,1,1)
DEV1=date(2024,1,1)
OOS0=date(2024,1,1)
OOS1=date(2026,1,1)


def base_returns(daily: pl.DataFrame) -> pl.DataFrame:
    x=(daily.sort(["symbol","date"])
       .with_columns(
           pl.col("close").shift(1).over("symbol").alias("_prev_close"),
           pl.col("date").shift(1).over("symbol").alias("_prev_date"),
       )
       .with_columns(
           pl.when(pl.col("date")-pl.col("_prev_date")==pl.duration(days=1))
             .then(pl.col("close")/pl.col("_prev_close")-1.0)
             .otherwise(None).alias("ret")
       ))
    market=x.group_by("date").agg(pl.col("ret").mean().alias("mkt_ret"))
    return x.join(market,on="date",how="left").sort(["symbol","date"])


def feature_frame(base: pl.DataFrame, window: int) -> pl.DataFrame:
    valid=pl.col("ret").is_finite() & pl.col("mkt_ret").is_finite() & (pl.col("mkt_ret")<0)
    min_down=max(5,window//5)
    x=(base.with_columns(
          pl.when(valid).then(1.0).otherwise(0.0).alias("_n0"),
          pl.when(valid).then(pl.col("ret")).otherwise(0.0).alias("_a0"),
          pl.when(valid).then(pl.col("mkt_ret")).otherwise(0.0).alias("_m0"),
          pl.when(valid).then(pl.col("ret")*pl.col("mkt_ret")).otherwise(0.0).alias("_am0"),
          pl.when(valid).then(pl.col("mkt_ret")**2).otherwise(0.0).alias("_mm0"),
          pl.col("qv").shift(1).rolling_sum(30).over("symbol").alias("_liq"),
          pl.col("date").shift(window).over("symbol").alias("_anchorw"),
          pl.col("date").shift(30).over("symbol").alias("_anchor30"),
       )
       .with_columns(
          pl.col("_n0").shift(1).rolling_sum(window).over("symbol").alias("_n"),
          pl.col("_a0").shift(1).rolling_sum(window).over("symbol").alias("_sa"),
          pl.col("_m0").shift(1).rolling_sum(window).over("symbol").alias("_sm"),
          pl.col("_am0").shift(1).rolling_sum(window).over("symbol").alias("_sam"),
          pl.col("_mm0").shift(1).rolling_sum(window).over("symbol").alias("_smm"),
       )
       .with_columns(
          (pl.col("_sam")-pl.col("_sa")*pl.col("_sm")/pl.col("_n")).alias("_cov_num"),
          (pl.col("_smm")-pl.col("_sm")*pl.col("_sm")/pl.col("_n")).alias("_var_num"),
       )
       .with_columns((pl.col("_cov_num")/pl.col("_var_num")).alias("signal"))
       .filter(
          (pl.col("date").dt.weekday()==1)
          & pl.col("signal").is_finite()
          & pl.col("_liq").is_finite()
          & (pl.col("_n")>=min_down)
          & (pl.col("_var_num")>0)
          & (pl.col("_anchorw")==pl.col("date")-pl.duration(days=window))
          & (pl.col("_anchor30")==pl.col("date")-pl.duration(days=30))
       ))
    out=[]
    for p in x.partition_by("date",maintain_order=True):
        p=p.sort("_liq",descending=True).head(TOPN)
        if p.height>=MIN_XS:
            out.append(p.select("date","symbol","signal","_liq","_n"))
    return pl.concat(out,how="vertical").sort(["date","symbol"]) if out else pl.DataFrame()


def hac_mean(values: np.ndarray, max_lag: int=4) -> tuple[float,float]:
    if len(values)<8:
        return 0.0,1.0
    c=values-values.mean()
    n=len(values)
    lrv=float(np.dot(c,c)/n)
    for lag in range(1,min(max_lag,n-1)+1):
        gamma=float(np.dot(c[lag:],c[:-lag])/n)
        lrv+=2.0*(1.0-lag/(max_lag+1.0))*gamma
    if lrv<=0:
        return 0.0,1.0
    t=float(values.mean()/math.sqrt(lrv/n))
    return t,float(2.0*stats.norm.sf(abs(t)))


def diagnostics(frame: pl.DataFrame, returns: dict, start: date, end: date) -> dict:
    ics=[]
    spreads=[]
    for p in frame.filter((pl.col("date")>=start)&(pl.col("date")<end)).partition_by("date",maintain_order=True):
        d=p["date"][0]
        rows=[r for r in p.iter_rows(named=True) if (d,str(r["symbol"])) in returns]
        if len(rows)<MIN_XS:
            continue
        s=np.array([float(r["signal"]) for r in rows])
        y=np.array([returns[(d,str(r["symbol"]))] for r in rows],dtype=float)
        ic=float(spearmanr(s,y).statistic)
        if np.isfinite(ic):
            ics.append(ic)
        ix=np.argsort(s)
        k=max(2,len(ix)//5)
        spreads.append(float(y[ix[-k:]].mean()-y[ix[:k]].mean()))
    a=np.array(ics,dtype=float)
    t,p=hac_mean(a)
    sd=float(a.std(ddof=1)) if len(a)>1 else 0.0
    return {
        "n_weeks":int(len(a)),
        "mean_ic":float(a.mean()) if len(a) else 0.0,
        "ic_ir":float(a.mean()/sd) if sd>0 else 0.0,
        "hac_t":t,
        "hac_p":p,
        "high_minus_low":float(np.mean(spreads)) if spreads else 0.0,
    }


def targets(frame: pl.DataFrame, start: date, end: date, exclude: set[str]|None=None) -> dict:
    ex=exclude or set()
    out={}
    for p in frame.filter((pl.col("date")>=start)&(pl.col("date")<end)).partition_by("date",maintain_order=True):
        rows=sorted(
            [(str(r["symbol"]),float(r["signal"])) for r in p.iter_rows(named=True) if str(r["symbol"]) not in ex],
            key=lambda z:z[1],
        )
        if len(rows)<MIN_XS:
            continue
        k=max(2,len(rows)//5)
        w={}
        for s,_ in rows[:k]:
            w[s]=-0.5/k
        for s,_ in rows[-k:]:
            w[s]=0.5/k
        out[p["date"][0]]=w
    return out


def sim(tg: dict, returns: dict, start: date, end: date, cost_bps: float) -> dict:
    prev={}
    rr=[]
    cont={}
    turns=[]
    for d in sorted(k for k in tg if start<=k<end):
        w=tg[d]
        turn=sum(abs(w.get(s,0.0)-prev.get(s,0.0)) for s in set(w)|set(prev))
        gross=0.0
        for s,weight in w.items():
            r=returns.get((d,s))
            if r is not None:
                gross+=weight*r
                cont[s]=cont.get(s,0.0)+weight*r
        rr.append((d,gross-turn*cost_bps/10000.0))
        turns.append(turn)
        prev=w
    if not rr:
        return {"metrics":{"annualized_sharpe":0.0,"total_return":0.0,"max_drawdown":0.0,"n_weeks":0},"by_year":{},"asset_contribution":{}}
    a=np.array([r for _,r in rr],dtype=float)
    eq=np.cumprod(1.0+a)
    peak=np.maximum.accumulate(eq)
    dd=eq/peak-1.0
    sd=float(a.std(ddof=1)) if len(a)>1 else 0.0
    by={}
    for y in sorted({d.year for d,_ in rr}):
        q=np.array([r for d,r in rr if d.year==y],dtype=float)
        qs=float(q.std(ddof=1)) if len(q)>1 else 0.0
        by[str(y)]={"total_return":float(np.prod(1.0+q)-1.0),"sharpe":float(q.mean()/qs*math.sqrt(52.0)) if qs>0 else 0.0}
    return {
        "metrics":{
            "annualized_sharpe":float(a.mean()/sd*math.sqrt(52.0)) if sd>0 else 0.0,
            "total_return":float(eq[-1]-1.0),
            "max_drawdown":float(dd.min()),
            "n_weeks":len(a),
            "turnover":float(sum(turns)),
        },
        "by_year":by,
        "asset_contribution":cont,
    }


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",type=Path,required=True)
    args=ap.parse_args()

    daily=load_daily(args.root)
    base=base_returns(daily)
    wr=week_ret_map(daily)
    frames={w:feature_frame(base,w) for w in WINDOWS}
    dev_diag={w:diagnostics(frames[w],wr,DEV0,DEV1) for w in WINDOWS}
    dev={w:sim(targets(frames[w],DEV0,DEV1),wr,DEV0,DEV1,COST) for w in WINDOWS}
    dm=dev[CAN]["metrics"]
    gate=(
        dev_diag[CAN]["mean_ic"]>0.02
        and dev_diag[CAN]["hac_p"]<0.05
        and dev_diag[CAN]["high_minus_low"]>0
        and dm["annualized_sharpe"]>0.70
        and dm["total_return"]>0
        and sum(dev[w]["metrics"]["total_return"]>0 for w in WINDOWS)>=2
    )
    out={
        "schema_version":1,
        "run_id":"20260928-downside-beta-weekly",
        "universe_symbols":int(daily["symbol"].n_unique()),
        "development_diagnostics":{str(w):dev_diag[w] for w in WINDOWS},
        "development":{str(w):dev[w] for w in WINDOWS},
        "development_gate_passed":gate,
        "oos_consumed":False,
        "trial_accounting":{"previous_parameter_trials":87,"new_parameter_trials":3,"cumulative_parameter_trials":90},
    }
    if not gate:
        out.update(classification="REJECT",success_gate_candidate=False,conclusion="Development gate failed; OOS not consumed.")
        print(json.dumps(out,indent=2,default=str))
        return

    res={}
    sharp=[]
    for w in WINDOWS:
        res[str(w)]={}
        tg=targets(frames[w],OOS0,OOS1)
        for mult in (1,2,3):
            res[str(w)][str(mult)]=sim(tg,wr,OOS0,OOS1,COST*mult)
        sharp.append(res[str(w)]["1"]["metrics"]["annualized_sharpe"])
    baseo=res[str(CAN)]["1"]
    bm=baseo["metrics"]
    oos_diag={w:diagnostics(frames[w],wr,OOS0,OOS1) for w in WINDOWS}
    ex=sim(targets(frames[CAN],OOS0,OOS1,{"BTCUSDT","ETHUSDT"}),wr,OOS0,OOS1,COST)
    strongest=max(baseo["asset_contribution"],key=lambda s:abs(baseo["asset_contribution"][s])) if baseo["asset_contribution"] else None
    exs=sim(targets(frames[CAN],OOS0,OOS1,{strongest} if strongest else set()),wr,OOS0,OOS1,COST) if strongest else None
    years=all(baseo["by_year"].get(str(y),{}).get("total_return",-1.0)>=0 for y in (2024,2025))
    stable=sum(res[str(w)]["1"]["metrics"]["total_return"]>0 for w in WINDOWS)>=2
    dsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp,n_obs_days=max(bm["n_weeks"]*7,1))
    gdsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp+[0.0]*87,n_obs_days=max(bm["n_weeks"]*7,1))
    qual=(
        bm["annualized_sharpe"]>1.0
        and oos_diag[CAN]["mean_ic"]>0.02
        and res[str(CAN)]["2"]["metrics"]["total_return"]>0
        and stable
        and years
        and bm["max_drawdown"]>-0.35
        and ex["metrics"]["total_return"]>0
        and (exs is None or exs["metrics"]["total_return"]>0)
    )
    out.update(
        oos_consumed=True,
        oos_diagnostics={str(w):oos_diag[w] for w in WINDOWS},
        oos_results=res,
        exclude_btc_eth=ex,
        strongest_asset=strongest,
        exclude_strongest=exs,
        multiple_testing={"family_dsr":dsr,"global_90_trial_proxy":gdsr,"pbo":"N/A: three preregistered estimation windows"},
        success_gate_candidate=qual,
        classification="EXPLORATORY_PASS" if qual else "REJECT",
    )
    print(json.dumps(out,indent=2,default=str))


if __name__=="__main__":
    main()
