#!/usr/bin/env python3
"""Pre-registered Binance perpetual premium-index factor research."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import polars as pl
from scipy import stats

from scripts.run_crypto_high_momentum import hac_mean_test, simulate
from src.experiment import compute_deflated_sharpe

DEV_START = datetime(2021,1,1,tzinfo=timezone.utc)
DEV_END = datetime(2024,1,1,tzinfo=timezone.utc)
OOS_START = datetime(2024,1,1,tzinfo=timezone.utc)
OOS_END = datetime(2026,1,1,tzinfo=timezone.utc)
LOOKBACK_DAYS = (3,5,7)
BASE_COST_BPS = 3.0
MIN_HISTORY_HOURS = 720
MIN_CROSS_SECTION = 8
LIQUID_FRACTION = 0.80


def make_factor_frame(prices: pl.DataFrame, premium: pl.DataFrame, lookback_days: int) -> pl.DataFrame:
    p = premium.with_columns(pl.col("timestamp").dt.cast_time_unit("ms")).sort(["symbol","timestamp"]).with_columns(
        pl.col("premium_index_close").shift(1).rolling_mean(window_size=lookback_days*3).over("symbol").alias("signal"),
        pl.col("timestamp").shift(lookback_days*3).over("symbol").alias("premium_anchor"),
    ).filter(
        (pl.col("timestamp").dt.hour() == 0)
        & pl.col("signal").is_finite()
        & (pl.col("premium_anchor") == pl.col("timestamp") - pl.duration(days=lookback_days))
    ).select("timestamp","symbol","signal")

    px = prices.sort(["symbol","timestamp"]).with_columns(
        (pl.col("close")*pl.col("volume")).alias("_dvol")
    ).with_columns(
        pl.col("_dvol").shift(1).rolling_mean(window_size=MIN_HISTORY_HOURS).over("symbol").alias("trailing_dvol"),
        pl.col("timestamp").shift(MIN_HISTORY_HOURS).over("symbol").alias("history_anchor"),
        pl.col("timestamp").shift(-1).over("symbol").alias("exec_ts"),
        pl.col("open").shift(-1).over("symbol").alias("exec_open"),
        pl.col("timestamp").shift(-25).over("symbol").alias("next_exec_ts"),
        pl.col("open").shift(-25).over("symbol").alias("next_exec_open"),
    ).filter(
        (pl.col("timestamp").dt.hour()==0)
        & (pl.col("history_anchor") == pl.col("timestamp") - pl.duration(hours=MIN_HISTORY_HOURS))
        & (pl.col("exec_ts") == pl.col("timestamp") + pl.duration(hours=1))
        & (pl.col("next_exec_ts") == pl.col("timestamp") + pl.duration(hours=25))
    ).select("timestamp","symbol","trailing_dvol","exec_open","next_exec_open")

    frame = p.join(px,on=["timestamp","symbol"],how="inner").with_columns(
        (pl.col("next_exec_open")/pl.col("exec_open")-1.0).alias("forward_day_return")
    ).with_columns(
        pl.col("trailing_dvol").rank(method="ordinal",descending=True).over("timestamp").alias("liq_rank"),
        pl.len().over("timestamp").alias("n_preliq"),
    ).filter(
        pl.col("liq_rank") <= (pl.col("n_preliq").cast(pl.Float64)*LIQUID_FRACTION).ceil()
    )
    return frame.filter(pl.len().over("timestamp") >= MIN_CROSS_SECTION).sort(["timestamp","symbol"])


def diagnostic(frame: pl.DataFrame) -> dict:
    dev = frame.filter((pl.col("timestamp")>=DEV_START)&(pl.col("timestamp")<DEV_END))
    ics=[]; spreads=[]; counts=[]
    for part in dev.partition_by("timestamp",maintain_order=True):
        if part.height < MIN_CROSS_SECTION:
            continue
        s=part["signal"].to_numpy(); r=part["forward_day_return"].to_numpy()
        ic=stats.spearmanr(s,r).statistic
        if np.isfinite(ic):
            ics.append(float(ic)); counts.append(part.height)
        order=np.argsort(s); k=max(1,math.ceil(part.height/3))
        spreads.append(float(np.mean(r[order[-k:]])-np.mean(r[order[:k]])))
    arr=np.asarray(ics,dtype=float)
    t,p=hac_mean_test(arr,max_lag=7)
    return {"n_days":len(ics),"mean_ic":float(np.mean(arr)) if len(arr) else math.nan,"ic_ir":float(np.mean(arr)/np.std(arr,ddof=1)) if len(arr)>1 and np.std(arr,ddof=1)>0 else 0.0,"hac_t":t,"hac_p":p,"high_minus_low":float(np.mean(spreads)) if spreads else math.nan,"mean_assets":float(np.mean(counts)) if counts else 0.0}


def build_targets(frame: pl.DataFrame, start: datetime, end: datetime, exclude: set[str] | None=None, extra_delay_hours: int=0) -> dict[datetime,dict[str,float]]:
    selected=frame.filter((pl.col("timestamp")>=start)&(pl.col("timestamp")<end)&(~pl.col("symbol").is_in(sorted(exclude or set()))))
    targets={}
    for part in selected.partition_by("timestamp",maintain_order=True):
        if part.height < MIN_CROSS_SECTION:
            continue
        rows=sorted([(r["symbol"],float(r["signal"])) for r in part.iter_rows(named=True)],key=lambda z:z[1])
        k=max(1,math.ceil(len(rows)/3))
        w={}
        for sym,_ in rows[-k:]: w[sym]=0.5/k
        for sym,_ in rows[:k]: w[sym]=-0.5/k
        targets[part["timestamp"][0]+timedelta(hours=1+extra_delay_hours)]=w
    return targets


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--prices",type=Path,required=True)
    ap.add_argument("--premium",type=Path,required=True)
    args=ap.parse_args()
    prices=pl.read_parquet(args.prices).sort(["symbol","timestamp"])
    premium=pl.read_parquet(args.premium).sort(["symbol","timestamp"])

    dev_premium=premium.filter(pl.col("timestamp") < datetime(2024,1,3,tzinfo=timezone.utc))
    dev_prices=prices.filter(pl.col("timestamp") < datetime(2024,1,3,tzinfo=timezone.utc))
    dev_frames={d:make_factor_frame(dev_prices,dev_premium,d) for d in LOOKBACK_DAYS}
    diagnostics={d:diagnostic(dev_frames[d]) for d in LOOKBACK_DAYS}
    canonical=diagnostics[5]
    gate=(canonical["n_days"]>=700 and canonical["mean_ic"]>=0.02 and canonical["hac_p"]<0.05 and canonical["high_minus_low"]>0)
    payload={
        "schema_version":1,
        "run_id":"20260928-perp-premium-basis",
        "diagnostics":{str(d):diagnostics[d] for d in LOOKBACK_DAYS},
        "development_gate_passed":gate,
        "oos_consumed":False,
        "trial_accounting":{"previous_parameter_trials":6,"new_parameter_trials":3,"cumulative_parameter_trials":9},
    }
    if not gate:
        payload["classification"]="REJECT"
        payload["conclusion"]="Development basis-proxy diagnostic failed; primary OOS was not consumed."
        print(json.dumps(payload,indent=2,default=str)); return 0

    frames={d:make_factor_frame(prices,premium,d) for d in LOOKBACK_DAYS}
    results={}; base_sharpes=[]
    for d in LOOKBACK_DAYS:
        targets=build_targets(frames[d],OOS_START,OOS_END)
        results[str(d)]={}
        for mult in (1.0,2.0,3.0):
            results[str(d)][str(mult)]=simulate(prices,targets,BASE_COST_BPS*mult,OOS_START,OOS_END)
        base_sharpes.append(float(results[str(d)]["1.0"]["metrics"]["annualized_sharpe"]))
    canon=results["5"]["1.0"]
    contrib=canon["asset_contribution"]
    strongest=max(contrib,key=contrib.get) if contrib else None
    ablations={
        "exclude_btc_eth":simulate(prices,build_targets(frames[5],OOS_START,OOS_END,exclude={"BTCUSDT","ETHUSDT"}),BASE_COST_BPS,OOS_START,OOS_END),
        "extra_one_hour_delay":simulate(prices,build_targets(frames[5],OOS_START,OOS_END,extra_delay_hours=1),BASE_COST_BPS,OOS_START,OOS_END),
    }
    if strongest:
        ablations["exclude_strongest"]={"asset":strongest,"result":simulate(prices,build_targets(frames[5],OOS_START,OOS_END,exclude={strongest}),BASE_COST_BPS,OOS_START,OOS_END)}
    dsr=compute_deflated_sharpe(float(canon["metrics"]["annualized_sharpe"]),base_sharpes,n_obs_days=int(canon["metrics"]["n_days"]))
    base=canon["metrics"]; two=results["5"]["2.0"]["metrics"]
    neighbors=sum(results[str(d)]["1.0"]["metrics"]["total_return"]>0 for d in LOOKBACK_DAYS)
    breadth=(ablations["exclude_btc_eth"]["metrics"]["total_return"]>0 and ablations["extra_one_hour_delay"]["metrics"]["total_return"]>0 and (not strongest or ablations["exclude_strongest"]["result"]["metrics"]["total_return"]>0))
    qualifies=(base["annualized_sharpe"]>1.0 and base["total_return"]>0 and two["total_return"]>0 and neighbors>=2 and breadth)
    payload.update({"oos_consumed":True,"oos_results":results,"ablations":ablations,"multiple_testing":{"base_cost_sharpes":base_sharpes,"dsr":dsr,"pbo":"N/A: three preregistered lookbacks"},"success_gate_candidate":qualifies,"classification":"EXPLORATORY_PASS" if qualifies else "REJECT"})
    print(json.dumps(payload,indent=2,default=str)); return 0


if __name__=="__main__":
    raise SystemExit(main())
