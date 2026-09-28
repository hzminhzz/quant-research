#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from datetime import date,timedelta
from pathlib import Path
import numpy as np
import polars as pl
from scipy import stats
from scripts.run_crypto_risk_managed_xs_momentum import load_daily,week_ret_map
from scripts.run_crypto_skewness_risk import diagnostic,targets,sim
from src.experiment import compute_deflated_sharpe

WINDOWS=(14,30,60);CAN=30;COST=10.;TOPN=50;MIN_XS=10
DEV0=date(2022,1,1);DEV1=date(2024,1,1);OOS0=date(2024,1,1);OOS1=date(2026,1,1)

def base_frame(d):
    x=(d.sort(["symbol","date"]).with_columns(
        pl.col("close").shift(1).over("symbol").alias("_pc"),
        pl.col("date").shift(1).over("symbol").alias("_pd"))
       .with_columns(pl.when(pl.col("date")-pl.col("_pd")==pl.duration(days=1))
                     .then(pl.col("close")/pl.col("_pc")-1).otherwise(None).alias("ret")))
    m=x.group_by("date").agg(pl.col("ret").mean().alias("mkt_ret"))
    return x.join(m,on="date",how="left").sort(["symbol","date"])

def feature_frame(b,w):
    from numpy.lib.stride_tricks import sliding_window_view
    rows=[]
    for p in b.partition_by("symbol",maintain_order=True):
        sym=str(p["symbol"][0]);ds=np.array(p["date"].to_list(),dtype="datetime64[D]")
        ar=np.asarray(p["ret"].to_numpy(),float);mr=np.asarray(p["mkt_ret"].to_numpy(),float);qv=np.asarray(p["qv"].to_numpy(),float)
        n=len(ds)
        if n<=max(w,30):continue
        aw=sliding_window_view(ar,w)[:-1];mw=sliding_window_view(mr,w)[:-1]
        am=aw.mean(1);mm=mw.mean(1);ac=aw-am[:,None];mc=mw-mm[:,None]
        den=np.sum(mc*mc,axis=1);beta=np.divide(np.sum(ac*mc,axis=1),den,out=np.full(len(den),np.nan),where=den>0)
        resid=aw-beta[:,None]*mw;sk=stats.skew(resid,axis=1,bias=False,nan_policy="propagate")
        lqw=sliding_window_view(qv,30)[:-1].sum(1)
        for i in range(max(w,30),n):
            d=ds[i]
            if int((d-np.datetime64("1970-01-05","D")).astype(int))%7!=0:continue
            if ds[i-w]!=d-np.timedelta64(w,"D") or ds[i-30]!=d-np.timedelta64(30,"D"):continue
            sig=sk[i-w];liq=lqw[i-30]
            if np.isfinite(sig) and np.isfinite(liq):
                rows.append({"date":d.astype(object),"symbol":sym,"signal":-float(sig),"_liq":float(liq)})
    if not rows:return pl.DataFrame()
    x=pl.DataFrame(rows).sort(["date","symbol"]);out=[]
    for p in x.partition_by("date",maintain_order=True):
        p=p.sort("_liq",descending=True).head(TOPN)
        if p.height>=MIN_XS:out.append(p.select("date","symbol","signal"))
    return pl.concat(out,how="vertical").sort(["date","symbol"]) if out else pl.DataFrame()

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",type=Path,required=True);a=ap.parse_args()
    d=load_daily(a.root);b=base_frame(d);rm=week_ret_map(d);fs={w:feature_frame(b,w) for w in WINDOWS}
    di={w:diagnostic(fs[w],rm,DEV0,DEV1) for w in WINDOWS}
    dev={w:sim(targets(fs[w],DEV0,DEV1),rm,DEV0,DEV1,COST) for w in WINDOWS}
    dm=dev[CAN]["metrics"];dc=di[CAN]
    spread=dc.get("low_minus_high_skew",0)
    gate=dc["mean_ic"]>.02 and dc["hac_p"]<.05 and spread>0 and dm["annualized_sharpe"]>.70 and dm["total_return"]>0 and sum(dev[w]["metrics"]["total_return"]>0 for w in WINDOWS)>=2
    out={"schema_version":1,"run_id":"20260928-idiosyncratic-skewness-weekly","strategy_family":"idiosyncratic_skewness_risk","research_archetype":"cross_sectional_residual_risk_factor","universe_symbols":d["symbol"].n_unique(),"development_diagnostics":{str(w):di[w] for w in WINDOWS},"development":{str(w):dev[w] for w in WINDOWS},"development_gate_passed":gate,"oos_consumed":False,"trial_accounting":{"previous_parameter_trials":112,"new_parameter_trials":3,"cumulative_parameter_trials":115}}
    if not gate:
        out.update(classification="REJECT",success_gate_candidate=False,multiple_testing={"dsr_probability":None,"pbo":"N/A: development gate failed before OOS."},conclusion="REJECT. Development gate failed; OOS not consumed.")
        print(json.dumps(out,indent=2,default=str));return
    res={};sharp=[]
    for w in WINDOWS:
        res[str(w)]={str(m):sim(targets(fs[w],OOS0,OOS1),rm,OOS0,OOS1,COST*m) for m in (1,2,3)}
        sharp.append(res[str(w)]["1"]["metrics"]["annualized_sharpe"])
    base=res[str(CAN)]["1"];bm=base["metrics"];odi={w:diagnostic(fs[w],rm,OOS0,OOS1) for w in WINDOWS}
    ex=sim(targets(fs[CAN],OOS0,OOS1,{"BTCUSDT","ETHUSDT"}),rm,OOS0,OOS1,COST)
    strong=max(base["asset_contribution"],key=lambda s:abs(base["asset_contribution"][s])) if base["asset_contribution"] else None
    exs=sim(targets(fs[CAN],OOS0,OOS1,{strong} if strong else set()),rm,OOS0,OOS1,COST) if strong else None
    years=all(base["by_year"].get(str(y),{}).get("total_return",-1)>=0 for y in (2024,2025));stable=sum(res[str(w)]["1"]["metrics"]["total_return"]>0 for w in WINDOWS)>=2
    dsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp,n_obs_days=max(bm["n_weeks"]*7,1));gdsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp+[0.]*112,n_obs_days=max(bm["n_weeks"]*7,1))
    qual=bm["annualized_sharpe"]>1 and odi[CAN]["mean_ic"]>.02 and res[str(CAN)]["2"]["metrics"]["total_return"]>0 and stable and years and bm["max_drawdown"]>-.35 and ex["metrics"]["total_return"]>0 and (exs is None or exs["metrics"]["total_return"]>0)
    out.update(oos_consumed=True,oos_diagnostics={str(w):odi[w] for w in WINDOWS},oos_results=res,exclude_btc_eth=ex,strongest_asset=strong,exclude_strongest=exs,multiple_testing={"family_dsr":dsr,"global_115_trial_proxy":gdsr,"pbo":"N/A: three preregistered windows"},success_gate_candidate=qual,classification="EXPLORATORY_PASS" if qual else "REJECT")
    print(json.dumps(out,indent=2,default=str))
if __name__=="__main__":main()
