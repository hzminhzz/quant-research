#!/usr/bin/env python3
"""Explicitly incomplete NQ.F July-Sep native replay: 19/64 complete sessions.

This is not a full Phase 5 validation pass. Preserve both failure and
the bounded diagnostic; never interpolate missing minutes.
"""
from __future__ import annotations
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import run_vwap_pullback_adx_phase5_20261012 as phase5
from scripts import run_vwap_pullback_adx_phase4_20261012 as original
from scripts.run_vwap_pullback_adx_execfix_v3_20261012 import LegalLimitsEngine
SID=phase5.SID
DIR=ROOT/"run_log"/SID/"phase5_incomplete_nqf_19sessions"
FLAG=ROOT/"run_log"/SID/"phase5_primary_blocker.json"

def main():
 if DIR.exists() or FLAG.exists():raise FileExistsError("Existing evidence")
 bars,qa=phase5.build()
 reason={
 "classification":"BLOCKED_INCOMPLETE_PRIMARY_NQF",
 "expected_XNYS_full_sessions":qa["calendar_valid_sessions"],
 "accepted_full_sessions":qa["accepted_count"],
 "excluded_issues":qa["excluded_due_to_quality"],
 "coverage_rate":qa["accepted_count"]/qa["calendar_valid_sessions"],
 "primary_phase5_pass":False,
 "do_not_report_as_oos_verified":True,
 "july_to_september_data_coverage_not_random":True,
 "source":"LSE NQ.F continuous proxy",
 "retrospective_related_NQ_2026_already_explored":True,
 }
 FLAG.parent.mkdir(parents=True,exist_ok=True)
 FLAG.write_text(json.dumps(reason,indent=2)+"\n")
 DIR.mkdir(parents=True,exist_ok=True)
 (DIR/"source_qa.json").write_text(json.dumps(qa,indent=2)+"\n")
 original.Engine=LegalLimitsEngine
 original.OUT=DIR
 rows=[]
 for mode in ("B1","B2","B3"):
  for label,fee,slip in (("gross",0.,0.),("cost",2.5,.25),("stress",2.5,.5)):
   r=original.run_mode(bars,mode,label,fee,slip)
   rows.append(r)
   print("SUBSET_ONLY",mode,label,r["trades"],round(r["net_account_pnl_usd"],2),flush=True)
 (DIR/"all_trials.json").write_text(json.dumps(rows,indent=2,default=str)+"\n")
 print("INCOMPLETE_SOURCE_EXPLORATORY_ONLY")
if __name__=="__main__":main()
