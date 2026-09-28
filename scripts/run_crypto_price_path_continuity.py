#!/usr/bin/env python3
from __future__ import annotations
import argparse, glob, json, math
from datetime import date, timedelta
from pathlib import Path
import numpy as np
import polars as pl
from scipy import stats
from scipy.stats import spearmanr
from src.experiment import compute_deflated_sharpe

WINDOWS=(7,14,28); CAN=14; COST=10.0; TOPN=50; MIN_XS=10
DEV0=date(2022,1,1); DEV1=date(2024,1,1); OOS0=date(2024,1,1); OOS1=date(2026,1,1)

def load_daily(root: Path) -> pl.DataFrame:
    mani=json.load(open(root/"dataset_manifest.json"))
    fs=[]
    for s,v in mani["symbol_summaries"].items():
        if not s.endswith("USDT") or s=="BTCDOMUSDT": continue
        if v["first_timestamp"]>"2021-12-31T23:59:59+00:00": continue
        paths=glob.glob(str(root/f"symbol={s}"/"year=*"/"month=*"/"data.parquet"))
        if not paths: continue
        x=(pl.scan_parquet(paths,hive_partitioning=False)
           .filter(pl.col("timestamp")<pl.datetime(2026,1,6,time_zone="UTC"))
           .select("timestamp","open","close","quote_volume").collect().sort("timestamp"))
        if x.height==0: continue
        d=(x.with_columns(pl.col("timestamp").dt.date().alias("date"))
           .group_by("date").agg(pl.col("open").first().alias("open"),pl.col("close").last().alias("close"),
                                 pl.col("quote_volume").sum().alias("qv"),pl.len().alias("hours"))
           .sort("date").filter(pl.col("hours")==24).drop("hours").with_columns(pl.lit(s).alias("symbol")))
        if d.height>=60: fs.append(d)
    return pl.concat(fs,how="vertical").sort(["symbol","date"])

def weekly_return_map(d: pl.DataFrame):
    out={}
    for p in d.partition_by("symbol",maintain_order=True):
        s=str(p["symbol"][0]); rows=p.select("date","open","close").to_dicts(); idx={r["date"]:i for i,r in enumerate(rows)}
        for dt,i in idx.items():
            if dt.weekday()!=0: continue
            end=dt+timedelta(days=7); entry=rows[i]["open"]; exitp=None
            if end in idx: exitp=rows[idx[end]]["open"]
            else:
                cand=[r for r in rows[i:] if r["date"]<end]
                if cand: exitp=cand[-1]["close"]
            if entry and exitp and entry>0: out[(dt,s)]=float(exitp/entry-1)
    return out

def feature_frame(d: pl.DataFrame,w:int)->pl.DataFrame:
    x=(d.sort(["symbol","date"])
       .with_columns(
           (pl.col("close")/pl.col("close").shift(1).over("symbol")-1).alias("_r"),
           pl.col("qv").shift(1).rolling_sum(30).over("symbol").alias("_liq"),
           pl.col("date").shift(max(w,30)).over("symbol").alias("_anchor"))
       .with_columns(
           (pl.col("_r").shift(1).log1p().rolling_sum(w).over("symbol").exp()-1).alias("_pret"),
           (pl.col("_r").shift(1).rolling_sum(w).over("symbol").abs()/pl.col("_r").shift(1).abs().rolling_sum(w).over("symbol")).alias("_eff"))
       .with_columns((pl.col("_pret")*pl.col("_eff")).alias("signal"))
       .filter((pl.col("date").dt.weekday()==1)&pl.col("signal").is_finite()&pl.col("_liq").is_finite()
               &(pl.col("_anchor")==pl.col("date")-pl.duration(days=max(w,30)))))
    out=[]
    for p in x.partition_by("date",maintain_order=True):
        p=p.sort("_liq",descending=True).head(TOPN)
        if p.height>=MIN_XS: out.append(p.select("date","symbol","signal"))
    return pl.concat(out,how="vertical").sort(["date","symbol"]) if out else pl.DataFrame()

def hac(a,max_lag=4):
    if len(a)<8:return 0.0,1.0
    c=a-a.mean();n=len(a);lrv=float(np.dot(c,c)/n)
    for lag in range(1,min(max_lag,n-1)+1):
        lrv+=2*(1-lag/(max_lag+1))*float(np.dot(c[lag:],c[:-lag])/n)
    if lrv<=0:return 0.0,1.0
    t=float(a.mean()/math.sqrt(lrv/n)); return t,float(2*stats.norm.sf(abs(t)))

def diagnostic(f,rm,start,end):
    ics=[];sp=[]
    for p in f.filter((pl.col("date")>=start)&(pl.col("date")<end)).partition_by("date",maintain_order=True):
        dt=p["date"][0]; rows=[r for r in p.iter_rows(named=True) if (dt,str(r["symbol"])) in rm]
        if len(rows)<MIN_XS: continue
        s=np.array([float(r["signal"]) for r in rows]); y=np.array([rm[(dt,str(r["symbol"]))] for r in rows])
        ic=float(spearmanr(s,y).statistic)
        if np.isfinite(ic): ics.append(ic)
        ix=np.argsort(s); k=max(2,len(ix)//5); sp.append(float(y[ix[-k:]].mean()-y[ix[:k]].mean()))
    a=np.array(ics); m=float(a.mean()) if len(a) else 0.; sd=float(a.std(ddof=1)) if len(a)>1 else 0.; t,p=hac(a)
    return {"n_weeks":len(a),"mean_ic":m,"ic_ir":m/sd if sd>0 else 0.,"hac_t":t,"hac_p":p,"high_minus_low":float(np.mean(sp)) if sp else 0.}

def targets(f,start,end,exclude=None):
    ex=exclude or set(); out={}
    for p in f.filter((pl.col("date")>=start)&(pl.col("date")<end)).partition_by("date",maintain_order=True):
        rows=sorted([(str(r["symbol"]),float(r["signal"])) for r in p.iter_rows(named=True) if str(r["symbol"]) not in ex],key=lambda x:x[1])
        if len(rows)<MIN_XS: continue
        k=max(2,len(rows)//5); w={}
        for s,_ in rows[:k]: w[s]=-.5/k
        for s,_ in rows[-k:]: w[s]=.5/k
        out[p["date"][0]]=w
    return out

def sim(tg,rm,start,end,cost):
    prev={}; rr=[]; cont={}; turns=[]
    for dt in sorted(k for k in tg if start<=k<end):
        w=tg[dt]; turn=sum(abs(w.get(s,0)-prev.get(s,0)) for s in set(w)|set(prev)); gross=0.
        for s,ww in w.items():
            r=rm.get((dt,s))
            if r is not None: gross+=ww*r; cont[s]=cont.get(s,0.)+ww*r
        rr.append((dt,gross-turn*cost/10000)); turns.append(turn); prev=w
    if not rr:return {"metrics":{"annualized_sharpe":0.,"total_return":0.,"max_drawdown":0.,"n_weeks":0},"by_year":{},"asset_contribution":{}}
    a=np.array([r for _,r in rr]); eq=np.cumprod(1+a); pk=np.maximum.accumulate(eq); dd=eq/pk-1; sd=np.std(a,ddof=1)
    by={}
    for y in sorted({d.year for d,_ in rr}):
        q=np.array([r for d,r in rr if d.year==y]); qs=np.std(q,ddof=1)
        by[str(y)]={"total_return":float(np.prod(1+q)-1),"sharpe":float(q.mean()/qs*math.sqrt(52)) if len(q)>1 and qs>0 else 0.}
    return {"metrics":{"annualized_sharpe":float(a.mean()/sd*math.sqrt(52)) if sd>0 else 0.,"total_return":float(eq[-1]-1),
                       "max_drawdown":float(dd.min()),"n_weeks":len(a),"turnover":float(sum(turns))},
            "by_year":by,"asset_contribution":cont}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",type=Path,required=True); a=ap.parse_args()
    d=load_daily(a.root); rm=weekly_return_map(d); fs={w:feature_frame(d,w) for w in WINDOWS}
    di={w:diagnostic(fs[w],rm,DEV0,DEV1) for w in WINDOWS}
    dev={w:sim(targets(fs[w],DEV0,DEV1),rm,DEV0,DEV1,COST) for w in WINDOWS}
    dm=dev[CAN]["metrics"]
    gate=(di[CAN]["mean_ic"]>.02 and di[CAN]["hac_p"]<.05 and di[CAN]["high_minus_low"]>0 and
          dm["annualized_sharpe"]>.7 and dm["total_return"]>0 and sum(dev[w]["metrics"]["total_return"]>0 for w in WINDOWS)>=2)
    out={"schema_version":1,"run_id":"20260928-price-path-continuity-weekly","universe_symbols":d["symbol"].n_unique(),
         "development_diagnostics":{str(w):di[w] for w in WINDOWS},"development":{str(w):dev[w] for w in WINDOWS},
         "development_gate_passed":gate,"oos_consumed":False,
         "trial_accounting":{"previous_parameter_trials":136,"new_parameter_trials":3,"cumulative_parameter_trials":139}}
    if not gate:
        out.update(classification="REJECT",success_gate_candidate=False,conclusion="Development gate failed; OOS not consumed.")
        print(json.dumps(out,indent=2,default=str)); return
    res={}; sharp=[]
    for w in WINDOWS:
        res[str(w)]={str(m):sim(targets(fs[w],OOS0,OOS1),rm,OOS0,OOS1,COST*m) for m in (1,2,3)}
        sharp.append(res[str(w)]["1"]["metrics"]["annualized_sharpe"])
    base=res[str(CAN)]["1"]; bm=base["metrics"]; odi={w:diagnostic(fs[w],rm,OOS0,OOS1) for w in WINDOWS}
    ex=sim(targets(fs[CAN],OOS0,OOS1,{"BTCUSDT","ETHUSDT"}),rm,OOS0,OOS1,COST)
    strong=max(base["asset_contribution"],key=lambda s:abs(base["asset_contribution"][s])) if base["asset_contribution"] else None
    exs=sim(targets(fs[CAN],OOS0,OOS1,{strong} if strong else set()),rm,OOS0,OOS1,COST) if strong else None
    years=all(base["by_year"].get(str(y),{}).get("total_return",-1)>=0 for y in (2024,2025))
    stable=sum(res[str(w)]["1"]["metrics"]["total_return"]>0 for w in WINDOWS)>=2
    dsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp,n_obs_days=max(bm["n_weeks"]*7,1))
    gdsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp+[0.]*136,n_obs_days=max(bm["n_weeks"]*7,1))
    qual=(bm["annualized_sharpe"]>1 and odi[CAN]["mean_ic"]>.02 and res[str(CAN)]["2"]["metrics"]["total_return"]>0 and
          stable and years and bm["max_drawdown"]>-.35 and ex["metrics"]["total_return"]>0 and
          (exs is None or exs["metrics"]["total_return"]>0))
    out.update(oos_consumed=True,oos_diagnostics={str(w):odi[w] for w in WINDOWS},oos_results=res,
               exclude_btc_eth=ex,strongest_asset=strong,exclude_strongest=exs,
               multiple_testing={"family_dsr":dsr,"global_139_trial_proxy":gdsr,"pbo":"N/A: three preregistered windows"},
               success_gate_candidate=qual,classification="EXPLORATORY_PASS" if qual else "REJECT")
    print(json.dumps(out,indent=2,default=str))

if __name__=="__main__": main()
