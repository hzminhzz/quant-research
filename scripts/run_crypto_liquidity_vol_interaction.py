#!/usr/bin/env python3
from __future__ import annotations
import argparse,glob,json,math
from datetime import date,datetime,timedelta
from pathlib import Path
import numpy as np
import polars as pl
from src.experiment import compute_deflated_sharpe

VOLS=(14,30,60); CAN=30; LIQ=30; COST=10.0
DEV0=date(2022,1,1); DEV1=date(2024,1,1); OOS0=date(2024,1,1); OOS1=date(2026,1,1)

def symbols_from_manifest(root:Path):
    d=json.load(open(root/"dataset_manifest.json"))
    return sorted(k for k,v in d["symbol_summaries"].items()
                  if k.endswith("USDT") and v["first_timestamp"]<="2021-12-31T23:59:59+00:00"
                  and k!="BTCDOMUSDT")

def load_daily(root:Path,symbols):
    frames=[]
    for s in symbols:
        fs=glob.glob(str(root/f"symbol={s}"/"year=*"/"month=*"/"data.parquet"))
        if not fs: continue
        x=(pl.scan_parquet(fs,hive_partitioning=False)
           .filter(pl.col("timestamp")<pl.datetime(2026,1,6,time_zone="UTC"))
           .select("timestamp","open","high","low","close","quote_volume")
           .collect().sort("timestamp"))
        if x.height==0: continue
        d=(x.with_columns(pl.col("timestamp").dt.date().alias("date"))
           .group_by("date").agg(pl.col("open").first().alias("open"),pl.col("close").last().alias("close"),
             pl.col("high").max().alias("high"),pl.col("low").min().alias("low"),
             pl.col("quote_volume").sum().alias("quote_volume"),pl.len().alias("hours"))
           .sort("date").with_columns(pl.lit(s).alias("symbol")))
        # Partial listing/delisting boundary days are kept only for liquidation marks, never for feature estimation.
        frames.append(d)
    return pl.concat(frames,how="vertical").sort(["symbol","date"])

def feature_frame(daily,volw):
    x=(daily.with_columns(
       (pl.col("close")/pl.col("close").shift(1).over("symbol")-1).alias("_ret"),
       (pl.col("hours")==24).alias("_complete"))
       .with_columns(
       pl.when(pl.col("_complete")).then(pl.col("quote_volume")).otherwise(None).shift(1).rolling_mean(LIQ).over("symbol").alias("_liq"),
       pl.when(pl.col("_complete")).then(pl.col("_ret")).otherwise(None).shift(1).rolling_std(volw).over("symbol").alias("_vol"),
       pl.col("date").shift(max(LIQ,volw)+1).over("symbol").alias("_anchor")))
    mondays=(x.filter((pl.col("date").dt.weekday()==1)&(pl.col("hours")==24)&pl.col("_liq").is_finite()&pl.col("_vol").is_finite())
             .filter(pl.len().over("date")>=12)
             .with_columns(pl.len().over("date").alias("_n_xs"))
             .with_columns(
               (pl.col("_liq").rank(method="average").over("date") / pl.col("_n_xs")).alias("_liq_pct"),
               (pl.col("_vol").rank(method="average").over("date") / pl.col("_n_xs")).alias("_vol_pct")))
    return mondays.sort(["date","symbol"])

def week_return_map(daily):
    by={}
    for p in daily.partition_by("symbol",maintain_order=True):
        s=p["symbol"][0]; rows=p.select("date","open","close").to_dicts(); idx={r["date"]:i for i,r in enumerate(rows)}
        for d,i in idx.items():
            if d.weekday()!=0: continue
            end=d+timedelta(days=7)
            entry=rows[i]["open"]; exitp=None
            if end in idx: exitp=rows[idx[end]]["open"]
            else:
                candidates=[r for r in rows[i:] if r["date"]<end]
                if candidates: exitp=candidates[-1]["close"]
            if entry and exitp and entry>0: by[(d,s)]=float(exitp/entry-1)
    return by

def targets(frame,start,end):
    out={}
    for p in frame.filter((pl.col("date")>=start)&(pl.col("date")<end)).partition_by("date",maintain_order=True):
        rows=p.to_dicts()
        longs=[r["symbol"] for r in rows if r["_liq_pct"]<=1/3 and r["_vol_pct"]>=2/3]
        shorts=[r["symbol"] for r in rows if r["_liq_pct"]>=2/3 and r["_vol_pct"]<=1/3]
        if len(longs)<2 or len(shorts)<2: continue
        w={s:0.5/len(longs) for s in longs}
        w.update({s:-0.5/len(shorts) for s in shorts})
        out[p["date"][0]]=w
    return out

def simulate(tg,wr,start,end,costbps):
    dates=sorted(d for d in tg if start<=d<end); prev={}; rets=[]; turnovers=[]; contrib={}
    for d in dates:
        w=tg[d]; turnover=sum(abs(w.get(s,0)-prev.get(s,0)) for s in set(w)|set(prev))
        gross=0
        for s,ww in w.items():
            r=wr.get((d,s))
            if r is None: continue
            pnl=ww*r; gross+=pnl; contrib[s]=contrib.get(s,0)+pnl
        net=gross-turnover*costbps/10000
        rets.append((d,net,gross)); turnovers.append(turnover); prev=w
    if not rets:return {"metrics":{"annualized_sharpe":0,"total_return":0,"max_drawdown":0,"n_weeks":0}}
    a=np.array([r[1] for r in rets]); eq=np.cumprod(1+a); pk=np.maximum.accumulate(eq); dd=eq/pk-1
    sd=np.std(a,ddof=1); sr=np.mean(a)/sd*math.sqrt(52) if sd>0 else 0
    by={}
    for y in sorted({d.year for d,_,_ in rets}):
        z=np.array([r for d,r,_ in rets if d.year==y]); e=np.prod(1+z)-1; s=np.std(z,ddof=1)
        by[str(y)]={"total_return":float(e),"sharpe":float(np.mean(z)/s*math.sqrt(52)) if len(z)>1 and s>0 else 0}
    return {"metrics":{"annualized_sharpe":float(sr),"total_return":float(eq[-1]-1),"max_drawdown":float(dd.min()),"n_weeks":len(a),
                       "mean_weekly_return":float(np.mean(a)),"turnover":float(sum(turnovers))},
            "by_year":by,"asset_contribution":contrib}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--anchor",type=Path,required=True); a=ap.parse_args()
    root=a.anchor.parents[3]/".data"/"store"/"crypto_futures_ohlcv_1h_BINANCE_UM_PERP"
    syms=symbols_from_manifest(root); daily=load_daily(root,syms); wr=week_return_map(daily)
    frames={v:feature_frame(daily,v) for v in VOLS}
    dev={v:simulate(targets(frames[v],DEV0,DEV1),wr,DEV0,DEV1,COST) for v in VOLS}
    ds={v:dev[v]["metrics"]["annualized_sharpe"] for v in VOLS}; dr={v:dev[v]["metrics"]["total_return"] for v in VOLS}
    gate=ds[CAN]>.70 and dr[CAN]>0 and sum(x>0 for x in dr.values())>=2
    out={"schema_version":1,"run_id":"20260928-liquidity-volatility-interaction","universe_symbols":len(syms),
         "daily_rows":daily.height,"development":{str(v):dev[v] for v in VOLS},"development_gate_passed":gate,
         "oos_consumed":False,"trial_accounting":{"previous_parameter_trials":48,"new_parameter_trials":3,"cumulative_parameter_trials":51}}
    if not gate:
        out.update(classification="REJECT",conclusion="Development gate failed; OOS not consumed."); print(json.dumps(out,indent=2,default=str));return
    res={}; sharpes=[]
    for v in VOLS:
        res[str(v)]={}
        tg=targets(frames[v],OOS0,OOS1)
        for m in (1,2,3):res[str(v)][str(m)]=simulate(tg,wr,OOS0,OOS1,COST*m)
        sharpes.append(res[str(v)]["1"]["metrics"]["annualized_sharpe"])
    can=res[str(CAN)]["1"]; fam=compute_deflated_sharpe(can["metrics"]["annualized_sharpe"],sharpes,n_obs_days=max(can["metrics"]["n_weeks"]*7,1))
    b=can["metrics"]; two=res[str(CAN)]["2"]["metrics"]
    years=all(can["by_year"].get(str(y),{}).get("total_return",-1)>=0 for y in (2024,2025))
    qual=b["annualized_sharpe"]>1 and b["total_return"]>0 and two["total_return"]>0 and sum(res[str(v)]["1"]["metrics"]["total_return"]>0 for v in VOLS)>=2 and years
    out.update(oos_consumed=True,oos_results=res,multiple_testing={"family_dsr":fam},success_gate_candidate=qual,
               classification="EXPLORATORY_PASS" if qual else "REJECT")
    print(json.dumps(out,indent=2,default=str))
if __name__=="__main__":main()
