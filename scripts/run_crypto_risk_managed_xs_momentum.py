#!/usr/bin/env python3
from __future__ import annotations
import argparse,glob,json,math
from datetime import date,timedelta
from pathlib import Path
import numpy as np
import polars as pl
from src.experiment import compute_deflated_sharpe
VW=(4,8,12);CAN=8;COST=10.;TARGET=.10
DEV0=date(2022,1,1);DEV1=date(2024,1,1);OOS0=date(2024,1,1);OOS1=date(2026,1,1)

def load_daily(root):
 mani=json.load(open(root/"dataset_manifest.json"));fs=[]
 for s,v in mani["symbol_summaries"].items():
  if not s.endswith("USDT") or s=="BTCDOMUSDT" or v["first_timestamp"]>"2025-11-01T00:00:00+00:00":continue
  paths=glob.glob(str(root/f"symbol={s}"/"year=*"/"month=*"/"data.parquet"))
  if not paths:continue
  x=(pl.scan_parquet(paths,hive_partitioning=False).filter(pl.col("timestamp")<pl.datetime(2026,1,6,time_zone="UTC"))
      .select("timestamp","open","close","quote_volume").collect().sort("timestamp"))
  if x.height==0:continue
  d=(x.with_columns(pl.col("timestamp").dt.date().alias("date")).group_by("date").agg(
     pl.col("open").first().alias("open"),pl.col("close").last().alias("close"),pl.col("quote_volume").sum().alias("qv"),pl.len().alias("hours"))
     .sort("date").filter(pl.col("hours")==24).drop("hours").with_columns(pl.lit(s).alias("symbol")))
  if d.height>=40:fs.append(d)
 return pl.concat(fs,how="vertical").sort(["symbol","date"])

def weekly_rows(daily):
 x=(daily.with_columns(
      pl.col("close").shift(1).over("symbol").alias("_c1"),
      pl.col("close").shift(30).over("symbol").alias("_c30"),
      pl.col("qv").shift(1).rolling_sum(30).over("symbol").alias("_liq"),
      pl.col("date").shift(30).over("symbol").alias("_anchor"))
    .with_columns((pl.col("_c1")/pl.col("_c30")-1).alias("mom")))
 return (x.filter((pl.col("date").dt.weekday()==1)&pl.col("mom").is_finite()&pl.col("_liq").is_finite()
                  &(pl.col("_anchor")==pl.col("date")-pl.duration(days=30)))
         .sort(["date","symbol"]))

def week_ret_map(daily):
 by={}
 for p in daily.partition_by("symbol",maintain_order=True):
  s=p["symbol"][0];rows=p.select("date","open","close").to_dicts();idx={r["date"]:i for i,r in enumerate(rows)}
  for d,i in idx.items():
   if d.weekday()!=0:continue
   e=d+timedelta(days=7);entry=rows[i]["open"];exitp=None
   if e in idx:exitp=rows[idx[e]]["open"]
   else:
    cand=[r for r in rows[i:] if r["date"]<e]
    if cand:exitp=cand[-1]["close"]
   if entry and exitp:by[(d,s)]=float(exitp/entry-1)
 return by

def raw_targets(frame,start,end):
 out={}
 for p in frame.filter((pl.col("date")>=start)&(pl.col("date")<end)).partition_by("date",maintain_order=True):
  # top 30 contemporaneous lagged-liquidity names
  rows=sorted([(r["symbol"],float(r["mom"]),float(r["_liq"])) for r in p.iter_rows(named=True)],key=lambda x:x[2],reverse=True)[:30]
  if len(rows)<10:continue
  rows=sorted(rows,key=lambda x:x[1]);k=max(2,len(rows)//5);w={}
  for s,_,_ in rows[:k]:w[s]=-.5/k
  for s,_,_ in rows[-k:]:w[s]=.5/k
  out[p["date"][0]]=w
 return out

def raw_returns(targets,wr):
 out={}
 for d,w in targets.items():out[d]=sum(ww*wr.get((d,s),0.) for s,ww in w.items())
 return out

def scaled_targets(targets,raw,window):
 dates=sorted(targets);out={}
 for i,d in enumerate(dates):
  hist=[raw[dates[j]] for j in range(max(0,i-window),i) if dates[j] in raw]
  if len(hist)<window:continue
  rv=math.sqrt(float(np.mean(np.square(hist))))
  if not np.isfinite(rv) or rv<=0:continue
  scale=TARGET/rv
  out[d]={s:ww*scale for s,ww in targets[d].items()}
 return out

def sim(tg,wr,start,end,cost):
 prev={};rr=[];turns=[];lev=[]
 for d in sorted(x for x in tg if start<=x<end):
  w=tg[d];turn=sum(abs(w.get(s,0)-prev.get(s,0)) for s in set(w)|set(prev));gross=sum(ww*wr.get((d,s),0.) for s,ww in w.items())
  rr.append((d,gross-turn*cost/10000));turns.append(turn);lev.append(sum(abs(v) for v in w.values()));prev=w
 if not rr:return {"metrics":{"annualized_sharpe":0,"total_return":0,"max_drawdown":0,"n_weeks":0}}
 a=np.array([r for _,r in rr]);eq=np.cumprod(1+a);pk=np.maximum.accumulate(eq);dd=eq/pk-1;sd=np.std(a,ddof=1)
 by={}
 for y in sorted({d.year for d,_ in rr}):
  q=np.array([r for d,r in rr if d.year==y]);s=np.std(q,ddof=1)
  by[str(y)]={"total_return":float(np.prod(1+q)-1),"sharpe":float(np.mean(q)/s*math.sqrt(52)) if len(q)>1 and s>0 else 0}
 return {"metrics":{"annualized_sharpe":float(np.mean(a)/sd*math.sqrt(52)) if sd>0 else 0,"total_return":float(eq[-1]-1),
     "max_drawdown":float(dd.min()),"n_weeks":len(a),"mean_gross_leverage":float(np.mean(lev)),"turnover":float(sum(turns))},"by_year":by}

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--root",type=Path,required=True);a=ap.parse_args();d=load_daily(a.root);f=weekly_rows(d);wr=week_ret_map(d)
 # build enough pre-dev history so scaling at DEV0 is causal
 base_all=raw_targets(f,date(2021,9,1),DEV1);raw_all=raw_returns(base_all,wr)
 dev={}
 for v in VW:
  tg=scaled_targets(base_all,raw_all,v);dev[v]=sim(tg,wr,DEV0,DEV1,COST)
 ds={v:dev[v]["metrics"]["annualized_sharpe"] for v in VW};dr={v:dev[v]["metrics"]["total_return"] for v in VW}
 gate=ds[CAN]>.8 and dr[CAN]>0 and sum(x>0 for x in dr.values())>=2
 out={"schema_version":1,"run_id":"20260928-risk-managed-cross-sectional-momentum","daily_rows":d.height,"symbols":d["symbol"].n_unique(),
      "development":{str(v):dev[v] for v in VW},"development_gate_passed":gate,"oos_consumed":False,
      "trial_accounting":{"previous_parameter_trials":65,"new_parameter_trials":3,"cumulative_parameter_trials":68}}
 if not gate:out.update(classification="REJECT",conclusion="Development gate failed; OOS not consumed.");print(json.dumps(out,indent=2,default=str));return
 # OOS scaling history starts before OOS but targets are fixed; no OOS future enters scale.
 allbase=raw_targets(f,date(2023,9,1),OOS1);allraw=raw_returns(allbase,wr);res={};sharp=[]
 for v in VW:
  tg=scaled_targets(allbase,allraw,v);res[str(v)]={}
  for m in (1,2,3):res[str(v)][str(m)]=sim(tg,wr,OOS0,OOS1,COST*m)
  sharp.append(res[str(v)]["1"]["metrics"]["annualized_sharpe"])
 can=res[str(CAN)]["1"];b=can["metrics"];two=res[str(CAN)]["2"]["metrics"];years=all(can["by_year"].get(str(y),{}).get("total_return",-1)>=0 for y in (2024,2025))
 qual=b["annualized_sharpe"]>1 and b["total_return"]>0 and two["total_return"]>0 and sum(res[str(v)]["1"]["metrics"]["total_return"]>0 for v in VW)>=2 and years and b["max_drawdown"]>-.35
 dsr=compute_deflated_sharpe(b["annualized_sharpe"],sharp,n_obs_days=max(b["n_weeks"]*7,1))
 out.update(oos_consumed=True,oos_results=res,multiple_testing={"family_dsr":dsr},success_gate_candidate=qual,classification="EXPLORATORY_PASS" if qual else "REJECT")
 print(json.dumps(out,indent=2,default=str))
if __name__=="__main__":main()
