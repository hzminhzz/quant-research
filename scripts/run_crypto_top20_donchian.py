#!/usr/bin/env python3
from __future__ import annotations
import argparse,glob,json,math
from concurrent.futures import ThreadPoolExecutor
from datetime import date,datetime,timedelta
from pathlib import Path
import numpy as np
import polars as pl
from src.experiment import compute_deflated_sharpe

H=(5,10,20,30,60,90,150,250,360);COST=10.;DEV0=date(2022,1,1);DEV1=date(2024,1,1);OOS0=date(2024,1,1);OOS1=date(2026,1,1)

def model_states(close,dates,h):
 n=len(close);state=np.zeros(n);active=False;trail=np.nan
 for i in range(n):
  if i<h+1:continue
  if (dates[i-1]-dates[i-h-1]).days!=h: active=False;trail=np.nan;continue
  prior=close[i-1];hist=close[i-h-1:i-1];hi=float(np.max(hist));lo=float(np.min(hist));mid=(hi+lo)/2
  if active:
   trail=max(trail,mid) if np.isfinite(trail) else mid
   if prior<trail:active=False;trail=np.nan
  if not active and prior>hi:active=True;trail=mid
  state[i]=1.0 if active else 0.0
 return state

def symbol_daily(root,s,first_ts):
 fs=glob.glob(str(root/f"symbol={s}"/"year=*"/"month=*"/"data.parquet"))
 if not fs:return None
 x=(pl.scan_parquet(fs,hive_partitioning=False).filter(pl.col("timestamp")<pl.datetime(2026,1,2,time_zone="UTC"))
   .select("timestamp","open","close","quote_volume").collect().sort("timestamp"))
 d=(x.with_columns(pl.col("timestamp").dt.date().alias("date")).group_by("date").agg(
   pl.col("open").first().alias("open"),pl.col("close").last().alias("close"),pl.col("quote_volume").sum().alias("qv"),pl.len().alias("hours")).sort("date"))
 d=d.filter(pl.col("hours")==24).drop("hours")
 if d.height<370:return None
 dates=np.array(d["date"].to_list(),dtype=object);c=d["close"].to_numpy();combo=np.mean(np.column_stack([model_states(c,dates,h) for h in H]),axis=1)
 ret=np.full(len(c),np.nan);ret[1:]=c[1:]/c[:-1]-1;vol=np.full(len(c),np.nan);liq=np.full(len(c),np.nan)
 q=d["qv"].to_numpy()
 for i in range(len(c)):
  if i>=91 and (dates[i-1]-dates[i-91]).days==90:
   z=ret[i-90:i]
   if np.all(np.isfinite(z)):vol[i]=np.std(z,ddof=1)*math.sqrt(365)
  if i>=30 and (dates[i-1]-dates[i-30]).days==29:liq[i]=float(np.median(q[i-30:i]))
 lev=np.where(np.isfinite(vol)&(vol>0),np.minimum(2.,.25/vol),0.)
 exp=combo*lev
 next_open=np.r_[d["open"].to_numpy()[1:],np.nan]
 age=np.array([(x-dates[0]).days for x in dates])
 return pl.DataFrame({"date":dates,"symbol":[s]*len(dates),"open":d["open"].to_numpy(),"next_open":next_open,
                      "exposure":exp,"liq":liq,"age":age})

def panel(root):
 mani=json.load(open(root/"dataset_manifest.json"))
 items=[(s,v) for s,v in sorted(mani["symbol_summaries"].items())
        if s.endswith("USDT") and s!="BTCDOMUSDT"
        and v["first_timestamp"]<="2024-12-31T23:59:59+00:00"]
 def load_one(item):
  s,v=item
  return symbol_daily(root,s,v["first_timestamp"])
 with ThreadPoolExecutor(max_workers=8) as ex:
  frames=[z for z in ex.map(load_one,items) if z is not None]
 return pl.concat(frames,how="vertical").filter(pl.col("next_open").is_finite()&pl.col("liq").is_finite()&(pl.col("age")>=365))

def desired_weights(p):
 z=(p.sort("liq",descending=True).head(20))
 return {r["symbol"]:float(r["exposure"])/20.0 for r in z.iter_rows(named=True)}

def run(p,start,end,cost,delay=0):
 sub=p.filter((pl.col("date")>=start-timedelta(days=delay))&(pl.col("date")<end)).sort(["date","symbol"])
 dates=sorted(set(sub["date"].to_list())); raw={}
 for d in dates:raw[d]=desired_weights(sub.filter(pl.col("date")==d))
 rr=[];prev={}
 for d in dates:
  if not(start<=d<end):continue
  src=d-timedelta(days=delay);w=raw.get(src,{})
  part=sub.filter(pl.col("date")==d);rmap={r["symbol"]:float(r["next_open"]/r["open"]-1) for r in part.iter_rows(named=True)}
  gross=sum(ww*rmap.get(s,0.) for s,ww in w.items());turn=sum(abs(w.get(s,0)-prev.get(s,0)) for s in set(w)|set(prev))
  rr.append((d,gross-turn*cost/10000));prev=w
 if not rr:return {"metrics":{"annualized_sharpe":0,"total_return":0,"max_drawdown":0,"n_days":0}}
 a=np.array([r for _,r in rr]);eq=np.cumprod(1+a);pk=np.maximum.accumulate(eq);dd=eq/pk-1;sd=np.std(a,ddof=1)
 by={}
 for y in sorted({d.year for d,_ in rr}):
  q=np.array([r for d,r in rr if d.year==y]);s=np.std(q,ddof=1)
  by[str(y)]={"total_return":float(np.prod(1+q)-1),"sharpe":float(np.mean(q)/s*math.sqrt(365)) if len(q)>1 and s>0 else 0}
 return {"metrics":{"annualized_sharpe":float(np.mean(a)/sd*math.sqrt(365)) if sd>0 else 0,"total_return":float(eq[-1]-1),"max_drawdown":float(dd.min()),"n_days":len(a)},"by_year":by}

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--anchor",type=Path,required=True);ap.add_argument("--output",type=Path);a=ap.parse_args();root=a.anchor.parents[3]/".data"/"store"/"crypto_futures_ohlcv_1h_BINANCE_UM_PERP";p=panel(root)
 dev=run(p,DEV0,DEV1,COST);gate=dev["metrics"]["annualized_sharpe"]>.8 and dev["metrics"]["total_return"]>0 and dev["metrics"]["max_drawdown"]>-.30
 out={"schema_version":1,"run_id":"20260928-top20-donchian-ensemble","panel_rows":p.height,"symbols":p["symbol"].n_unique(),
      "development":dev,"development_gate_passed":gate,"oos_consumed":False,
      "trial_accounting":{"previous_parameter_trials":61,"new_parameter_trials":1,"cumulative_parameter_trials":62}}
 if not gate:
  out.update(classification="REJECT",conclusion="Development gate failed; OOS not consumed.")
  payload=json.dumps(out,indent=2,default=str)
  if a.output:a.output.write_text(payload,encoding="utf-8")
  print(payload);return
 res={str(m):run(p,OOS0,OOS1,COST*m) for m in (1,2,3,5)};delay=run(p,OOS0,OOS1,COST,delay=1);can=res["1"];b=can["metrics"];two=res["2"]["metrics"]
 years=all(can["by_year"].get(str(y),{}).get("total_return",-1)>0 for y in (2024,2025))
 qual=b["annualized_sharpe"]>1 and b["total_return"]>0 and two["total_return"]>0 and years and b["max_drawdown"]>-.25 and delay["metrics"]["annualized_sharpe"]>.8
 glob=compute_deflated_sharpe(b["annualized_sharpe"],[b["annualized_sharpe"]]+[0.0]*61,n_obs_days=b["n_days"])
 out.update(oos_consumed=True,oos_results=res,delay_one_day=delay,multiple_testing={"global_62_trial_proxy":glob},success_gate_candidate=qual,
            classification="EXPLORATORY_PASS" if qual else "REJECT")
 payload=json.dumps(out,indent=2,default=str)
 if a.output:a.output.write_text(payload,encoding="utf-8")
 print(payload)
if __name__=="__main__":main()
