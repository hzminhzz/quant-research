#!/usr/bin/env python3
from __future__ import annotations
import argparse,glob,json,math,re
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
import numpy as np
import polars as pl
from src.experiment import compute_deflated_sharpe

WINS=(3,7,14); CAN=7; COST=10.; DEV0=date(2022,1,1);DEV1=date(2024,1,1);OOS0=date(2024,1,1);OOS1=date(2026,1,1)

def funding_symbols(store):
 out=[]
 for p in store.glob("crypto_futures_funding_*_PERP"):
  m=re.match(r"crypto_futures_funding_(.+)_PERP",p.name)
  if m:out.append(m.group(1))
 return sorted(out)

def load_price(root,symbol):
 fs=glob.glob(str(root/f"symbol={symbol}"/"year=*"/"month=*"/"data.parquet"))
 if not fs:return None
 return (pl.scan_parquet(fs,hive_partitioning=False).filter(pl.col("timestamp")<pl.datetime(2026,1,6,time_zone="UTC"))
   .select("timestamp","open","close","quote_volume").collect().sort("timestamp"))

def load_funding(store,symbol):
 fs=glob.glob(str(store/f"crypto_futures_funding_{symbol}_PERP"/"year=*"/"month=*"/"data.parquet"))
 if not fs:return None
 return (pl.scan_parquet(fs,hive_partitioning=False).filter(pl.col("timestamp")<pl.datetime(2026,1,6,time_zone="UTC"))
   .select("timestamp","funding_rate").collect().sort("timestamp"))

def build_maps(price_root,fund_store):
 sy=[];weeks={}; fundhist={}
 for s in funding_symbols(fund_store):
  px=load_price(price_root,s);fd=load_funding(fund_store,s)
  if px is None or fd is None or px.height<1000 or fd.height<100:continue
  sy.append(s)
  # Monday entry prices and trailing liquidity.
  q=(px.with_columns(pl.col("quote_volume").shift(1).rolling_sum(720).alias("_liq"))
     .filter((pl.col("timestamp").dt.weekday()==1)&(pl.col("timestamp").dt.hour()==0)&pl.col("_liq").is_finite()))
  qrows=q.select("timestamp","open","_liq").to_dicts(); qmap={r["timestamp"].date():r for r in qrows}
  fts=fd["timestamp"].to_numpy().astype("datetime64[us]")
  fr=fd["funding_rate"].to_numpy().astype(float)
  fcum=np.concatenate([[0.0],np.cumsum(fr)])
  for d,r in qmap.items():
   end=d+timedelta(days=7)
   if end not in qmap:continue
   t0=np.datetime64(datetime.combine(d,datetime.min.time(),tzinfo=timezone.utc).replace(tzinfo=None),"us")
   t1=np.datetime64(datetime.combine(end,datetime.min.time(),tzinfo=timezone.utc).replace(tzinfo=None),"us")
   i0=int(np.searchsorted(fts,t0,side="right")); i1=int(np.searchsorted(fts,t1,side="right"))
   if i1<=i0:continue
   weeks[(d,s)]={"price_ret":float(qmap[end]["open"]/r["open"]-1),"funding_sum":float(fcum[i1]-fcum[i0]),"liq":float(r["_liq"])}
  fundhist[s]=(fts,fr,fcum)
 return sy,weeks,fundhist

def targets(sy,weeks,fh,look,start,end):
 out={}
 d=start
 while d.weekday()!=0:d+=timedelta(days=1)
 while d<end:
  t=datetime.combine(d,datetime.min.time(),tzinfo=timezone.utc);lo=t-timedelta(days=look)
  rows=[]
  for s in sy:
   if (d,s) not in weeks:continue
   fts,fr,fcum=fh[s]
   lo64=np.datetime64(lo.replace(tzinfo=None),"us"); t64=np.datetime64(t.replace(tzinfo=None),"us")
   i0=int(np.searchsorted(fts,lo64,side="left")); i1=int(np.searchsorted(fts,t64,side="left"))
   n=i1-i0
   if n<max(3,look*2):continue
   rows.append((s,float((fcum[i1]-fcum[i0])/n),weeks[(d,s)]["liq"]))
  if len(rows)>=8:
   liqs=np.array([r[2] for r in rows]);cut=np.quantile(liqs,.20);rows=[r for r in rows if r[2]>=cut]
   rows=sorted(rows,key=lambda x:x[1]);n=len(rows);k=max(2,n//4)
   w={s:-.5/k for s,_,_ in rows[-k:]}
   for s,_,_ in rows[:k]:w[s]=.5/k
   out[d]=w
  d+=timedelta(days=7)
 return out

def sim(tg,weeks,start,end,cost):
 prev={};rr=[];fundcomp=[];pricecomp=[]
 for d in sorted(x for x in tg if start<=x<end):
  w=tg[d];turn=sum(abs(w.get(s,0)-prev.get(s,0)) for s in set(w)|set(prev));pr=0;fu=0
  for s,ww in w.items():
   z=weeks.get((d,s))
   if not z:continue
   pr+=ww*z["price_ret"];fu+=-ww*z["funding_sum"]
  net=pr+fu-turn*cost/10000;rr.append((d,net));fundcomp.append(fu);pricecomp.append(pr);prev=w
 if not rr:return {"metrics":{"annualized_sharpe":0,"total_return":0,"max_drawdown":0,"n_weeks":0}}
 a=np.array([x[1] for x in rr]);eq=np.cumprod(1+a);pk=np.maximum.accumulate(eq);dd=eq/pk-1;sd=np.std(a,ddof=1)
 by={}
 for y in sorted({d.year for d,_ in rr}):
  q=np.array([r for d,r in rr if d.year==y]);qs=np.std(q,ddof=1)
  by[str(y)]={"total_return":float(np.prod(1+q)-1),"sharpe":float(np.mean(q)/qs*math.sqrt(52)) if len(q)>1 and qs>0 else 0}
 return {"metrics":{"annualized_sharpe":float(np.mean(a)/sd*math.sqrt(52)) if sd>0 else 0,"total_return":float(eq[-1]-1),"max_drawdown":float(dd.min()),"n_weeks":len(a),
                    "funding_component_sum":float(sum(fundcomp)),"price_component_sum":float(sum(pricecomp))},"by_year":by}

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--anchor",type=Path,required=True);a=ap.parse_args()
 store=a.anchor.parents[3]/".data"/"store"
 price_root=store/"crypto_futures_ohlcv_1h_BINANCE_UM_PERP"
 sy,weeks,fh=build_maps(price_root,store)
 dev={w:sim(targets(sy,weeks,fh,w,DEV0,DEV1),weeks,DEV0,DEV1,COST) for w in WINS};ds={w:dev[w]["metrics"]["annualized_sharpe"] for w in WINS};dr={w:dev[w]["metrics"]["total_return"] for w in WINS}
 gate=ds[CAN]>.70 and dr[CAN]>0 and sum(v>0 for v in dr.values())>=2
 out={"schema_version":1,"run_id":"20260928-realized-funding-carry-weekly","symbols":sy,"n_symbols":len(sy),"development":{str(w):dev[w] for w in WINS},
      "development_gate_passed":gate,"oos_consumed":False,"trial_accounting":{"previous_parameter_trials":54,"new_parameter_trials":3,"cumulative_parameter_trials":57}}
 if not gate:out.update(classification="REJECT",conclusion="Development gate failed; OOS not consumed.");print(json.dumps(out,indent=2,default=str));return
 res={};sharp=[]
 for w in WINS:
  res[str(w)]={}
  tg=targets(sy,weeks,fh,w,OOS0,OOS1)
  for m in (1,2,3):res[str(w)][str(m)]=sim(tg,weeks,OOS0,OOS1,COST*m)
  sharp.append(res[str(w)]["1"]["metrics"]["annualized_sharpe"])
 can=res[str(CAN)]["1"];dsr=compute_deflated_sharpe(can["metrics"]["annualized_sharpe"],sharp,n_obs_days=max(can["metrics"]["n_weeks"]*7,1));b=can["metrics"];two=res[str(CAN)]["2"]["metrics"]
 years=all(can["by_year"].get(str(y),{}).get("total_return",-1)>=0 for y in (2024,2025))
 qual=b["annualized_sharpe"]>1 and b["total_return"]>0 and two["total_return"]>0 and b["funding_component_sum"]>0 and sum(res[str(w)]["1"]["metrics"]["total_return"]>0 for w in WINS)>=2 and years
 out.update(oos_consumed=True,oos_results=res,multiple_testing={"family_dsr":dsr},success_gate_candidate=qual,classification="EXPLORATORY_PASS" if qual else "REJECT")
 print(json.dumps(out,indent=2,default=str))
if __name__=="__main__":main()
