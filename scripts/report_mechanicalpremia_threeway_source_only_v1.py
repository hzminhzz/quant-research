"""Source-weighted 14-year tri-candidate annual report before ancillary cells.

Reads ONLY existing native ML4T summaries/fills/trades/equity; will not fabricate
missing cells or produce a continuous 14-year portfolio from annual resets.
"""
import json
from pathlib import Path
from statistics import mean,median
import numpy as np
from scripts.report_mechanicalpremia_threeway_v1 import ROOT,OUT,TRIALS,read_cell

def main():
    data={}
    missing=[]
    for c in TRIALS:
        data[c]=[]
        for y in range(2013,2027):
            row=read_cell(c,y,"source",1.0)
            if row is None:missing.append((c,y))
            else:data[c].append(row)
    if missing:
        print(json.dumps({"status":"SOURCE_PENDING","complete_source_cells":42-len(missing),
                          "expected":42,"missing":missing},indent=2))
        return 24
    OUT.mkdir(parents=True,exist_ok=True)
    lines=["# Mechanical Premia: complete 2013–2026 YTD source-weighted comparison",
            "","**Method:** Native ml4t.backtest.Engine; one independent $100,000 synthetic price-unit account per calendar year. NOT continuous CAGR, broker USD PnL, or fresh OOS.",
            "**Costs:** 1 bp commission and 2 bps slippage per side; no ASK spread, financing or FX conversion.",
            "**Windows:** 2013–2025 full years; 2026 Jan 1–Oct 11 inclusive. EU50 D1 enters the C1/C2 eligible universe only after June 2014; 2013 portfolios have three D1 indices.",
            "","| Year | C1 DE30/EU50 | C2 JP225/EU50 | C3 US500/US100 |",
            "|---|---:|---:|---:|"]
    for y in range(2013,2027):
        vals=[next(x["return_pct"] for x in data[c] if x["year"]==y) for c in TRIALS]
        lines.append("| "+(str(y)+" YTD" if y==2026 else str(y))+" | "+" | ".join(f"{v:+.2f}%" for v in vals)+" |")
    lines += ["","| Candidate | Mean year return | Positive years | Mean yearly daily Sharpe | Worst within-year DD | Closed trades | Win rate |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    summary={}
    for c,rows in data.items():
        wins=sum(x["closed_wins"] for x in rows)
        closed=sum(x["closed_trades"] for x in rows)
        s={"mean_annual_return_pct":mean(x["return_pct"] for x in rows),
           "positive_years":sum(x["return_pct"]>0 for x in rows),
           "mean_annual_sharpe":mean(x["daily_sharpe"] for x in rows),
           "worst_year_mdd_pct":min(x["maxdd_pct"] for x in rows),
           "total_closed_trades":closed,"win_rate":wins/closed if closed else None,
           "open_occurrences":sum(x["open_trades"] for x in rows)}
        summary[c]=s
        lines.append(f"| {c} | {s['mean_annual_return_pct']:+.2f}% | {s['positive_years']}/14 | {s['mean_annual_sharpe']:.2f} | {s['worst_year_mdd_pct']:.2f}% | {closed} | {100*s['win_rate']:.1f}% |")
    pairs={}
    b={x["year"]:x for x in data["C1_DE30"]}
    for c in ("C2_JP225","C3_US_ONLY"):
        a={x["year"]:x for x in data[c]}
        deltas=np.asarray([a[y]["return_pct"]-b[y]["return_pct"] for y in range(2013,2026)])
        rng=np.random.default_rng(20261014)
        ci=np.quantile(rng.choice(deltas,(10000,len(deltas)),replace=True).mean(axis=1),[.025,.975])
        pairs[c]={"full_year_mean_delta_pp":float(deltas.mean()),
                  "bootstrap_mean_delta_ci95_pp":[float(z) for z in ci],
                  "return_better_years_2013_2026":sum(a[y]["return_pct"]>b[y]["return_pct"] for y in b),
                  "sharpe_better_years":sum(a[y]["daily_sharpe"]>b[y]["daily_sharpe"] for y in b),
                  "drawdown_better_years":sum(a[y]["maxdd_pct"]>b[y]["maxdd_pct"] for y in b)}
    lines += ["","## Paired-year comparison vs original C1 (bootstrap descriptive only; variants were post-selected)",
              "", "| Candidate | Years higher return | 2013-25 mean annual return delta | 95% bootstrap CI (pp) |",
              "|---|---:|---:|---:|"]
    for c,p in pairs.items():
        lo,hi=p["bootstrap_mean_delta_ci95_pp"]
        lines.append(f"| {c} | {p['return_better_years_2013_2026']}/14 | {p['full_year_mean_delta_pp']:+.2f} pp | [{lo:+.2f}, {hi:+.2f}] |")
    lines+=["","**Limitations:** currency-mixed synthetic units for C1/C2, native stop initial-minute gap, undocumented broker sessions, omitted real financing and ASK spread. Year-end marked positions not carried. These data were already observed before C2/C3 selection.",""]
    (OUT/"source_only_annual_2013_2026.md").write_text("\n".join(lines))
    (OUT/"source_only_annual_2013_2026.json").write_text(json.dumps({"status":"42_NATIVE_SOURCE_CELLS_VERIFIED","summary":summary,"paired":pairs,"rows":data},indent=2))
    print(json.dumps({"status":"42_NATIVE_SOURCE_CELLS_VERIFIED","summary":summary,"paired":pairs},indent=2))
    return 0
if __name__=="__main__":
    raise SystemExit(main())
