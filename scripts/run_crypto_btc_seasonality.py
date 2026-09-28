#!/usr/bin/env python3
from __future__ import annotations
import argparse,glob,json,math
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import polars as pl
from src.experiment import compute_deflated_sharpe
DEV0=datetime(2021,1,1,tzinfo=timezone.utc);DEV1=datetime(2024,1,1,tzinfo=timezone.utc);OOS0=datetime(2024,1,1,tzinfo=timezone.utc);OOS1=datetime(2026,1,1,tzinfo=timezone.utc)

def load(root):
 fs=glob.glob(str(root/"symbol=BTCUSDT"/"year=*"/"month=*"/"data.parquet"))
 return (pl.scan_parquet(fs,hive_partitioning=False).filter(pl.col("timestamp")<pl.datetime(2026,9,1,time_zone="UTC"))
  .select("timestamp","open").collect().sort("timestamp"))

def run(h,start,end,cost):
 x=h.filter((pl.col("timestamp")>=start)&(pl.col("timestamp")<end)&pl.col("timestamp").dt.hour().is_in([21,23]))
 rows=x.to_dicts(); by={}
 for r in rows:by[(r["timestamp"].date(),r["timestamp"].hour)]=r
 rr=[]
 for d in sorted({k[0] for k in by}):
  if (d,21) not in by or (d,23) not in by:continue
  r=float(by[(d,23)]["open"]/by[(d,21)]["open"]-1)-2*cost/10000
  rr.append((d,r))
 if not rr:return {"metrics":{"annualized_sharpe":0,"total_return":0,"max_drawdown":0,"n_days":0}}
 a=np.array([r for _,r in rr]);eq=np.cumprod(1+a);pk=np.maximum.accumulate(eq);dd=eq/pk-1;sd=np.std(a,ddof=1)
 byy={}
 for y in sorted({d.year for d,_ in rr}):
  q=np.array([r for d,r in rr if d.year==y]);s=np.std(q,ddof=1)
  byy[str(y)]={"total_return":float(np.prod(1+q)-1),"sharpe":float(np.mean(q)/s*math.sqrt(365)) if len(q)>1 and s>0 else 0}
 return {"metrics":{"annualized_sharpe":float(np.mean(a)/sd*math.sqrt(365)) if sd>0 else 0,"total_return":float(eq[-1]-1),"max_drawdown":float(dd.min()),"n_days":len(a)},"by_year":byy}

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--root",type=Path,required=True);a=ap.parse_args();h=load(a.root)
 dev=run(h,DEV0,DEV1,3.);gate=dev["metrics"]["annualized_sharpe"]>.5 and dev["metrics"]["total_return"]>0
 out={"schema_version":1,"run_id":"20260928-btc-21-23-seasonality","development":dev,"development_gate_passed":gate,"oos_consumed":False,
      "trial_accounting":{"previous_parameter_trials":64,"new_parameter_trials":1,"cumulative_parameter_trials":65}}
 if not gate:out.update(classification="REJECT",conclusion="Development gate failed; OOS not consumed.");print(json.dumps(out,indent=2,default=str));return
 res={str(c):run(h,OOS0,OOS1,c) for c in (3.,6.,10.)};can=res["3.0"];m=can["metrics"];years=all(can["by_year"].get(str(y),{}).get("total_return",-1)>=0 for y in (2024,2025))
 qual=m["annualized_sharpe"]>1 and m["total_return"]>0 and res["6.0"]["metrics"]["total_return"]>0 and years and m["max_drawdown"]>-.25
 glob=compute_deflated_sharpe(m["annualized_sharpe"],[m["annualized_sharpe"]]+[0.0]*64,n_obs_days=m["n_days"])
 out.update(oos_consumed=True,oos_results=res,multiple_testing={"global_65_trial_proxy":glob},success_gate_candidate=qual,classification="EXPLORATORY_PASS" if qual else "REJECT")
 print(json.dumps(out,indent=2,default=str))
if __name__=="__main__":main()
