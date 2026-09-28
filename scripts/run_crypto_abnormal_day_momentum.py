#!/usr/bin/env python3
# Pre-registered abnormal-day intraday momentum research.
from __future__ import annotations
import argparse, json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import polars as pl

from scripts.run_crypto_high_momentum import simulate, validate_panel
from src.experiment import compute_deflated_sharpe

KS=(1.5,2.0,2.5)
CANONICAL=2.0
HIST_DAYS=60
LIQ_WINDOW=720
LIQ_FRAC=.80
MIN_ELIGIBLE=5
COST=3.0
DEV0=datetime(2021,1,1,tzinfo=timezone.utc)
DEV1=datetime(2024,1,1,tzinfo=timezone.utc)
OOS0=datetime(2024,1,1,tzinfo=timezone.utc)
OOS1=datetime(2026,1,1,tzinfo=timezone.utc)

def enrich(df:pl.DataFrame)->pl.DataFrame:
    ordered=df.sort(["symbol","timestamp"]).with_columns(
        pl.col("timestamp").dt.date().alias("_date"),
        (pl.col("close")*pl.col("volume")).alias("_dv"),
    )
    daily=ordered.group_by(["symbol","_date"]).agg(
        pl.col("open").first().alias("_day_open"),
        pl.col("close").last().alias("_day_close"),
        pl.len().alias("_day_rows"),
    ).sort(["symbol","_date"]).with_columns(
        (pl.col("_day_close")/pl.col("_day_open")-1.0).alias("_day_ret")
    ).with_columns(
        pl.col("_day_ret").shift(1).rolling_mean(HIST_DAYS).over("symbol").alias("_mu"),
        pl.col("_day_ret").shift(1).rolling_std(HIST_DAYS).over("symbol").alias("_sd"),
        pl.col("_date").shift(HIST_DAYS).over("symbol").alias("_hist_date"),
    ).filter(
        pl.col("_mu").is_finite()&pl.col("_sd").is_finite()&(pl.col("_sd")>0)
        &(pl.col("_hist_date")==pl.col("_date")-pl.duration(days=HIST_DAYS))
    ).select("symbol","_date","_day_open","_mu","_sd")
    return ordered.join(daily,on=["symbol","_date"],how="left").with_columns(
        pl.col("_dv").shift(1).rolling_mean(LIQ_WINDOW).over("symbol").alias("_liq")
    ).with_columns(
        pl.col("_liq").rank(method="ordinal",descending=True).over("timestamp").alias("_liq_rank"),
        pl.col("_liq").is_finite().sum().over("timestamp").alias("_n_liq"),
        (pl.col("close")/pl.col("_day_open")-1.0).alias("_cumret"),
    )

def first_triggers(enriched:pl.DataFrame,k:float,start:datetime,end:datetime,exclude=None):
    ex=exclude or set()
    x=enriched.filter(
        (pl.col("timestamp")>=start)&(pl.col("timestamp")<end)
        &pl.col("_mu").is_finite()&pl.col("_sd").is_finite()
        &pl.col("_liq").is_finite()
        &(pl.col("_n_liq")>=MIN_ELIGIBLE)
        &(pl.col("_liq_rank")<=(pl.col("_n_liq").cast(pl.Float64)*LIQ_FRAC).ceil())
        &(~pl.col("symbol").is_in(sorted(ex)))
    ).with_columns(
        pl.when(pl.col("_cumret")>pl.col("_mu")+k*pl.col("_sd")).then(1.0)
        .when(pl.col("_cumret")<pl.col("_mu")-k*pl.col("_sd")).then(-1.0)
        .otherwise(0.0).alias("_dir")
    ).filter(pl.col("_dir")!=0)
    return x.group_by(["symbol","_date"]).agg(
        pl.col("timestamp").first().alias("_signal_ts"),
        pl.col("_dir").first().alias("_dir"),
    ).sort("_signal_ts")

def build_targets(enriched,start,end,k,exclude=None,extra_delay=0):
    triggers=first_triggers(enriched,k,start,end,exclude=exclude)
    events={}
    valid_triggers=0
    for r in triggers.iter_rows(named=True):
        signal_ts=r["_signal_ts"]
        entry=signal_ts+timedelta(hours=1+extra_delay)
        day_end=datetime.combine(signal_ts.date()+timedelta(days=1),datetime.min.time(),tzinfo=timezone.utc)
        if entry>=day_end or entry>=end:
            continue
        sym=str(r["symbol"]); direction=float(r["_dir"])
        events.setdefault(entry,[]).append(("add",sym,direction))
        events.setdefault(day_end,[]).append(("remove",sym,0.0))
        valid_triggers+=1
    active={}
    targets={}
    for ts in sorted(events):
        if ts<start or ts>end:
            continue
        for action,sym,direction in events[ts]:
            if action=="remove":
                active.pop(sym,None)
            else:
                active[sym]=direction
        if active:
            gross=float(len(active))
            targets[ts]={sym:direction/gross for sym,direction in active.items()}
        else:
            targets[ts]={}
    return targets,valid_triggers

def run_variant(prices,enriched,k,start,end,cost,exclude=None,delay=0):
    tg,n=build_targets(enriched,start,end,k,exclude=exclude,extra_delay=delay)
    result=simulate(prices,tg,cost,start,end)
    result["triggered_asset_days"]=n
    return result

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--data",type=Path,required=True); a=ap.parse_args()
    prices=pl.read_parquet(a.data).sort(["symbol","timestamp"])
    integrity=validate_panel(prices)
    dev_source=prices.filter(pl.col("timestamp")<DEV1)
    dev_enriched=enrich(dev_source)
    development={k:run_variant(dev_source,dev_enriched,k,DEV0,DEV1,COST) for k in KS}
    sh={k:float(development[k]["metrics"]["annualized_sharpe"]) for k in KS}
    rr={k:float(development[k]["metrics"]["total_return"]) for k in KS}
    events={k:int(development[k]["triggered_asset_days"]) for k in KS}
    gate=(
        sh[CANONICAL]>.70
        and rr[CANONICAL]>0
        and events[CANONICAL]>=100
        and sum(v>0 for v in rr.values())>=2
    )
    out={
        "schema_version":1,
        "run_id":"20260928-abnormal-day-momentum",
        "data_integrity":integrity,
        "development":{
            str(k):{
                "net_sharpe":sh[k],
                "total_return":rr[k],
                "max_drawdown":development[k]["metrics"]["max_drawdown"],
                "triggered_asset_days":events[k],
                "rebalances":development[k]["rebalances"],
            } for k in KS
        },
        "development_gate_passed":gate,
        "oos_consumed":False,
        "trial_accounting":{"previous_parameter_trials":39,"new_parameter_trials":3,"cumulative_parameter_trials":42},
    }
    if not gate:
        out["classification"]="REJECT"
        out["conclusion"]="Development abnormal-day momentum gate failed; OOS was not consumed."
        print(json.dumps(out,indent=2,default=str))
        return 0

    enriched=enrich(prices)
    res={}; sharpes=[]
    for k in KS:
        res[str(k)]={}
        for m in (1.0,2.0,3.0):
            res[str(k)][str(m)]=run_variant(prices,enriched,k,OOS0,OOS1,COST*m)
        sharpes.append(float(res[str(k)]["1.0"]["metrics"]["annualized_sharpe"]))
    can=res[str(CANONICAL)]["1.0"]
    contrib=can["asset_contribution"]
    strong=max(contrib,key=contrib.get) if contrib else None
    abl={
        "exclude_btc_eth":run_variant(prices,enriched,CANONICAL,OOS0,OOS1,COST,exclude={"BTCUSDT","ETHUSDT"}),
        "delay_one_extra_hour":run_variant(prices,enriched,CANONICAL,OOS0,OOS1,COST,delay=1),
    }
    if strong:
        abl["exclude_strongest"]={
            "asset":strong,
            "result":run_variant(prices,enriched,CANONICAL,OOS0,OOS1,COST,exclude={strong}),
        }
    dsr=compute_deflated_sharpe(
        float(can["metrics"]["annualized_sharpe"]),
        sharpes,
        n_obs_days=int(can["metrics"]["n_days"]),
    )
    b=can["metrics"]; two=res[str(CANONICAL)]["2.0"]["metrics"]
    stable=sum(res[str(k)]["1.0"]["metrics"]["total_return"]>0 for k in KS)>=2
    years=all(can["by_year"][str(y)]["total_return"]>=0 for y in (2024,2025))
    breadth=(
        abl["exclude_btc_eth"]["metrics"]["total_return"]>0
        and abl["delay_one_extra_hour"]["metrics"]["total_return"]>0
        and (not strong or abl["exclude_strongest"]["result"]["metrics"]["total_return"]>0)
    )
    qual=(
        b["annualized_sharpe"]>1
        and b["total_return"]>0
        and two["total_return"]>0
        and stable
        and years
        and breadth
        and dsr["dsr_probability"]>=.95
    )
    out.update({
        "oos_consumed":True,
        "oos_results":res,
        "ablations":abl,
        "multiple_testing":{
            "base_cost_sharpes":sharpes,
            "dsr":dsr,
            "pbo":"N/A: three preregistered k thresholds",
            "global_cumulative_parameter_trials":42,
        },
        "funding_treatment":"not modeled",
        "success_gate_candidate":qual,
        "classification":"EXPLORATORY_PASS" if qual else "REJECT",
    })
    print(json.dumps(out,indent=2,default=str))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
