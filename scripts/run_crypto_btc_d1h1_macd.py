#!/usr/bin/env python3
from __future__ import annotations
import argparse,glob,json,math
from datetime import datetime,timedelta,timezone
from pathlib import Path
import numpy as np
import polars as pl
from src.experiment import compute_deflated_sharpe
COST=10.;DEV0=datetime(2021,1,1,tzinfo=timezone.utc);DEV1=datetime(2024,1,1,tzinfo=timezone.utc);OOS0=datetime(2024,1,1,tzinfo=timezone.utc);OOS1=datetime(2026,1,1,tzinfo=timezone.utc)

def ema(x,span):
 a=2/(span+1);out=np.empty(len(x));out[:]=np.nan
 if not len(x):return out
 out[0]=x[0]
 for i in range(1,len(x)):out[i]=a*x[i]+(1-a)*out[i-1]
 return out
def macd(x):
 fast=ema(x,12);slow=ema(x,26);m=fast-slow;sig=ema(m,9);return m,sig

def load(root):
 fs=glob.glob(str(root/"symbol=BTCUSDT"/"year=*"/"month=*"/"data.parquet"))
 h=(pl.scan_parquet(fs,hive_partitioning=False).filter(pl.col("timestamp")<pl.datetime(2026,9,1,time_zone="UTC"))
    .select("timestamp","open","close").collect().sort("timestamp"))
 # enforce continuous hours within tested range naturally by checking shifted timestamp before signal use.
 daily=(h.with_columns(pl.col("timestamp").dt.date().alias("date")).group_by("date").agg(pl.col("close").last().alias("close"),pl.len().alias("hours"))
        .sort("date").filter(pl.col("hours")==24))
 dc=daily["close"].to_numpy();dm,ds=macd(dc)
 dstate={d:bool(m>s) for d,m,s in zip(daily["date"].to_list(),dm,ds)}
 return h,dstate

def positions(h,dstate,delay=0):
 rows=h.to_dicts();c=h["close"].to_numpy();m,s=macd(c);pos=np.zeros(len(rows));active=False; pending_entry=False; pending_exit=False
 for i in range(1,len(rows)):
  # Execute decisions generated at previous completed bar; optional extra hour delay by reading older signal state below.
  j=max(1,i-1-delay)
  prevj=j-1
  ts=rows[i]["timestamp"]
  if rows[i]["timestamp"]-rows[i-1]["timestamp"] != timedelta(hours=1):
   active=False
  # daily filter from day before current UTC date; never use current incomplete daily candle
  prev_date=(ts.date())
  available_days=[d for d in dstate.keys() if d < prev_date]
  daybull=dstate[max(available_days)] if available_days else False
  cross=(m[j]>s[j]) and (m[prevj]<=s[prevj])
  negative=rows[j]["close"]<rows[j]["open"]
  if active and negative: active=False
  if (not active) and cross and daybull: active=True
  pos[i]=1.0 if active else 0.0
 return pos

def run(h,dstate,start,end,cost,delay=0):
 p=positions(h,dstate,delay);o=h["open"].to_numpy();ts=h["timestamp"].to_list();rr=[];prev=0.
 for i in range(len(h)-1):
  if not(start<=ts[i]<end):continue
  if ts[i+1]-ts[i] != timedelta(hours=1):continue
  w=float(p[i]);r=float(o[i+1]/o[i]-1);net=w*r-abs(w-prev)*cost/10000;rr.append((ts[i],net));prev=w
 if not rr:return {"metrics":{"annualized_sharpe":0,"total_return":0,"max_drawdown":0,"n_hours":0}}
 # Aggregate exact hourly PnL to UTC daily returns before Sharpe.
 df=pl.DataFrame({"timestamp":[x[0] for x in rr],"r":[x[1] for x in rr]}).with_columns(pl.col("timestamp").dt.date().alias("date"))
 dr=df.group_by("date").agg(((pl.col("r")+1).product()-1).alias("r")).sort("date")
 a=dr["r"].to_numpy();eq=np.cumprod(1+a);pk=np.maximum.accumulate(eq);dd=eq/pk-1;sd=np.std(a,ddof=1)
 by={}
 for y in sorted(set(dr["date"].dt.year().to_list())):
  q=dr.filter(pl.col("date").dt.year()==y)["r"].to_numpy();s=np.std(q,ddof=1)
  by[str(y)]={"total_return":float(np.prod(1+q)-1),"sharpe":float(np.mean(q)/s*math.sqrt(365)) if len(q)>1 and s>0 else 0}
 return {"metrics":{"annualized_sharpe":float(np.mean(a)/sd*math.sqrt(365)) if sd>0 else 0,"total_return":float(eq[-1]-1),
   "max_drawdown":float(dd.min()),"n_days":len(a),"n_hours":len(rr)},"by_year":by}

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--anchor",type=Path,required=True);a=ap.parse_args();root=a.anchor.parents[3]/".data"/"store"/"crypto_futures_ohlcv_1h_BINANCE_UM_PERP";h,d=load(root)
 dev=run(h,d,DEV0,DEV1,COST);b=dev["metrics"];gate=b["annualized_sharpe"]>.7 and b["total_return"]>0 and b["max_drawdown"]>-.30
 out={"schema_version":1,"run_id":"20260928-btc-d1h1-macd-trailing","development":dev,"development_gate_passed":gate,"oos_consumed":False,
      "trial_accounting":{"previous_parameter_trials":63,"new_parameter_trials":1,"cumulative_parameter_trials":64}}
 if not gate:out.update(classification="REJECT",conclusion="Development gate failed; OOS not consumed.");print(json.dumps(out,indent=2,default=str));return
 res={str(m):run(h,d,OOS0,OOS1,COST*m) for m in (1,2,3)};delay=run(h,d,OOS0,OOS1,COST,delay=1);can=res["1"];x=can["metrics"]
 years=all(can["by_year"].get(str(y),{}).get("total_return",-1)>=0 for y in (2024,2025))
 qual=x["annualized_sharpe"]>1 and x["total_return"]>0 and res["2"]["metrics"]["total_return"]>0 and years and x["max_drawdown"]>-.25 and delay["metrics"]["annualized_sharpe"]>.8
 glob=compute_deflated_sharpe(x["annualized_sharpe"],[x["annualized_sharpe"]]+[0.0]*63,n_obs_days=x["n_days"])
 out.update(oos_consumed=True,oos_results=res,delay_one_hour=delay,multiple_testing={"global_64_trial_proxy":glob},success_gate_candidate=qual,classification="EXPLORATORY_PASS" if qual else "REJECT")
 print(json.dumps(out,indent=2,default=str))
if __name__=="__main__":main()
