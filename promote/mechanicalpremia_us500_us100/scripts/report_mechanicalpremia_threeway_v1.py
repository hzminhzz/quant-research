"""Compare all frozen Mechanical Premia candidates from native Engine artifacts.

Reporting only: never simulates fills or constructs positions. Rejects incomplete
matrices. Native yearly account resets are NOT a continuous compounded strategy.
"""
from __future__ import annotations
import csv
import json
import math
from pathlib import Path
from statistics import mean, median

import polars as pl
import numpy as np
from ml4t.diagnostic.api import PortfolioAnalysis

ROOT = Path(__file__).resolve().parents[1]
C1_A = ROOT / "run_log/research_sessions/mechanicalpremia-original-four-2013-2024-v1/yearly_native"
C1_B = ROOT / "run_log/research_sessions/mechanicalpremia-authorized-2025-2026-ytd-v1/yearly_native"
C2 = ROOT / "run_log/research_sessions/mechanicalpremia-nikkei-replaces-dax-2013-2026-v1/yearly_native"
C3 = ROOT / "run_log/research_sessions/mechanicalpremia-us500-us100-2013-2026-v1/yearly_native"
OUT = ROOT / "docs/audit/mechanicalpremia_three_candidates_2013_2026"
TRIALS = {
    "C1_DE30": {"base": [(2013,2024,C1_A),(2025,2026,C1_B)], "prefix":{"h1":"H1-SOURCE-3","d1":"D1-SOURCE-4","equal":"EQUAL-RISK-7","source":"SOURCE-RISK-7","cost":"COST-STRESS"}},
    "C2_JP225": {"base":[(2013,2026,C2)], "prefix":{"h1":"H1-JP225-3","d1":"D1-JP225-4","equal":"EQUAL-JP225-7","source":"SOURCE-JP225-7","cost":"COST-JP225"}},
    "C3_US_ONLY":{"base":[(2013,2026,C3)], "prefix":{"h1":"H1-US2","d1":"D1-US2","equal":"EQUAL-US2","source":"SOURCE-US2","cost":"COST-US2"}},
}
def read_cell(candidate:str,year:int,sleeve:str,cost:float=1.0)->dict|None:
    spec=TRIALS[candidate]
    basedir=next(base for lo,hi,base in spec["base"] if lo<=year<=hi)
    trial=spec["prefix"][sleeve]
    path=basedir/f"year={year}"/trial/f"cost_{cost:g}x"
    summary=path/"summary.json"
    if not summary.exists():
        return None
    d=json.loads(summary.read_text())
    if d.get("year")!=year or d.get("trial")!=trial or float(d.get("cost_multiplier",-1))!=cost:
        raise ValueError(f"Trial identity mismatch: {summary}")
    n=d["native"]
    if not d["cash_plus_positions_reconciles"]:
        raise ValueError(f"Native cash and position equity failed {summary}")
    fills=pl.scan_parquet(path/"fills.parquet").select(pl.len()).collect().item()
    trades=pl.scan_parquet(path/"trades.parquet").filter(pl.col("status")=="closed").select(pl.len()).collect().item()
    if fills!=n["num_fills"] or trades!=d["closed_trades"]:
        raise ValueError(f"Fill/trade count mismatch: {summary}")
    if n["num_rejected_orders"]!=0:raise ValueError(f"Rejected native order {summary}")
    daily=pl.read_parquet(path/"daily_equity.parquet")
    if daily.is_empty():raise ValueError(f"Missing daily equity {summary}")
    if not math.isclose(float(daily["equity"][-1]),float(n["final_value"]),abs_tol=0.1):
        raise ValueError(f"Daily equity does not end at native final value {summary}")
    # Local New York date of Jan 1 UTC can be Dec 31 of previous year.
    # Yearly native fills remain restricted to UTC scoring boundaries.
    if max(daily["day"]).year>year or min(daily["day"]).year<year-1:
        raise ValueError(f"Out of period daily equity {summary}")
    return {
        "year":year,"candidate":candidate,"sleeve":sleeve,"cost_mult":cost,
        "return_pct":100*(n["final_value"]/n["initial_cash"]-1),
        "daily_sharpe":d["daily"].get("sharpe_ratio"),
        "calmar":d["daily"].get("calmar_ratio"),
        "maxdd_pct":100*d["daily"].get("max_drawdown"),
        "closed_trades":int(d["closed_trades"]),
        "open_trades":int(d["open_trades"]),
        "closed_wins":float(n["win_rate"])*int(d["closed_trades"]) if n["win_rate"] is not None else 0,
        "native_fills":int(n["num_fills"]), "native_rejections":int(n["num_rejected_orders"]),
        "cash_reconciles":bool(d["cash_plus_positions_reconciles"]),
        "native_end_equity":float(n["final_value"]),
        "artifact":str(summary.relative_to(ROOT)),
    }

def main():
    statuses=[]
    expected=[(c,y,leg,cost) for c in TRIALS for y in range(2013,2027)
              for leg,cost in [("h1",1.0),("d1",1.0),("equal",1.0),("source",1.0),
                               ("cost",1.5),("cost",2.0)]]
    for c,y,leg,cost in expected:
        r=read_cell(c,y,leg,cost)
        if r is not None: statuses.append(r)
    missing=sorted(set(expected)-set((r["candidate"],r["year"],r["sleeve"],r["cost_mult"]) for r in statuses))
    if missing:
        print(json.dumps({"status":"RUNNING_OR_INCOMPLETE","completed":len(statuses),
                          "expected":len(expected),"missing":missing[:22],"missing_count":len(missing)},indent=2))
        return 24
    OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/"all_annual_metrics.csv").open("w",newline="",encoding="utf-8") as f:
        wr=csv.DictWriter(f,fieldnames=list(statuses[0]));wr.writeheader();wr.writerows(statuses)
    summary={}
    for candidate in TRIALS:
        sub=[r for r in statuses if r["candidate"]==candidate]
        rec={}
        for leg,cost in [("h1",1.),("d1",1.),("equal",1.),("source",1.),("cost",1.5),("cost",2.)]:
            rows=sorted((r for r in sub if r["sleeve"]==leg and r["cost_mult"]==cost),key=lambda x:x["year"])
            if len(rows)!=14: raise ValueError("Missing yearly metric")
            rec[f"{leg}_{cost:g}"]={
                "mean_annual_return_pct":mean(x["return_pct"] for x in rows),
                "median_annual_return_pct":median(x["return_pct"] for x in rows),
                "positive_years":sum(x["return_pct"]>0 for x in rows),
                "mean_annual_daily_sharpe":mean(x["daily_sharpe"] for x in rows if x["daily_sharpe"] is not None),
                "mean_annual_calmar":mean(x["calmar"] for x in rows if x["calmar"] is not None),
                "worst_single_year_drawdown_pct":min(x["maxdd_pct"] for x in rows),
                "closed_trades":sum(x["closed_trades"] for x in rows),
                "open_trade_occurrences":sum(x["open_trades"] for x in rows),
                "closed_trade_win_rate_pct":100*sum(x["closed_wins"] for x in rows)/sum(x["closed_trades"] for x in rows) if sum(x["closed_trades"] for x in rows) else None,
                "2026_ytd_return_pct":rows[-1]["return_pct"],
                "2025_return_pct":rows[-2]["return_pct"],
            }
        summary[candidate]=rec
    paired={}
    for challenger in ("C2_JP225","C3_US_ONLY"):
        base={r["year"]:r for r in statuses if r["candidate"]=="C1_DE30" and r["sleeve"]=="source" and r["cost_mult"]==1}
        test={r["year"]:r for r in statuses if r["candidate"]==challenger and r["sleeve"]=="source" and r["cost_mult"]==1}
        # Pre-2026 full-year paired bootstrap of mean annual return differences.
        # Does not cure prior selection bias; 2026 YTD is excluded from CI.
        full_year_deltas=np.asarray([test[y]["return_pct"]-base[y]["return_pct"]
                                    for y in range(2013,2026)],dtype=float)
        rng=np.random.default_rng(20261014)
        draws=rng.choice(full_year_deltas,size=(10000,len(full_year_deltas)),replace=True).mean(axis=1)
        paired[challenger]={
            "years_positive_delta":sum(test[y]["return_pct"]>base[y]["return_pct"] for y in base),
            "mean_annual_delta_pp":mean(test[y]["return_pct"]-base[y]["return_pct"] for y in base),
            "mean_delta_2013_2025_pp":float(full_year_deltas.mean()),
            "bootstrap95_ci_full_year_mean_delta_pp":list(map(float,np.quantile(draws,[.025,.975]))),
            "years_better_sharpe":sum(test[y]["daily_sharpe"]>base[y]["daily_sharpe"] for y in base),
            "years_better_mdd":sum(test[y]["maxdd_pct"]>base[y]["maxdd_pct"] for y in base),
        }
    payload={"status":"ALL_NATIVE_ANNUAL_CELLS_VERIFIED","completed":len(statuses),
             "expected":len(expected),"years":"2013-2025 full; 2026 through Oct11",
             "annual_reset_warning":"Not 14-year continuous equity. Cannot infer continuous CAGR/Sharpe/Calmar.",
             "currency_warning":"Mixed JPY/EUR/USD synthetic price units and non-certified CFD contract multipliers. Not real USD PnL.",
             "selection_warning":"C2/C3 selected after historical C1 and 2025/2026 observations; not OOS",
             "comparative_summary":summary,"paired_delta_vs_c1":paired}
    (OUT/"summary.json").write_text(json.dumps(payload,indent=2)+"\n")
    md=["# Mechanical Premia three-candidate comparison | 2013-2026 YTD",
        "",
        "**Evidence:** 252/252 native annual cells independently reconciled, no order rejections. Annual separate resets, not continuous equity.",
        "**Qualification:** synthetic price-unit only; cannot call real PnL without broker point value, currency conversion, ASK spread and overnight financing.",
        "**Selection:** all dates are observed exploratory data, not pristine OOS.",
        "",
        "## Source-weighted H1 + D1 annual net returns (1x assumed costs)",
        "",
        "| Year | C1 DE30 + EU50 | C2 JP225 + EU50 | C3 US500/US100 |",
        "|---|---:|---:|---:|"]
    index={(r["year"],r["candidate"]):r for r in statuses if r["sleeve"]=="source" and r["cost_mult"]==1}
    for year in range(2013,2027):
        label=f"{year} YTD" if year==2026 else str(year)
        a=[index[(year,c)]["return_pct"] for c in TRIALS]
        md.append(f"| {label} | "+ " | ".join(f"{x:+.2f}%" for x in a)+" |")
    md += ["","## Aggregate of independent annual native runs (NOT continuous CAGR)",
           "","| Candidate | Mean annual return | Positive years | Closed trades | Win rate | Mean yearly Sharpe | Worst year DD | 2x mean annual return |",
           "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for c in TRIALS:
        b=summary[c]["source_1"];stress=summary[c]["cost_2"]
        md.append(f"| {c} | {b['mean_annual_return_pct']:+.2f}% | {b['positive_years']}/14 | {b['closed_trades']} | {b['closed_trade_win_rate_pct']:.1f}% | {b['mean_annual_daily_sharpe']:.2f} | {b['worst_single_year_drawdown_pct']:.2f}% | {stress['mean_annual_return_pct']:+.2f}% |")
    md+=["","## Paired-year diagnostics vs C1",
          "","| Challenger | Return better (years) | Mean return delta (pp) | Sharpe better (years) | Drawdown better (years) |",
          "|---|---:|---:|---:|---:|"]
    for c,p in paired.items():
        md.append(f"| {c} | {p['years_positive_delta']}/14 | {p['mean_annual_delta_pp']:+.2f} | {p['years_better_sharpe']}/14 | {p['years_better_mdd']}/14 |")
    md+=["","## Limitations", "- All three variants are exploratory selected/observed data.",
          "- 2026 ends October 11; partial year.",
          "- Broker ASK and spread, overnight CFD financing, lot/multiplier and FX conversion missing.",
          "- H1 initial protective stop submitted after entry-minute callback; not source MT5 stop parity.",
          "- Year-end open trades are marked, not carried into subsequent separate annual runs.",
          "- For each year/candidate/sleeve and cost, consult all_annual_metrics.csv and source native fill/trade/equity Parquet.",
          "- Annual reset Sharpe/Calmar means are descriptive and not global 2013-2026 risk metrics.",
          ""]
    (OUT/"report.md").write_text("\n".join(md))
    print(json.dumps({"status":payload["status"],"report":str(OUT/"report.md"),
       "source_summary":{k:summary[k]["source_1"] for k in TRIALS},
       "paired":paired},indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
