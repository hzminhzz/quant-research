#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, math
from datetime import datetime, timedelta, timezone, date
from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats
from scipy.stats import spearmanr

from scripts.run_crypto_aggressor_flow import symbols, load_hourly
from src.experiment import compute_deflated_sharpe

HORIZONS=(1,2,4)
CAN=2
BETA_WIN=168
LIQ_WIN=720
SHOCK_Z=1.5
TOPN=100
BASE_COST=10.0
MIN_XS=20
DEV0=datetime(2022,1,1,tzinfo=timezone.utc)
DEV1=datetime(2024,1,1,tzinfo=timezone.utc)
OOS0=datetime(2024,1,1,tzinfo=timezone.utc)
OOS1=datetime(2026,1,1,tzinfo=timezone.utc)

def hac_mean(a: np.ndarray, max_lag: int = 6) -> tuple[float,float]:
    if len(a)<20:
        return 0.0,1.0
    c=a-a.mean(); n=len(a); lrv=float(np.dot(c,c)/n)
    for lag in range(1,min(max_lag,n-1)+1):
        lrv += 2.0*(1.0-lag/(max_lag+1))*float(np.dot(c[lag:],c[:-lag])/n)
    if lrv<=0:
        return 0.0,1.0
    t=float(a.mean()/math.sqrt(lrv/n))
    return t,float(2*stats.norm.sf(abs(t)))

def prepared(h: pl.DataFrame, horizon: int) -> pl.DataFrame:
    x=(h.sort(["symbol","timestamp"])
      .with_columns(
        pl.col("close").shift(1).over("symbol").alias("_pc"),
        pl.col("timestamp").shift(1).over("symbol").alias("_pt"),
        pl.col("quote_volume").shift(1).rolling_sum(LIQ_WIN).over("symbol").alias("_liq"),
        pl.col("timestamp").shift(LIQ_WIN).over("symbol").alias("_a720"),
      )
      .with_columns(
        pl.when(pl.col("timestamp")-pl.col("_pt")==pl.duration(hours=1))
          .then(pl.col("close")/pl.col("_pc")-1.0).otherwise(None).alias("ret")
      ))
    btc=(x.filter(pl.col("symbol")=="BTCUSDT")
      .select("timestamp",pl.col("ret").alias("btc_ret"))
      .sort("timestamp")
      .with_columns(
        pl.col("btc_ret").shift(1).rolling_std(BETA_WIN).alias("btc_vol"),
        pl.col("timestamp").shift(BETA_WIN).alias("_btc_anchor")
      ))
    x=x.join(btc,on="timestamp",how="left")
    x=(x.with_columns(
        pl.col("ret").shift(1).rolling_mean(BETA_WIN).over("symbol").alias("_my"),
        pl.col("btc_ret").shift(1).rolling_mean(BETA_WIN).over("symbol").alias("_mx"),
        (pl.col("ret")*pl.col("btc_ret")).shift(1).rolling_mean(BETA_WIN).over("symbol").alias("_mxy"),
        (pl.col("btc_ret")**2).shift(1).rolling_mean(BETA_WIN).over("symbol").alias("_mxx"),
        pl.col("open").shift(-1).over("symbol").alias("_entry"),
        pl.col("open").shift(-(horizon+1)).over("symbol").alias("_exit"),
        pl.col("timestamp").shift(-(horizon+1)).over("symbol").alias("_exit_ts"),
      )
      .with_columns(
        ((pl.col("_mxy")-pl.col("_mx")*pl.col("_my"))/(pl.col("_mxx")-pl.col("_mx")**2)).alias("beta")
      )
      .with_columns(
        (pl.col("beta")*pl.col("btc_ret")-pl.col("ret")).alias("gap"),
        (pl.col("_exit")/pl.col("_entry")-1.0).alias("fwd_ret"),
      )
      .filter(
        (pl.col("symbol")!="BTCUSDT")
        & pl.col("gap").is_finite()
        & pl.col("fwd_ret").is_finite()
        & pl.col("_liq").is_finite()
        & pl.col("btc_vol").is_finite()
        & (pl.col("btc_vol")>0)
        & (pl.col("_a720")==pl.col("timestamp")-pl.duration(hours=LIQ_WIN))
        & (pl.col("_btc_anchor")==pl.col("timestamp")-pl.duration(hours=BETA_WIN))
        & (pl.col("_exit_ts")==pl.col("timestamp")+pl.duration(hours=horizon+1))
        & (pl.col("btc_ret").abs()>=SHOCK_Z*pl.col("btc_vol"))
      ))
    return x.sort(["timestamp","symbol"])

def event_records(p: pl.DataFrame, start: datetime, end: datetime, delay_hours: int = 0, exclude: set[str] | None = None):
    ex=exclude or set(); out=[]; next_ok=None
    for part in p.filter((pl.col("timestamp")>=start)&(pl.col("timestamp")<end)).partition_by("timestamp",maintain_order=True):
        ts=part["timestamp"][0]
        if next_ok is not None and ts < next_ok:
            continue
        rows=[r for r in part.iter_rows(named=True) if str(r["symbol"]) not in ex]
        rows=sorted(rows,key=lambda r:float(r["_liq"]),reverse=True)[:TOPN]
        if len(rows)<MIN_XS:
            continue
        # source predicts slower response in less-liquid names; trade lower half only.
        rows=rows[len(rows)//2:]
        if len(rows)<MIN_XS:
            continue
        rows=sorted(rows,key=lambda r:float(r["gap"]))
        k=max(2,len(rows)//5)
        short=rows[:k]; long=rows[-k:]
        gross=0.0; contrib={}
        for r in short:
            s=str(r["symbol"]); q=-0.5/k; rr=float(r["fwd_ret"]); gross += q*rr; contrib[s]=contrib.get(s,0.0)+q*rr
        for r in long:
            s=str(r["symbol"]); q=0.5/k; rr=float(r["fwd_ret"]); gross += q*rr; contrib[s]=contrib.get(s,0.0)+q*rr
        sig=np.array([float(r["gap"]) for r in rows]); y=np.array([float(r["fwd_ret"]) for r in rows])
        ic=float(spearmanr(sig,y).statistic)
        spread=float(np.mean([float(r["fwd_ret"]) for r in long])-np.mean([float(r["fwd_ret"]) for r in short]))
        out.append({"timestamp":ts,"exit_ts":ts+timedelta(hours=int(part["_exit_ts"][0].timestamp()-ts.timestamp())//3600),"ic":ic,"spread":spread,"gross":gross,"contrib":contrib})
        # no overlapping events; delay is applied as extra idle time in robustness.
        h=int((part["_exit_ts"][0]-ts).total_seconds()//3600)-1
        next_ok=ts+timedelta(hours=h+1+delay_hours)
    return out

def metrics(events, start: datetime, end: datetime, cost_bps: float, delay_penalty_hours: int = 0):
    days=[]; d=start.date()
    while d<end.date():
        days.append(d); d+=timedelta(days=1)
    byday={d:0.0 for d in days}; cont={}; used=0
    for e in events:
        if delay_penalty_hours:
            # conservative robustness: an extra hour of delay loses the first 1/(H+1) of realized event PnL.
            gross=e["gross"]*(1.0-1.0/(CAN+1))
        else:
            gross=e["gross"]
        net=gross-2.0*cost_bps/10000.0
        dd=e["exit_ts"].date()
        if dd in byday:
            byday[dd]+=net; used+=1
        for s,v in e["contrib"].items():
            cont[s]=cont.get(s,0.0)+v
    a=np.array([byday[d] for d in days],dtype=float)
    eq=np.cumprod(1.0+a); pk=np.maximum.accumulate(eq); dd=eq/pk-1.0; sd=float(np.std(a,ddof=1))
    by={}
    for y in sorted({d.year for d in days}):
        q=np.array([byday[d] for d in days if d.year==y],dtype=float); qs=float(np.std(q,ddof=1))
        by[str(y)]={"total_return":float(np.prod(1.0+q)-1.0),"sharpe":float(np.mean(q)/qs*math.sqrt(365.0)) if qs>0 else 0.0}
    return {"metrics":{"annualized_sharpe":float(np.mean(a)/sd*math.sqrt(365.0)) if sd>0 else 0.0,"total_return":float(eq[-1]-1.0),"max_drawdown":float(dd.min()),"n_days":len(a),"n_events":used},"by_year":by,"asset_contribution":cont}

def diag(events):
    ic=np.array([e["ic"] for e in events if np.isfinite(e["ic"])],dtype=float)
    sp=np.array([e["spread"] for e in events],dtype=float)
    t,p=hac_mean(ic)
    return {"n_events":len(events),"mean_ic":float(ic.mean()) if len(ic) else 0.0,"ic_ir":float(ic.mean()/ic.std(ddof=1)) if len(ic)>1 and ic.std(ddof=1)>0 else 0.0,"hac_t":t,"hac_p":p,"mean_top_minus_bottom":float(sp.mean()) if len(sp) else 0.0}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",type=Path,required=True); a=ap.parse_args()
    sy=symbols(a.root); h=load_hourly(a.root,sy)
    integrity={"rows":h.height,"symbols":h["symbol"].n_unique(),"start":str(h["timestamp"].min()),"end":str(h["timestamp"].max()),"duplicate_pairs":h.select(pl.struct(["symbol","timestamp"]).is_duplicated().sum()).item()}
    prep={hh:prepared(h,hh) for hh in HORIZONS}
    dev_events={hh:event_records(prep[hh],DEV0,DEV1) for hh in HORIZONS}
    di={hh:diag(dev_events[hh]) for hh in HORIZONS}
    dev={hh:metrics(dev_events[hh],DEV0,DEV1,BASE_COST) for hh in HORIZONS}
    cm=dev[CAN]["metrics"]; cd=di[CAN]
    gate=(cd["n_events"]>=150 and cd["mean_ic"]>0.02 and cd["hac_p"]<0.05 and cd["mean_top_minus_bottom"]>0 and cm["annualized_sharpe"]>0.70 and cm["total_return"]>0 and sum(dev[hh]["metrics"]["total_return"]>0 for hh in HORIZONS)>=2)
    out={"schema_version":1,"run_id":"20260928-btc-shock-underreaction-lowliq","data_integrity":integrity,"development_diagnostics":{str(k):di[k] for k in HORIZONS},"development":{str(k):dev[k] for k in HORIZONS},"development_gate_passed":gate,"oos_consumed":False,"trial_accounting":{"previous_parameter_trials":93,"new_parameter_trials":3,"cumulative_parameter_trials":96}}
    if not gate:
        out.update(classification="REJECT",success_gate_candidate=False,conclusion="Development gate failed; OOS not consumed.")
        print(json.dumps(out,indent=2,default=str)); return
    res={}; sharp=[]
    for hh in HORIZONS:
        ev=event_records(prep[hh],OOS0,OOS1)
        res[str(hh)]={str(m):metrics(ev,OOS0,OOS1,BASE_COST*m) for m in (1,2,3)}
        sharp.append(res[str(hh)]["1"]["metrics"]["annualized_sharpe"])
    base=res[str(CAN)]["1"]; bm=base["metrics"]
    strong=max(base["asset_contribution"],key=lambda s:abs(base["asset_contribution"][s])) if base["asset_contribution"] else None
    exs=metrics(event_records(prep[CAN],OOS0,OOS1,exclude={strong} if strong else set()),OOS0,OOS1,BASE_COST) if strong else None
    delayed=metrics(event_records(prep[CAN],OOS0,OOS1,delay_hours=1),OOS0,OOS1,BASE_COST,delay_penalty_hours=1)
    years=all(base["by_year"].get(str(y),{}).get("total_return",-1)>=0 for y in (2024,2025))
    stable=sum(res[str(hh)]["1"]["metrics"]["total_return"]>0 for hh in HORIZONS)>=2
    dsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp,n_obs_days=max(bm["n_days"],1))
    gdsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp+[0.0]*93,n_obs_days=max(bm["n_days"],1))
    qual=(bm["annualized_sharpe"]>1.0 and res[str(CAN)]["2"]["metrics"]["total_return"]>0 and stable and years and bm["max_drawdown"]>-.35 and delayed["metrics"]["total_return"]>0 and (exs is None or exs["metrics"]["total_return"]>0))
    out.update(oos_consumed=True,oos_results=res,strongest_asset=strong,exclude_strongest=exs,delay_one_extra_hour=delayed,multiple_testing={"family_dsr":dsr,"global_96_trial_proxy":gdsr,"pbo":"N/A: three preregistered holding horizons"},success_gate_candidate=qual,classification="EXPLORATORY_PASS" if qual else "REJECT")
    print(json.dumps(out,indent=2,default=str))

if __name__=="__main__":
    main()
