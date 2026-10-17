"""Idempotently close out C2/C3 research trial ledgers after FULL native verification.

No strategy changes, fills, orders or data are simulated. Do not mark VALIDATE.
Runs only after 252/252 cells pass the three-way report's direct checks.
"""
from __future__ import annotations
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts.report_mechanicalpremia_threeway_v1 import ROOT, OUT, main as compare_main

CANDIDATES={
  "C2_JP225":{
     "session":"mechanicalpremia-nikkei-replaces-dax-2013-2026-v1",
     "trials":{"H1-JP225-3":"h1_1","D1-JP225-4":"d1_1","EQUAL-JP225-7":"equal_1",
               "SOURCE-JP225-7":"source_1","COST-JP225":"cost_2","NATIVE-AUDIT":"source_1"},
  },
  "C3_US_ONLY":{
     "session":"mechanicalpremia-us500-us100-2013-2026-v1",
     "trials":{"H1-US2":"h1_1","D1-US2":"d1_1","EQUAL-US2":"equal_1",
               "SOURCE-US2":"source_1","COST-US2":"cost_2","NATIVE-AUDIT":"source_1"},
  }
}
def main():
    if compare_main()!=0:
        print("INCOMPLETE_MATRIX: not recording terminal trials")
        return 24
    total=json.loads((OUT/"summary.json").read_text())
    if total["status"]!="ALL_NATIVE_ANNUAL_CELLS_VERIFIED" or total["completed"]!=252:
        raise RuntimeError("Cannot finalize incomplete or malformed 252-cell evidence")
    log=[]
    for candidate, spec in CANDIDATES.items():
        session=spec["session"]
        for trial,metric_key in spec["trials"].items():
            evidence={
                "trial":trial,
                "session":session,
                "terminal_status":"completed",
                "scientific_status":"NOT_APPROVED",
                "research_classification":"EXPLORATORY_OBSERVED_POST_SELECTION",
                "native_metric_snapshot":total["comparative_summary"][candidate][metric_key],
                "reference_report":str((OUT/"report.md").relative_to(ROOT)),
                "reference_csv":str((OUT/"all_annual_metrics.csv").relative_to(ROOT)),
                "execution_reconciled_cells":84,
                "notes":["Complete native Engine execution does not mean strategy validation",
                         "C2/C3 candidate universe selected after prior observed C1 results",
                         "No continuous 14-year portfolio across annual resets",
                         "Actual CFD spreads, financing, lot multipliers and FX translation not modeled",
                         "H1 stop not fully source-equivalent; NY17 session assumed",
                         "No protected 2026-10-12+ price observations scored"]
            }
            artifact=ROOT/"docs/audit"/f"{session}_{trial.lower().replace('-','_')}_terminal_v1.json"
            artifact.write_text(json.dumps(evidence,indent=2)+"\n")
            cmd=[sys.executable,"scripts/research_session.py","record",
                 "--root",".","--session",session,"--trial",trial,
                 "--status","completed","--artifact",str(artifact.relative_to(ROOT))]
            proc=subprocess.run(cmd,cwd=ROOT,stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,text=True,timeout=60)
            item={"session":session,"trial":trial,"returncode":proc.returncode,
                  "error_tail":proc.stderr[-600:] if proc.returncode else None}
            log.append(item)
            if proc.returncode: print(json.dumps(item),flush=True)
    result={"finalized_at":datetime.now(timezone.utc).isoformat(),
            "verified_native_annual_cells":252,
            "evidence":str(OUT/"summary.json"),
            "trial_records":log,
            "status":"COMPLETE" if all(x["returncode"]==0 for x in log) else "PARTIAL_RECORD_FAILURE"}
    (OUT/"finalize_status.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({"status":result["status"],"trial_records":len(log),
                      "failures":sum(x["returncode"]!=0 for x in log)}))
    return 0 if result["status"]=="COMPLETE" else 1
if __name__=="__main__":
    raise SystemExit(main())
