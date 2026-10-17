"""Native fill-ledger ambiguity attribution. Not an alternative trading simulator."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path
import polars as pl

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"run_log/one_bar_b0_cross_indices_20261012/phase34"
STOP_R_SYNTHETIC=1000.0
ROUND_TRIP_SYNTHETIC_COST=2*2.5+2*0.25*20.0  # NQ synthetic only
WORST_REPLACEMENT_PNL=-(STOP_R_SYNTHETIC+ROUND_TRIP_SYNTHETIC_COST)

def main():
    output={}
    for sym in ("ES","DAX","NIKKEI225"):
        years=[]
        for year in range(2013,2027):
            folder=OUT/sym/str(year)/"native_costed_synthetic"
            metrics=json.loads((folder/"metrics.json").read_text())
            trades=pl.read_csv(folder/"evaluation_trades.csv",try_parse_dates=True).filter(pl.col("status")=="closed")
            times=[datetime.fromisoformat(x["timestamp"]) for x in metrics.get("ambiguous_examples",[])]
            affected=trades.filter(pl.col("entry_time").is_in(times))
            risk0=float(trades["pnl"].sum()/1000) if trades.height else 0.0
            affectedR=float(affected["pnl"].sum()/1000) if affected.height else 0.0
            revised=risk0-affectedR+(WORST_REPLACEMENT_PNL/1000)*affected.height
            years.append({
                "year":year, "closed_trades":trades.height,
                "native_costed_net_R":risk0,
                "ambiguous_entry_stop_matched_trades":affected.height,
                "ambiguous_fraction":affected.height/trades.height if trades.height else None,
                "actual_net_R_of_ambiguous_trades":affectedR,
                "pessimistic_replace_each_with_minus_1R_plus_costs":revised,
                "unmatched_native_ambiguous_events_may_be_warmup":len(times)-affected.height,
                "not_native_replay":True,
            })
        groups={}
        for label,filterfn in {
            "all":lambda y:True,
            "pre_corruption_2013_2023":lambda y:y<=2023,
            "2022_2025":lambda y:2022<=y<=2025,
            "2026":lambda y:y==2026,
        }.items():
            selected=[x for x in years if filterfn(x["year"])]
            groups[label]={
                "trades":sum(x["closed_trades"] for x in selected),
                "ambiguous_trades":sum(x["ambiguous_entry_stop_matched_trades"] for x in selected),
                "native_total_R":sum(x["native_costed_net_R"] for x in selected),
                "pessimistic_sensitivity_total_R":
                    sum(x["pessimistic_replace_each_with_minus_1R_plus_costs"] for x in selected),
            }
            groups[label]["ambiguous_fraction"]=groups[label]["ambiguous_trades"]/groups[label]["trades"] if groups[label]["trades"] else None
        output[sym]={"years":years,"groups":groups}
    result={
        "status":"NON_NATIVE_PESSIMISTIC_ENTRY_STOP_SENSITIVITY_ONLY",
        "method":"For each matched native evaluation trade with same-minute entry and stop crossing, replace realized net trade PnL by -50 index points times synthetic 20 per point, less native illustrative round-trip costs. All other trades unchanged.",
        "replacement_R":WORST_REPLACEMENT_PNL/1000,
        "not_a_guaranteed_loss_floor":"Actual gap-through or bid/ask unavailability may be worse; no tick-level sequence available; original native fills remain unchanged.",
        "results":output}
    (OUT/"intraminute_ambiguity_sensitivity.json").write_text(json.dumps(result,indent=2)+"\n")
    for sym,rows in output.items():
        print(sym)
        for label,x in rows["groups"].items():
            print(label,"ambig",x["ambiguous_trades"],"/",x["trades"],"pct",round((x["ambiguous_fraction"] or 0)*100,1),"native",round(x["native_total_R"],2),"pessimistic",round(x["pessimistic_sensitivity_total_R"],2))
if __name__=="__main__":main()
