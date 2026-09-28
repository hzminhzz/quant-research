#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math
from datetime import date
from pathlib import Path
import numpy as np
import polars as pl
from scripts.run_crypto_aggressor_flow import symbols,load_hourly
from src.experiment import compute_deflated_sharpe

THRESHOLDS=(1.0,1.5,2.0); CAN=1.5; COST=10.0; TOPN=20; LB=180; MIN_XS=8
DEV0=date(2022,1,1); DEV1=date(2024,1,1); OOS0=date(2024,1,1); OOS1=date(2026,1,1)

def bars4(h):
    return (h.with_columns(pl.col("timestamp").dt.truncate("4h").alias("bar"))
        .group_by(["symbol","bar"]).agg(
            pl.col("open").first().alias("open"),
            pl.col("close").last().alias("close"),
            pl.col("quote_volume").sum().alias("qv"),
            pl.len().alias("hours"))
        .filter(pl.col("hours")==4).drop("hours").rename({"bar":"timestamp"})
        .sort(["symbol","timestamp"])
        .with_columns((pl.col("close")/pl.col("open")-1).alias("ret4")))

def eligible_frame(b):
    x=(b.with_columns(
          pl.col("ret4").shift(1).over("symbol").alias("_prev_ret"),
          pl.col("ret4").shift(1).rolling_std(LB).over("symbol").alias("_vol"),
          pl.col("qv").shift(1).rolling_sum(LB).over("symbol").alias("_liq"),
          pl.col("timestamp").shift(LB).over("symbol").alias("_anchor"))
       .with_columns((pl.col("_prev_ret")/pl.col("_vol")).alias("z"))
       .filter(pl.col("z").is_finite()&pl.col("_liq").is_finite()&(pl.col("_vol")>0)
               &(pl.col("_anchor")==pl.col("timestamp")-pl.duration(hours=4*LB))))
    out=[]
    for p in x.partition_by("timestamp",maintain_order=True):
        p=p.sort("_liq",descending=True).head(TOPN)
        if p.height>=MIN_XS: out.append(p.select("timestamp","symbol","z","ret4"))
    return pl.concat(out,how="vertical").sort(["timestamp","symbol"]) if out else pl.DataFrame()

def targets(f,thr,start,end,exclude=None):
    ex=exclude or set(); out={}
    ff=f.filter((pl.col("timestamp").dt.date()>=start)&(pl.col("timestamp").dt.date()<end))
    for p in ff.partition_by("timestamp",maintain_order=True):
        rows=[(str(r["symbol"]),float(r["z"])) for r in p.iter_rows(named=True)
              if str(r["symbol"]) not in ex and abs(float(r["z"]))>=thr]
        if not rows:
            out[p["timestamp"][0]]={}
            continue
        w=1.0/len(rows)
        out[p["timestamp"][0]]={s:(-w if z>0 else w) for s,z in rows}
    return out

def ret_map(f):
    return {(r["timestamp"],str(r["symbol"])):float(r["ret4"]) for r in f.iter_rows(named=True)}

def sim(tg,rm,start,end,cost):
    prev={}; slot=[]; cont={}; active=[]
    for ts in sorted(t for t in tg if start<=t.date()<end):
        w=tg[ts]; turn=sum(abs(w.get(s,0)-prev.get(s,0)) for s in set(w)|set(prev)); gross=0.
        for s,ww in w.items():
            r=rm.get((ts,s))
            if r is not None:
                gross+=ww*r
                cont[s]=cont.get(s,0.)+ww*r
        net=gross-turn*cost/10000.
        slot.append((ts,net)); active.append(len(w)); prev=w
    if not slot:
        return {"metrics":{"annualized_sharpe":0.,"total_return":0.,"max_drawdown":0.,"n_days":0,"n_slots":0,"n_events":0},"by_year":{},"asset_contribution":{}}
    daily={}
    for ts,r in slot:
        daily.setdefault(ts.date(),[]).append(r)
    dr=[(d,float(np.prod(1+np.asarray(rs))-1)) for d,rs in sorted(daily.items())]
    a=np.array([r for _,r in dr]);eq=np.cumprod(1+a);pk=np.maximum.accumulate(eq);dd=eq/pk-1;sd=np.std(a,ddof=1)
    by={}
    for y in sorted({d.year for d,_ in dr}):
        q=np.array([r for d,r in dr if d.year==y]);qs=np.std(q,ddof=1)
        by[str(y)]={"total_return":float(np.prod(1+q)-1),"sharpe":float(q.mean()/qs*math.sqrt(365)) if len(q)>1 and qs>0 else 0.}
    return {"metrics":{"annualized_sharpe":float(a.mean()/sd*math.sqrt(365)) if sd>0 else 0.,"total_return":float(eq[-1]-1),
                       "max_drawdown":float(dd.min()),"n_days":len(a),"n_slots":len(slot),"n_events":int(sum(active)),
                       "avg_active_assets":float(np.mean(active)) if active else 0.},
            "by_year":by,"asset_contribution":cont}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",type=Path,required=True);a=ap.parse_args()
    sy=symbols(a.root);h=load_hourly(a.root,sy);b=bars4(h);f=eligible_frame(b);rm=ret_map(f)
    dev={thr:sim(targets(f,thr,DEV0,DEV1),rm,DEV0,DEV1,COST) for thr in THRESHOLDS}
    cm=dev[CAN]["metrics"];gate=cm["annualized_sharpe"]>.70 and cm["total_return"]>0 and sum(dev[x]["metrics"]["total_return"]>0 for x in THRESHOLDS)>=2
    out={"schema_version":1,"run_id":"20260928-extreme-4h-mean-reversion","strategy_family":"extreme_move_4h_mean_reversion",
         "research_archetype":"time_series_event_rule","universe_symbols":len(sy),"eligible_rows":f.height,
         "development":{str(x):dev[x] for x in THRESHOLDS},"development_gate_passed":gate,"oos_consumed":False,
         "trial_accounting":{"previous_parameter_trials":142,"new_parameter_trials":3,"cumulative_parameter_trials":145}}
    if not gate:
        out.update(classification="REJECT",success_gate_candidate=False,multiple_testing={"dsr_probability":None,"pbo":"N/A: development gate failed before OOS."},conclusion="REJECT. Development gate failed; OOS not consumed.")
        print(json.dumps(out,indent=2,default=str));return
    res={};sharp=[]
    for thr in THRESHOLDS:
        res[str(thr)]={str(m):sim(targets(f,thr,OOS0,OOS1),rm,OOS0,OOS1,COST*m) for m in (1,2,3)}
        sharp.append(res[str(thr)]["1"]["metrics"]["annualized_sharpe"])
    base=res[str(CAN)]["1"];bm=base["metrics"]
    ex=sim(targets(f,CAN,OOS0,OOS1,{"BTCUSDT","ETHUSDT"}),rm,OOS0,OOS1,COST)
    strong=max(base["asset_contribution"],key=lambda s:abs(base["asset_contribution"][s])) if base["asset_contribution"] else None
    exs=sim(targets(f,CAN,OOS0,OOS1,{strong} if strong else set()),rm,OOS0,OOS1,COST) if strong else None
    years=all(base["by_year"].get(str(y),{}).get("total_return",-1)>=0 for y in (2024,2025))
    stable=sum(res[str(x)]["1"]["metrics"]["total_return"]>0 for x in THRESHOLDS)>=2
    dsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp,n_obs_days=max(bm["n_days"],1))
    gdsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp+[0.]*142,n_obs_days=max(bm["n_days"],1))
    qual=(bm["annualized_sharpe"]>1 and res[str(CAN)]["2"]["metrics"]["total_return"]>0 and stable and years and bm["max_drawdown"]>-.35
          and ex["metrics"]["total_return"]>0 and (exs is None or exs["metrics"]["total_return"]>0))
    out.update(oos_consumed=True,oos_results=res,exclude_btc_eth=ex,strongest_asset=strong,exclude_strongest=exs,
               multiple_testing={"family_dsr":dsr,"global_145_trial_proxy":gdsr,"pbo":"N/A: three preregistered thresholds"},
               success_gate_candidate=qual,classification="EXPLORATORY_PASS" if qual else "REJECT")
    print(json.dumps(out,indent=2,default=str))

if __name__=="__main__":main()
