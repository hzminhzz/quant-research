#!/usr/bin/env python3
from __future__ import annotations
import argparse,glob,json,math
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
import numpy as np
import polars as pl
from src.experiment import compute_deflated_sharpe

H=(5,10,20,30,60,90,150,250,360); COST=10.; DEV0=date(2021,1,1);DEV1=date(2024,1,1);OOS0=date(2024,1,1);OOS1=date(2026,1,1)

def load(price_root,fund_store):
 fs=glob.glob(str(price_root/"symbol=BTCUSDT"/"year=*"/"month=*"/"data.parquet"))
 x=(pl.scan_parquet(fs,hive_partitioning=False).filter(pl.col("timestamp")<pl.datetime(2026,9,1,time_zone="UTC"))
    .select("timestamp","open","high","low","close").collect().sort("timestamp"))
 d=(x.with_columns(pl.col("timestamp").dt.date().alias("date")).group_by("date").agg(
     pl.col("open").first().alias("open"),pl.col("high").max().alias("high"),pl.col("low").min().alias("low"),
     pl.col("close").last().alias("close"),pl.len().alias("hours")).sort("date")).filter(pl.col("hours")==24).drop("hours")
 ffs=glob.glob(str(fund_store/"crypto_futures_funding_BTCUSDT_PERP"/"year=*"/"month=*"/"data.parquet"))
 f=(pl.scan_parquet(ffs,hive_partitioning=False).filter(pl.col("timestamp")<pl.datetime(2026,9,1,time_zone="UTC"))
    .select("timestamp","funding_rate").collect().sort("timestamp"))
 return d,f

def model_states(close,h):
 n=len(close);state=np.zeros(n);stop=np.full(n,np.nan);active=False;trail=np.nan
 for i in range(n):
  if i<h+1:continue
  prior=close[i-1]
  hist=close[i-h-1:i-1]
  hi=float(np.max(hist));lo=float(np.min(hist));mid=(hi+lo)/2
  if active:
   trail=max(trail,mid) if np.isfinite(trail) else mid
   if prior<trail:
    active=False;trail=np.nan
  if not active and prior>hi:
   active=True;trail=mid
  state[i]=1.0 if active else 0.0
 return state

def exposure(d):
 c=d["close"].to_numpy(); n=len(c); combo=np.mean(np.column_stack([model_states(c,h) for h in H]),axis=1)
 r=np.full(n,np.nan);r[1:]=c[1:]/c[:-1]-1
 vol=np.full(n,np.nan)
 for i in range(91,n):
  vals=r[i-90:i]
  if np.all(np.isfinite(vals)):vol[i]=np.std(vals,ddof=1)*math.sqrt(365)
 lev=np.where(np.isfinite(vol)&(vol>0),np.minimum(2.0,.25/vol),0.0)
 return combo*lev

def funding_by_day(f):
 out={}
 for p in f.with_columns(pl.col("timestamp").dt.date().alias("date")).group_by("date").agg(pl.col("funding_rate").sum().alias("fund")).iter_rows(named=True):
  out[p["date"]]=float(p["fund"])
 return out

def run(d,f,start,end,cost,delay=0):
 exp=exposure(d); rows=d.to_dicts(); fb=funding_by_day(f); rr=[];prev=0.
 # exp[i] is executable at open of day i from information through day i-1.
 for i in range(len(rows)-1):
  day=rows[i]["date"]
  if not(start<=day<end):continue
  src=max(0,i-delay); pos=float(exp[src])
  price_ret=float(rows[i+1]["open"]/rows[i]["open"]-1)
  fund=fb.get(day,0.0)
  ret=pos*price_ret-pos*fund-abs(pos-prev)*cost/10000
  rr.append((day,ret,pos));prev=pos
 if not rr:return {"metrics":{"annualized_sharpe":0,"total_return":0,"max_drawdown":0,"n_days":0}}
 a=np.array([r for _,r,_ in rr]);eq=np.cumprod(1+a);pk=np.maximum.accumulate(eq);dd=eq/pk-1;sd=np.std(a,ddof=1)
 by={}
 for y in sorted({d.year for d,_,_ in rr}):
  q=np.array([r for d,r,_ in rr if d.year==y]);s=np.std(q,ddof=1)
  by[str(y)]={"total_return":float(np.prod(1+q)-1),"sharpe":float(np.mean(q)/s*math.sqrt(365)) if len(q)>1 and s>0 else 0}
 return {"metrics":{"annualized_sharpe":float(np.mean(a)/sd*math.sqrt(365)) if sd>0 else 0,"total_return":float(eq[-1]-1),
      "max_drawdown":float(dd.min()),"n_days":len(a),"mean_exposure":float(np.mean([p for _,_,p in rr]))},"by_year":by}

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--anchor",type=Path,required=True);a=ap.parse_args()
 store=a.anchor.parents[3]/".data"/"store";price_root=store/"crypto_futures_ohlcv_1h_BINANCE_UM_PERP"
 d,f=load(price_root,store);dev=run(d,f,DEV0,DEV1,COST);gate=dev["metrics"]["annualized_sharpe"]>.70 and dev["metrics"]["total_return"]>0
 out={"schema_version":1,"run_id":"20260928-btc-donchian-ensemble","development":dev,"development_gate_passed":gate,"oos_consumed":False,
      "trial_accounting":{"previous_parameter_trials":60,"new_parameter_trials":1,"cumulative_parameter_trials":61}}
 if not gate:out.update(classification="REJECT",conclusion="Development gate failed; OOS not consumed.");print(json.dumps(out,indent=2,default=str));return
 res={str(m):run(d,f,OOS0,OOS1,COST*m) for m in (1,2,3,5)};delay=run(d,f,OOS0,OOS1,COST,delay=1);can=res["1"];b=can["metrics"];two=res["2"]["metrics"]
 years=all(can["by_year"].get(str(y),{}).get("total_return",-1)>=0 for y in (2024,2025))
 qual=b["annualized_sharpe"]>1 and b["total_return"]>0 and two["total_return"]>0 and years and b["max_drawdown"]>-0.35 and delay["metrics"]["annualized_sharpe"]>.8
 # Global multiple-testing proxy uses 61 total attempts conservatively with null competitors; report separately from one-trial family PSR.
 glob=compute_deflated_sharpe(b["annualized_sharpe"],[b["annualized_sharpe"]]+[0.0]*60,n_obs_days=b["n_days"])
 out.update(oos_consumed=True,oos_results=res,delay_one_day=delay,multiple_testing={"global_61_trial_proxy":glob},success_gate_candidate=qual,
            classification="EXPLORATORY_PASS" if qual else "REJECT")
 print(json.dumps(out,indent=2,default=str))
if __name__=="__main__":main()
