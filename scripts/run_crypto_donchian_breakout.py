#!/usr/bin/env python3
# Pre-registered crypto trading-range breakout research runner.
from __future__ import annotations
import argparse, json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import polars as pl
from scripts.run_crypto_high_momentum import simulate, validate_panel
from src.experiment import compute_deflated_sharpe

CHANNELS=(168,336,720)
CANONICAL=336
VOL=720
LIQ=720
MIN_XS=8
COST=3.0
DEV0=datetime(2021,1,1,tzinfo=timezone.utc)
DEV1=datetime(2024,1,1,tzinfo=timezone.utc)
OOS0=datetime(2024,1,1,tzinfo=timezone.utc)
OOS1=datetime(2026,1,1,tzinfo=timezone.utc)

def frame(df:pl.DataFrame,ch:int)->pl.DataFrame:
    hist=max(VOL,ch+2)
    x=df.sort(["symbol","timestamp"]).with_columns(
        (pl.col("close")*pl.col("volume")).alias("_dv"),
        (pl.col("close")/pl.col("close").shift(1).over("symbol")).log().alias("_lr"),
    ).with_columns(
        pl.col("close").shift(1).over("symbol").alias("_pc"),
        pl.col("high").shift(2).rolling_max(ch).over("symbol").alias("_hi"),
        pl.col("low").shift(2).rolling_min(ch).over("symbol").alias("_lo"),
        pl.col("_lr").shift(1).rolling_std(VOL).over("symbol").alias("_vol"),
        pl.col("_dv").shift(1).rolling_mean(LIQ).over("symbol").alias("_liq"),
        pl.col("timestamp").shift(hist).over("symbol").alias("_anchor"),
    ).with_columns(
        pl.when(pl.col("_pc")>pl.col("_hi")).then(1.0)
        .when(pl.col("_pc")<pl.col("_lo")).then(-1.0)
        .otherwise(None).alias("_evt")
    ).with_columns(
        pl.col("_evt").forward_fill().over("symbol").fill_null(0.0).alias("_state")
    ).filter(
        pl.col("_vol").is_finite()&(pl.col("_vol")>0)&pl.col("_liq").is_finite()
        &(pl.col("_anchor")==pl.col("timestamp")-pl.duration(hours=hist))
    ).with_columns(
        pl.col("_liq").rank(method="ordinal",descending=True).over("timestamp").alias("_r"),
        pl.len().over("timestamp").alias("_n"),
    ).filter(pl.col("_r")<=(pl.col("_n")*0.8).ceil())
    return x.filter(pl.len().over("timestamp")>=MIN_XS).sort(["timestamp","symbol"])

def targets(f,start,end,exclude=None,delay=0):
    ex=exclude or set()
    z=f.filter(
        (pl.col("timestamp")>=start)&(pl.col("timestamp")<end)
        &(~pl.col("symbol").is_in(sorted(ex)))
    )
    out={}
    for p in z.partition_by("timestamp",maintain_order=True):
        ts=p["timestamp"][0]
        if int(ts.timestamp()//3600)%6 or p.height<MIN_XS:
            continue
        rows=list(p.iter_rows(named=True))
        w={}
        for sign,gross in ((1,0.7),(-1,0.3)):
            side=[r for r in rows if float(r["_state"])*sign>0]
            if not side:
                continue
            raw={str(r["symbol"]):1.0/float(r["_vol"]) for r in side}
            den=sum(raw.values())
            for sym,v in raw.items():
                w[sym]=sign*gross*v/den
        if w:
            out[ts+timedelta(hours=delay)]=w
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--data",type=Path,required=True)
    a=ap.parse_args()
    prices=pl.read_parquet(a.data).sort(["symbol","timestamp"])
    integrity=validate_panel(prices)

    dev=prices.filter(pl.col("timestamp")<DEV1)
    fs={c:frame(dev,c) for c in CHANNELS}
    dr={c:simulate(dev,targets(fs[c],DEV0,DEV1),COST,DEV0,DEV1) for c in CHANNELS}
    sh={c:float(dr[c]["metrics"]["annualized_sharpe"]) for c in CHANNELS}
    rr={c:float(dr[c]["metrics"]["total_return"]) for c in CHANNELS}
    gate=sh[CANONICAL]>0.7 and rr[CANONICAL]>0 and sum(v>0 for v in rr.values())>=2

    out={
        "schema_version":1,
        "run_id":"20260928-donchian-trend-breakout-6h",
        "data_integrity":integrity,
        "development":{
            str(c):{
                "net_sharpe":sh[c],
                "total_return":rr[c],
                "max_drawdown":dr[c]["metrics"]["max_drawdown"],
                "rebalances":dr[c]["rebalances"],
            } for c in CHANNELS
        },
        "development_gate_passed":gate,
        "oos_consumed":False,
        "trial_accounting":{
            "previous_parameter_trials":27,
            "new_parameter_trials":3,
            "cumulative_parameter_trials":30,
        },
    }
    if not gate:
        out["classification"]="REJECT"
        out["conclusion"]="Development Donchian breakout gate failed; OOS was not consumed."
        print(json.dumps(out,indent=2,default=str))
        return 0

    fs={c:frame(prices,c) for c in CHANNELS}
    res={}
    sharpes=[]
    for c in CHANNELS:
        res[str(c)]={}
        tg=targets(fs[c],OOS0,OOS1)
        for m in (1.0,2.0,3.0):
            res[str(c)][str(m)]=simulate(prices,tg,COST*m,OOS0,OOS1)
        sharpes.append(float(res[str(c)]["1.0"]["metrics"]["annualized_sharpe"]))

    can=res[str(CANONICAL)]["1.0"]
    contrib=can["asset_contribution"]
    strong=max(contrib,key=contrib.get) if contrib else None
    abl={
        "exclude_btc_eth":simulate(
            prices,targets(fs[CANONICAL],OOS0,OOS1,{"BTCUSDT","ETHUSDT"}),
            COST,OOS0,OOS1,
        ),
        "delay_one_hour":simulate(
            prices,targets(fs[CANONICAL],OOS0,OOS1,delay=1),
            COST,OOS0,OOS1,
        ),
    }
    if strong:
        abl["exclude_strongest"]={
            "asset":strong,
            "result":simulate(
                prices,targets(fs[CANONICAL],OOS0,OOS1,{strong}),
                COST,OOS0,OOS1,
            ),
        }

    dsr=compute_deflated_sharpe(
        float(can["metrics"]["annualized_sharpe"]),
        sharpes,
        n_obs_days=int(can["metrics"]["n_days"]),
    )
    b=can["metrics"]
    two=res[str(CANONICAL)]["2.0"]["metrics"]
    robust=(
        abl["exclude_btc_eth"]["metrics"]["total_return"]>0
        and abl["delay_one_hour"]["metrics"]["total_return"]>0
        and (
            not strong
            or abl["exclude_strongest"]["result"]["metrics"]["total_return"]>0
        )
    )
    years=all(can["by_year"][str(y)]["total_return"]>=0 for y in (2024,2025))
    stable=sum(
        res[str(c)]["1.0"]["metrics"]["total_return"]>0 for c in CHANNELS
    )>=2
    qual=(
        b["annualized_sharpe"]>1.0
        and b["total_return"]>0
        and two["total_return"]>0
        and stable
        and robust
        and years
        and dsr["dsr_probability"]>=0.95
    )
    out.update({
        "oos_consumed":True,
        "oos_results":res,
        "ablations":abl,
        "multiple_testing":{
            "base_cost_sharpes":sharpes,
            "dsr":dsr,
            "pbo":"N/A: three preregistered channel windows",
            "global_cumulative_parameter_trials":30,
        },
        "funding_treatment":"not modeled; separate sensitivity required before confirmation",
        "success_gate_candidate":qual,
        "classification":"EXPLORATORY_PASS" if qual else "REJECT",
    })
    print(json.dumps(out,indent=2,default=str))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
