#!/usr/bin/env python3
from __future__ import annotations
import argparse,glob,json,math
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
import numpy as np
import polars as pl
from src.experiment import compute_deflated_sharpe
W=(150,200,250);CAN=200;COST=10.;DEV0=date(2021,1,1);DEV1=date(2024,1,1);OOS0=date(2024,1,1);OOS1=date(2026,1,1)

def load(price_root,funding_store):
 fs=glob.glob(str(price_root/"symbol=BTCUSDT"/"year=*"/"month=*"/"data.parquet"))
 x=(pl.scan_parquet(fs,hive_partitioning=False).filter(pl.col("timestamp")<pl.datetime(2026,9,1,time_zone="UTC"))
    .select("timestamp","open","high","low","close").collect().sort("timestamp"))
 d=(x.with_columns(pl.col("timestamp").dt.date().alias("date")).group_by("date").agg(
    pl.col("open").first().alias("open"),pl.col("close").last().alias("close"),pl.len().alias("hours")).sort("date"))
 d=d.filter(pl.col("hours")==24).drop("hours")
 ffs=glob.glob(str(funding_store/"crypto_futures_funding_BTCUSDT_PERP"/"year=*"/"month=*"/"data.parquet"))
 f=(pl.scan_parquet(ffs,hive_partitioning=False).filter(pl.col("timestamp")<pl.datetime(2026,9,1,time_zone="UTC"))
    .select("timestamp","funding_rate").collect().sort("timestamp"))
 return d,f

def run(d,f,window,start,end,cost):
 x=(d.with_columns(
    pl.col("close").shift(1).rolling_mean(window).alias("_sma"),
    pl.col("close").shift(1).alias("_prev_close"),
    pl.col("open").shift(-1).alias("_next_open"),
    pl.col("date").shift(-1).alias("_next_date"))
    .with_columns((pl.col("_prev_close")>pl.col("_sma")).cast(pl.Float64).alias("target"))
    .filter(pl.col("_sma").is_finite()&pl.col("_next_open").is_finite()))
 fr=f.to_dicts(); rr=[];prev=0.; funding_total=0.
 for r in x.to_dicts():
  day=r["date"]
  if not(start<=day<end):continue
  t0=datetime.combine(day,datetime.min.time(),tzinfo=timezone.utc);t1=t0+timedelta(days=1)
  pos=float(r["target"]); price_ret=float(r["_next_open"]/r["open"]-1)
  fund=sum(float(z["funding_rate"]) for z in fr if t0<z["timestamp"]<=t1)
  ret=pos*price_ret-pos*fund-abs(pos-prev)*cost/10000
  rr.append((day,ret));funding_total+=-pos*fund;prev=pos
 if not rr:return {"metrics":{"annualized_sharpe":0,"total_return":0,"max_drawdown":0,"n_days":0}}
 a=np.array([r for _,r in rr]);eq=np.cumprod(1+a);pk=np.maximum.accumulate(eq);dd=eq/pk-1;sd=np.std(a,ddof=1)
 by={}
 for y in sorted({d.year for d,_ in rr}):
  q=np.array([r for d,r in rr if d.year==y]);s=np.std(q,ddof=1)
  by[str(y)]={"total_return":float(np.prod(1+q)-1),"sharpe":float(np.mean(q)/s*math.sqrt(365)) if len(q)>1 and s>0 else 0}
 return {"metrics":{"annualized_sharpe":float(np.mean(a)/sd*math.sqrt(365)) if sd>0 else 0,
     "total_return":float(eq[-1]-1),"max_drawdown":float(dd.min()),"n_days":len(a),"funding_component":float(funding_total)},"by_year":by}

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--price-root",type=Path,required=True);ap.add_argument("--funding-store",type=Path,required=True);a=ap.parse_args()
 d,f=load(a.price_root,a.funding_store)
 dev={w:run(d,f,w,DEV0,DEV1,COST) for w in W};ds={w:dev[w]["metrics"]["annualized_sharpe"] for w in W};dr={w:dev[w]["metrics"]["total_return"] for w in W}
 gate=ds[CAN]>.70 and dr[CAN]>0 and sum(v>0 for v in dr.values())>=2
 out={"schema_version":1,"run_id":"20260928-btc-sma-trend-longonly","development":{str(w):dev[w] for w in W},"development_gate_passed":gate,"oos_consumed":False,
      "trial_accounting":{"previous_parameter_trials":57,"new_parameter_trials":3,"cumulative_parameter_trials":60}}
 if not gate:out.update(classification="REJECT",conclusion="Development gate failed; OOS not consumed.");print(json.dumps(out,indent=2,default=str));return
 res={};sharp=[]
 for w in W:
  res[str(w)]={}
  for m in (1,2,3):res[str(w)][str(m)]=run(d,f,w,OOS0,OOS1,COST*m)
  sharp.append(res[str(w)]["1"]["metrics"]["annualized_sharpe"])
 can=res[str(CAN)]["1"];dsr=compute_deflated_sharpe(can["metrics"]["annualized_sharpe"],sharp,n_obs_days=can["metrics"]["n_days"])
 b=can["metrics"];two=res[str(CAN)]["2"]["metrics"];years=all(can["by_year"].get(str(y),{}).get("total_return",-1)>=0 for y in (2024,2025))
 qual=b["annualized_sharpe"]>1 and b["total_return"]>0 and two["total_return"]>0 and sum(res[str(w)]["1"]["metrics"]["total_return"]>0 for w in W)>=2 and years
 out.update(oos_consumed=True,oos_results=res,multiple_testing={"family_dsr":dsr},success_gate_candidate=qual,classification="EXPLORATORY_PASS" if qual else "REJECT")
 print(json.dumps(out,indent=2,default=str))
if __name__=="__main__":main()
