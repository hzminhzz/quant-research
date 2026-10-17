"""Read-only scoreboard of 10 predeclared D1 simplifications vs frozen C3.

Uses actual native annual ML4T equity/trades/fills. Reports all 180 cells with
explicit missing status and no ranking of missing results. Never compounds
separate yearly accounts into a real USD portfolio.
"""
from __future__ import annotations
import csv
import json
import math
from datetime import datetime,timezone
from pathlib import Path
from statistics import mean,median

import polars as pl
from scripts.mechanicalpremia_c3_d1_naive_ten_20261014 import VARIANTS, ROOT

SID="mechanicalpremia-c3-d1-naive-ten-20261014-v1"
NEW=ROOT/"run_log/research_sessions"/SID/"yearly_native"
BASE=ROOT/"run_log/research_sessions/mechanicalpremia-us500-us100-2013-2026-v1/yearly_native"
OUT=ROOT/"docs/audit"/SID
COST_YEARS={2021,2024,2025,2026}
YEARS=range(2013,2027)
def metrics(path:Path,year:int,trial:str,cost:float,source=False)->dict|None:
    s=path/"summary.json"
    if not s.exists():return None
    d=json.loads(s.read_text())
    assert d["year"]==year and d["trial"]==trial and float(d["cost_multiplier"])==cost
    assert d.get("cash_plus_positions_reconciles") is True
    assert int(d["native"]["num_rejected_orders"])==0
    fills=pl.read_parquet(path/"fills.parquet")
    trades=pl.read_parquet(path/"trades.parquet")
    closed=trades.filter(pl.col("status")=="closed")
    daily=pl.read_parquet(path/"daily_equity.parquet")
    assert fills.height==d["native"]["num_fills"]
    assert closed.height==d["closed_trades"]
    assert not daily.is_empty()
    assert abs(float(daily["equity"][-1])-d["native"]["final_value"])<.11
    d1_closed=closed.filter(pl.col("symbol").str.ends_with("_D"))
    d1_fills=fills.filter(pl.col("asset").str.ends_with("_D") & (pl.col("side")=="buy"))
    pos=d1_closed.filter(pl.col("pnl")>0)["pnl"].sum()
    neg=d1_closed.filter(pl.col("pnl")<0)["pnl"].sum()
    return {
        "trial":trial,"year":year,"cost_mult":cost,
        "net_return_pct":100*(d["native"]["final_value"]/d["native"]["initial_cash"]-1),
        "annual_daily_sharpe":d["daily"].get("sharpe_ratio"),
        "annual_calmar":d["daily"].get("calmar_ratio"),
        "maxdd_pct":100*d["daily"].get("max_drawdown"),
        "d1_signal_events":sum(c.get("d1_signals",0) for c in d.get("coverage",[])),
        "d1_entry_fills":d1_fills.height,
        "d1_closed_trades":d1_closed.height,
        "d1_closed_win_rate_pct":100*(d1_closed.filter(pl.col("pnl")>0).height/d1_closed.height) if d1_closed.height else None,
        "d1_gross_profit":float(pos or 0),
        "d1_gross_loss":float(neg or 0),
        "d1_closed_net_pnl":float(d1_closed["pnl"].sum() or 0),
        "d1_profit_factor":float(pos/abs(neg)) if neg and neg<0 else None,
        "total_closed":closed.height,
        "native_rejections":int(d["native"]["num_rejected_orders"]),
        "year_end_open":int(d["open_trades"]),
        "relative_summary":str(s.relative_to(ROOT)),
    }
def main():
    rows=[]
    missing=[]
    for year in YEARS:
        p=BASE/f"year={year}"/"SOURCE-US2"/"cost_1x"
        rows.append(metrics(p,year,"SOURCE-US2",1.,True))
        if year in COST_YEARS:
            baseline_stress=BASE/f"year={year}"/"COST-US2"/"cost_2x"
            rows.append(metrics(baseline_stress,year,"COST-US2",2.,True))
        for variant in VARIANTS:
            for cost in ((1.,2.) if year in COST_YEARS else (1.,)):
                r=metrics(NEW/f"year={year}"/variant/f"cost_{cost:g}x",year,variant,cost)
                if r is None:missing.append(f"{year}:{variant}:{cost:g}")
                else:rows.append(r)
    assert rows[:1] and all(r is not None for r in rows)
    # Year-specific baseline before ranking prevents rare-year selection artifacts.
    baselines={r["year"]:r for r in rows if r["trial"]=="SOURCE-US2"}
    agg=[]
    for key in ("SOURCE-US2",*VARIANTS):
        data=sorted((r for r in rows if r["trial"]==key and r["cost_mult"]==1.),key=lambda r:r["year"])
        if not data:continue
        n=sum(x["d1_closed_trades"] for x in data)
        pfwin=sum(x["d1_gross_profit"] for x in data)
        pfloss=sum(x["d1_gross_loss"] for x in data)
        profits=[x["net_return_pct"] for x in data]
        complete=len(data)==14
        stress_key="COST-US2" if key=="SOURCE-US2" else key
        stress=[r for r in rows if r["trial"]==stress_key and r["cost_mult"]==2.]
        rec={
           "trial":key,"years_completed":len(data),"out_of_14":14,
           "d1_signals":sum(x["d1_signal_events"] for x in data),
           "d1_entry_fills":sum(x["d1_entry_fills"] for x in data),
           "d1_closed_trades":n,
           "d1_win_rate_pct":100*sum(x["d1_closed_trades"]*(x["d1_closed_win_rate_pct"] or 0)/100 for x in data)/n if n else None,
           "d1_closed_profit_factor":pfwin/abs(pfloss) if pfloss<0 else None,
           "d1_closed_net_pnl_units":sum(x["d1_closed_net_pnl"] for x in data),
           "mean_annual_net_return_pct":mean(profits),
           "positive_years":sum(x>0 for x in profits),
           "mean_annual_daily_sharpe":mean(x["annual_daily_sharpe"] for x in data if x["annual_daily_sharpe"] is not None),
           "worst_year_maxdd_pct":min(x["maxdd_pct"] for x in data),
           "baseline_d1_closed_matched_years":sum(baselines[x["year"]]["d1_closed_trades"] for x in data),
           "better_return_years_vs_baseline":sum(x["net_return_pct"]>baselines[x["year"]]["net_return_pct"] for x in data),
           "cost2x_years":len(stress),
           "cost2x_mean_return_pct":mean(x["net_return_pct"] for x in stress) if stress else None,
           "eligible_for_descriptive_ranking":complete,
        }
        agg.append(rec)
    complete_trials=[r for r in agg if r["eligible_for_descriptive_ranking"]]
    scores={"session":SID,"status":"ALL_180_VERIFIED" if not missing else "RUNNING",
      "native_candidate_cells_complete":len(rows)-18,"native_candidate_expected":180,
      "missing_count":len(missing),"missing_cells":missing,"baselines_completed":14,
      "selection_note":"All history observed; no fresh OOS or valid significance claim",
      "scientific_status":"NOT_APPROVED",
      "criteria":"Trade count increase >= 1.5x old matched baseline 58 AND >=8/14 positive years AND mean annual return >0 AND worst-year DD no worse than 1.5x baseline -7.83% AND stress/cost sensible; DESCRIPTIVE ONLY",
      "aggregate":agg}
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/"scoreboard.json").write_text(json.dumps(scores,indent=2)+"\n")
    if rows:
        with (OUT/"all_native_year_metrics.csv").open("w",newline="") as f:
            c=csv.DictWriter(f,fieldnames=rows[0].keys())
            c.writeheader();c.writerows(rows)
    lines=["# C3 daily entry simplification — ten variants (native ML4T)",
           "",f"**Status:** {scores['status']}; {scores['native_candidate_cells_complete']}/180 native annual/stress cells completed.",
           "**Decision:** Not approved, all years observed; no new OOS. C3 promoted baseline unchanged.",
           "**Model:** H1 and D1 exits, risk splits and next-bar fills fixed. The 10 trials change ONLY daily entry eligibility.",
           "**Accounting:** Annual $100k synthetic price-unit simulations reset independently, not a continuous account. Real CFD spreads, financing, lot mapping and D1 protective stop unqualified.",
           "",
           "| Variant | Complete years | D1 closed trades | D1 trade PF | Mean annual return | Mean Sharpe | Positive years | Worst-year DD |",
           "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in agg:
        pf=("-" if r["d1_closed_profit_factor"] is None else f"{r['d1_closed_profit_factor']:.2f}")
        lines.append(f"| {r['trial']} | {r['years_completed']}/14 | {r['d1_closed_trades']} | {pf} | {r['mean_annual_net_return_pct']:+.2f}% | {r['mean_annual_daily_sharpe']:.2f} | {r['positive_years']}/{r['years_completed']} | {r['worst_year_maxdd_pct']:.2f}% |")
    lines+=["","**Do not rank incomplete trials by these values.** See scoreboard.json for explicit missing cells, sample sizes and native per-year evidence.",
            "**Fees:** 1bp commission + 2bps slippage per side; 2x tests are preregistered in 2021/2024/2025/2026.",
            "**Baseline:** SOURCE-US2 combined portfolio; baseline D1 closed-trade subset extracted from native trades.parquet, NOT standalone D1-only where position sizes differ.",
            "**Interpretation:** If a relaxed rule produces more signals but unchanged native D1 entries, position occupancy or the unchanged exit rule is the bottleneck.",
            ""]
    (OUT/"scoreboard.md").write_text("\n".join(lines))
    print(json.dumps({"status":scores["status"],"candidate_cells":scores["native_candidate_cells_complete"],
       "expected":180,"variants_fully_completed":sum(r["eligible_for_descriptive_ranking"] for r in agg if r["trial"]!="SOURCE-US2"),
       "recent_2025":[{k:r[k] for k in ("trial","d1_closed_trades","mean_annual_net_return_pct")} for r in agg if r["years_completed"]==1 and r["trial"]!="SOURCE-US2"]},indent=2))
if __name__=="__main__":main()
