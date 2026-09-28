#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math
from datetime import date,timedelta
from pathlib import Path
import numpy as np
import polars as pl
from scipy.stats import spearmanr
from scripts.run_crypto_risk_managed_xs_momentum import load_daily,week_ret_map,sim
from src.experiment import compute_deflated_sharpe

DEV0=date(2022,1,1);DEV1=date(2024,1,1);OOS0=date(2024,1,1);OOS1=date(2026,1,1)
COST=10.;MIN_XS=10

def features(d):
 x=(d.with_columns(
   pl.col("close").shift(1).over("symbol").alias("_c1"),
   pl.col("close").shift(8).over("symbol").alias("_c8"),
   pl.col("close").shift(31).over("symbol").alias("_c31"),
   pl.col("close").shift(91).over("symbol").alias("_c91"),
   pl.col("qv").shift(1).rolling_mean(7).over("symbol").alias("_q7"),
   pl.col("qv").shift(1).rolling_mean(30).over("symbol").alias("_q30"),
   pl.col("qv").shift(1).rolling_sum(30).over("symbol").alias("_liq"),
   pl.col("date").shift(91).over("symbol").alias("_anchor"))
  .with_columns(
   (pl.col("_c1")/pl.col("_c8")-1).alias("_m7"),
   (pl.col("_c1")/pl.col("_c31")-1).alias("_m30"),
   (pl.col("_c1")/pl.col("_c91")-1).alias("_m90"),
   (pl.col("_q7")/pl.col("_q30")-1).alias("_vt"))
  .filter((pl.col("date").dt.weekday()==1)&pl.col("_m7").is_finite()&pl.col("_m30").is_finite()
          &pl.col("_m90").is_finite()&pl.col("_vt").is_finite()&pl.col("_liq").is_finite()
          &(pl.col("_anchor")==pl.col("date")-pl.duration(days=91))))
 out=[]
 for p in x.partition_by("date",maintain_order=True):
  p=p.sort("_liq",descending=True).head(30);n=p.height
  if n<MIN_XS:continue
  p=(p.with_columns(
    (pl.col("_m7").rank(method="average")/n).alias("_r7"),
    (pl.col("_m30").rank(method="average")/n).alias("_r30"),
    (pl.col("_m90").rank(method="average")/n).alias("_r90"),
    (pl.col("_vt").rank(method="average")/n).alias("_rv"))
    .with_columns(((pl.col("_r7")+pl.col("_r30")+pl.col("_r90")+pl.col("_rv"))/4).alias("signal")))
  out.append(p.select("date","symbol","signal"))
 return pl.concat(out,how="vertical").sort(["date","symbol"])

def targets(f,start,end,exclude=None,delay=0):
 ex=exclude or set();out={}
 z=f.filter((pl.col("date")>=start-timedelta(days=7*delay))&(pl.col("date")<end))
 for p in z.partition_by("date",maintain_order=True):
  rows=sorted([(str(r["symbol"]),float(r["signal"])) for r in p.iter_rows(named=True) if str(r["symbol"]) not in ex],key=lambda q:q[1])
  if len(rows)<MIN_XS:continue
  k=max(2,len(rows)//5);w={}
  for s,_ in rows[:k]:w[s]=-.5/k
  for s,_ in rows[-k:]:w[s]=.5/k
  dd=p["date"][0]+timedelta(days=7*delay)
  if start<=dd<end:out[dd]=w
 return out

def diag(f,wr,start,end):
 vals=[];sp=[]
 for p in f.filter((pl.col("date")>=start)&(pl.col("date")<end)).partition_by("date",maintain_order=True):
  rows=[r for r in p.iter_rows(named=True) if (r["date"],str(r["symbol"])) in wr]
  if len(rows)<MIN_XS:continue
  s=np.array([float(r["signal"]) for r in rows]);y=np.array([wr[(r["date"],str(r["symbol"]))] for r in rows])
  ic=float(spearmanr(s,y).statistic)
  if np.isfinite(ic):vals.append(ic)
  ix=np.argsort(s);k=max(2,len(ix)//5);sp.append(float(y[ix[-k:]].mean()-y[ix[:k]].mean()))
 a=np.array(vals);m=float(a.mean()) if len(a) else 0.;sd=float(a.std(ddof=1)) if len(a)>1 else 0.
 return {"n_weeks":len(a),"mean_ic":m,"ic_ir":m/sd if sd>0 else 0.,"mean_top_minus_bottom":float(np.mean(sp)) if sp else 0.}





def main():
 ap=argparse.ArgumentParser();ap.add_argument("--root",type=Path,required=True);a=ap.parse_args()
 d=load_daily(a.root);f=features(d);wr=week_ret_map(d)
 di=diag(f,wr,DEV0,DEV1);dev=sim(targets(f,DEV0,DEV1),wr,DEV0,DEV1,COST);dm=dev["metrics"]
 gate=di["mean_ic"]>.02 and di["mean_top_minus_bottom"]>0 and dm["annualized_sharpe"]>.70 and dm["total_return"]>0
 out={"schema_version":1,"run_id":"20260928-ctrend-lite-weekly","universe_symbols":d["symbol"].n_unique(),
      "development_ic":di,"development":dev,"development_gate_passed":gate,"oos_consumed":False,
      "trial_accounting":{"previous_parameter_trials":70,"new_parameter_trials":1,"cumulative_parameter_trials":71}}
 if not gate:
  out.update(classification="REJECT",success_gate_candidate=False,conclusion="Development gate failed; OOS not consumed.")
  print(json.dumps(out,indent=2,default=str));return
 res={str(m):sim(targets(f,OOS0,OOS1),wr,OOS0,OOS1,COST*m) for m in (1,2,3)}
 base=res["1"];bm=base["metrics"];delay=sim(targets(f,OOS0,OOS1,delay=1),wr,OOS0,OOS1,COST)
 ex=sim(targets(f,OOS0,OOS1,{"BTCUSDT","ETHUSDT"}),wr,OOS0,OOS1,COST)
 strong=max(base["asset_contribution"],key=base["asset_contribution"].get) if base.get("asset_contribution") else None
 exs=sim(targets(f,OOS0,OOS1,{strong} if strong else set()),wr,OOS0,OOS1,COST) if strong else None
 yrs=all(base["by_year"].get(str(y),{}).get("total_return",-1)>=0 for y in (2024,2025))
 qual=(bm["annualized_sharpe"]>1 and bm["total_return"]>0 and res["2"]["metrics"]["total_return"]>0
       and yrs and bm["max_drawdown"]>-.35 and delay["metrics"]["total_return"]>0 and ex["metrics"]["total_return"]>0
       and (exs is None or exs["metrics"]["total_return"]>0))
 dsr=compute_deflated_sharpe(bm["annualized_sharpe"],[bm["annualized_sharpe"]]+[0.]*70,n_obs_days=max(bm["n_weeks"]*7,1))
 out.update(oos_consumed=True,oos_ic=diag(f,wr,OOS0,OOS1),oos_results=res,delay_one_week=delay,exclude_btc_eth=ex,
            strongest_asset=strong,exclude_strongest=exs,multiple_testing={"global_71_trial_proxy":dsr,"pbo":"N/A: one fixed composite"},
            success_gate_candidate=qual,classification="EXPLORATORY_PASS" if qual else "REJECT")
 print(json.dumps(out,indent=2,default=str))

if __name__=="__main__":main()
