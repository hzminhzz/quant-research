#!/usr/bin/env python3
"""Pre-registered liquidity-conditioned daily momentum/reversal research."""

from __future__ import annotations
import argparse, json, math
from datetime import datetime, timedelta, timezone
from pathlib import Path
import polars as pl

from scripts.run_crypto_high_momentum import simulate, validate_panel
from src.experiment import compute_deflated_sharpe

FRACTIONS=(0.20,0.25,0.33)
CANONICAL=0.25
LIQ_WINDOW=720
MIN_XS=8
COST=3.0
DEV0=datetime(2021,1,1,tzinfo=timezone.utc)
DEV1=datetime(2024,1,1,tzinfo=timezone.utc)
OOS0=datetime(2024,1,1,tzinfo=timezone.utc)
OOS1=datetime(2026,1,1,tzinfo=timezone.utc)

def daily_frame(df):
    x=df.sort(["symbol","timestamp"]).with_columns(
        (pl.col("close")*pl.col("volume")).alias("_dv"),
    ).with_columns(
        (pl.col("close").shift(1).over("symbol")/pl.col("close").shift(25).over("symbol")-1.0).alias("_prev_day_ret"),
        pl.col("_dv").shift(1).rolling_mean(LIQ_WINDOW).over("symbol").alias("_liq"),
        pl.col("timestamp").shift(LIQ_WINDOW).over("symbol").alias("_anchor"),
    ).filter(
        (pl.col("timestamp").dt.hour()==0)
        &pl.col("_prev_day_ret").is_finite()
        &pl.col("_liq").is_finite()
        &(pl.col("_anchor")==pl.col("timestamp")-pl.duration(hours=LIQ_WINDOW))
    ).with_columns(
        pl.col("_liq").rank(method="ordinal",descending=True).over("timestamp").alias("_liq_rank"),
        pl.len().over("timestamp").alias("_n"),
    )
    return x.filter(pl.col("_n")>=MIN_XS).sort(["timestamp","symbol"])

def targets(frame,start,end,fraction,exclude=None,delay=0):
    ex=exclude or set()
    z=frame.filter((pl.col("timestamp")>=start)&(pl.col("timestamp")<end)&(~pl.col("symbol").is_in(sorted(ex))))
    out={}
    for p in z.partition_by("timestamp",maintain_order=True):
        rows=list(p.iter_rows(named=True)); n=len(rows)
        if n<MIN_XS: continue
        cut=max(2,min(n-2,math.ceil(n*fraction)))
        rows=sorted(rows,key=lambda r:float(r["_liq"]),reverse=True)
        liquid=rows[:cut]; illiquid=rows[cut:]; w={}
        if len(liquid)>=2:
            q=sorted(liquid,key=lambda r:float(r["_prev_day_ret"]))
            k=max(1,len(q)//2)
            lo=q[:k]; hi=q[-k:]
            for r in hi: w[str(r["symbol"])]=w.get(str(r["symbol"]),0.0)+.25/len(hi)
            for r in lo: w[str(r["symbol"])]=w.get(str(r["symbol"]),0.0)-.25/len(lo)
        if len(illiquid)>=2:
            q=sorted(illiquid,key=lambda r:float(r["_prev_day_ret"]))
            k=max(1,len(q)//2)
            lo=q[:k]; hi=q[-k:]
            for r in lo: w[str(r["symbol"])]=w.get(str(r["symbol"]),0.0)+.25/len(lo)
            for r in hi: w[str(r["symbol"])]=w.get(str(r["symbol"]),0.0)-.25/len(hi)
        if w:
            out[p["timestamp"][0]+timedelta(hours=delay)]=w
    return out

def run_variant(prices,frame,fraction,start,end,cost,exclude=None,delay=0):
    return simulate(prices,targets(frame,start,end,fraction,exclude=exclude,delay=delay),cost,start,end)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--data",type=Path,required=True); a=ap.parse_args()
    prices=pl.read_parquet(a.data).sort(["symbol","timestamp"]); integrity=validate_panel(prices)
    dev_source=prices.filter(pl.col("timestamp")<DEV1); dev_frame=daily_frame(dev_source)
    development={f:run_variant(dev_source,dev_frame,f,DEV0,DEV1,COST) for f in FRACTIONS}
    sh={f:float(development[f]["metrics"]["annualized_sharpe"]) for f in FRACTIONS}
    rr={f:float(development[f]["metrics"]["total_return"]) for f in FRACTIONS}
    gate=sh[CANONICAL]>.70 and rr[CANONICAL]>0 and sum(v>0 for v in rr.values())>=2
    out={"schema_version":1,"run_id":"20260928-liquidity-signflip-daily","data_integrity":integrity,
         "development":{str(f):{"net_sharpe":sh[f],"total_return":rr[f],"max_drawdown":development[f]["metrics"]["max_drawdown"],"rebalances":development[f]["rebalances"]} for f in FRACTIONS},
         "development_gate_passed":gate,"oos_consumed":False,
         "trial_accounting":{"previous_parameter_trials":42,"new_parameter_trials":3,"cumulative_parameter_trials":45}}
    if not gate:
        out["classification"]="REJECT"; out["conclusion"]="Development liquidity-signflip gate failed; OOS was not consumed."; print(json.dumps(out,indent=2,default=str)); return 0
    full=daily_frame(prices); res={}; sharpes=[]
    for f in FRACTIONS:
        res[str(f)]={}
        for m in (1.0,2.0,3.0): res[str(f)][str(m)]=run_variant(prices,full,f,OOS0,OOS1,COST*m)
        sharpes.append(float(res[str(f)]["1.0"]["metrics"]["annualized_sharpe"]))
    can=res[str(CANONICAL)]["1.0"]; contrib=can["asset_contribution"]; strong=max(contrib,key=contrib.get) if contrib else None
    abl={"exclude_btc_eth":run_variant(prices,full,CANONICAL,OOS0,OOS1,COST,exclude={"BTCUSDT","ETHUSDT"}),
         "delay_one_hour":run_variant(prices,full,CANONICAL,OOS0,OOS1,COST,delay=1)}
    if strong: abl["exclude_strongest"]={"asset":strong,"result":run_variant(prices,full,CANONICAL,OOS0,OOS1,COST,exclude={strong})}
    dsr=compute_deflated_sharpe(float(can["metrics"]["annualized_sharpe"]),sharpes,n_obs_days=int(can["metrics"]["n_days"]))
    b=can["metrics"]; two=res[str(CANONICAL)]["2.0"]["metrics"]
    stable=sum(res[str(f)]["1.0"]["metrics"]["total_return"]>0 for f in FRACTIONS)>=2
    years=all(can["by_year"][str(y)]["total_return"]>=0 for y in (2024,2025))
    breadth=abl["exclude_btc_eth"]["metrics"]["total_return"]>0 and abl["delay_one_hour"]["metrics"]["total_return"]>0 and (not strong or abl["exclude_strongest"]["result"]["metrics"]["total_return"]>0)
    qual=b["annualized_sharpe"]>1 and b["total_return"]>0 and two["total_return"]>0 and stable and years and breadth and dsr["dsr_probability"]>=.95
    out.update({"oos_consumed":True,"oos_results":res,"ablations":abl,
                "multiple_testing":{"base_cost_sharpes":sharpes,"dsr":dsr,"pbo":"N/A: three preregistered liquidity splits","global_cumulative_parameter_trials":45},
                "funding_treatment":"not modeled","success_gate_candidate":qual,
                "classification":"EXPLORATORY_PASS" if qual else "REJECT"})
    print(json.dumps(out,indent=2,default=str)); return 0

if __name__=="__main__": raise SystemExit(main())
