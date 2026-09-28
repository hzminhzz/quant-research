#!/usr/bin/env python3
from __future__ import annotations
import argparse,glob,json,math
from datetime import date,timedelta
from pathlib import Path
import numpy as np
import polars as pl
from src.experiment import compute_deflated_sharpe

WINDOWS=(72,168,336); CAN=168; LIQ=720; COST=10.0
DEV0=date(2022,1,1); DEV1=date(2024,1,1); OOS0=date(2024,1,1); OOS1=date(2026,1,1)

def symbols(root):
 d=json.load(open(root/"dataset_manifest.json"))
 return sorted(k for k,v in d["symbol_summaries"].items() if k.endswith("USDT") and k!="BTCDOMUSDT" and v["first_timestamp"]<="2021-12-31T23:59:59+00:00")

def load_hourly(root,syms):
 fs=[]
 for s in syms:
  paths=glob.glob(str(root/f"symbol={s}"/"year=*"/"month=*"/"data.parquet"))
  if paths:
   x=(pl.scan_parquet(paths,hive_partitioning=False).filter(pl.col("timestamp")<pl.datetime(2026,1,6,time_zone="UTC"))
      .select("timestamp","open","close","quote_volume","taker_buy_quote_volume").collect().sort("timestamp")
      .with_columns(pl.lit(s).alias("symbol")))
   fs.append(x)
 return pl.concat(fs,how="vertical").sort(["symbol","timestamp"])

def features(h,w):
 x=(h.with_columns(
   pl.col("quote_volume").shift(1).rolling_sum(w).over("symbol").alias("_q"),
   pl.col("taker_buy_quote_volume").shift(1).rolling_sum(w).over("symbol").alias("_b"),
   pl.col("quote_volume").shift(1).rolling_sum(LIQ).over("symbol").alias("_liq"),
   pl.col("timestamp").shift(max(w,LIQ)).over("symbol").alias("_anchor"))
   .with_columns((2*pl.col("_b")/pl.col("_q")-1).alias("signal")))
 z=(x.filter((pl.col("timestamp").dt.weekday()==1)&(pl.col("timestamp").dt.hour()==0)
             &pl.col("signal").is_finite()&pl.col("_liq").is_finite()
             &(pl.col("_anchor")==pl.col("timestamp")-pl.duration(hours=max(w,LIQ))))
    .with_columns(pl.len().over("timestamp").alias("_n"))
    .filter(pl.col("_n")>=12)
    .with_columns((pl.col("_liq").rank(method="average").over("timestamp")/pl.col("_n")).alias("_liq_pct"))
    .filter(pl.col("_liq_pct")>0.20))
 return z.sort(["timestamp","symbol"])

def target(z,start,end):
 out={}
 for p in z.filter((pl.col("timestamp").dt.date()>=start)&(pl.col("timestamp").dt.date()<end)).partition_by("timestamp",maintain_order=True):
  rows=sorted([(r["symbol"],float(r["signal"])) for r in p.iter_rows(named=True)],key=lambda q:q[1]); n=len(rows)
  if n<8: continue
  k=max(2,n//4); w={}
  for s,_ in rows[:k]:w[str(s)]=-0.5/k
  for s,_ in rows[-k:]:w[str(s)]=0.5/k
  out[p["timestamp"][0].date()]=w
 return out

def return_map(h):
 by={}
 for p in h.partition_by("symbol",maintain_order=True):
  s=p["symbol"][0]; rows=p.select("timestamp","open","close").to_dicts()
  mond={r["timestamp"].date():i for i,r in enumerate(rows) if r["timestamp"].weekday()==0 and r["timestamp"].hour==0}
  for d,i in mond.items():
   end=d+timedelta(days=7); entry=rows[i]["open"]; exitp=None
   if end in mond: exitp=rows[mond[end]]["open"]
   else:
    e=rows[i]["timestamp"]+timedelta(days=7); cand=[r for r in rows[i:] if r["timestamp"]<e]
    if cand: exitp=cand[-1]["close"]
   if entry and exitp and entry>0:by[(d,s)]=float(exitp/entry-1)
 return by

def sim(tg,rm,start,end,cost):
 dates=sorted(d for d in tg if start<=d<end); prev={}; rr=[]; cont={}
 for d in dates:
  w=tg[d]; turn=sum(abs(w.get(s,0)-prev.get(s,0)) for s in set(w)|set(prev)); gross=0
  for s,ww in w.items():
   r=rm.get((d,s))
   if r is not None:gross+=ww*r;cont[s]=cont.get(s,0)+ww*r
  rr.append((d,gross-turn*cost/10000));prev=w
 if not rr:return {"metrics":{"annualized_sharpe":0,"total_return":0,"max_drawdown":0,"n_weeks":0}}
 a=np.array([r for _,r in rr]);eq=np.cumprod(1+a);pk=np.maximum.accumulate(eq);dd=eq/pk-1;sd=np.std(a,ddof=1)
 by={}
 for y in sorted({d.year for d,_ in rr}):
  q=np.array([r for d,r in rr if d.year==y]); qs=np.std(q,ddof=1)
  by[str(y)]={"total_return":float(np.prod(1+q)-1),"sharpe":float(np.mean(q)/qs*math.sqrt(52)) if len(q)>1 and qs>0 else 0}
 return {"metrics":{"annualized_sharpe":float(np.mean(a)/sd*math.sqrt(52)) if sd>0 else 0,"total_return":float(eq[-1]-1),"max_drawdown":float(dd.min()),"n_weeks":len(a)},
         "by_year":by,"asset_contribution":cont}

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--root",type=Path,required=True);a=ap.parse_args()
 sy=symbols(a.root);h=load_hourly(a.root,sy);rm=return_map(h);fr={w:features(h,w) for w in WINDOWS}
 dev={w:sim(target(fr[w],DEV0,DEV1),rm,DEV0,DEV1,COST) for w in WINDOWS}; ds={w:dev[w]["metrics"]["annualized_sharpe"] for w in WINDOWS};dr={w:dev[w]["metrics"]["total_return"] for w in WINDOWS}
 gate=ds[CAN]>.70 and dr[CAN]>0 and sum(v>0 for v in dr.values())>=2
 out={"schema_version":1,"run_id":"20260928-aggressor-flow-weekly","universe_symbols":len(sy),"development":{str(w):dev[w] for w in WINDOWS},
      "development_gate_passed":gate,"oos_consumed":False,"trial_accounting":{"previous_parameter_trials":51,"new_parameter_trials":3,"cumulative_parameter_trials":54}}
 if not gate:out.update(classification="REJECT",conclusion="Development gate failed; OOS not consumed.");print(json.dumps(out,indent=2,default=str));return
 res={};sharp=[]
 for w in WINDOWS:
  res[str(w)]={}
  tg=target(fr[w],OOS0,OOS1)
  for m in (1,2,3):res[str(w)][str(m)]=sim(tg,rm,OOS0,OOS1,COST*m)
  sharp.append(res[str(w)]["1"]["metrics"]["annualized_sharpe"])
 can=res[str(CAN)]["1"];dsr=compute_deflated_sharpe(can["metrics"]["annualized_sharpe"],sharp,n_obs_days=max(can["metrics"]["n_weeks"]*7,1))
 b=can["metrics"];two=res[str(CAN)]["2"]["metrics"]; years=all(can["by_year"].get(str(y),{}).get("total_return",-1)>=0 for y in (2024,2025))
 qual=b["annualized_sharpe"]>1 and b["total_return"]>0 and two["total_return"]>0 and sum(res[str(w)]["1"]["metrics"]["total_return"]>0 for w in WINDOWS)>=2 and years
 out.update(oos_consumed=True,oos_results=res,multiple_testing={"family_dsr":dsr},success_gate_candidate=qual,classification="EXPLORATORY_PASS" if qual else "REJECT")
 print(json.dumps(out,indent=2,default=str))
if __name__=="__main__":main()
