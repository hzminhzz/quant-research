#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math
from datetime import date,timedelta
from pathlib import Path
import numpy as np
import polars as pl
from scipy import stats
from scipy.stats import spearmanr
from scripts.run_crypto_aggressor_flow import symbols,load_hourly,return_map
from src.experiment import compute_deflated_sharpe

LEADERS=("BTCUSDT","ETHUSDT","BNBUSDT","XRPUSDT","ADAUSDT","DOGEUSDT","LTCUSDT","SOLUSDT")
ALPHAS=(0.1,1.0,10.0);CAN=1.0;TRAIN=52;MINTRAIN=40;TOPN=50;MIN_XS=10;COST=10.
DEV0=date(2022,1,1);DEV1=date(2024,1,1);OOS0=date(2024,1,1);OOS1=date(2026,1,1)

def eligible_weeks(h):
    z=(h.sort(["symbol","timestamp"]).with_columns(
        pl.col("quote_volume").shift(1).rolling_sum(720).over("symbol").alias("_liq"),
        pl.col("timestamp").shift(720).over("symbol").alias("_anchor"))
      .filter((pl.col("timestamp").dt.weekday()==1)&(pl.col("timestamp").dt.hour()==0)&pl.col("_liq").is_finite()
              &(pl.col("_anchor")==pl.col("timestamp")-pl.duration(hours=720)))
      .with_columns(pl.col("timestamp").dt.date().alias("date")))
    out={}
    for p in z.partition_by("date",maintain_order=True):
        p=p.sort("_liq",descending=True).head(TOPN)
        if p.height>=MIN_XS:out[p["date"][0]]=[str(x) for x in p["symbol"].to_list()]
    return out

def ridge_predict(X,y,x,alpha):
    mu=X.mean(axis=0);sd=X.std(axis=0,ddof=1);sd=np.where(sd>1e-10,sd,1.0)
    Z=(X-mu)/sd;zx=(x-mu)/sd;ym=float(y.mean());yc=y-ym
    beta=np.linalg.solve(Z.T@Z+alpha*np.eye(Z.shape[1]),Z.T@yc)
    return float(ym+zx@beta)

def prediction_frame(eligible,rm,alpha):
    weeks=sorted(eligible)
    rows=[]
    for i,d in enumerate(weeks):
        prev=d-timedelta(days=7)
        x=np.array([rm.get((prev,s),np.nan) for s in LEADERS],dtype=float)
        if not np.isfinite(x).all():continue
        hist=[w for w in weeks if w<d][-TRAIN:]
        for target in eligible[d]:
            X=[];y=[]
            for tw in hist:
                px=tw-timedelta(days=7)
                xx=np.array([rm.get((px,s),np.nan) for s in LEADERS],dtype=float)
                yy=rm.get((tw,target))
                if yy is not None and np.isfinite(yy) and np.isfinite(xx).all():
                    X.append(xx);y.append(float(yy))
            if len(y)<MINTRAIN:continue
            pred=ridge_predict(np.asarray(X),np.asarray(y),x,alpha)
            if np.isfinite(pred):rows.append({"date":d,"symbol":target,"signal":pred})
    return pl.DataFrame(rows).sort(["date","symbol"]) if rows else pl.DataFrame(schema={"date":pl.Date,"symbol":pl.String,"signal":pl.Float64})

def hac(a,max_lag=4):
    if len(a)<8:return 0.,1.
    c=a-a.mean();n=len(a);lrv=float(np.dot(c,c)/n)
    for lag in range(1,min(max_lag,n-1)+1):
        lrv+=2*(1-lag/(max_lag+1))*float(np.dot(c[lag:],c[:-lag])/n)
    if lrv<=0:return 0.,1.
    t=float(a.mean()/math.sqrt(lrv/n));return t,float(2*stats.norm.sf(abs(t)))

def diagnostic(f,rm,start,end):
    ics=[]
    for p in f.filter((pl.col("date")>=start)&(pl.col("date")<end)).partition_by("date",maintain_order=True):
        d=p["date"][0];rows=[r for r in p.iter_rows(named=True) if (d,str(r["symbol"])) in rm]
        if len(rows)<MIN_XS:continue
        s=np.array([float(r["signal"]) for r in rows]);y=np.array([rm[(d,str(r["symbol"]))] for r in rows])
        ic=float(spearmanr(s,y).statistic)
        if np.isfinite(ic):ics.append(ic)
    a=np.asarray(ics);m=float(a.mean()) if len(a) else 0.;sd=float(a.std(ddof=1)) if len(a)>1 else 0.;t,p=hac(a)
    return {"n_weeks":len(a),"mean_ic":m,"ic_ir":m/sd if sd>0 else 0.,"hac_t":t,"hac_p":p}

def targets(f,start,end,exclude=None):
    ex=exclude or set();out={}
    for p in f.filter((pl.col("date")>=start)&(pl.col("date")<end)).partition_by("date",maintain_order=True):
        rows=sorted([(str(r["symbol"]),float(r["signal"])) for r in p.iter_rows(named=True) if str(r["symbol"]) not in ex],key=lambda z:z[1])
        if len(rows)<MIN_XS:continue
        k=max(2,len(rows)//5);w={}
        for s,_ in rows[:k]:w[s]=-.5/k
        for s,_ in rows[-k:]:w[s]=.5/k
        out[p["date"][0]]=w
    return out

def sim(tg,rm,start,end,cost):
    prev={};rr=[];cont={};turns=[]
    for d in sorted(x for x in tg if start<=x<end):
        w=tg[d];turn=sum(abs(w.get(s,0)-prev.get(s,0)) for s in set(w)|set(prev));gross=0.
        for s,ww in w.items():
            r=rm.get((d,s))
            if r is not None:gross+=ww*r;cont[s]=cont.get(s,0.)+ww*r
        rr.append((d,gross-turn*cost/10000));turns.append(turn);prev=w
    if not rr:return {"metrics":{"annualized_sharpe":0.,"total_return":0.,"max_drawdown":0.,"n_weeks":0},"by_year":{},"asset_contribution":{}}
    a=np.array([r for _,r in rr]);eq=np.cumprod(1+a);pk=np.maximum.accumulate(eq);dd=eq/pk-1;sd=np.std(a,ddof=1)
    by={}
    for y in sorted({d.year for d,_ in rr}):
        q=np.array([r for d,r in rr if d.year==y]);qs=np.std(q,ddof=1)
        by[str(y)]={"total_return":float(np.prod(1+q)-1),"sharpe":float(q.mean()/qs*math.sqrt(52)) if len(q)>1 and qs>0 else 0.}
    return {"metrics":{"annualized_sharpe":float(a.mean()/sd*math.sqrt(52)) if sd>0 else 0.,"total_return":float(eq[-1]-1),"max_drawdown":float(dd.min()),"n_weeks":len(a),"turnover":float(sum(turns))},"by_year":by,"asset_contribution":cont}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",type=Path,required=True);ap.add_argument("--out",type=Path);a=ap.parse_args()
    sy=symbols(a.root);h=load_hourly(a.root,sy);rm=return_map(h);eligible=eligible_weeks(h);fs={al:prediction_frame(eligible,rm,al) for al in ALPHAS}
    di={al:diagnostic(fs[al],rm,DEV0,DEV1) for al in ALPHAS};dev={al:sim(targets(fs[al],DEV0,DEV1),rm,DEV0,DEV1,COST) for al in ALPHAS}
    dm=dev[CAN]["metrics"];dc=di[CAN]
    gate=dc["mean_ic"]>.02 and dc["hac_p"]<.05 and dc["n_weeks"]>=80 and dm["annualized_sharpe"]>.70 and dm["total_return"]>0 and sum(dev[x]["metrics"]["total_return"]>0 for x in ALPHAS)>=2
    out={"schema_version":1,"run_id":"20260928-cross-crypto-spillover-ridge-weekly","strategy_family":"cross_crypto_return_spillover","research_archetype":"supervised_cross_asset_spillover","universe_symbols":len(sy),"development_diagnostics":{str(x):di[x] for x in ALPHAS},"development":{str(x):dev[x] for x in ALPHAS},"development_gate_passed":gate,"oos_consumed":False,"trial_accounting":{"previous_parameter_trials":133,"new_parameter_trials":3,"cumulative_parameter_trials":136}}
    if not gate:
        out.update(classification="REJECT",success_gate_candidate=False,multiple_testing={"dsr_probability":None,"pbo":"N/A: development gate failed before OOS."},conclusion="REJECT. Development gate failed; OOS not consumed.")
        payload=json.dumps(out,indent=2,default=str)
        if a.out:a.out.write_text(payload,encoding="utf-8")
        print(payload);return
    res={};sharp=[]
    for al in ALPHAS:
        res[str(al)]={str(m):sim(targets(fs[al],OOS0,OOS1),rm,OOS0,OOS1,COST*m) for m in (1,2,3)}
        sharp.append(res[str(al)]["1"]["metrics"]["annualized_sharpe"])
    base=res[str(CAN)]["1"];bm=base["metrics"];odi={al:diagnostic(fs[al],rm,OOS0,OOS1) for al in ALPHAS}
    ex=sim(targets(fs[CAN],OOS0,OOS1,{"BTCUSDT","ETHUSDT"}),rm,OOS0,OOS1,COST)
    strong=max(base["asset_contribution"],key=lambda s:abs(base["asset_contribution"][s])) if base["asset_contribution"] else None
    exs=sim(targets(fs[CAN],OOS0,OOS1,{strong} if strong else set()),rm,OOS0,OOS1,COST) if strong else None
    years=all(base["by_year"].get(str(y),{}).get("total_return",-1)>=0 for y in (2024,2025));stable=sum(res[str(al)]["1"]["metrics"]["total_return"]>0 for al in ALPHAS)>=2
    dsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp,n_obs_days=max(bm["n_weeks"]*7,1));gdsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp+[0.]*133,n_obs_days=max(bm["n_weeks"]*7,1))
    qual=bm["annualized_sharpe"]>1 and odi[CAN]["mean_ic"]>.02 and res[str(CAN)]["2"]["metrics"]["total_return"]>0 and stable and years and bm["max_drawdown"]>-.35 and ex["metrics"]["total_return"]>0 and (exs is None or exs["metrics"]["total_return"]>0)
    out.update(oos_consumed=True,oos_diagnostics={str(al):odi[al] for al in ALPHAS},oos_results=res,exclude_btc_eth=ex,strongest_asset=strong,exclude_strongest=exs,multiple_testing={"family_dsr":dsr,"global_136_trial_proxy":gdsr,"pbo":"N/A: three preregistered ridge alphas"},success_gate_candidate=qual,classification="EXPLORATORY_PASS" if qual else "REJECT")
    payload=json.dumps(out,indent=2,default=str)
    if a.out:a.out.write_text(payload,encoding="utf-8")
    print(payload)
if __name__=="__main__":main()
