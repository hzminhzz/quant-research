#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from datetime import date
from pathlib import Path
import polars as pl
from scripts.run_crypto_aggressor_flow import symbols,load_hourly,return_map
from scripts.run_crypto_skewness_risk import diagnostic,targets,sim
from src.experiment import compute_deflated_sharpe

WINDOWS=(7,14,30);CAN=14;COST=10.;TOPN=50;MIN_XS=10
DEV0=date(2022,1,1);DEV1=date(2024,1,1);OOS0=date(2024,1,1);OOS1=date(2026,1,1)

def daily(h):
    d=(h.with_columns(pl.col("timestamp").dt.date().alias("date"))
       .group_by(["symbol","date"]).agg(
           pl.col("open").first().alias("open"),pl.col("close").last().alias("close"),
           pl.col("quote_volume").sum().alias("qv"),pl.len().alias("hours"))
       .filter(pl.col("hours")==24).drop("hours").sort(["symbol","date"]))
    return (d.with_columns(
        pl.col("close").shift(1).over("symbol").alias("_pc"),
        pl.col("date").shift(1).over("symbol").alias("_pd"))
      .with_columns(pl.when(pl.col("date")-pl.col("_pd")==pl.duration(days=1))
                    .then(pl.col("close")/pl.col("_pc")-1).otherwise(None).alias("ret"))
      .with_columns(pl.when(pl.col("ret")<0).then(pl.col("ret")**2).otherwise(0.0).alias("down2")))

def feature_frame(d,w):
    x=(d.with_columns(
        pl.col("down2").shift(1).rolling_mean(w).over("symbol").alias("signal"),
        pl.col("qv").shift(1).rolling_sum(30).over("symbol").alias("_liq"),
        pl.col("date").shift(w).over("symbol").alias("_aw"),
        pl.col("date").shift(30).over("symbol").alias("_a30"))
      .filter((pl.col("date").dt.weekday()==1)&pl.col("signal").is_finite()&pl.col("_liq").is_finite()
              &(pl.col("_aw")==pl.col("date")-pl.duration(days=w))
              &(pl.col("_a30")==pl.col("date")-pl.duration(days=30))))
    out=[]
    for p in x.partition_by("date",maintain_order=True):
        p=p.sort("_liq",descending=True).head(TOPN)
        if p.height>=MIN_XS:out.append(p.select("date","symbol","signal"))
    return pl.concat(out,how="vertical").sort(["date","symbol"]) if out else pl.DataFrame()

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",type=Path,required=True);a=ap.parse_args()
    sy=symbols(a.root);h=load_hourly(a.root,sy);d=daily(h);rm=return_map(h);fs={w:feature_frame(d,w) for w in WINDOWS}
    di={w:diagnostic(fs[w],rm,DEV0,DEV1) for w in WINDOWS}
    dev={w:sim(targets(fs[w],DEV0,DEV1),rm,DEV0,DEV1,COST) for w in WINDOWS}
    dm=dev[CAN]["metrics"];dc=di[CAN];spread=dc.get("low_minus_high_skew",0)
    gate=dc["mean_ic"]>.02 and dc["hac_p"]<.05 and spread>0 and dm["annualized_sharpe"]>.70 and dm["total_return"]>0 and sum(dev[w]["metrics"]["total_return"]>0 for w in WINDOWS)>=2
    out={"schema_version":1,"run_id":"20260928-downside-semivariance-weekly","strategy_family":"downside_semivariance_risk","research_archetype":"cross_sectional_downside_risk_factor","universe_symbols":len(sy),"development_diagnostics":{str(w):di[w] for w in WINDOWS},"development":{str(w):dev[w] for w in WINDOWS},"development_gate_passed":gate,"oos_consumed":False,"trial_accounting":{"previous_parameter_trials":118,"new_parameter_trials":3,"cumulative_parameter_trials":121}}
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
    dsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp,n_obs_days=max(bm["n_weeks"]*7,1));gdsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp+[0.]*118,n_obs_days=max(bm["n_weeks"]*7,1))
    qual=bm["annualized_sharpe"]>1 and odi[CAN]["mean_ic"]>.02 and res[str(CAN)]["2"]["metrics"]["total_return"]>0 and stable and years and bm["max_drawdown"]>-.35 and ex["metrics"]["total_return"]>0 and (exs is None or exs["metrics"]["total_return"]>0)
    out.update(oos_consumed=True,oos_diagnostics={str(w):odi[w] for w in WINDOWS},oos_results=res,exclude_btc_eth=ex,strongest_asset=strong,exclude_strongest=exs,multiple_testing={"family_dsr":dsr,"global_121_trial_proxy":gdsr,"pbo":"N/A: three preregistered windows"},success_gate_candidate=qual,classification="EXPLORATORY_PASS" if qual else "REJECT")
    print(json.dumps(out,indent=2,default=str))
if __name__=="__main__":main()
