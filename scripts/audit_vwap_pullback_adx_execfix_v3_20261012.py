#!/usr/bin/env python3
"""Independent immutable v3 execution replay audit, with OCO/cost checks.

Uses source bars and saved native engine ledgers, not an alternative simulator.
"""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import audit_vwap_pullback_adx_phase4_20261012 as existing

SID="vwap_pullback_adx_nq_20261012_proxy_v3_execfix"
RUN=ROOT/"run_log"/SID/"phase4_remediated"
PARENT=ROOT/"run_log/vwap_pullback_adx_nq_20261012_proxy_v2/phase4"


def inspect():
    existing.RUN=RUN
    base=existing.inspect()
    assert base["status"]=="PASS_MECHANICAL",base
    comparisons=[]
    for mode in ("B1","B2","B3"):
        for scenario in ("gross","cost","stress"):
            now=RUN/f"{mode}_{scenario}"
            before=PARENT/f"{mode}_{scenario}"
            a=json.loads((now/"metrics.json").read_text())
            b=json.loads((before/"metrics.json").read_text())
            signals_hash=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
            signal_same=signals_hash(now/"signals.json")==signals_hash(before/"signals.json")
            fills=pl.read_parquet(now/"fills.parquet")
            trades=pl.read_parquet(now/"trades.parquet")
            limits=fills.filter(pl.col("order_type")=="limit")
            wrong_limit=limits.filter(
                (pl.col("side")=="sell")&(pl.col("price")+1e-8<pl.col("limit_price"))
                |(pl.col("side")=="buy")&(pl.col("price")-1e-8>pl.col("limit_price"))
            ).height
            wrong_limit_slip=limits.filter(pl.col("slippage").abs()>1e-9).height
            stop_market=fills.filter(pl.col("order_type").is_in(["market","stop"]))
            slip_pts={"gross":0.0,"cost":.25,"stress":.5}[scenario]
            wrong_aggressive_slip=stop_market.filter((pl.col("slippage")-slip_pts).abs()>1e-8).height
            wrong_fees=fills.filter((pl.col("commission")-(0 if scenario=="gross" else 2.50)).abs()>1e-8).height
            parent_net=a["net_account_pnl_usd"]
            expected_delta=limits.height*slip_pts*20.0
            actual_delta=parent_net-b["net_account_pnl_usd"]
            matched_trades=trades.height==pl.read_parquet(before/"trades.parquet").height
            order_paths_equal=fills.select("timestamp","side","order_type").equals(
                pl.read_parquet(before/"fills.parquet").select("timestamp","side","order_type"))
            invalid=bool(
                wrong_limit or wrong_limit_slip or wrong_aggressive_slip or wrong_fees
                or not signal_same or not matched_trades or not order_paths_equal
                or abs(actual_delta-expected_delta)>1e-6
                or abs(a["reconciliation_difference_usd"])>1e-6
            )
            comparisons.append(dict(mode=mode,cost=scenario,
                matched_signals=signal_same,matched_fills_timing_and_type=order_paths_equal,
                matched_trade_count=matched_trades,trades=trades.height,
                limit_fill_count=limits.height,illegal_limit_fill_count=wrong_limit,
                limit_slippage_nonzero_count=wrong_limit_slip,
                wrong_aggressive_slippage_count=wrong_aggressive_slip,
                wrong_commission_count=wrong_fees,
                previous_net_pnl=b["net_account_pnl_usd"],
                remediated_net_pnl=parent_net,
                pnl_delta=actual_delta,
                expected_delta=expected_delta,
                passed=not invalid,
                summary={
                    "win_rate":a["win_rate"],
                    "expectancy_usd":a["expectancy_net_usd"],
                    "daily_sharpe":a["daily_equity_sharpe"],
                    "calmar":a["daily_equity_calmar"],
                    "max_drawdown_pct":a["daily_equity_max_dd_pct"],
                }
            ))
    base["comparisons"]=comparisons
    base["status"]="PASS_PROXY_NATIVE_EXECUTION_REPAIR" if all(x["passed"] for x in comparisons) else "FAILED_REMEDIATION"
    base["CME_execution_qualified"]=False
    base["remaining_nonsoftware_blockers"]=[
        "Provider-defined continuous NQ.F is not a dated CME NQ contract; no roll or contract mapping",
        "Source volume cannot be authenticated as CME traded contracts; session VWAP is a volume proxy",
        "No bid/ask tick/L2 feed for fill probability, adverse selection or impact",
        "Broker-specific CME exchange/clearing/commission schedule and actual fills not available",
        "OHLC touch does not guarantee a passive limit queue fill",
        "No independent chronological retrospective or prospective holdout run",
    ]
    # 10,000 session-resampled paired delta. Development *re-analysis* only.
    b2=pl.read_parquet(RUN/"B2_cost/daily_equity.parquet").sort("day")
    b3=pl.read_parquet(RUN/"B3_cost/daily_equity.parquet").sort("day")
    assert b2["day"].to_list()==b3["day"].to_list()
    da=np.diff(np.r_[1_000_000,b2["equity"].to_numpy()])
    db=np.diff(np.r_[1_000_000,b3["equity"].to_numpy()])
    delta=db-da
    rng=np.random.default_rng(20261012)
    boot=rng.choice(delta,size=(10000,len(delta)),replace=True).mean(axis=1)
    base["b3_minus_b2_base_daily_pnl"]={
        "paired_sessions":len(delta),
        "total_usd":round(float(delta.sum()),6),
        "mean_daily_usd":round(float(delta.mean()),6),
        "bootstrap_95pct_mean_daily_usd":list(map(float,np.quantile(boot,[.025,.975]))),
        "status":"INCONCLUSIVE; DEVELOPMENT ONLY"
    }
    return base


def main():
    report=inspect()
    target=RUN/"remediation_audit.json"
    if target.exists():
        raise FileExistsError("Do not overwrite immutable audit")
    target.write_text(json.dumps(report,indent=2,default=str)+"\n")
    print(json.dumps({"status":report["status"],
        "daily":report["b3_minus_b2_base_daily_pnl"],
        "comparison":[{k:v for k,v in x.items() if k in
            ("mode","cost","trades","limit_fill_count","illegal_limit_fill_count","pnl_delta","expected_delta","passed")}
            for x in report["comparisons"]]},indent=2))
    assert report["status"]=="PASS_PROXY_NATIVE_EXECUTION_REPAIR",report


if __name__=="__main__":
    main()
