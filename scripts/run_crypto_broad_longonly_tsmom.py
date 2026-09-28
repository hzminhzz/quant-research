#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from datetime import date, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import polars as pl

from scripts.run_crypto_risk_managed_xs_momentum import load_daily, week_ret_map
from src.experiment import compute_deflated_sharpe

LOOKBACKS=(14,30,60)
CAN=30
VOL=30
TOPN=30
MIN_POS=5
COST=10.0
DEV0=date(2022,1,1)
DEV1=date(2024,1,1)
OOS0=date(2024,1,1)
OOS1=date(2026,1,1)

def feature_frame(d: pl.DataFrame, lookback: int) -> pl.DataFrame:
    hist=max(lookback+1,VOL+1,31)
    x=(d.sort(["symbol","date"])
       .with_columns(
          pl.col("close").shift(1).over("symbol").alias("_c1"),
          pl.col("close").shift(lookback+1).over("symbol").alias("_cl"),
          pl.col("close").shift(1).over("symbol").alias("_pc"),
          pl.col("date").shift(1).over("symbol").alias("_pd"),
          pl.col("qv").shift(1).rolling_sum(30).over("symbol").alias("_liq"),
          pl.col("date").shift(hist).over("symbol").alias("_anchor"))
       .with_columns(
          pl.when(pl.col("date")-pl.col("_pd")==pl.duration(days=1))
            .then(pl.col("close")/pl.col("_pc")-1.0)
            .otherwise(None).alias("_ret"))
       .with_columns(
          pl.col("_ret").shift(1).rolling_std(VOL).over("symbol").alias("_vol"),
          (pl.col("_c1")/pl.col("_cl")-1.0).alias("signal"))
       .filter((pl.col("date").dt.weekday()==1)
               & pl.col("signal").is_finite()
               & pl.col("_vol").is_finite()
               & (pl.col("_vol")>0)
               & pl.col("_liq").is_finite()
               & (pl.col("_anchor")==pl.col("date")-pl.duration(days=hist))))
    out=[]
    for p in x.partition_by("date",maintain_order=True):
        p=p.sort("_liq",descending=True).head(TOPN)
        if p.height>=MIN_POS:
            out.append(p.select("date","symbol","signal","_vol"))
    return pl.concat(out,how="vertical").sort(["date","symbol"]) if out else pl.DataFrame()


def targets(f: pl.DataFrame, start: date, end: date, exclude=None, delay_days: int=0):
    ex=exclude or set()
    out={}
    for p in f.filter((pl.col("date")>=start)&(pl.col("date")<end)).partition_by("date",maintain_order=True):
        rows=[r for r in p.iter_rows(named=True) if str(r["symbol"]) not in ex and float(r["signal"])>0]
        d=p["date"][0]+timedelta(days=delay_days)
        if len(rows)<MIN_POS:
            out[d]={}
            continue
        inv=np.array([1.0/float(r["_vol"]) for r in rows],dtype=float)
        inv=inv/inv.sum()
        out[d]={str(r["symbol"]):float(w) for r,w in zip(rows,inv)}
    return out

def perf(points):
    if len(points)<3:
        return {"n_days":0,"annualized_sharpe":0.0,"total_return":0.0,"max_drawdown":0.0}
    eq=np.array([v for _,v in points],dtype=float)
    r=eq[1:]/eq[:-1]-1.0
    sd=float(r.std(ddof=1))
    peak=np.maximum.accumulate(eq)
    dd=eq/peak-1.0
    neg=r[r<0]
    dsd=float(neg.std(ddof=1)) if len(neg)>1 else 0.0
    return {
        "n_days":int(len(r)),
        "annualized_sharpe":float(r.mean()/sd*math.sqrt(365)) if sd>0 else 0.0,
        "sortino":float(r.mean()/dsd*math.sqrt(365)) if dsd>0 else 0.0,
        "total_return":float(eq[-1]/eq[0]-1.0),
        "max_drawdown":float(dd.min()),
    }


def simulate(d: pl.DataFrame, tg, start: date, end: date, cost_bps: float):
    panel=d.filter((pl.col("date")>=start)&(pl.col("date")<end)).sort(["date","symbol"])
    qty={}
    cash=1.0
    last={}
    contrib={}
    points=[]
    turnover=0.0
    costs=0.0
    rebalances=0
    for p in panel.partition_by("date",maintain_order=True):
        dt=p["date"][0]
        current={str(r["symbol"]):float(r["open"]) for r in p.iter_rows(named=True) if r["open"] is not None and float(r["open"])>0}
        # If a held contract disappears from the daily panel, settle at its last
        # observed open rather than forward-filling an untradeable position.
        for s in list(qty):
            if s not in current and s in last:
                cash+=qty[s]*last[s]
                qty.pop(s,None)
        for s,px in current.items():
            if s in qty and s in last:
                contrib[s]=contrib.get(s,0.0)+qty[s]*(px-last[s])
        if dt in tg:
            equity=cash+sum(q*current[s] for s,q in qty.items() if s in current)
            desired=tg[dt]
            trades=[]
            for s in sorted(set(qty)|set(desired)):
                px=current.get(s)
                if px is None:
                    continue
                delta=desired.get(s,0.0)*equity-qty.get(s,0.0)*px
                if abs(delta)>1e-12:
                    trades.append((s,delta,px))
            traded=sum(abs(delta) for _,delta,_ in trades)
            cost=traded*cost_bps/10000.0
            cash-=cost
            costs+=cost
            turnover+=traded
            for s,delta,px in trades:
                cash-=delta
                qty[s]=qty.get(s,0.0)+delta/px
                contrib[s]=contrib.get(s,0.0)-abs(delta)*cost_bps/10000.0
                if abs(qty[s])<1e-12:
                    qty.pop(s,None)
            rebalances+=1
        last.update(current)
        equity=cash+sum(q*last[s] for s,q in qty.items() if s in last)
        points.append((dt,equity))
    return {
        "metrics":perf(points),
        "by_year":{str(y):perf([(dt,v) for dt,v in points if dt.year==y]) for y in sorted({dt.year for dt,_ in points})},
        "rebalances":rebalances,
        "turnover_on_initial_equity":turnover,
        "cost_on_initial_equity":costs,
        "asset_contribution":contrib,
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--anchor",type=Path,required=True)
    ap.add_argument("--out",type=Path)
    a=ap.parse_args()
    root=a.anchor.parents[3]/".data"/"store"/"crypto_futures_ohlcv_1h_BINANCE_UM_PERP"
    d=load_daily(root)
    fs={w:feature_frame(d,w) for w in LOOKBACKS}
    dev={w:simulate(d,targets(fs[w],DEV0,DEV1),DEV0,DEV1,COST) for w in LOOKBACKS}
    dm=dev[CAN]["metrics"]
    gate=(dm["annualized_sharpe"]>.70 and dm["total_return"]>0 and dm["max_drawdown"]>-.45
          and sum(dev[w]["metrics"]["total_return"]>0 for w in LOOKBACKS)>=2)
    out={
        "schema_version":1,
        "run_id":"20260928-broad-longonly-tsmom-weekly",
        "strategy_family":"broad_longonly_vol_scaled_tsmom",
        "research_archetype":"time_series_rule",
        "universe_symbols":int(d["symbol"].n_unique()),
        "development":{str(w):dev[w] for w in LOOKBACKS},
        "development_gate_passed":gate,
        "oos_consumed":False,
        "trial_accounting":{"previous_parameter_trials":145,"new_parameter_trials":3,"cumulative_parameter_trials":148},
    }
    if not gate:
        out.update(
            classification="REJECT",
            success_gate_candidate=False,
            multiple_testing={"dsr_probability":None,"pbo":"N/A: development gate failed before OOS."},
            conclusion="REJECT. Development gate failed; OOS not consumed.")
        payload=json.dumps(out,indent=2,default=str)
        if a.out:
            a.out.write_text(payload,encoding="utf-8")
        print(payload)
        return

    res={}
    base_sharpes=[]
    for w in LOOKBACKS:
        res[str(w)]={}
        for mult in (1,2,3):
            res[str(w)][str(mult)]=simulate(d,targets(fs[w],OOS0,OOS1),OOS0,OOS1,COST*mult)
        base_sharpes.append(res[str(w)]["1"]["metrics"]["annualized_sharpe"])

    base=res[str(CAN)]["1"]
    bm=base["metrics"]
    ex=simulate(d,targets(fs[CAN],OOS0,OOS1,{"BTCUSDT","ETHUSDT"}),OOS0,OOS1,COST)
    strongest=max(base["asset_contribution"],key=lambda s:abs(base["asset_contribution"][s])) if base["asset_contribution"] else None
    exs=simulate(d,targets(fs[CAN],OOS0,OOS1,{strongest} if strongest else set()),OOS0,OOS1,COST) if strongest else None
    delay=simulate(d,targets(fs[CAN],OOS0,OOS1,delay_days=1),OOS0,OOS1,COST)

    years_ok=all(base["by_year"].get(str(y),{}).get("total_return",-1)>=0 for y in (2024,2025))
    stable=sum(res[str(w)]["1"]["metrics"]["total_return"]>0 for w in LOOKBACKS)>=2
    family_dsr=compute_deflated_sharpe(bm["annualized_sharpe"],base_sharpes,n_obs_days=max(bm["n_days"],1))
    global_dsr=compute_deflated_sharpe(bm["annualized_sharpe"],base_sharpes+[0.0]*145,n_obs_days=max(bm["n_days"],1))
    qual=(bm["annualized_sharpe"]>1.0
          and res[str(CAN)]["2"]["metrics"]["total_return"]>0
          and stable and years_ok and bm["max_drawdown"]>-.35
          and delay["metrics"]["total_return"]>0
          and ex["metrics"]["total_return"]>0
          and (exs is None or exs["metrics"]["total_return"]>0)
          and family_dsr["dsr_probability"]>=.95
          and global_dsr["dsr_probability"]>=.95)

    out.update(
        oos_consumed=True,
        oos_results=res,
        exclude_btc_eth=ex,
        strongest_asset=strongest,
        exclude_strongest=exs,
        one_day_delay=delay,
        multiple_testing={
            "family_dsr":family_dsr,
            "global_148_trial_proxy":global_dsr,
            "pbo":"N/A: three preregistered lookbacks; no winner-selection CPCV."
        },
        robustness_evaluations=6,
        success_gate_candidate=qual,
        classification="EXPLORATORY_PASS" if qual else "REJECT",
        conclusion=("EXPLORATORY_PASS. Meets preregistered exploratory success gate; sealed confirmation remains untouched."
                    if qual else "REJECT. OOS or robustness/multiple-testing gate failed."))
    payload=json.dumps(out,indent=2,default=str)
    if a.out:
        a.out.write_text(payload,encoding="utf-8")
    print(payload)


if __name__=="__main__":
    main()
