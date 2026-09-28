#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math
from datetime import date,timedelta
from pathlib import Path
import numpy as np
import polars as pl
from scipy.stats import spearmanr
from scripts.run_crypto_risk_managed_xs_momentum import load_daily,week_ret_map
from src.experiment import compute_deflated_sharpe

FORMS=(7,14,28); CAN=7; COST=10.0; TOPN=50; MIN_XS=10
DEV0=date(2022,1,1); DEV1=date(2024,1,1); OOS0=date(2024,1,1); OOS1=date(2026,1,1)

def base_mondays(daily):
    x=(daily.sort(["symbol","date"]).with_columns(
        pl.col("close").shift(1).over("symbol").alias("_c1"),
        pl.col("close").shift(29).over("symbol").alias("_c29"),
        pl.col("qv").shift(1).rolling_sum(30).over("symbol").alias("_liq"),
        pl.col("date").shift(29).over("symbol").alias("_a29"),
        pl.col("date").shift(30).over("symbol").alias("_a30"),
    ).filter(
        (pl.col("date").dt.weekday()==1)&pl.col("_c1").is_finite()&pl.col("_c29").is_finite()
        &pl.col("_liq").is_finite()&(pl.col("_a29")==pl.col("date")-pl.duration(days=29))
        &(pl.col("_a30")==pl.col("date")-pl.duration(days=30))
    ).with_columns((pl.col("_c1")/pl.col("_c29")-1).alias("_mkt28")))
    out=[]
    for p in x.partition_by("date",maintain_order=True):
        p=p.sort("_liq",descending=True).head(TOPN)
        if p.height>=MIN_XS: out.append(p)
    return pl.concat(out,how="vertical").sort(["date","symbol"]) if out else pl.DataFrame()

def state_map(base):
    st={}
    for p in base.partition_by("date",maintain_order=True):
        q=p["_liq"].to_numpy().astype(float); r=p["_mkt28"].to_numpy().astype(float)
        if len(q)<MIN_XS or not np.isfinite(q).all() or q.sum()<=0: continue
        m=float(np.dot(q/q.sum(),r))
        st[p["date"][0]]=m>=0
    return st

def feature_frame(daily,base,f):
    cols=base.select("date","symbol","_liq")
    x=(daily.sort(["symbol","date"]).with_columns(
        pl.col("close").shift(1).over("symbol").alias("_c1"),
        pl.col("close").shift(1+f).over("symbol").alias("_cf"),
        pl.col("date").shift(1+f).over("symbol").alias("_af"),
    ).filter((pl.col("date").dt.weekday()==1)&pl.col("_c1").is_finite()&pl.col("_cf").is_finite()
             &(pl.col("_af")==pl.col("date")-pl.duration(days=1+f)))
      .with_columns((pl.col("_c1")/pl.col("_cf")-1).alias("signal"))
      .select("date","symbol","signal"))
    return cols.join(x,on=["date","symbol"],how="inner").sort(["date","symbol"])

def is_upup(d,states):
    return bool(states.get(d,False) and states.get(d-timedelta(days=7),False))

def targets(frame,states,start,end,exclude=None):
    ex=exclude or set(); out={}
    for p in frame.filter((pl.col("date")>=start)&(pl.col("date")<end)).partition_by("date",maintain_order=True):
        d=p["date"][0]
        rows=[(str(r["symbol"]),float(r["signal"])) for r in p.iter_rows(named=True) if str(r["symbol"]) not in ex]
        if len(rows)<MIN_XS:
            continue
        if not is_upup(d,states):
            out[d]={}
            continue
        rows.sort(key=lambda x:x[1]); k=max(2,len(rows)//5); w={}
        for s,_ in rows[:k]: w[s]=-.5/k
        for s,_ in rows[-k:]: w[s]=.5/k
        out[d]=w
    return out

def diagnostic(frame,states,rm,start,end):
    ics=[]; spreads=[]; active=0; total=0
    for p in frame.filter((pl.col("date")>=start)&(pl.col("date")<end)).partition_by("date",maintain_order=True):
        d=p["date"][0]; total+=1
        if not is_upup(d,states): continue
        rows=[r for r in p.iter_rows(named=True) if (d,str(r["symbol"])) in rm]
        if len(rows)<MIN_XS: continue
        active+=1
        s=np.array([float(r["signal"]) for r in rows]); y=np.array([rm[(d,str(r["symbol"]))] for r in rows])
        ic=float(spearmanr(s,y).statistic)
        if np.isfinite(ic): ics.append(ic)
        ix=np.argsort(s); k=max(2,len(ix)//5)
        spreads.append(float(y[ix[-k:]].mean()-y[ix[:k]].mean()))
    a=np.array(ics); m=float(a.mean()) if len(a) else 0.; sd=float(a.std(ddof=1)) if len(a)>1 else 0.
    return {"n_active_weeks":active,"n_total_weeks":total,"active_fraction":active/total if total else 0,
            "mean_ic":m,"ic_ir":m/sd if sd>0 else 0.,"winner_minus_loser":float(np.mean(spreads)) if spreads else 0.}

def sim(tg,rm,start,end,cost):
    dates=sorted(d for d in tg if start<=d<end); prev={}; rr=[]; cont={}
    for d in dates:
        w=tg[d]
        turn=sum(abs(w.get(s,0)-prev.get(s,0)) for s in set(w)|set(prev))
        gross=0.
        for s,ww in w.items():
            r=rm.get((d,s))
            if r is not None:
                gross+=ww*r; cont[s]=cont.get(s,0.)+ww*r
        rr.append((d,gross-turn*cost/10000.)); prev=w
    if not rr: return {"metrics":{"annualized_sharpe":0.,"total_return":0.,"max_drawdown":0.,"n_weeks":0},"by_year":{},"asset_contribution":{}}
    a=np.array([r for _,r in rr]); eq=np.cumprod(1+a); pk=np.maximum.accumulate(eq); dd=eq/pk-1; sd=np.std(a,ddof=1)
    by={}
    for y in sorted({d.year for d,_ in rr}):
        q=np.array([r for d,r in rr if d.year==y]); qs=np.std(q,ddof=1)
        by[str(y)]={"total_return":float(np.prod(1+q)-1),"sharpe":float(np.mean(q)/qs*math.sqrt(52)) if len(q)>1 and qs>0 else 0.}
    return {"metrics":{"annualized_sharpe":float(np.mean(a)/sd*math.sqrt(52)) if sd>0 else 0.,
                       "total_return":float(eq[-1]-1),"max_drawdown":float(dd.min()),"n_weeks":len(a)},
            "by_year":by,"asset_contribution":cont}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",type=Path,required=True); a=ap.parse_args()
    d=load_daily(a.root); base=base_mondays(d); states=state_map(base); rm=week_ret_map(d)
    frames={f:feature_frame(d,base,f) for f in FORMS}
    di={f:diagnostic(frames[f],states,rm,DEV0,DEV1) for f in FORMS}
    dev={f:sim(targets(frames[f],states,DEV0,DEV1),rm,DEV0,DEV1,COST) for f in FORMS}
    gate=(di[CAN]["mean_ic"]>.02 and di[CAN]["winner_minus_loser"]>0
          and dev[CAN]["metrics"]["annualized_sharpe"]>.70 and dev[CAN]["metrics"]["total_return"]>0
          and sum(dev[f]["metrics"]["total_return"]>0 for f in FORMS)>=2)
    out={"schema_version":1,"run_id":"20260928-upup-regime-momentum-weekly","universe_symbols":d["symbol"].n_unique(),
         "development_diagnostics":{str(f):di[f] for f in FORMS},"development":{str(f):dev[f] for f in FORMS},
         "development_gate_passed":gate,"oos_consumed":False,
         "trial_accounting":{"previous_parameter_trials":80,"new_parameter_trials":3,"cumulative_parameter_trials":83}}
    if not gate:
        out.update(classification="REJECT",success_gate_candidate=False,conclusion="Development gate failed; OOS not consumed.")
        print(json.dumps(out,indent=2,default=str)); return
    res={}; sharp=[]
    for f in FORMS:
        res[str(f)]={}
        tg=targets(frames[f],states,OOS0,OOS1)
        for mult in (1,2,3): res[str(f)][str(mult)]=sim(tg,rm,OOS0,OOS1,COST*mult)
        sharp.append(res[str(f)]["1"]["metrics"]["annualized_sharpe"])
    baseo=res[str(CAN)]["1"]; bm=baseo["metrics"]
    ex=sim(targets(frames[CAN],states,OOS0,OOS1,{"BTCUSDT","ETHUSDT"}),rm,OOS0,OOS1,COST)
    strongest=max(baseo["asset_contribution"],key=lambda s:abs(baseo["asset_contribution"][s])) if baseo["asset_contribution"] else None
    exs=sim(targets(frames[CAN],states,OOS0,OOS1,{strongest} if strongest else set()),rm,OOS0,OOS1,COST) if strongest else None
    years=all(baseo["by_year"].get(str(y),{}).get("total_return",-1)>=0 for y in (2024,2025))
    stable=sum(res[str(f)]["1"]["metrics"]["total_return"]>0 for f in FORMS)>=2
    qual=(bm["annualized_sharpe"]>1 and bm["total_return"]>0 and res[str(CAN)]["2"]["metrics"]["total_return"]>0
          and stable and years and bm["max_drawdown"]>-.35 and ex["metrics"]["total_return"]>0
          and (exs is None or exs["metrics"]["total_return"]>0))
    dsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp,n_obs_days=max(bm["n_weeks"]*7,1))
    gdsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp+[0.]*80,n_obs_days=max(bm["n_weeks"]*7,1))
    out.update(oos_consumed=True,oos_diagnostics={str(f):diagnostic(frames[f],states,rm,OOS0,OOS1) for f in FORMS},
               oos_results=res,exclude_btc_eth=ex,strongest_asset=strongest,exclude_strongest=exs,
               multiple_testing={"family_dsr":dsr,"global_83_trial_proxy":gdsr,"pbo":"N/A: three preregistered formation windows"},
               success_gate_candidate=qual,classification="EXPLORATORY_PASS" if qual else "REJECT")
    print(json.dumps(out,indent=2,default=str))

if __name__=="__main__": main()
