"""Fail-closed final registry for the preregistered C3 D1 ten-rule trial matrix.

Produces the final scoreboard and records completed *technical* trials.
Never changes source baseline, never approves a strategy, never creates
missing annual observations or re-labels observed history as holdout.
"""
from __future__ import annotations
import json
import subprocess
import sys
from datetime import datetime,timezone
from pathlib import Path

from scripts.report_mechanicalpremia_c3_d1_naive_ten_20261014 import main as make_scoreboard
from scripts.mechanicalpremia_c3_d1_naive_ten_20261014 import ROOT, VARIANTS

SID="mechanicalpremia-c3-d1-naive-ten-20261014-v1"
OUT=ROOT/"docs/audit"/SID
REC=ROOT/"run_log/research_sessions"/SID
def record(trial,path):
    cmd=[sys.executable,"scripts/research_session.py","record",
         "--root",".","--session",SID,"--trial",trial,
         "--status","completed","--artifact",str(path.relative_to(ROOT))]
    p=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True,timeout=90)
    if p.returncode:raise RuntimeError(f"Trial record failed {trial}: {p.stderr[-1200:]}")
def main():
    make_scoreboard()
    summary=json.loads((OUT/"scoreboard.json").read_text())
    if summary["status"]!="ALL_180_VERIFIED" or summary["native_candidate_cells_complete"]!=180:
        print(json.dumps({"status":"INCOMPLETE","completed":summary["native_candidate_cells_complete"],
                          "missing":summary["missing_count"],"session":SID}))
        return 24
    assert set(VARIANTS)=={r["trial"] for r in summary["aggregate"] if r["trial"]!="SOURCE-US2"}
    assert all(x["years_completed"]==14 for x in summary["aggregate"])
    assert all(x["cost2x_years"]==4 for x in summary["aggregate"] if x["trial"]!="SOURCE-US2")
    for variant in VARIANTS:
        result=next(x for x in summary["aggregate"] if x["trial"]==variant)
        evidence={"session":SID,"trial":variant,"technical_status":"COMPLETED",
             "scientific_approval":"NOT_APPROVED","research_class":"EXPLORATORY_OBSERVED_DATA",
             "years":14,"extra_cost_stress_years":[2021,2024,2025,2026],
             "summary":result,
             "report":"docs/audit/"+SID+"/scoreboard.md",
             "caveats":["already observed historical development period",
                        "multiple hypothesis testing 10 variants + prior universe selection",
                        "real CFD spread financing and point-values unknown",
                        "annual reset accounts; no continuous NAV"]}
        path=OUT/f"{variant}_terminal.json"
        path.write_text(json.dumps(evidence,indent=2)+"\n")
        record(variant,path)
    dat={"session":SID,"trial":"DATA-ELIGIBILITY","technical_status":"COMPLETED",
         "input_scope":"US500 and US100 canonical Dukascopy 1min, prior-Jul warmup, <= Oct11 2026",
         "original_source":"mechanicalpremia-us500-us100-2013-2026-v1",
         "source_holdout_after":"2026-10-12T00:00:00Z",
         "scientific_approval":"NOT_APPROVED",
         "native_variants_predeclared":list(VARIANTS)}
    path=OUT/"DATA-ELIGIBILITY_terminal.json";path.write_text(json.dumps(dat,indent=2)+"\n")
    record("DATA-ELIGIBILITY",path)
    audit={"session":SID,"trial":"NATIVE-AUDIT","status":"COMPLETED",
       "verified_native_cells":180,"failed_or_missing_cells":0,
       "scientific_approval":"NOT_APPROVED","portfolio":"source C3 H1+D1",
       "baseline":"SOURCE-US2","report":str(OUT/"scoreboard.md"),
       "warning":"Good historical results cannot establish qualified live trading economics."}
    path=OUT/"NATIVE-AUDIT_terminal.json";path.write_text(json.dumps(audit,indent=2)+"\n")
    record("NATIVE-AUDIT",path)
    (OUT/"terminal_status.json").write_text(json.dumps({
         "utc":datetime.now(timezone.utc).isoformat(),
         "status":"ALL_180_VERIFIED","trial_records":12,
         "recommendation":"NEEDS_INDEPENDENT_VALIDATION","live_approval":"NOT_APPROVED",
         "report":str(OUT/"scoreboard.md")},indent=2)+"\n")
    print(json.dumps({"state":"VERIFIED_180_AND_RECORDED_12","report":str(OUT/"scoreboard.md")},indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
