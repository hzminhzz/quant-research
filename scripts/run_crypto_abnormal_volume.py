#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math
from datetime import date,timedelta
from pathlib import Path
import numpy as np
import polars as pl
from scipy import stats
from scipy.stats import spearmanr
from src.experiment import compute_deflated_sharpe

WINDOWS=(7,15,30,45); CAN=30; COST=10.0; TOPN=50; MIN_XS=10
DEV0=date(2022,1,1); DEV1=date(2024,1,1); OOS0=date(2024,1,1); OOS1=date(2026,1,1)

def load_daily(root):
    pattern=str(root/"symbol=*"/"year=*"/"month=*"/"data.parquet")
    return (
      pl.scan_parquet(pattern,hive_partitioning=True)
      .filter(
        pl.col("symbol").str.ends_with("USDT")
        & (pl.col("symbol")!="BTCDOMUSDT")
        & (pl.col("timestamp")>=pl.datetime(2021,9,1,time_zone="UTC"))
        & (pl.col("timestamp")<pl.datetime(2026,1,1,time_zone="UTC"))
      )
      .select("timestamp","symbol","open","close","quote_volume")
      .with_columns(pl.col("timestamp").dt.date().alias("date"))
      .group_by(["symbol","date"])
      .agg(
        pl.col("open").first().alias("open"),
        pl.col("close").last().alias("close"),
        pl.col("quote_volume").sum().alias("qv"),
        pl.len().alias("hours"),
      )
      .filter(pl.col("hours")==24)
      .drop("hours")
      .sort(["symbol","date"])
      .collect()
    )

def feature_frame(d,w):
    x=(d.sort(["symbol","date"])
      .with_columns(
        pl.col("qv").shift(1).alias("_q1"),
        pl.col("qv").shift(2).rolling_mean(w).over("symbol").alias("_mu"),
        pl.col("qv").shift(2).rolling_std(w).over("symbol").alias("_sd"),
        pl.col("qv").shift(1).rolling_sum(30).over("symbol").alias("_liq"),
        pl.col("date").shift(w+1).over("symbol").alias("_aw"),
        pl.col("date").shift(30).over("symbol").alias("_a30"),
        pl.col("open").shift(-1).over("symbol").alias("_next_open"),
        pl.col("date").shift(-1).over("symbol").alias("_next_date"),
      )
      .with_columns((-(pl.col("_q1")-pl.col("_mu"))/pl.col("_sd")).alias("signal"))
      .with_columns((pl.col("_next_open")/pl.col("open")-1.0).alias("fwd_ret"))
      .filter(
        pl.col("signal").is_finite() & pl.col("_liq").is_finite()
        & (pl.col("_sd")>0)
        & (pl.col("_next_date")==pl.col("date")+pl.duration(days=1))
        & (pl.col("_aw")==pl.col("date")-pl.duration(days=w+1))
        & (pl.col("_a30")==pl.col("date")-pl.duration(days=30))
      ))
    out=[]
    for p in x.partition_by("date",maintain_order=True):
        p=p.sort("_liq",descending=True).head(TOPN)
        if p.height>=MIN_XS:
            out.append(p.select("date","symbol","signal","fwd_ret"))
    return pl.concat(out,how="vertical").sort(["date","symbol"]) if out else pl.DataFrame()

def hac(a,max_lag=5):
    if len(a)<20:return 0.0,1.0
    c=a-a.mean();n=len(a);lrv=float(np.dot(c,c)/n)
    for lag in range(1,min(max_lag,n-1)+1):
        lrv+=2*(1-lag/(max_lag+1))*float(np.dot(c[lag:],c[:-lag])/n)
    if lrv<=0:return 0.0,1.0
    t=float(a.mean()/math.sqrt(lrv/n))
    return t,float(2*stats.norm.sf(abs(t)))

def diagnostic(f,start,end):
    ics=[];sp=[]
    for p in f.filter((pl.col("date")>=start)&(pl.col("date")<end)).partition_by("date",maintain_order=True):
        if p.height<MIN_XS:continue
        s=p["signal"].to_numpy();y=p["fwd_ret"].to_numpy()
        ic=float(spearmanr(s,y).statistic)
        if np.isfinite(ic):ics.append(ic)
        ix=np.argsort(s);k=max(2,len(ix)//5);sp.append(float(y[ix[-k:]].mean()-y[ix[:k]].mean()))
    a=np.array(ics);m=float(a.mean()) if len(a) else 0.;sd=float(a.std(ddof=1)) if len(a)>1 else 0.;t,p=hac(a)
    return {"n_days":len(a),"mean_ic":m,"ic_ir":m/sd if sd>0 else 0.,"hac_t":t,"hac_p":p,"low_minus_high_abnormal_volume":float(np.mean(sp)) if sp else 0.}

def targets(f,start,end,exclude=None,delay_days=0):
    ex=exclude or set();out={}
    ff=f.filter((pl.col("date")>=start)&(pl.col("date")<end))
    for p in ff.partition_by("date",maintain_order=True):
        rows=sorted([(str(r["symbol"]),float(r["signal"])) for r in p.iter_rows(named=True) if str(r["symbol"]) not in ex],key=lambda z:z[1])
        if len(rows)<MIN_XS:continue
        k=max(2,len(rows)//5);w={}
        for s,_ in rows[:k]:w[s]=-.5/k
        for s,_ in rows[-k:]:w[s]=.5/k
        out[p["date"][0]+timedelta(days=delay_days)]=w
    return out

def ret_map(d):
    out={}
    for p in d.partition_by("symbol",maintain_order=True):
        s=str(p["symbol"][0]);rows=p.select("date","open").to_dicts();idx={r["date"]:i for i,r in enumerate(rows)}
        for dt,i in idx.items():
            nxt=dt+timedelta(days=1)
            if nxt in idx and rows[i]["open"] and rows[idx[nxt]]["open"]:
                out[(dt,s)]=float(rows[idx[nxt]]["open"]/rows[i]["open"]-1.0)
    return out

def sim(tg,rm,start,end,cost):
    prev={};rr=[];cont={};turns=[]
    d=start
    while d<end:
        w=tg.get(d,{})
        turn=sum(abs(w.get(s,0)-prev.get(s,0)) for s in set(w)|set(prev))
        gross=0.
        for s,ww in w.items():
            r=rm.get((d,s))
            if r is not None:
                gross+=ww*r;cont[s]=cont.get(s,0.)+ww*r
        rr.append((d,gross-turn*cost/10000.));turns.append(turn);prev=w;d+=timedelta(days=1)
    a=np.array([r for _,r in rr]);eq=np.cumprod(1+a);pk=np.maximum.accumulate(eq);dd=eq/pk-1;sd=float(np.std(a,ddof=1))
    by={}
    for y in sorted({d.year for d,_ in rr}):
        q=np.array([r for d,r in rr if d.year==y]);qs=float(np.std(q,ddof=1))
        by[str(y)]={"total_return":float(np.prod(1+q)-1),"sharpe":float(np.mean(q)/qs*math.sqrt(365.)) if qs>0 else 0.}
    return {"metrics":{"annualized_sharpe":float(np.mean(a)/sd*math.sqrt(365.)) if sd>0 else 0.,"total_return":float(eq[-1]-1),"max_drawdown":float(dd.min()),"n_days":len(a),"turnover":float(sum(turns))},"by_year":by,"asset_contribution":cont}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",type=Path,required=True);a=ap.parse_args()
    d=load_daily(a.root);rm=ret_map(d);fs={w:feature_frame(d,w) for w in WINDOWS}
    di={w:diagnostic(fs[w],DEV0,DEV1) for w in WINDOWS};dev={w:sim(targets(fs[w],DEV0,DEV1),rm,DEV0,DEV1,COST) for w in WINDOWS}
    cd=di[CAN];cm=dev[CAN]["metrics"]
    gate=(cd["mean_ic"]>.02 and cd["hac_p"]<.05 and cd["low_minus_high_abnormal_volume"]>0 and cm["annualized_sharpe"]>.70 and cm["total_return"]>0 and sum(dev[w]["metrics"]["total_return"]>0 for w in WINDOWS)>=3)
    out={"schema_version":1,"run_id":"20260928-abnormal-volume-disagreement-daily","universe_symbols":d["symbol"].n_unique(),"development_diagnostics":{str(w):di[w] for w in WINDOWS},"development":{str(w):dev[w] for w in WINDOWS},"development_gate_passed":gate,"oos_consumed":False,"trial_accounting":{"previous_parameter_trials":96,"new_parameter_trials":4,"cumulative_parameter_trials":100}}
    if not gate:
        out.update(classification="REJECT",success_gate_candidate=False,conclusion="Development gate failed; OOS not consumed.");print(json.dumps(out,indent=2,default=str));return
    res={};sharp=[]
    for w in WINDOWS:
        tg=targets(fs[w],OOS0,OOS1);res[str(w)]={str(m):sim(tg,rm,OOS0,OOS1,COST*m) for m in (1,2,3)}
        sharp.append(res[str(w)]["1"]["metrics"]["annualized_sharpe"])
    base=res[str(CAN)]["1"];bm=base["metrics"];odi=diagnostic(fs[CAN],OOS0,OOS1)
    ex=sim(targets(fs[CAN],OOS0,OOS1,{"BTCUSDT","ETHUSDT"}),rm,OOS0,OOS1,COST)
    strong=max(base["asset_contribution"],key=lambda s:abs(base["asset_contribution"][s])) if base["asset_contribution"] else None
    exs=sim(targets(fs[CAN],OOS0,OOS1,{strong} if strong else set()),rm,OOS0,OOS1,COST) if strong else None
    delayed=sim(targets(fs[CAN],OOS0,OOS1,delay_days=1),rm,OOS0,OOS1,COST)
    years=all(base["by_year"].get(str(y),{}).get("total_return",-1)>=0 for y in (2024,2025));stable=sum(res[str(w)]["1"]["metrics"]["total_return"]>0 for w in WINDOWS)>=3
    dsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp,n_obs_days=max(bm["n_days"],1));gdsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp+[0.]*96,n_obs_days=max(bm["n_days"],1))
    qual=(bm["annualized_sharpe"]>1 and odi["mean_ic"]>.02 and res[str(CAN)]["2"]["metrics"]["total_return"]>0 and stable and years and bm["max_drawdown"]>-.35 and ex["metrics"]["total_return"]>0 and delayed["metrics"]["total_return"]>0 and (exs is None or exs["metrics"]["total_return"]>0))
    out.update(oos_consumed=True,oos_diagnostics=odi,oos_results=res,exclude_btc_eth=ex,strongest_asset=strong,exclude_strongest=exs,delay_one_day=delayed,multiple_testing={"family_dsr":dsr,"global_100_trial_proxy":gdsr,"pbo":"N/A: four preregistered windows"},success_gate_candidate=qual,classification="EXPLORATORY_PASS" if qual else "REJECT")
    print(json.dumps(out,indent=2,default=str))

if __name__=="__main__":main()
