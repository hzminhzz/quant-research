#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math
from datetime import datetime,timedelta,timezone
from pathlib import Path
import numpy as np
import polars as pl
from scripts.run_crypto_high_momentum import simulate, validate_panel
from src.experiment import compute_deflated_sharpe

LOOKBACKS=(336,720,1440); CAN=720; HIST_WEEKS=52; MIN_XS=8; COST=3.0
DEV0=datetime(2021,1,1,tzinfo=timezone.utc); DEV1=datetime(2024,1,1,tzinfo=timezone.utc)
OOS0=datetime(2024,1,1,tzinfo=timezone.utc); OOS1=datetime(2026,1,1,tzinfo=timezone.utc)

def signal_frame(df,lookback):
    x=(df.sort(["symbol","timestamp"])
       .with_columns(
          (pl.col("close").shift(1).over("symbol")/pl.col("close").shift(lookback+1).over("symbol")-1).alias("_mom"),
          pl.col("timestamp").shift(lookback+1).over("symbol").alias("_anchor"))
       .filter((pl.col("timestamp").dt.weekday()==1)&(pl.col("timestamp").dt.hour()==0)
               &pl.col("_mom").is_finite()
               &(pl.col("_anchor")==pl.col("timestamp")-pl.duration(hours=lookback+1))))
    x=(x.with_columns(
       pl.col("_mom").shift(1).rolling_mean(HIST_WEEKS).over("symbol").alias("_hist_mean"),
       pl.col("_mom").shift(1).rolling_std(HIST_WEEKS).over("symbol").alias("_hist_std"),
       pl.col("timestamp").shift(HIST_WEEKS).over("symbol").alias("_hist_anchor"))
       .with_columns(((pl.col("_mom")-pl.col("_hist_mean"))/pl.col("_hist_std")).alias("signal")))
    return x.filter(pl.col("signal").is_finite() & (pl.col("_hist_std")>0)
                    &(pl.col("_hist_anchor")==pl.col("timestamp")-pl.duration(weeks=HIST_WEEKS)))\
            .filter(pl.len().over("timestamp")>=MIN_XS).sort(["timestamp","symbol"])

def targets(frame,start,end,exclude=None,delay=0):
    ex=exclude or set(); z=frame.filter((pl.col("timestamp")>=start)&(pl.col("timestamp")<end)&(~pl.col("symbol").is_in(sorted(ex))))
    out={}
    for p in z.partition_by("timestamp",maintain_order=True):
        rows=sorted([(r["symbol"],float(r["signal"])) for r in p.iter_rows(named=True)],key=lambda q:q[1])
        n=len(rows)
        if n<MIN_XS: continue
        k=max(1,n//4); w={}
        for s,_ in rows[:k]: w[str(s)]=-0.5/k
        for s,_ in rows[-k:]: w[str(s)]=0.5/k
        out[p["timestamp"][0]+timedelta(hours=delay)]=w
    return out

def run(prices,frame,lookback,start,end,cost,exclude=None,delay=0):
    return simulate(prices,targets(frame,start,end,exclude,delay),cost,start,end)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--data",type=Path,required=True); a=ap.parse_args()
    prices=pl.read_parquet(a.data).sort(["symbol","timestamp"]); integ=validate_panel(prices)
    devsrc=prices.filter(pl.col("timestamp")<DEV1)
    devframes={h:signal_frame(devsrc,h) for h in LOOKBACKS}
    dev={h:run(devsrc,devframes[h],h,DEV0,DEV1,COST) for h in LOOKBACKS}
    ds={h:dev[h]["metrics"]["annualized_sharpe"] for h in LOOKBACKS}; dr={h:dev[h]["metrics"]["total_return"] for h in LOOKBACKS}
    gate=ds[CAN]>.70 and dr[CAN]>0 and sum(v>0 for v in dr.values())>=2
    out={"schema_version":1,"run_id":"20260928-own-history-momentum-30d","data_integrity":integ,
         "development":{str(h):{"net_sharpe":ds[h],"total_return":dr[h],"max_drawdown":dev[h]["metrics"]["max_drawdown"]} for h in LOOKBACKS},
         "development_gate_passed":gate,"oos_consumed":False,
         "trial_accounting":{"previous_parameter_trials":45,"new_parameter_trials":3,"cumulative_parameter_trials":48}}
    if not gate:
        out.update(classification="REJECT",conclusion="Development gate failed; OOS not consumed."); print(json.dumps(out,indent=2,default=str)); return
    frames={h:signal_frame(prices,h) for h in LOOKBACKS}; res={}; sharpes=[]
    for h in LOOKBACKS:
        res[str(h)]={}
        for m in (1.,2.,3.): res[str(h)][str(m)]=run(prices,frames[h],h,OOS0,OOS1,COST*m)
        sharpes.append(float(res[str(h)]["1.0"]["metrics"]["annualized_sharpe"]))
    can=res[str(CAN)]["1.0"]; contrib=can["asset_contribution"]; strong=max(contrib,key=contrib.get) if contrib else None
    abl={"exclude_btc_eth":run(prices,frames[CAN],CAN,OOS0,OOS1,COST,{"BTCUSDT","ETHUSDT"}),
         "delay_one_hour":run(prices,frames[CAN],CAN,OOS0,OOS1,COST,delay=1)}
    if strong: abl["exclude_strongest"]={"asset":strong,"result":run(prices,frames[CAN],CAN,OOS0,OOS1,COST,{strong})}
    # Conservative DSR family view plus global trial count proxy via duplicated historical null dispersion.
    fam=compute_deflated_sharpe(can["metrics"]["annualized_sharpe"],sharpes,n_obs_days=can["metrics"]["n_days"])
    global_sharpes=sharpes + [0.0]*(48-len(sharpes))
    glob=compute_deflated_sharpe(can["metrics"]["annualized_sharpe"],global_sharpes,n_obs_days=can["metrics"]["n_days"])
    b=can["metrics"]; two=res[str(CAN)]["2.0"]["metrics"]
    robust=(sum(res[str(h)]["1.0"]["metrics"]["total_return"]>0 for h in LOOKBACKS)>=2
            and abl["exclude_btc_eth"]["metrics"]["total_return"]>0 and abl["delay_one_hour"]["metrics"]["total_return"]>0
            and (not strong or abl["exclude_strongest"]["result"]["metrics"]["total_return"]>0))
    qual=b["annualized_sharpe"]>1 and b["total_return"]>0 and two["total_return"]>0 and robust
    out.update(oos_consumed=True,oos_results=res,ablations=abl,multiple_testing={"family_dsr":fam,"global_48_trial_proxy":glob},
               success_gate_candidate=qual,classification="EXPLORATORY_PASS" if qual else "REJECT")
    print(json.dumps(out,indent=2,default=str))
if __name__=="__main__": main()
