#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math
from datetime import date,timedelta
from pathlib import Path
import numpy as np
import polars as pl
from scipy import stats
from scipy.stats import spearmanr
from scripts.run_crypto_aggressor_flow import symbols,load_hourly
from src.experiment import compute_deflated_sharpe

WINDOWS=(12,24,48);CAN=24;LIQ=720;TOPN=50;MIN_XS=10;COST=10.
DEV0=date(2022,1,1);DEV1=date(2024,1,1);OOS0=date(2024,1,1);OOS1=date(2026,1,1)

def return_map(h):
    out={}
    for p in h.partition_by("symbol",maintain_order=True):
        s=str(p["symbol"][0]); rows=p.select("timestamp","open").to_dicts()
        idx={r["timestamp"]:i for i,r in enumerate(rows)}
        for i,r in enumerate(rows[:-1]):
            ts=r["timestamp"]
            if ts.hour!=0: continue
            nxt=ts+timedelta(days=1)
            j=idx.get(nxt)
            if j is None: continue
            a=float(r["open"]);b=float(rows[j]["open"])
            if a>0 and np.isfinite(a) and np.isfinite(b):out[(ts.date(),s)]=b/a-1.
    return out

def feature_frame(h,w):
    x=(h.sort(["symbol","timestamp"]).with_columns(
        pl.col("close").shift(1).over("symbol").alias("_pc"))
      .with_columns((pl.col("close")/pl.col("_pc")-1).alias("_ret"))
      .with_columns(
        (-pl.col("_ret").shift(1).rolling_max(w).over("symbol")).alias("signal"),
        pl.col("quote_volume").shift(1).rolling_sum(LIQ).over("symbol").alias("_liq"),
        pl.col("timestamp").shift(max(w,LIQ)).over("symbol").alias("_anchor"))
      .filter((pl.col("timestamp").dt.hour()==0)&pl.col("signal").is_finite()&pl.col("_liq").is_finite()
              &(pl.col("_anchor")==pl.col("timestamp")-pl.duration(hours=max(w,LIQ))))
      .with_columns(pl.col("timestamp").dt.date().alias("date")))
    out=[]
    for p in x.partition_by("date",maintain_order=True):
        p=p.sort("_liq",descending=True).head(TOPN)
        if p.height>=MIN_XS:out.append(p.select("date","symbol","signal"))
    return pl.concat(out,how="vertical").sort(["date","symbol"]) if out else pl.DataFrame(schema={"date":pl.Date,"symbol":pl.String,"signal":pl.Float64})

def hac(a,max_lag=7):
    if len(a)<20:return 0.,1.
    c=a-a.mean();n=len(a);lrv=float(np.dot(c,c)/n)
    for lag in range(1,min(max_lag,n-1)+1):
        lrv+=2*(1-lag/(max_lag+1))*float(np.dot(c[lag:],c[:-lag])/n)
    if lrv<=0:return 0.,1.
    t=float(a.mean()/math.sqrt(lrv/n));return t,float(2*stats.norm.sf(abs(t)))

def diagnostic(f,rm,start,end):
    ics=[];sp=[]
    for p in f.filter((pl.col("date")>=start)&(pl.col("date")<end)).partition_by("date",maintain_order=True):
        d=p["date"][0];rows=[r for r in p.iter_rows(named=True) if (d,str(r["symbol"])) in rm]
        if len(rows)<MIN_XS:continue
        s=np.array([float(r["signal"]) for r in rows]);y=np.array([rm[(d,str(r["symbol"]))] for r in rows])
        ic=float(spearmanr(s,y).statistic)
        if np.isfinite(ic):ics.append(ic)
        ix=np.argsort(s);k=max(2,len(ix)//5);sp.append(float(y[ix[-k:]].mean()-y[ix[:k]].mean()))
    a=np.array(ics);m=float(a.mean()) if len(a) else 0.;sd=float(a.std(ddof=1)) if len(a)>1 else 0.;t,p=hac(a)
    return {"n_days":len(a),"mean_ic":m,"ic_ir":m/sd if sd>0 else 0.,"hac_t":t,"hac_p":p,"high_minus_low_signal":float(np.mean(sp)) if sp else 0.}

def targets(f,start,end,exclude=None):
    ex=exclude or set();out={}
    for p in f.filter((pl.col("date")>=start)&(pl.col("date")<end)).partition_by("date",maintain_order=True):
        rows=sorted([(str(r["symbol"]),float(r["signal"])) for r in p.iter_rows(named=True) if str(r["symbol"]) not in ex],key=lambda z:z[1])
        if len(rows)<MIN_XS:continue
        k=max(2,len(rows)//5);ww={}
        for s,_ in rows[:k]:ww[s]=-.5/k
        for s,_ in rows[-k:]:ww[s]=.5/k
        out[p["date"][0]]=ww
    return out

def sim(tg,rm,start,end,cost):
    prev={};rr=[];cont={};turns=[]
    for d in sorted(x for x in tg if start<=x<end):
        w=tg[d];turn=sum(abs(w.get(s,0)-prev.get(s,0)) for s in set(w)|set(prev));gross=0.
        for s,ww in w.items():
            r=rm.get((d,s))
            if r is not None:gross+=ww*r;cont[s]=cont.get(s,0.)+ww*r
        rr.append((d,gross-turn*cost/10000));turns.append(turn);prev=w
    if not rr:return {"metrics":{"annualized_sharpe":0.,"total_return":0.,"max_drawdown":0.,"n_days":0},"by_year":{},"asset_contribution":{}}
    a=np.array([r for _,r in rr]);eq=np.cumprod(1+a);pk=np.maximum.accumulate(eq);dd=eq/pk-1;sd=np.std(a,ddof=1)
    by={}
    for y in sorted({d.year for d,_ in rr}):
        q=np.array([r for d,r in rr if d.year==y]);qs=np.std(q,ddof=1)
        by[str(y)]={"total_return":float(np.prod(1+q)-1),"sharpe":float(q.mean()/qs*math.sqrt(365)) if len(q)>1 and qs>0 else 0.}
    return {"metrics":{"annualized_sharpe":float(a.mean()/sd*math.sqrt(365)) if sd>0 else 0.,"total_return":float(eq[-1]-1),"max_drawdown":float(dd.min()),"n_days":len(a),"turnover":float(sum(turns))},"by_year":by,"asset_contribution":cont}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",type=Path,required=True);ap.add_argument("--out",type=Path);a=ap.parse_args()
    sy=symbols(a.root);h=load_hourly(a.root,sy);rm=return_map(h);fs={w:feature_frame(h,w) for w in WINDOWS}
    di={w:diagnostic(fs[w],rm,DEV0,DEV1) for w in WINDOWS};dev={w:sim(targets(fs[w],DEV0,DEV1),rm,DEV0,DEV1,COST) for w in WINDOWS}
    dm=dev[CAN]["metrics"];dc=di[CAN];gate=dc["mean_ic"]>.02 and dc["hac_p"]<.05 and dc["high_minus_low_signal"]>0 and dm["annualized_sharpe"]>.70 and dm["total_return"]>0 and sum(dev[w]["metrics"]["total_return"]>0 for w in WINDOWS)>=2
    out={"schema_version":1,"run_id":"20260928-intraday-max-lottery-daily","strategy_family":"intraday_max_effect","research_archetype":"cross_sectional_intraday_lottery_factor","universe_symbols":len(sy),"development_diagnostics":{str(w):di[w] for w in WINDOWS},"development":{str(w):dev[w] for w in WINDOWS},"development_gate_passed":gate,"oos_consumed":False,"trial_accounting":{"previous_parameter_trials":127,"new_parameter_trials":3,"cumulative_parameter_trials":130}}
    if not gate:
        out.update(classification="REJECT",success_gate_candidate=False,multiple_testing={"dsr_probability":None,"pbo":"N/A: development gate failed before OOS."},conclusion="REJECT. Development gate failed; OOS not consumed.")
        payload=json.dumps(out,indent=2,default=str)
        if a.out:a.out.write_text(payload,encoding="utf-8")
        print(payload);return
    res={};sharp=[]
    for w in WINDOWS:
        res[str(w)]={str(m):sim(targets(fs[w],OOS0,OOS1),rm,OOS0,OOS1,COST*m) for m in (1,2,3)}
        sharp.append(res[str(w)]["1"]["metrics"]["annualized_sharpe"])
    base=res[str(CAN)]["1"];bm=base["metrics"];odi={w:diagnostic(fs[w],rm,OOS0,OOS1) for w in WINDOWS}
    ex=sim(targets(fs[CAN],OOS0,OOS1,{"BTCUSDT","ETHUSDT"}),rm,OOS0,OOS1,COST)
    strong=max(base["asset_contribution"],key=lambda s:abs(base["asset_contribution"][s])) if base["asset_contribution"] else None
    exs=sim(targets(fs[CAN],OOS0,OOS1,{strong} if strong else set()),rm,OOS0,OOS1,COST) if strong else None
    years=all(base["by_year"].get(str(y),{}).get("total_return",-1)>=0 for y in (2024,2025));stable=sum(res[str(w)]["1"]["metrics"]["total_return"]>0 for w in WINDOWS)>=2
    dsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp,n_obs_days=max(bm["n_days"],1));gdsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp+[0.]*127,n_obs_days=max(bm["n_days"],1))
    qual=bm["annualized_sharpe"]>1 and odi[CAN]["mean_ic"]>.02 and res[str(CAN)]["2"]["metrics"]["total_return"]>0 and stable and years and bm["max_drawdown"]>-.35 and ex["metrics"]["total_return"]>0 and (exs is None or exs["metrics"]["total_return"]>0)
    out.update(oos_consumed=True,oos_diagnostics={str(w):odi[w] for w in WINDOWS},oos_results=res,exclude_btc_eth=ex,strongest_asset=strong,exclude_strongest=exs,multiple_testing={"family_dsr":dsr,"global_130_trial_proxy":gdsr,"pbo":"N/A: three preregistered lookbacks"},success_gate_candidate=qual,classification="EXPLORATORY_PASS" if qual else "REJECT")
    payload=json.dumps(out,indent=2,default=str)
    if a.out:a.out.write_text(payload,encoding="utf-8")
    print(payload)
if __name__=="__main__":main()
