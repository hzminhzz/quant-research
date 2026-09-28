#!/usr/bin/env python3
"""Pre-registered 30d cross-sectional reversal replication on Binance 1h perps."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Dict, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import polars as pl
from scipy import stats

from run_crypto_xs_momentum import (
    aggregate_daily,
    load_panel,
    load_previous_sharpes,
    metrics,
    row_map,
    wide,
)
from src.experiment import compute_deflated_sharpe


def run_variant(
    panel: pl.DataFrame,
    formation_hours: int,
    end_exclusive: str,
    oos_start: str,
    exclude: Iterable[str] = (),
    top_n_liquid: int = 15,
    min_history_hours: int = 1440,
    liquidity_lookback_hours: int = 720,
) -> dict:
    excluded=set(exclude)
    close_w=wide(panel,"close")
    open_w=wide(panel,"open")
    notional_w=wide(panel.with_columns((pl.col("close")*pl.col("volume")).alias("notional")),"notional")
    idx,symbols=row_map(close_w)
    symbols=[s for s in symbols if s not in excluded]
    ts_list=close_w["timestamp"].to_list()
    close_np={s:close_w[s].to_numpy() for s in symbols}
    open_np={s:open_w[s].to_numpy() for s in symbols}
    notional_np={s:notional_w[s].to_numpy() for s in symbols}
    first_valid={
        s: next((i for i,v in enumerate(close_np[s]) if np.isfinite(v)),len(ts_list))
        for s in symbols
    }

    end_dt=np.datetime64(end_exclusive.replace("Z",""))
    signal_indices=[
        (i,ts) for i,ts in enumerate(ts_list)
        if ts.day==1 and ts.hour==0 and ts.minute==0
        and i-formation_hours>=0 and i+1<len(ts_list)
        and np.datetime64(ts.replace(tzinfo=None))<end_dt
    ]

    hourly=[]
    monthly=[]
    prev_w={s:0.0 for s in symbols}
    asset_contrib:Dict[str,float]={s:0.0 for s in symbols}
    ic_values=[]
    reversal_spreads=[]
    eligible_counts=[]
    traded_counts=[]

    for k in range(len(signal_indices)-1):
        i,ts=signal_indices[k]
        j,next_ts=signal_indices[k+1]
        entry_i=i+1
        exit_i=j+1
        if exit_i>=len(ts_list):
            continue
        exit_ts=ts_list[exit_i]
        if np.datetime64(exit_ts.replace(tzinfo=None))>=end_dt:
            continue

        candidates=[]
        for s in symbols:
            if first_valid[s] > i-min_history_hours:
                continue
            c_now=close_np[s][i]
            c_then=close_np[s][i-formation_hours]
            o_entry=open_np[s][entry_i]
            o_exit=open_np[s][exit_i]
            if not all(np.isfinite(v) and v>0 for v in (c_now,c_then,o_entry,o_exit)):
                continue
            liq_slice=notional_np[s][i-liquidity_lookback_hours+1:i+1]
            if len(liq_slice)!=liquidity_lookback_hours or np.isfinite(liq_slice).sum()!=liquidity_lookback_hours:
                continue
            avg_notional=float(np.mean(liq_slice))
            trailing=float(c_now/c_then-1.0)
            fwd=float(o_exit/o_entry-1.0)
            candidates.append((s,avg_notional,trailing,fwd))

        candidates.sort(key=lambda x:x[1],reverse=True)
        candidates=candidates[:top_n_liquid]
        eligible_counts.append(len(candidates))
        if len(candidates)<8:
            continue

        trails=np.asarray([x[2] for x in candidates],dtype=float)
        fwd=np.asarray([x[3] for x in candidates],dtype=float)
        ic=stats.spearmanr(trails,fwd).statistic
        if np.isfinite(ic):
            ic_values.append(float(ic))

        ranked=sorted(candidates,key=lambda x:x[2])
        n_leg=max(1,int(math.ceil(len(ranked)*0.25)))
        losers=ranked[:n_leg]
        winners=ranked[-n_leg:]
        reversal_spreads.append(float(np.mean([x[3] for x in losers])-np.mean([x[3] for x in winners])))

        new_w={s:0.0 for s in symbols}
        for s,_,_,_ in losers:
            new_w[s]=0.5/n_leg
        for s,_,_,_ in winners:
            new_w[s]=-0.5/n_leg
        traded_counts.append(sum(1 for v in new_w.values() if v!=0.0))
        turnover=float(sum(abs(new_w[s]-prev_w.get(s,0.0)) for s in symbols))

        for h in range(entry_i,exit_i):
            gross=0.0
            for s,w in new_w.items():
                if w==0.0:
                    continue
                p0=open_np[s][h]
                p1=open_np[s][h+1] if h+1<len(ts_list) else np.nan
                if not (np.isfinite(p0) and np.isfinite(p1) and p0>0):
                    continue
                r=float(p1/p0-1.0)
                gross+=w*r
                asset_contrib[s]+=w*r
            hourly.append({
                "timestamp":ts_list[h],
                "gross_return":gross,
                "turnover_units":turnover if h==entry_i else 0.0,
            })

        monthly.append({
            "signal_timestamp":ts,
            "next_signal_timestamp":next_ts,
            "eligible":len(candidates),
            "n_leg":n_leg,
            "turnover_units":turnover,
            "rank_ic":float(ic) if np.isfinite(ic) else None,
            "reversal_spread":reversal_spreads[-1],
            "long_losers":[x[0] for x in losers],
            "short_winners":[x[0] for x in winners],
        })
        prev_w=new_w

    cost_results={}
    for mult in (1.0,2.0,3.0):
        daily=aggregate_daily(hourly,3.0*mult,np.datetime64(oos_start.replace("Z","")))
        cost_results[str(mult)]={
            "net":metrics(daily,"net_return"),
            "gross":metrics(daily,"gross_return"),
            "cost_drag_sum":float(sum(x["cost_drag"] for x in daily)),
            "by_year":{
                str(y):metrics([x for x in daily if x["date"].year==y],"net_return")
                for y in (2022,2023,2024,2025)
            },
        }

    return {
        "formation_hours":formation_hours,
        "excluded_symbols":sorted(excluded),
        "monthly_rebalances":len(monthly),
        "eligible_count_min":min(eligible_counts) if eligible_counts else 0,
        "eligible_count_median":float(np.median(eligible_counts)) if eligible_counts else 0.0,
        "traded_count_median":float(np.median(traded_counts)) if traded_counts else 0.0,
        "mean_rank_ic":float(np.mean(ic_values)) if ic_values else None,
        "ic_ir":float(np.mean(ic_values)/np.std(ic_values,ddof=1)) if len(ic_values)>1 and np.std(ic_values,ddof=1)>0 else None,
        "ic_negative_fraction":float(np.mean(np.asarray(ic_values)<0)) if ic_values else None,
        "mean_reversal_spread":float(np.mean(reversal_spreads)) if reversal_spreads else None,
        "costs":cost_results,
        "asset_contribution_gross":sorted(asset_contrib.items(),key=lambda kv:kv[1],reverse=True),
        "monthly_preview":monthly[:5],
    }


def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--data-root",type=Path,default=Path("/home/quant/dev/quant/ml4t-data/data/crypto/market/ohlcv_1h"))
    p.add_argument("--end-exclusive",default="2025-10-01T00:00:00Z")
    p.add_argument("--oos-start",default="2022-01-01T00:00:00Z")
    p.add_argument("--registry",type=Path,default=Path("run_log/crypto_research/registry.jsonl"))
    p.add_argument("--compact",action="store_true")
    args=p.parse_args()

    panel,integrity=load_panel(args.data_root,args.end_exclusive)
    formations=[504,720,1008]
    variants={str(h):run_variant(panel,h,args.end_exclusive,args.oos_start) for h in formations}
    canonical=variants["720"]
    strongest=canonical["asset_contribution_gross"][0][0] if canonical["asset_contribution_gross"] else None
    exclude_btc_eth=run_variant(panel,720,args.end_exclusive,args.oos_start,exclude={"BTCUSDT","ETHUSDT"})
    remove_strongest=run_variant(panel,720,args.end_exclusive,args.oos_start,exclude={strongest} if strongest else set())

    current=[
        variants[str(h)]["costs"]["1.0"]["net"]["annualized_sharpe"] for h in formations
    ]+[
        exclude_btc_eth["costs"]["1.0"]["net"]["annualized_sharpe"],
        remove_strongest["costs"]["1.0"]["net"]["annualized_sharpe"],
    ]
    previous=load_previous_sharpes(args.registry)
    all_sharpes=previous+current
    canonical_sr=canonical["costs"]["1.0"]["net"]["annualized_sharpe"]
    dsr=compute_deflated_sharpe(canonical_sr,all_sharpes,n_obs_days=canonical["costs"]["1.0"]["net"]["n_days"])

    payload={
        "schema_version":1,
        "run_id":"20260928-xs-reversal-30d",
        "strategy":"30-day cross-sectional reversal",
        "market":"Binance USDT-margined perpetual futures",
        "symbol_count":panel["symbol"].n_unique(),
        "symbols_loaded":sorted(panel["symbol"].unique().to_list()),
        "integrity":integrity,
        "oos_start":args.oos_start,
        "exploration_end_exclusive":args.end_exclusive,
        "canonical_formation_hours":720,
        "variants":variants,
        "robustness":{
            "exclude_btc_eth":exclude_btc_eth,
            "remove_strongest_asset":{"removed":strongest,"result":remove_strongest},
        },
        "multiple_testing":{
            "previous_strategy_sharpes":previous,
            "current_variant_sharpes":current,
            "cumulative_strategy_trials_used_for_dsr":len(all_sharpes),
            "dsr":dsr,
            "pbo":{"status":"N/A","reason":"Five pre-registered rule/robustness variants are insufficient for a meaningful CPCV winner-selection PBO estimate."},
        },
    }

    if args.compact:
        c=payload["variants"]["720"]
        out={
            "run_id":payload["run_id"],
            "symbol_count":payload["symbol_count"],
            "mean_rank_ic":c["mean_rank_ic"],
            "ic_ir":c["ic_ir"],
            "ic_negative_fraction":c["ic_negative_fraction"],
            "mean_reversal_spread":c["mean_reversal_spread"],
            "base":c["costs"]["1.0"]["net"],
            "two_x":c["costs"]["2.0"]["net"],
            "three_x":c["costs"]["3.0"]["net"],
            "by_year":{y:v["annualized_sharpe"] for y,v in c["costs"]["1.0"]["by_year"].items()},
            "h504_sharpe":payload["variants"]["504"]["costs"]["1.0"]["net"]["annualized_sharpe"],
            "h1008_sharpe":payload["variants"]["1008"]["costs"]["1.0"]["net"]["annualized_sharpe"],
            "exclude_btc_eth_sharpe":payload["robustness"]["exclude_btc_eth"]["costs"]["1.0"]["net"]["annualized_sharpe"],
            "remove_strongest_asset":payload["robustness"]["remove_strongest_asset"]["removed"],
            "remove_strongest_sharpe":payload["robustness"]["remove_strongest_asset"]["result"]["costs"]["1.0"]["net"]["annualized_sharpe"],
            "multiple_testing":payload["multiple_testing"],
        }
        print(json.dumps(out,indent=2,sort_keys=True,default=str))
    else:
        print(json.dumps(payload,indent=2,sort_keys=True,default=str))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
