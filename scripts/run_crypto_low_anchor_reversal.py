#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from datetime import date
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import polars as pl

from scripts.run_crypto_nearness52 import load_daily,diagnostic,portfolio,sim,MIN_XS
from src.experiment import compute_deflated_sharpe

LOOKBACKS=(14,30,60)
CAN=30
COST=10.0
TOPN=50
DEV0=date(2022,1,1)
DEV1=date(2024,1,1)
OOS0=date(2024,1,1)
OOS1=date(2026,1,1)


def feature_frame(d,w):
    hist=max(w,30)
    x=(d.sort(["symbol","date"])
      .with_columns(
        pl.col("close").shift(1).over("symbol").alias("_c1"),
        pl.col("close").shift(1).rolling_min(w).over("symbol").alias("_lo"),
        pl.col("qv").shift(1).rolling_sum(30).over("symbol").alias("_liq"),
        pl.col("date").shift(hist).over("symbol").alias("_anchor"),
        pl.col("open").shift(-7).over("symbol").alias("_next_open"),
        pl.col("date").shift(-7).over("symbol").alias("_next_date"),
        pl.col("open").shift(-1).over("symbol").alias("_delay_entry"),
        pl.col("date").shift(-1).over("symbol").alias("_delay_entry_date"),
        pl.col("open").shift(-8).over("symbol").alias("_delay_exit"),
        pl.col("date").shift(-8).over("symbol").alias("_delay_exit_date"))
      .with_columns(
        (-(pl.col("_c1")/pl.col("_lo")-1.0)).alias("signal"),
        (pl.col("_next_open")/pl.col("open")-1.0).alias("fwd_ret"),
        (pl.col("_delay_exit")/pl.col("_delay_entry")-1.0).alias("delay_ret"))
      .filter(
        (pl.col("date").dt.weekday()==1)
        & pl.col("signal").is_finite() & pl.col("_liq").is_finite()
        & (pl.col("_anchor")==pl.col("date")-pl.duration(days=hist))
        & (pl.col("_next_date")==pl.col("date")+pl.duration(days=7))
        & (pl.col("_delay_entry_date")==pl.col("date")+pl.duration(days=1))
        & (pl.col("_delay_exit_date")==pl.col("date")+pl.duration(days=8))))
    out=[]
    for p in x.partition_by("date",maintain_order=True):
        p=p.sort("_liq",descending=True).head(TOPN)
        if p.height>=MIN_XS:
            out.append(p.select("date","symbol","signal","fwd_ret","delay_ret"))
    return pl.concat(out,how="vertical").sort(["date","symbol"]) if out else pl.DataFrame()


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",type=Path,required=True)
    a=ap.parse_args()
    d=load_daily(a.root)
    fs={w:feature_frame(d,w) for w in LOOKBACKS}
    di={w:diagnostic(fs[w],DEV0,DEV1) for w in LOOKBACKS}
    dev={w:sim(portfolio(fs[w],DEV0,DEV1),COST) for w in LOOKBACKS}
    cd=di[CAN]
    cm=dev[CAN]["metrics"]
    gate=(cd["mean_ic"]>.02 and cd["hac_p"]<.05 and cd["high_minus_low"]>0
          and cm["annualized_sharpe"]>.70 and cm["total_return"]>0
          and sum(dev[w]["metrics"]["total_return"]>0 for w in LOOKBACKS)>=2)
    out={
        "schema_version":1,
        "run_id":"20260928-low-anchor-reversal-weekly",
        "strategy_family":"formation_low_anchor_reversal",
        "research_archetype":"cross_sectional_behavioral_factor",
        "universe_symbols":int(d["symbol"].n_unique()),
        "development_diagnostics":{str(w):di[w] for w in LOOKBACKS},
        "development":{str(w):dev[w] for w in LOOKBACKS},
        "development_gate_passed":gate,
        "oos_consumed":False,
        "trial_accounting":{"previous_parameter_trials":148,"new_parameter_trials":3,"cumulative_parameter_trials":151},
    }
    if not gate:
        out.update(classification="REJECT",success_gate_candidate=False,
                   multiple_testing={"dsr_probability":None,"pbo":"N/A: development gate failed before OOS."},
                   conclusion="REJECT. Development gate failed; OOS not consumed.")
        print(json.dumps(out,indent=2,default=str))
        return

    res={}
    sharp=[]
    for w in LOOKBACKS:
        rows=portfolio(fs[w],OOS0,OOS1)
        res[str(w)]={str(m):sim(rows,COST*m) for m in (1,2,3)}
        sharp.append(res[str(w)]["1"]["metrics"]["annualized_sharpe"])
    base=res[str(CAN)]["1"]
    bm=base["metrics"]
    odi=diagnostic(fs[CAN],OOS0,OOS1)
    ex=sim(portfolio(fs[CAN],OOS0,OOS1,exclude={"BTCUSDT","ETHUSDT"}),COST)
    strong=max(base["asset_contribution"],key=lambda s:abs(base["asset_contribution"][s])) if base["asset_contribution"] else None
    exs=sim(portfolio(fs[CAN],OOS0,OOS1,exclude={strong} if strong else set()),COST) if strong else None
    delayed=sim(portfolio(fs[CAN],OOS0,OOS1,retcol="delay_ret"),COST)
    years=all(base["by_year"].get(str(y),{}).get("total_return",-1)>=0 for y in (2024,2025))
    stable=sum(res[str(w)]["1"]["metrics"]["total_return"]>0 for w in LOOKBACKS)>=2
    dsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp,n_obs_days=max(bm["n_weeks"]*7,1))
    gdsr=compute_deflated_sharpe(bm["annualized_sharpe"],sharp+[0.0]*148,n_obs_days=max(bm["n_weeks"]*7,1))
    qual=(bm["annualized_sharpe"]>1.0 and odi["mean_ic"]>.02
          and res[str(CAN)]["2"]["metrics"]["total_return"]>0 and stable and years
          and bm["max_drawdown"]>-.35 and ex["metrics"]["total_return"]>0
          and delayed["metrics"]["total_return"]>0
          and (exs is None or exs["metrics"]["total_return"]>0)
          and dsr["dsr_probability"]>=.95 and gdsr["dsr_probability"]>=.95)
    out.update(
        oos_consumed=True,
        oos_diagnostics=odi,
        oos_results=res,
        exclude_btc_eth=ex,
        strongest_asset=strong,
        exclude_strongest=exs,
        delay_one_day=delayed,
        multiple_testing={"family_dsr":dsr,"global_151_trial_proxy":gdsr,"pbo":"N/A: three preregistered lookbacks"},
        success_gate_candidate=qual,
        classification="EXPLORATORY_PASS" if qual else "REJECT",
        conclusion=("EXPLORATORY_PASS. Meets preregistered exploratory gate; sealed confirmation remains untouched."
                    if qual else "REJECT. OOS or robustness/multiple-testing gate failed."))
    print(json.dumps(out,indent=2,default=str))


if __name__=="__main__":
    main()
