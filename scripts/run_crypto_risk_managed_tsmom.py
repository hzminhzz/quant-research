#!/usr/bin/env python3
from __future__ import annotations
import argparse,glob,json,math
from datetime import date,timedelta
from pathlib import Path
import numpy as np
import polars as pl
from src.experiment import compute_deflated_sharpe

SYMS=["BTCUSDT","ETHUSDT","BNBUSDT","XRPUSDT","ADAUSDT","SOLUSDT","DOGEUSDT"]
COST=12.5; DEV0=date(2021,1,1);DEV1=date(2024,1,1);OOS0=date(2024,1,1);OOS1=date(2026,1,1)

def daily(root,s):
 fs=glob.glob(str(root/f"symbol={s}"/"year=*"/"month=*"/"data.parquet"))
 x=(pl.scan_parquet(fs,hive_partitioning=False).filter(pl.col("timestamp")<pl.datetime(2026,9,1,time_zone="UTC"))
    .select("timestamp","open","close").collect().sort("timestamp"))
 return (x.with_columns(pl.col("timestamp").dt.date().alias("date")).group_by("date").agg(
   pl.col("open").first().alias("open"),pl.col("close").last().alias("close"),pl.len().alias("hours")).sort("date")
   .filter(pl.col("hours")==24).drop("hours").with_columns(pl.lit(s).alias("symbol")))

def build(root):
 frames=[daily(root,s) for s in SYMS]
 panel=pl.concat(frames,how="vertical").sort(["symbol","date"])
 # Daily equal-weight market return from point-in-time available majors.
 m=(panel.with_columns((pl.col("close")/pl.col("close").shift(1).over("symbol")-1).alias("_ret"))
    .filter(pl.col("_ret").is_finite()).group_by("date").agg(pl.col("_ret").mean().alias("mret")).sort("date"))
 mr=m["mret"].to_numpy(); idx=np.cumprod(1+mr); peak=np.maximum.accumulate(idx)
 market={d:{"idx":float(i),"peak":float(p)} for d,i,p in zip(m["date"].to_list(),idx,peak)}
 target={}
 for s in SYMS:
  p=panel.filter(pl.col("symbol")==s).sort("date"); rows=p.to_dicts()
  for i in range(31,len(rows)):
   d=rows[i]["date"]
   if (rows[i-1]["date"]-rows[i-31]["date"]).days!=30:continue
   lr=math.log(rows[i-1]["close"]/rows[i-31]["close"])
   md=market.get(rows[i-1]["date"])
   scale=.5 if md and md["idx"]/md["peak"]-1 < -.15 else 1.
   target[(d,s)]=(1/7)*scale if lr>0 else 0.
 return panel,target

def run(panel,target,start,end,cost,delay=0):
 bysym={s:panel.filter(pl.col("symbol")==s).sort("date").to_dicts() for s in SYMS}
 dates=sorted({r["date"] for s in SYMS for r in bysym[s] if start<=r["date"]<end})
 prev={s:0. for s in SYMS}; rr=[]; exposures=[]
 for d in dates:
  gross=0.; turn=0.; expo=0.
  for s in SYMS:
   rows=bysym[s]; idx=next((i for i,r in enumerate(rows) if r["date"]==d),None)
   if idx is None or idx+1>=len(rows):continue
   src=d-timedelta(days=delay); w=float(target.get((src,s),0.))
   r=float(rows[idx+1]["open"]/rows[idx]["open"]-1)
   gross+=w*r;turn+=abs(w-prev[s]);expo+=abs(w);prev[s]=w
  rr.append((d,gross-turn*cost/10000));exposures.append(expo)
 if not rr:return {"metrics":{"annualized_sharpe":0,"total_return":0,"max_drawdown":0,"n_days":0}}
 a=np.array([x[1] for x in rr]);eq=np.cumprod(1+a);pk=np.maximum.accumulate(eq);dd=eq/pk-1;sd=np.std(a,ddof=1)
 by={}
 for y in sorted({d.year for d,_ in rr}):
  q=np.array([r for d,r in rr if d.year==y]);s=np.std(q,ddof=1)
  by[str(y)]={"total_return":float(np.prod(1+q)-1),"sharpe":float(np.mean(q)/s*math.sqrt(365)) if len(q)>1 and s>0 else 0}
 return {"metrics":{"annualized_sharpe":float(np.mean(a)/sd*math.sqrt(365)) if sd>0 else 0,"total_return":float(eq[-1]-1),
      "max_drawdown":float(dd.min()),"n_days":len(a),"mean_gross_exposure":float(np.mean(exposures))},"by_year":by}

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--root",type=Path,required=True);a=ap.parse_args();p,t=build(a.root)
 dev=run(p,t,DEV0,DEV1,COST);b=dev["metrics"];gate=b["annualized_sharpe"]>.8 and b["total_return"]>0 and b["max_drawdown"]>-.5
 out={"schema_version":1,"run_id":"20260928-risk-managed-tsmom-majors","development":dev,"development_gate_passed":gate,"oos_consumed":False,
      "trial_accounting":{"previous_parameter_trials":62,"new_parameter_trials":1,"cumulative_parameter_trials":63}}
 if not gate:out.update(classification="REJECT",conclusion="Development gate failed; OOS not consumed.");print(json.dumps(out,indent=2,default=str));return
 res={str(c):run(p,t,OOS0,OOS1,c) for c in (12.5,25.,50.)};delay=run(p,t,OOS0,OOS1,COST,delay=1);can=res["12.5"];m=can["metrics"]
 years=all(can["by_year"].get(str(y),{}).get("total_return",-1)>=0 for y in (2024,2025))
 qual=m["annualized_sharpe"]>1 and m["total_return"]>0 and res["25.0"]["metrics"]["total_return"]>0 and years and m["max_drawdown"]>-.35 and delay["metrics"]["annualized_sharpe"]>.8
 glob=compute_deflated_sharpe(m["annualized_sharpe"],[m["annualized_sharpe"]]+[0.0]*62,n_obs_days=m["n_days"])
 out.update(oos_consumed=True,oos_results=res,delay_one_day=delay,multiple_testing={"global_63_trial_proxy":glob},success_gate_candidate=qual,
            classification="EXPLORATORY_PASS" if qual else "REJECT")
 print(json.dumps(out,indent=2,default=str))
if __name__=="__main__":main()
