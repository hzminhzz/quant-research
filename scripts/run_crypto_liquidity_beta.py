#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from datetime import date,timedelta
from pathlib import Path
import numpy as np
import polars as pl
from scripts.run_crypto_risk_managed_xs_momentum import load_daily,week_ret_map
from scripts.run_crypto_salience import diagnostic,portfolio,sim
from src.experiment import compute_deflated_sharpe

WS=(26,52,78);CAN=52;COST=10.;TOPN=50
DEV0=date(2022,1,1);DEV1=date(2024,1,1);OOS0=date(2024,1,1);OOS1=date(2026,1,1)
OUT=Path("run_log/crypto_research/runs/20260928-liquidity-risk-beta-weekly-result.json")

def emit(x):
    s=json.dumps(x,indent=2,default=str)
    OUT.write_text(s+"\n",encoding="utf-8")
    print(s)

def prep(d):
    b=(d.sort(["symbol","date"]).with_columns(
        pl.col("close").shift(1).over("symbol").alias("_pc"),
        pl.col("date").shift(1).over("symbol").alias("_pd"),
        pl.col("qv").shift(1).rolling_sum(30).over("symbol").alias("_liq30"),
        pl.col("date").shift(30).over("symbol").alias("_a30"))
       .with_columns(
        pl.when(pl.col("date")-pl.col("_pd")==pl.duration(days=1))
          .then(pl.col("close")/pl.col("_pc")-1).otherwise(None).alias("_dr"))
       .with_columns(
        (pl.col("_dr").abs()/pl.col("qv")).alias("_amihud"),
        pl.col("date").dt.strftime("%G-%V").alias("_wk")))
    elig={}
    for p in b.filter(
        (pl.col("date").dt.weekday()==1)&pl.col("_liq30").is_finite()
        &(pl.col("_a30")==pl.col("date")-pl.duration(days=30))
    ).partition_by("date",maintain_order=True):
        elig[p["date"][0]]=set(str(x) for x in p.sort("_liq30",descending=True).head(TOPN)["symbol"].to_list())
    w=(b.group_by(["symbol","_wk"]).agg(
        pl.col("date").min().alias("week_start"),
        (pl.col("close").last()/pl.col("open").first()-1).alias("ret"),
        pl.col("_amihud").mean().alias("illiq"),
        pl.len().alias("days"))
       .filter((pl.col("days")==7)&pl.col("illiq").is_finite())
       .sort(["week_start","symbol"]))
    agg={};rmap={}
    for p in w.partition_by("week_start",maintain_order=True):
        ws=p["week_start"][0];allowed=elig.get(ws,set())
        rows=[r for r in p.iter_rows(named=True) if str(r["symbol"]) in allowed]
        if len(rows)<10:
            continue
        vals=np.array([float(r["illiq"]) for r in rows])
        lo,hi=np.quantile(vals,[.01,.99])
        agg[ws]=float(np.clip(vals,lo,hi).mean())
        for r in p.iter_rows(named=True):
            rmap[(ws,str(r["symbol"]))]=float(r["ret"])
    weeks=sorted(agg)
    delta={weeks[i]:agg[weeks[i]]-agg[weeks[i-1]] for i in range(1,len(weeks))}
    innov={}
    for i in range(27,len(weeks)):
        cur=weeks[i]
        y=np.array([delta[weeks[j]] for j in range(2,i)])
        xlag=np.array([delta[weeks[j-1]] for j in range(2,i)])
        X=np.column_stack([np.ones(len(xlag)),xlag])
        coef=np.linalg.lstsq(X,y,rcond=None)[0]
        pred=float(coef[0]+coef[1]*delta[weeks[i-1]])
        innov[cur]=-(delta[cur]-pred)
    return elig,rmap,innov

# PREP_BLOCK

def frame(d,L,elig,rmap,innov,fwd):
    out=[]
    dates=sorted(k for k in elig if DEV0-timedelta(weeks=90)<=k<OOS1)
    for reb in dates:
        prev=reb-timedelta(days=7)
        hist=[prev-timedelta(days=7*j) for j in range(L)][::-1]
        if any(h not in innov for h in hist):
            continue
        z=np.array([innov[h] for h in hist])
        v=float(np.var(z,ddof=1))
        if not np.isfinite(v) or v<=0:
            continue
        for s in elig[reb]:
            y=np.array([rmap.get((h,s),np.nan) for h in hist])
            fr=fwd.get((reb,s))
            if fr is None or not np.isfinite(y).all():
                continue
            beta=float(np.cov(y,z,ddof=1)[0,1]/v)
            if np.isfinite(beta):
                out.append((reb,s,beta,float(fr)))
    if not out:
        return pl.DataFrame()
    return pl.DataFrame(out,schema=["date","symbol","signal","fwd_ret"],orient="row").sort(["date","symbol"])

# FRAME_BLOCK

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",type=Path,required=True);args=ap.parse_args()
    d=load_daily(args.root)
    fwd=week_ret_map(d)
    elig,rmap,innov=prep(d)
    fs={w:frame(d,w,elig,rmap,innov,fwd) for w in WS}
    di={w:diagnostic(fs[w],DEV0,DEV1) for w in WS}
    dev={w:sim(portfolio(fs[w],DEV0,DEV1),COST) for w in WS}
    cd=di[CAN];cm=dev[CAN]["metrics"]
    gate=(cd["mean_ic"]>.02 and cd["hac_p"]<.05 and cd["high_minus_low"]>0
          and cm["annualized_sharpe"]>.7 and cm["total_return"]>0
          and sum(dev[w]["metrics"]["total_return"]>0 for w in WS)>=2)
    out={"schema_version":1,"run_id":"20260928-liquidity-risk-beta-weekly",
         "strategy_family":"liquidity_risk_beta","research_archetype":"cross_sectional_systematic_risk_factor",
         "universe_symbols":d["symbol"].n_unique(),
         "development_diagnostics":{str(w):di[w] for w in WS},
         "development":{str(w):dev[w] for w in WS},
         "development_gate_passed":gate,"oos_consumed":False,
         "trial_accounting":{"previous_parameter_trials":109,"new_parameter_trials":3,"cumulative_parameter_trials":112}}
    if not gate:
        out.update(classification="REJECT",success_gate_candidate=False,conclusion="Development gate failed; OOS not consumed.")
        emit(out);return
    res={};sharp=[]
    for w in WS:
        rows=portfolio(fs[w],OOS0,OOS1)
        res[str(w)]={str(m):sim(rows,COST*m) for m in (1,2,3)}
        sharp.append(res[str(w)]["1"]["metrics"]["annualized_sharpe"])
    base=res[str(CAN)]["1"];bm=base["metrics"];odi=diagnostic(fs[CAN],OOS0,OOS1)
    ex=sim(portfolio(fs[CAN],OOS0,OOS1,exclude={"BTCUSDT","ETHUSDT"}),COST)
    strong=max(base["asset_contribution"],key=lambda s:abs(base["asset_contribution"][s])) if base["asset_contribution"] else None
    exs=sim(portfolio(fs[CAN],OOS0,OOS1,exclude={strong}),COST) if strong else None
    years=all(base["by_year"].get(str(y),{}).get("total_return",-1)>=0 for y in (2024,2025))
    stable=sum(res[str(w)]["1"]["metrics"]["total_return"]>0 for w in WS)>=2
    dsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp,n_obs_days=max(bm["n_weeks"]*7,1))
    gdsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp+[0.]*109,n_obs_days=max(bm["n_weeks"]*7,1))
    qual=(bm["annualized_sharpe"]>1 and odi["mean_ic"]>.02 and res[str(CAN)]["2"]["metrics"]["total_return"]>0
          and stable and years and bm["max_drawdown"]>-.35 and ex["metrics"]["total_return"]>0
          and (exs is None or exs["metrics"]["total_return"]>0))
    out.update(oos_consumed=True,oos_diagnostics=odi,oos_results=res,exclude_btc_eth=ex,strongest_asset=strong,
               exclude_strongest=exs,multiple_testing={"family_dsr":dsr,"global_112_trial_proxy":gdsr,
               "pbo":"N/A: three preregistered beta windows"},success_gate_candidate=qual,
               classification="EXPLORATORY_PASS" if qual else "REJECT")
    emit(out)

if __name__=="__main__":
    main()
