#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math
from datetime import date
from pathlib import Path
import numpy as np
import polars as pl
from scripts.run_crypto_aggressor_flow import symbols,load_hourly,return_map
from scripts.run_crypto_downside_semivariance import daily
from scripts.run_crypto_skewness_risk import diagnostic,targets,sim
from src.experiment import compute_deflated_sharpe

WINDOWS=(30,60,90);CAN=60;COST=10.;TOPN=50;MIN_XS=10
DEV0=date(2022,1,1);DEV1=date(2024,1,1);OOS0=date(2024,1,1);OOS1=date(2026,1,1)

def feature_frame(d,w):
    rows=[]
    for p in d.sort(["symbol","date"]).partition_by("symbol",maintain_order=True):
        sym=str(p["symbol"][0]); dates=p["date"].to_list(); rets=p["ret"].to_numpy(); qv=p["qv"].to_numpy()
        for i,dt in enumerate(dates):
            if dt.weekday()!=0 or i < max(w,30):
                continue
            hist=rets[i-w:i]
            if len(hist)!=w or not np.isfinite(hist).all():
                continue
            mu=float(np.mean(hist)); centered=hist-mu
            down=centered[centered<0]; up=centered[centered>=0]
            if len(down)<5 or len(up)<5:
                continue
            sd_down=float(np.std(down,ddof=1)); sd_up=float(np.std(up,ddof=1))
            if not np.isfinite(sd_down) or not np.isfinite(sd_up) or sd_down<=0 or sd_up<=0:
                continue
            liq=qv[i-30:i]
            if len(liq)!=30 or not np.isfinite(liq).all():
                continue
            rows.append({"date":dt,"symbol":sym,"signal":-math.log(sd_down/sd_up),"_liq":float(np.sum(liq))})
    x=pl.DataFrame(rows) if rows else pl.DataFrame(schema={"date":pl.Date,"symbol":pl.String,"signal":pl.Float64,"_liq":pl.Float64})
    out=[]
    for p in x.partition_by("date",maintain_order=True):
        p=p.sort("_liq",descending=True).head(TOPN)
        if p.height>=MIN_XS:out.append(p.select("date","symbol","signal"))
    return pl.concat(out,how="vertical").sort(["date","symbol"]) if out else pl.DataFrame(schema={"date":pl.Date,"symbol":pl.String,"signal":pl.Float64})

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",type=Path,required=True);a=ap.parse_args()
    sy=symbols(a.root);h=load_hourly(a.root,sy);d=daily(h);rm=return_map(h);fs={w:feature_frame(d,w) for w in WINDOWS}
    di={w:diagnostic(fs[w],rm,DEV0,DEV1) for w in WINDOWS}
    dev={w:sim(targets(fs[w],DEV0,DEV1),rm,DEV0,DEV1,COST) for w in WINDOWS}
    dm=dev[CAN]["metrics"];dc=di[CAN];spread=dc.get("low_minus_high_skew",0.0)
    gate=dc["mean_ic"]>.02 and dc["hac_p"]<.05 and spread>0 and dm["annualized_sharpe"]>.70 and dm["total_return"]>0 and sum(dev[w]["metrics"]["total_return"]>0 for w in WINDOWS)>=2
    out={"schema_version":1,"run_id":"20260928-crash-risk-duvol-weekly","strategy_family":"down_to_up_volatility_crash_risk","research_archetype":"cross_sectional_crash_risk_factor","universe_symbols":len(sy),"development_diagnostics":{str(w):di[w] for w in WINDOWS},"development":{str(w):dev[w] for w in WINDOWS},"development_gate_passed":gate,"oos_consumed":False,"trial_accounting":{"previous_parameter_trials":124,"new_parameter_trials":3,"cumulative_parameter_trials":127}}
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
    dsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp,n_obs_days=max(bm["n_weeks"]*7,1));gdsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp+[0.]*124,n_obs_days=max(bm["n_weeks"]*7,1))
    qual=bm["annualized_sharpe"]>1 and odi[CAN]["mean_ic"]>.02 and res[str(CAN)]["2"]["metrics"]["total_return"]>0 and stable and years and bm["max_drawdown"]>-.35 and ex["metrics"]["total_return"]>0 and (exs is None or exs["metrics"]["total_return"]>0)
    out.update(oos_consumed=True,oos_diagnostics={str(w):odi[w] for w in WINDOWS},oos_results=res,exclude_btc_eth=ex,strongest_asset=strong,exclude_strongest=exs,multiple_testing={"family_dsr":dsr,"global_127_trial_proxy":gdsr,"pbo":"N/A: three preregistered windows"},success_gate_candidate=qual,classification="EXPLORATORY_PASS" if qual else "REJECT")
    print(json.dumps(out,indent=2,default=str))
if __name__=="__main__":main()
