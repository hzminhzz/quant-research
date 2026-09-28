#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math
from datetime import date
from pathlib import Path
import numpy as np
import polars as pl
from scripts.run_crypto_risk_managed_xs_momentum import load_daily,week_ret_map
from src.experiment import compute_deflated_sharpe

FORMS=(7,14,28); CAN=7; COST=10.; TOPN=100
DEV0=date(2022,1,1); DEV1=date(2024,1,1); OOS0=date(2024,1,1); OOS1=date(2026,1,1)

def frame(d,f):
    x=(d.sort(["symbol","date"]).with_columns(
       pl.col("close").shift(1).over("symbol").alias("c1"),
       pl.col("close").shift(1+f).over("symbol").alias("cf"),
       pl.col("qv").shift(1).rolling_sum(30).over("symbol").alias("liq"),
       pl.col("date").shift(1+f).over("symbol").alias("af"),
       pl.col("date").shift(30).over("symbol").alias("a30"))
      .filter((pl.col("date").dt.weekday()==1)&pl.col("c1").is_finite()&pl.col("cf").is_finite()
              &pl.col("liq").is_finite()&(pl.col("af")==pl.col("date")-pl.duration(days=1+f))
              &(pl.col("a30")==pl.col("date")-pl.duration(days=30)))
      .with_columns((pl.col("c1")/pl.col("cf")-1).alias("signal")))
    out=[]
    for p in x.partition_by("date",maintain_order=True):
        p=p.sort("liq",descending=True).head(TOPN)
        if p.height>=40:out.append(p.select("date","symbol","signal","liq"))
    return pl.concat(out,how="vertical") if out else pl.DataFrame()

def buckets(p,exclude=None):
    ex=exclude or set()
    r=[(str(x["symbol"]),float(x["signal"]),float(x["liq"])) for x in p.iter_rows(named=True) if str(x["symbol"]) not in ex]
    r.sort(key=lambda z:z[2],reverse=True)
    k=max(8,len(r)//5)
    return r[:k],r[-k:]

def sleeve(rows,momentum,gross):
    rows=sorted(rows,key=lambda z:z[1]);k=max(2,len(rows)//3);w={}
    lo,hi=rows[:k],rows[-k:]
    longs,shorts=(hi,lo) if momentum else (lo,hi)
    for s,_,_ in longs:w[s]=gross*.5/k
    for s,_,_ in shorts:w[s]=-gross*.5/k
    return w

def targets(f,start,end,exclude=None,which="both"):
    out={}
    for p in f.filter((pl.col("date")>=start)&(pl.col("date")<end)).partition_by("date",maintain_order=True):
        large,small=buckets(p,exclude);w={}
        if which in ("both","large"):
            for s,v in sleeve(large,True,.5 if which=="both" else 1.).items():w[s]=w.get(s,0)+v
        if which in ("both","small"):
            for s,v in sleeve(small,False,.5 if which=="both" else 1.).items():w[s]=w.get(s,0)+v
        out[p["date"][0]]=w
    return out

def diagnostic(f,rm,start,end):
    lg=[];sm=[]
    for p in f.filter((pl.col("date")>=start)&(pl.col("date")<end)).partition_by("date",maintain_order=True):
        d=p["date"][0];a,b=buckets(p)
        def sp(rows,mom):
            z=sorted([(x[1],rm[(d,x[0])]) for x in rows if (d,x[0]) in rm]);k=max(2,len(z)//3)
            lo=np.mean([v for _,v in z[:k]]);hi=np.mean([v for _,v in z[-k:]])
            return float(hi-lo) if mom else float(lo-hi)
        if len(a)>=6 and len(b)>=6:lg.append(sp(a,True));sm.append(sp(b,False))
    return {"n_weeks":len(lg),"large_momentum_spread":float(np.mean(lg)),"small_reversal_spread":float(np.mean(sm))}

def sim(tg,rm,start,end,cost):
    prev={};rr=[];cont={}
    for d in sorted(x for x in tg if start<=x<end):
        w=tg[d];turn=sum(abs(w.get(s,0)-prev.get(s,0)) for s in set(w)|set(prev));gross=0.
        for s,ww in w.items():
            r=rm.get((d,s))
            if r is not None:gross+=ww*r;cont[s]=cont.get(s,0)+ww*r
        rr.append((d,gross-turn*cost/10000.));prev=w
    a=np.array([r for _,r in rr]);eq=np.cumprod(1+a);pk=np.maximum.accumulate(eq);dd=eq/pk-1;sd=np.std(a,ddof=1)
    by={}
    for y in sorted({d.year for d,_ in rr}):
        q=np.array([r for d,r in rr if d.year==y]);qs=np.std(q,ddof=1)
        by[str(y)]={"total_return":float(np.prod(1+q)-1),"sharpe":float(np.mean(q)/qs*math.sqrt(52)) if qs>0 else 0.}
    return {"metrics":{"annualized_sharpe":float(np.mean(a)/sd*math.sqrt(52)) if sd>0 else 0.,"total_return":float(eq[-1]-1),
            "max_drawdown":float(dd.min()),"n_weeks":len(a)},"by_year":by,"asset_contribution":cont}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",type=Path,required=True);a=ap.parse_args()
    d=load_daily(a.root);rm=week_ret_map(d);fs={f:frame(d,f) for f in FORMS}
    di={f:diagnostic(fs[f],rm,DEV0,DEV1) for f in FORMS};dev={f:sim(targets(fs[f],DEV0,DEV1),rm,DEV0,DEV1,COST) for f in FORMS}
    gate=di[CAN]["large_momentum_spread"]>0 and di[CAN]["small_reversal_spread"]>0 and dev[CAN]["metrics"]["annualized_sharpe"]>.7 and sum(dev[f]["metrics"]["total_return"]>0 for f in FORMS)>=2
    out={"schema_version":1,"run_id":"20260928-size-split-momentum-reversal","development_diagnostics":{str(f):di[f] for f in FORMS},
         "development":{str(f):dev[f] for f in FORMS},"development_gate_passed":gate,"oos_consumed":False,
         "trial_accounting":{"previous_parameter_trials":83,"new_parameter_trials":3,"cumulative_parameter_trials":86}}
    if not gate:
        out.update(classification="REJECT",success_gate_candidate=False);print(json.dumps(out,indent=2));return
    res={};sharp=[]
    for f in FORMS:
        res[str(f)]={str(m):sim(targets(fs[f],OOS0,OOS1),rm,OOS0,OOS1,COST*m) for m in (1,2,3)}
        sharp.append(res[str(f)]["1"]["metrics"]["annualized_sharpe"])
    base=res[str(CAN)]["1"];bm=base["metrics"];large=sim(targets(fs[CAN],OOS0,OOS1,which="large"),rm,OOS0,OOS1,COST);small=sim(targets(fs[CAN],OOS0,OOS1,which="small"),rm,OOS0,OOS1,COST)
    strongest=max(base["asset_contribution"],key=lambda s:abs(base["asset_contribution"][s]));ex=sim(targets(fs[CAN],OOS0,OOS1,{strongest}),rm,OOS0,OOS1,COST)
    years=all(base["by_year"].get(str(y),{}).get("total_return",-1)>=0 for y in (2024,2025));stable=sum(res[str(f)]["1"]["metrics"]["total_return"]>0 for f in FORMS)>=2
    qual=bm["annualized_sharpe"]>1 and res[str(CAN)]["2"]["metrics"]["total_return"]>0 and stable and years and bm["max_drawdown"]>-.35 and large["metrics"]["total_return"]>0 and small["metrics"]["total_return"]>0 and ex["metrics"]["total_return"]>0
    out.update(oos_consumed=True,oos_diagnostics={str(f):diagnostic(fs[f],rm,OOS0,OOS1) for f in FORMS},oos_results=res,large_sleeve=large,small_sleeve=small,strongest_asset=strongest,exclude_strongest=ex,
      multiple_testing={"family_dsr":compute_deflated_sharpe(bm["annualized_sharpe"],sharp,n_obs_days=bm["n_weeks"]*7),"global_86_trial_proxy":compute_deflated_sharpe(bm["annualized_sharpe"],sharp+[0.]*83,n_obs_days=bm["n_weeks"]*7)},
      success_gate_candidate=qual,classification="EXPLORATORY_PASS" if qual else "REJECT")
    print(json.dumps(out,indent=2))
if __name__=="__main__":main()
