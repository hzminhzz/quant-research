#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math
from datetime import date
from pathlib import Path
import numpy as np
import polars as pl
from scipy import stats
from scipy.stats import spearmanr
from scripts.run_crypto_aggressor_flow import symbols,load_hourly,return_map
from scripts.run_crypto_downside_semivariance import daily
from src.experiment import compute_deflated_sharpe

REGIMES=(14,30,60);CAN=30;MOM=30;TOPN=30;MIN_XS=10;COST=10.
DEV0=date(2022,1,1);DEV1=date(2024,1,1);OOS0=date(2024,1,1);OOS1=date(2026,1,1)

def weekly_frame(d,regime_days):
    x=(d.sort(["symbol","date"]).with_columns(
        pl.col("close").shift(1).over("symbol").alias("_c1"),
        pl.col("close").shift(MOM+1).over("symbol").alias("_cm"),
        pl.col("qv").shift(1).rolling_sum(30).over("symbol").alias("_liq"),
        pl.col("date").shift(max(MOM+1,30)).over("symbol").alias("_anchor"))
      .with_columns((pl.col("_c1")/pl.col("_cm")-1).alias("signal"))
      .filter((pl.col("date").dt.weekday()==1)&pl.col("signal").is_finite()&pl.col("_liq").is_finite()
              &(pl.col("_anchor")==pl.col("date")-pl.duration(days=max(MOM+1,30)))))
    btc=(d.filter(pl.col("symbol")=="BTCUSDT").sort("date")
      .with_columns(
        pl.col("close").shift(1).alias("_c1"),
        pl.col("close").shift(regime_days+1).alias("_cr"),
        pl.col("date").shift(regime_days+1).alias("_ra"))
      .with_columns((pl.col("_c1")/pl.col("_cr")-1).alias("btc_regime_ret"))
      .filter((pl.col("date").dt.weekday()==1)&pl.col("btc_regime_ret").is_finite()
              &(pl.col("_ra")==pl.col("date")-pl.duration(days=regime_days+1)))
      .select("date","btc_regime_ret"))
    x=x.join(btc,on="date",how="inner")
    out=[]
    for p in x.partition_by("date",maintain_order=True):
        p=p.sort("_liq",descending=True).head(TOPN)
        if p.height>=MIN_XS:out.append(p.select("date","symbol","signal","btc_regime_ret"))
    return pl.concat(out,how="vertical").sort(["date","symbol"]) if out else pl.DataFrame()

def hac(a,max_lag=4):
    if len(a)<8:return 0.,1.
    c=a-a.mean();n=len(a);lrv=float(np.dot(c,c)/n)
    for lag in range(1,min(max_lag,n-1)+1):
        lrv+=2*(1-lag/(max_lag+1))*float(np.dot(c[lag:],c[:-lag])/n)
    if lrv<=0:return 0.,1.
    t=float(a.mean()/math.sqrt(lrv/n));return t,float(2*stats.norm.sf(abs(t)))

def diagnostic(f,rm,start,end):
    ics=[]
    for p in f.filter((pl.col("date")>=start)&(pl.col("date")<end)&(pl.col("btc_regime_ret")>0)).partition_by("date",maintain_order=True):
        d=p["date"][0];rows=[r for r in p.iter_rows(named=True) if (d,str(r["symbol"])) in rm]
        if len(rows)<MIN_XS:continue
        s=np.array([float(r["signal"]) for r in rows]);y=np.array([rm[(d,str(r["symbol"]))] for r in rows])
        ic=float(spearmanr(s,y).statistic)
        if np.isfinite(ic):ics.append(ic)
    a=np.array(ics);m=float(a.mean()) if len(a) else 0.;sd=float(a.std(ddof=1)) if len(a)>1 else 0.;t,p=hac(a)
    return {"active_weeks":len(a),"mean_ic":m,"ic_ir":m/sd if sd>0 else 0.,"hac_t":t,"hac_p":p}

def targets(f,start,end,exclude=None):
    ex=exclude or set();out={}
    for p in f.filter((pl.col("date")>=start)&(pl.col("date")<end)).partition_by("date",maintain_order=True):
        d=p["date"][0]
        if float(p["btc_regime_ret"][0])<=0:
            out[d]={};continue
        rows=sorted([(str(r["symbol"]),float(r["signal"])) for r in p.iter_rows(named=True) if str(r["symbol"]) not in ex],key=lambda z:z[1])
        if len(rows)<MIN_XS:
            out[d]={};continue
        k=max(2,len(rows)//5);w={s:1.0/k for s,_ in rows[-k:]};out[d]=w
    return out

def sim(tg,rm,start,end,cost):
    prev={};rr=[];cont={};turns=[];active=0
    for d in sorted(x for x in tg if start<=x<end):
        w=tg[d];turn=sum(abs(w.get(s,0)-prev.get(s,0)) for s in set(w)|set(prev));gross=0.
        if w:active+=1
        for s,ww in w.items():
            r=rm.get((d,s))
            if r is not None:gross+=ww*r;cont[s]=cont.get(s,0.)+ww*r
        rr.append((d,gross-turn*cost/10000));turns.append(turn);prev=w
    if not rr:return {"metrics":{"annualized_sharpe":0.,"total_return":0.,"max_drawdown":0.,"n_weeks":0,"active_weeks":0},"by_year":{},"asset_contribution":{}}
    a=np.array([r for _,r in rr]);eq=np.cumprod(1+a);pk=np.maximum.accumulate(eq);dd=eq/pk-1;sd=np.std(a,ddof=1)
    by={}
    for y in sorted({d.year for d,_ in rr}):
        q=np.array([r for d,r in rr if d.year==y]);qs=np.std(q,ddof=1)
        by[str(y)]={"total_return":float(np.prod(1+q)-1),"sharpe":float(q.mean()/qs*math.sqrt(52)) if len(q)>1 and qs>0 else 0.}
    return {"metrics":{"annualized_sharpe":float(a.mean()/sd*math.sqrt(52)) if sd>0 else 0.,"total_return":float(eq[-1]-1),"max_drawdown":float(dd.min()),"n_weeks":len(a),"active_weeks":active,"turnover":float(sum(turns))},"by_year":by,"asset_contribution":cont}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",type=Path,required=True);ap.add_argument("--out",type=Path);a=ap.parse_args()
    sy=symbols(a.root);h=load_hourly(a.root,sy);d=daily(h);rm=return_map(h);fs={r:weekly_frame(d,r) for r in REGIMES}
    di={r:diagnostic(fs[r],rm,DEV0,DEV1) for r in REGIMES};dev={r:sim(targets(fs[r],DEV0,DEV1),rm,DEV0,DEV1,COST) for r in REGIMES}
    dm=dev[CAN]["metrics"];dc=di[CAN]
    gate=dc["mean_ic"]>.02 and dc["hac_p"]<.05 and dc["active_weeks"]>=20 and dm["annualized_sharpe"]>.70 and dm["total_return"]>0 and sum(dev[r]["metrics"]["total_return"]>0 for r in REGIMES)>=2
    out={"schema_version":1,"run_id":"20260928-bull-regime-liquid-momentum-longonly","strategy_family":"bull_regime_liquid_momentum_longonly","research_archetype":"regime_conditioned_cross_sectional_momentum","universe_symbols":len(sy),"development_diagnostics":{str(r):di[r] for r in REGIMES},"development":{str(r):dev[r] for r in REGIMES},"development_gate_passed":gate,"oos_consumed":False,"trial_accounting":{"previous_parameter_trials":130,"new_parameter_trials":3,"cumulative_parameter_trials":133}}
    if not gate:
        out.update(classification="REJECT",success_gate_candidate=False,multiple_testing={"dsr_probability":None,"pbo":"N/A: development gate failed before OOS."},conclusion="REJECT. Development gate failed; OOS not consumed.")
        payload=json.dumps(out,indent=2,default=str)
        if a.out:a.out.write_text(payload,encoding="utf-8")
        print(payload);return
    res={};sharp=[]
    for r in REGIMES:
        res[str(r)]={str(m):sim(targets(fs[r],OOS0,OOS1),rm,OOS0,OOS1,COST*m) for m in (1,2,3)}
        sharp.append(res[str(r)]["1"]["metrics"]["annualized_sharpe"])
    base=res[str(CAN)]["1"];bm=base["metrics"];odi={r:diagnostic(fs[r],rm,OOS0,OOS1) for r in REGIMES}
    ex=sim(targets(fs[CAN],OOS0,OOS1,{"BTCUSDT","ETHUSDT"}),rm,OOS0,OOS1,COST)
    strong=max(base["asset_contribution"],key=lambda s:abs(base["asset_contribution"][s])) if base["asset_contribution"] else None
    exs=sim(targets(fs[CAN],OOS0,OOS1,{strong} if strong else set()),rm,OOS0,OOS1,COST) if strong else None
    years=all(base["by_year"].get(str(y),{}).get("total_return",-1)>=0 for y in (2024,2025));stable=sum(res[str(r)]["1"]["metrics"]["total_return"]>0 for r in REGIMES)>=2
    dsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp,n_obs_days=max(bm["n_weeks"]*7,1));gdsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp+[0.]*130,n_obs_days=max(bm["n_weeks"]*7,1))
    qual=bm["annualized_sharpe"]>1 and res[str(CAN)]["2"]["metrics"]["total_return"]>0 and stable and years and bm["max_drawdown"]>-.35 and bm["active_weeks"]>=20 and ex["metrics"]["total_return"]>0 and (exs is None or exs["metrics"]["total_return"]>0)
    out.update(oos_consumed=True,oos_diagnostics={str(r):odi[r] for r in REGIMES},oos_results=res,exclude_btc_eth=ex,strongest_asset=strong,exclude_strongest=exs,multiple_testing={"family_dsr":dsr,"global_133_trial_proxy":gdsr,"pbo":"N/A: three preregistered regime lookbacks"},success_gate_candidate=qual,classification="EXPLORATORY_PASS" if qual else "REJECT")
    payload=json.dumps(out,indent=2,default=str)
    if a.out:a.out.write_text(payload,encoding="utf-8")
    print(payload)
if __name__=="__main__":main()
