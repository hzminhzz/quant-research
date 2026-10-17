"""Compare exactly matched-year native ML4T summary artifacts; never simulate fills.

All comparisons use already-observed return metrics. Annual resets are not
stitched into a continuous portfolio. No protected 2026-10-12+ data accessed.
"""
from pathlib import Path
import json
from statistics import median

ROOT=Path(__file__).resolve().parents[1]
NEW=ROOT/"run_log/research_sessions/mechanicalpremia-nikkei-replaces-dax-2013-2026-v1/yearly_native"
OLD_A=ROOT/"run_log/research_sessions/mechanicalpremia-original-four-2013-2024-v1/yearly_native"
OLD_B=ROOT/"run_log/research_sessions/mechanicalpremia-authorized-2025-2026-ytd-v1/yearly_native"
TRIALS={
    "h1":("H1-SOURCE-3","H1-JP225-3"),
    "d1":("D1-SOURCE-4","D1-JP225-4"),
    "equal":("EQUAL-RISK-7","EQUAL-JP225-7"),
    "source":("SOURCE-RISK-7","SOURCE-JP225-7"),
    "stress_1_5":("COST-STRESS","COST-JP225"),
    "stress_2":("COST-STRESS","COST-JP225"),
}
def get(base,year,trial,mult=1):
    path=base/f"year={year}"/trial/f"cost_{mult:g}x"/"summary.json"
    if not path.exists():
        return None
    d=json.loads(path.read_text())
    return {"ret_pct": 100*(d["native"]["final_value"]/100_000-1),
            "sharpe":d["daily"].get("sharpe_ratio"),
            "calmar":d["daily"].get("calmar_ratio"),
            "max_dd_pct":100*d["daily"].get("max_drawdown"),
            "closed":d["closed_trades"],"open":d["open_trades"],
            "rejected_orders":d["native"]["num_rejected_orders"],
            "ledger_reconciled":d["cash_plus_positions_reconciles"],
            "artifact":str(path)}

def compare():
    report={"description":"Post-selected JP225 in place of DE30; exploratory comparison, NOT fresh OOS",
            "pricing_warning":"JPY/EUR/USD synthetic price units without FX conversion; real portfolio return invalid",
            "baseline": "old DE30 native Engine runs", "candidate":"JP225 substituted native Engine runs",
            "years":{},"totals":{}}
    for yr in [*range(2013,2027)]:
        old=OLD_A if yr<=2024 else OLD_B
        m={}
        for name,(bt,ct) in TRIALS.items():
            cost=1.5 if name=="stress_1_5" else 2 if name=="stress_2" else 1
            a,b=get(old,yr,bt,cost),get(NEW,yr,ct,cost)
            m[name]={"old":a,"new":b,"delta_return_pp":b["ret_pct"]-a["ret_pct"] if a and b else None,
                      "delta_sharpe":b["sharpe"]-a["sharpe"] if a and b else None}
        report["years"][str(yr)]=m
    for name in TRIALS:
        pairs=[(int(y),r[name]) for y,r in report["years"].items() if r[name]["new"] and r[name]["old"]]
        wins=[r for _,r in pairs if r["delta_return_pp"]>0]
        report["totals"][name]={"n_matched_years":len(pairs),"improved_return_years":len(wins),
                               "mean_annual_return_delta_pp":sum(r["delta_return_pp"] for _,r in pairs)/len(pairs) if pairs else None,
                               "median_annual_return_delta_pp":median([r["delta_return_pp"] for _,r in pairs]) if pairs else None,
                               "recent_2025_2026_both_complete":all(report["years"][str(y)][name]["new"] is not None for y in (2025,2026))}
    report["completed_cells"]=sum(1 for y in report["years"].values() for r in y.values() if r["new"])
    report["expected_cells"]=84
    return report

if __name__=="__main__":
    print(json.dumps(compare(),indent=2))
