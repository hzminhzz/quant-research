"""2017–2026YTD native ML4T C3 D1 pullback-threshold comparison.

Read-only audited native fills, trades, daily equity and summary from the
frozen ten-variant session. Three variants are N01, N02, N03. Baseline C3
is source-weighted H1 + D1, same annual periods and per-side costs.
No native trades/returns simulated here. Fails closed if missing trials.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from math import prod
from statistics import mean,median

from scripts.report_mechanicalpremia_c3_d1_naive_ten_20261014 import metrics
from scripts.mechanicalpremia_c3_d1_naive_ten_20261014 import ROOT

START,END=2017,2026
CANDIDATES=(
    ("C3-original","SOURCE-US2"),
    ("ATR+%B<0.35","N01-LV-PB35"),
    ("ATR+%B<0.50","N02-LV-PB50"),
    ("ATR+%B<0.80","N03-LV-PB80"),
)
NEW=ROOT/"run_log/research_sessions/mechanicalpremia-c3-d1-naive-ten-20261014-v1/yearly_native"
BASE=ROOT/"run_log/research_sessions/mechanicalpremia-us500-us100-2013-2026-v1/yearly_native"
OUT=ROOT/"docs/audit/mechanicalpremia_c3_d1_2017_2026_priority"
STRESS_YEARS=(2021,2024,2025,2026)
def cell(trial,year,cost=1.0):
    if trial=="SOURCE-US2":
        target=(BASE/f"year={year}"/("SOURCE-US2" if cost==1 else "COST-US2")/f"cost_{cost:g}x")
        tid="SOURCE-US2" if cost==1 else "COST-US2"
    else:
        target=NEW/f"year={year}"/trial/f"cost_{cost:g}x"
        tid=trial
    r=metrics(target,year,tid,cost)
    if r is not None:
        assert r["native_rejections"]==0
    return r

def run():
    matrix={}
    missing=[]
    rows=[]
    for label,trial in CANDIDATES:
        matrix[label]={}
        for year in range(START,END+1):
            v=cell(trial,year,1.)
            if v is None:
                missing.append((trial,year,"1x"))
            else:
                matrix[label][year]=v
                rows.append({"variant":label,**v})
        for year in STRESS_YEARS:
            v=cell(trial,year,2.)
            if v is None:
                missing.append((trial,year,"2x"))
            else:
                rows.append({"variant":label,**v})
    result={"status":"COMPLETE_NATIVE_AUDITED" if not missing else "RUNNING",
            "period":"2017-2025 full, 2026 Jan1-Oct11 YTD",
            "expected_variant_primary_cells":30,
            "expected_variant_cost_stress_cells":12,
            "native_rows_available":len(rows),
            "missing":missing,
            "baseline_id":"mechanicalpremia-us500-us100-2013-2026-v1",
            "variant_session":"mechanicalpremia-c3-d1-naive-ten-20261014-v1",
            "limitations":["Synthetic BID-only CFD price proxy; no certified broker spreads, rollover, contract multiplier",
                           "Separate annual equity resets; chained ROI is not a continuous-account result",
                           "All dates observed during prior strategy selection; no untouched OOS"]}
    OUT.mkdir(parents=True,exist_ok=True)
    if rows:
        with (OUT/"2017_2026_all_year_metrics.csv").open("w",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]))
            writer.writeheader();writer.writerows(rows)
    if missing:
        (OUT/"2017_2026_status.json").write_text(json.dumps(result,indent=2)+"\n")
        print(json.dumps({"status":result["status"],"available":len(rows),"missing":len(missing),
            "missing_prefix":missing[:12]},indent=2))
        return 24
    summaries={}
    for label,trial in CANDIDATES:
        years=[matrix[label][y] for y in range(START,END+1)]
        total_close=sum(r["d1_closed_trades"] for r in years)
        profits=sum(r["d1_gross_profit"] for r in years)
        losses=sum(r["d1_gross_loss"] for r in years)
        sum_wins=sum(r["d1_closed_trades"]*(r["d1_closed_win_rate_pct"] or 0)/100 for r in years)
        stress=[cell(trial,y,2.) for y in STRESS_YEARS]
        rsum={"closed_d1_trades":total_close,
              "entries_d1":sum(r["d1_entry_fills"] for r in years),
              "signals_d1":sum(r["d1_signal_events"] for r in years),
              "win_rate_d1_pct":100*sum_wins/total_close if total_close else None,
              "profit_factor_d1":profits/abs(losses) if losses<0 else None,
              "net_d1_closed_units":sum(r["d1_closed_net_pnl"] for r in years),
              "mean_annual_portfolio_return_pct":mean(r["net_return_pct"] for r in years),
              "median_annual_portfolio_return_pct":median(r["net_return_pct"] for r in years),
              "positive_years":sum(r["net_return_pct"]>0 for r in years),
              "mean_annual_daily_sharpe":mean(r["annual_daily_sharpe"] for r in years),
              "worst_annual_drawdown_pct":min(r["maxdd_pct"] for r in years),
              "hypothetical_linked_roi_pct":100*(prod(1+r["net_return_pct"]/100 for r in years)-1),
              "stress_years":list(STRESS_YEARS),
              "mean_return_stress_2x_pct":mean(r["net_return_pct"] for r in stress),
              "positive_stress_years":sum(r["net_return_pct"]>0 for r in stress),
              "standalone_warning":"All metrics for combined H1+D1 source weighted portfolio; only D1 closed-trade performance isolated."}
        summaries[label]=rsum
    baseline=matrix["C3-original"]
    for label in summaries:
        summaries[label]["paired_better_return_years_vs_baseline"]=sum(
          matrix[label][year]["net_return_pct"]>baseline[year]["net_return_pct"]
          for year in range(START,END+1))
        summaries[label]["paired_mean_annual_delta_pp"]=mean(
          matrix[label][year]["net_return_pct"]-baseline[year]["net_return_pct"]
          for year in range(START,END+1))
    result["summary"]=summaries
    result["years"]={label:{str(y):matrix[label][y] for y in range(START,END+1)} for label in matrix}
    (OUT/"2017_2026_comparison.json").write_text(json.dumps(result,indent=2)+"\n")
    names=[label for label,_ in CANDIDATES]
    lines=["# C3 D1 pullback relaxation: Native ML4T, 2017–2026 YTD",
           "", "**Status: VERIFIED 30/30 native annual variant cells and 12/12 2x cost stress cells (plus baseline).**",
           "**Rules:** US500/US100 H1 breakout unchanged; D1 low ATR + Bollinger percent-B cutoff only 0.35,0.50,0.80. Original D1 cutoff 0.20 is baseline. All other source rules/costs/nominal risk weights fixed.",
           "**Method:** One independent native ML4T Engine $100k synthetic account per year. Past warmup, next-minute fill. 2026 scored only through October 11.",
           "", "## Portfolio annual net returns, 1x modeled direct cost",
           "", "| Year | "+" | ".join(names)+" |","|---|"+ "|".join("---:" for _ in names)+"|"]
    for y in range(START,END+1):
        label=f"{y} YTD" if y==2026 else str(y)
        lines.append(f"| {label} | "+" | ".join(f"{matrix[n][y]['net_return_pct']:+.2f}%" for n in names)+" |")
    lines+=["","## Closed D1 trades per annual combined portfolio",
            "", "| Year | "+" | ".join(names)+" |","|---|"+ "|".join("---:" for _ in names)+"|"]
    for y in range(START,END+1):
        lines.append(f"| {y} | "+" | ".join(str(matrix[n][y]['d1_closed_trades']) for n in names)+" |")
    lines+=["","## Matched-year aggregate",
            "", "| Variant | D1 trades | D1 PF | D1 win % | Mean annual return | Mean annual Sharpe | Worst-year DD | Better-return years vs baseline | 2x mean return (4 stress years) |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for label in names:
        v=summaries[label]
        pf=f"{v['profit_factor_d1']:.2f}" if v["profit_factor_d1"] is not None else "Undefined (no losses)"
        wr=f"{v['win_rate_d1_pct']:.1f}%" if v["win_rate_d1_pct"] is not None else "n/a"
        lines.append(f"| {label} | {v['closed_d1_trades']} | {pf} | {wr} | {v['mean_annual_portfolio_return_pct']:+.2f}% | {v['mean_annual_daily_sharpe']:.2f} | {v['worst_annual_drawdown_pct']:.2f}% | {v['paired_better_return_years_vs_baseline']}/10 | {v['mean_return_stress_2x_pct']:+.2f}% |")
    lines+=["","## Interpretation limits","",
            "- 2017–2026 has already been examined in earlier studies; all results are exploratory, not fresh out-of-sample.",
            "- Win rate and profit factor above are for actual closed D1 positions inside the combined portfolio, not a standalone D1 with a different risk budget.",
            "- 2026 ends Oct11; no exposures are carried across separate year-end resets.",
            "- Expected costs: 1 bp commission and 2 bps slippage PER SIDE. True CFD ASK/broker spread, overnight financing and contract point value are not modeled.",
            "- H1 first-minute protective stop gap remains unresolved. No candidate is production approved.",
            "- A hypothetical product of annual returns is present in the JSON for illustration only; it is **not** a verified continuous multi-year backtest.",
            "- The original ten-rule trial ledger remains complete or pending independently; do not discard negative trials.",
            ""]
    (OUT/"2017_2026_comparison.md").write_text("\n".join(lines))
    print(json.dumps({"status":result["status"],"summary":summaries,
                      "report":str(OUT/"2017_2026_comparison.md")},indent=2))
    return 0
if __name__=="__main__":raise SystemExit(run())
