"""Read-only post-run audit of authorized 2025/2026 native ML4T artifacts."""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
import polars as pl

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"run_log/research_sessions/mechanicalpremia-authorized-2025-2026-ytd-v1/yearly_native"
CELLS=[("H1-SOURCE-3",1),("D1-SOURCE-4",1),
       ("EQUAL-RISK-7",1),("SOURCE-RISK-7",1),
       ("COST-STRESS",1.5),("COST-STRESS",2.0)]

def audit():
    result={"session":"mechanicalpremia-authorized-2025-2026-ytd-v1",
            "status":"INCOMPLETE", "years":{}, "cells":0, "errors":[],
            "fill_comparisons":{}}
    for year in (2025,2026):
        period={}
        low=datetime(year,1,1)
        high=datetime(2026,1,1) if year==2025 else datetime(2026,10,12)
        for trial,cost in CELLS:
            tag=f"{trial}:cost_{cost:g}x"
            path=BASE/f"year={year}"/trial/f"cost_{cost:g}x"
            summary=path/"summary.json"
            if not summary.exists():
                result["errors"].append(f"MISSING {year}:{tag}")
                continue
            s=json.loads(summary.read_text())
            fills=pl.read_parquet(path/"fills.parquet")
            trades=pl.read_parquet(path/"trades.parquet")
            daily=pl.read_parquet(path/"daily_equity.parquet")
            problems=[]
            if s["year"]!=year or s["trial"]!=trial: problems.append("cell identity")
            if not s["cash_plus_positions_reconciles"]:problems.append("native equity reconciliation")
            if s["native"]["num_rejected_orders"]:problems.append("native rejects")
            if s["native"]["num_fills"] != fills.height:problems.append("native fill ledger mismatch")
            if s["closed_trades"] != trades.filter(pl.col("status")=="closed").height:
                problems.append("native closed ledger mismatch")
            if fills.height and (fills["timestamp"].min()<low or fills["timestamp"].max()>=high):
                problems.append("fill outside period")
            if daily.height and (daily["day"].min().year != year or daily["day"].max().year >year):
                problems.append("daily equity outside year")
            if not all(str(x["last"])[:4] == str(year) for x in s["coverage"]):
                problems.append("source scored coverage outside period")
            if problems: result["errors"].append(f"{year}:{tag} "+",".join(problems))
            native=s["native"]
            piece={
                "ret_pct":(native["final_value"]/native["initial_cash"]-1)*100,
                "daily_sharpe":s["daily"].get("sharpe_ratio"),
                "daily_calmar":s["daily"].get("calmar_ratio"),
                "daily_maxdd_pct":100*s["daily"].get("max_drawdown"),
                "closed":s["closed_trades"],
                "win_rate":native.get("win_rate"),
                "open":s["open_trades"],
                "fills":fills.height,
                "native_rejected":native["num_rejected_orders"],
                "final_equity":native["final_value"],
                "last_scored_bar":max(x["last"] for x in s["coverage"]),
                "cash_reconciled":s["cash_plus_positions_reconciles"],
                "artifacts":str(path),
            }
            if trial in ("H1-SOURCE-3","D1-SOURCE-4"):
                closed=trades.filter(pl.col("status")=="closed")
                piece["by_instrument"]=(closed.group_by("symbol").agg(
                     pl.len().alias("closed"),pl.col("pnl").sum().alias("net"),
                     pl.col("gross_pnl").sum().alias("after_slippage_before_commission"),
                     pl.col("fees").sum().alias("commission"),
                     pl.col("total_slippage_cost").sum().alias("slippage"))
                     .sort("symbol").to_dicts())
            period[tag]=piece
            result["cells"]+=1
        result["years"][str(year)]=period
    result["status"]="VERIFIED_NATIVE_ARTIFACTS" if not result["errors"] and result["cells"]==12 else "INCOMPLETE_OR_FAILED"
    print(json.dumps(result,indent=2,default=str))

if __name__=="__main__":audit()
