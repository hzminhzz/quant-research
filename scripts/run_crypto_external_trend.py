#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, math
from pathlib import Path
import numpy as np
import polars as pl
from sklearn.covariance import LedoitWolf
import cvxpy as cp

SYMBOLS=["BTCUSDT","ETHUSDT","BNBUSDT","ADAUSDT"]

def load_daily(root: Path, symbol: str) -> pl.DataFrame:
    pattern=str(root / f"symbol={symbol}" / "year=*" / "month=*" / "data.parquet")
    x=(pl.scan_parquet(pattern, hive_partitioning=False)
       .select("timestamp","open","high","low","close","volume")
       .collect().sort("timestamp"))
    if x["timestamp"].is_duplicated().any():
        raise ValueError(f"{symbol}: duplicate timestamps")
    x=(x.with_columns(pl.col("timestamp").dt.truncate("1d").alias("date"))
       .group_by("date").agg(
          pl.col("open").first().alias("open"),
          pl.col("high").max().alias("high"),
          pl.col("low").min().alias("low"),
          pl.col("close").last().alias("close"),
          pl.col("volume").sum().alias("volume"),
          pl.len().alias("hours"))
       .sort("date"))
    bad=x.filter((pl.col("hours")!=24) | (pl.col("high")<pl.max_horizontal("open","close")) |
                 (pl.col("low")>pl.min_horizontal("open","close")) | (pl.col("volume")<0))
    if bad.height:
        raise ValueError(f"{symbol}: invalid/incomplete daily bars: {bad.height}")
    return x.drop("hours")

def aligned_arrays(root: Path):
    frames={s:load_daily(root,s) for s in SYMBOLS}
    dates=frames[SYMBOLS[0]].select("date")
    for s in SYMBOLS[1:]:
        dates=dates.join(frames[s].select("date"),on="date",how="inner")
    dates=dates.sort("date")
    fields={}
    for field in ["open","high","low","close"]:
        cols=[frames[s].select("date",pl.col(field).alias(s)) for s in SYMBOLS]
        w=dates
        for c in cols: w=w.join(c,on="date",how="left")
        fields[field]=w
    return dates["date"].to_numpy(), {k:v.select(SYMBOLS).to_numpy() for k,v in fields.items()}

def rolling_mean(a,w):
    out=np.full_like(a,np.nan,dtype=float)
    for j in range(a.shape[1]):
        for i in range(w-1,len(a)):
            out[i,j]=np.mean(a[i-w+1:i+1,j])
    return out

def rolling_std(a,w):
    out=np.full_like(a,np.nan,dtype=float)
    for j in range(a.shape[1]):
        for i in range(w-1,len(a)):
            out[i,j]=np.std(a[i-w+1:i+1,j],ddof=0)
    return out

def mvo(mu,Sigma):
    n=len(mu); w=cp.Variable(n)
    prob=cp.Problem(cp.Maximize(mu@w-0.5*cp.quad_form(w,Sigma)),[cp.norm1(w)<=1.0])
    try:
        prob.solve(solver=cp.CLARABEL,warm_start=True)
        if prob.status!="optimal" or w.value is None: return np.zeros(n)
        return np.asarray(w.value,dtype=float)
    except Exception:
        return np.zeros(n)

def half_spread(high,low,close,window=21):
    lh=np.log(high); ll=np.log(low); lc=np.log(close); mid=(lh+ll)/2
    s2=np.full_like(close,np.nan,dtype=float)
    s2[1:]=4*(lc[:-1]-mid[:-1])*(lc[:-1]-mid[1:])
    out=np.full_like(close,np.nan,dtype=float)
    for j in range(close.shape[1]):
        for i in range(window-1,len(close)):
            vals=s2[i-window+1:i+1,j]
            if np.all(np.isfinite(vals)):
                out[i,j]=0.5*math.sqrt(abs(float(np.mean(vals))))
    lag=np.full_like(out,np.nan); lag[1:]=out[:-1]
    return lag

def build_targets(close):
    ret=np.full_like(close,np.nan,dtype=float); ret[1:]=close[1:]/close[:-1]-1
    ma=rolling_mean(close,140); vol=rolling_std(ret,30)
    trend=close/ma-1; z=np.clip(trend/vol,-5,5)
    active=np.isfinite(z)&(np.abs(z)>1)
    target=np.zeros_like(close,dtype=float)
    for i in range(len(close)):
        if i<120:
            a=active[i]
            w=np.where(a,np.sign(z[i])/max(int(a.sum()),1),0.0) if a.any() else np.zeros(len(SYMBOLS))
        else:
            hist=ret[i-120:i]
            hist=hist[np.all(np.isfinite(hist),axis=1)]
            a=active[i]
            if len(hist)<14:
                w=np.where(a,np.sign(z[i])/max(int(a.sum()),1),0.0) if a.any() else np.zeros(len(SYMBOLS))
            else:
                Sigma=LedoitWolf().fit(hist).covariance_
                mu=np.where(a,z[i],0.0)
                w=mvo(mu,Sigma)
        target[i]=10000*w
    reb=np.arange(len(close))%10==0
    held=np.zeros_like(target)
    cur=np.zeros(len(SYMBOLS))
    for i in range(len(target)):
        if reb[i]: cur=target[i].copy()
        held[i]=cur
    return ret,target,held,reb

def simulate(ret,target,reb,spread,cost_mult=1.0,fixed_bps=None,short_carry=0.0):
    n,m=target.shape
    execpos=np.zeros_like(target); delta=np.zeros_like(target)
    equity=np.zeros(n); equity[0]=10000.0
    gross=np.zeros(n); costs=np.zeros(n); carry=np.zeros(n)
    for i in range(n):
        carried=np.zeros(m) if i==0 else execpos[i-1]*(1+np.nan_to_num(ret[i-1],nan=0.0))
        if reb[i]:
            execpos[i]=target[i]
            delta[i]=target[i]-carried
        else:
            execpos[i]=carried
        if i>0:
            gross[i]=float(np.sum(execpos[i-1]*np.nan_to_num(ret[i],nan=0.0)))
        if fixed_bps is None:
            hs=np.nan_to_num(spread[i],nan=0.0)*cost_mult
            costs[i]=float(np.sum(np.abs(delta[i])*hs))
        else:
            costs[i]=float(np.sum(np.abs(delta[i]))*fixed_bps/10000.0)
        carry[i]=float(np.sum(np.abs(np.minimum(execpos[i],0.0)))*short_carry/365.0)
        equity[i]=(equity[i-1] if i else 10000.0)+gross[i]-costs[i]-carry[i]
    return equity,gross,costs,carry,execpos,delta

def metrics(dates,equity,start):
    mask=dates>=np.datetime64(start)
    idx=np.where(mask)[0]
    if len(idx)<2: return {"n_days":len(idx)}
    anchor=max(idx[0]-1,0)
    eq=np.concatenate([[equity[anchor]],equity[idx]])
    r=eq[1:]/eq[:-1]-1
    sd=float(np.std(r,ddof=1)); mean=float(np.mean(r))
    sr252=mean/sd*math.sqrt(252) if sd>0 else 0.0
    sr365=mean/sd*math.sqrt(365) if sd>0 else 0.0
    peak=np.maximum.accumulate(eq); dd=eq/peak-1
    return {"n_days":len(r),"sharpe_252":sr252,"sharpe_365":sr365,
            "total_return":float(eq[-1]/eq[0]-1),"max_drawdown":float(dd.min()),
            "start_equity":float(eq[0]),"end_equity":float(eq[-1])}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",type=Path,required=True); args=ap.parse_args()
    dates,f=aligned_arrays(args.root); close=f["close"]
    ret,target,held,reb=build_targets(close); spread=half_spread(f["high"],f["low"],close)
    scenarios={
      "canonical":dict(cost_mult=1.0,fixed_bps=None,short_carry=0.0),
      "canonical_carry10":dict(cost_mult=1.0,fixed_bps=None,short_carry=0.10),
      "canonical_2x":dict(cost_mult=2.0,fixed_bps=None,short_carry=0.0),
      "canonical_3x":dict(cost_mult=3.0,fixed_bps=None,short_carry=0.0),
      "fixed5_carry10":dict(cost_mult=1.0,fixed_bps=5.0,short_carry=0.10),
      "fixed10_carry10":dict(cost_mult=1.0,fixed_bps=10.0,short_carry=0.10),
      "fixed20_carry10":dict(cost_mult=1.0,fixed_bps=20.0,short_carry=0.10),
    }
    out={}
    for name,kw in scenarios.items():
        eq,g,c,ca,pos,de=simulate(ret,target,reb,spread,**kw)
        mm=metrics(dates,eq,"2026-03-21")
        mask=dates>=np.datetime64("2026-03-21")
        mm.update(total_cost=float(c[mask].sum()),total_carry=float(ca[mask].sum()),
                  turnover=float(np.abs(de[mask]).sum()),
                  mean_gross_exposure=float(np.abs(pos[mask]).sum(axis=1).mean()))
        out[name]=mm
    eq,g,c,ca,pos,de=simulate(ret,target,reb,spread,cost_mult=1.0,fixed_bps=None,short_carry=0.10)
    mask=dates>=np.datetime64("2026-03-21")
    asset_gross=(np.roll(pos,1,axis=0)*np.nan_to_num(ret,nan=0.0)); asset_gross[0]=0
    attribution={s:{"gross_pnl":float(asset_gross[mask,j].sum()),"mean_abs_exposure":float(np.abs(pos[mask,j]).mean()),
                    "turnover":float(np.abs(de[mask,j]).sum())} for j,s in enumerate(SYMBOLS)}
    payload={"schema_version":1,"strategy":"external frozen four-asset trend",
             "data":{"start":str(dates[0]),"end":str(dates[-1]),"days":len(dates),"symbols":SYMBOLS},
             "evaluation":{"start":"2026-03-21","end":str(dates[-1])},
             "scenarios":out,"asset_attribution":attribution}
    print(json.dumps(payload,indent=2,sort_keys=True))
if __name__=="__main__": main()
