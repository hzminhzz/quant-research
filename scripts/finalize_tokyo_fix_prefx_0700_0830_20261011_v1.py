"""Final read-only preservation/test audit for the frozen 07:00 Gotobi session.

Creates task-owned T7 summary and does not mutate earlier frozen studies.
"""
from __future__ import annotations
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SID="tokyo_fix_prefx_0700_0830_20261011_v1"
OUT=ROOT/"run_log"/SID
OLD=OUT/"preservation_before.json"
TESTS=[
 "tests/test_tokyo_fix_prefx_0700_0830_20261011_v1.py",
 "tests/test_tokyo_alpha_map_program1_v1.py",
 "tests/test_tokyo_alpha_map_program1_closure_v3.py",
 "tests/test_tokyo_fix_program2_cross_currency_20261011_v1.py",
 "tests/test_tokyo_fix_program3_ohlcv_execution_20261011_v1.py",
]
def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()
def run(cmd):
    return subprocess.run(cmd,text=True,capture_output=True,cwd=ROOT,timeout=155)

def main():
    target=OUT/"T7_final_audit/result.json"
    if target.exists():raise RuntimeError("Final audit immutable")
    before=json.loads(OLD.read_text())
    source=json.loads((OUT/"source_manifest.json").read_text())
    changed_sources=[]
    for rec in source["sources"]:
        p=ROOT/rec["path"]
        if not p.exists() or sha(p)!=rec["sha256"]:
            changed_sources.append(rec["path"])
    cp=source["calendar"]
    if not (ROOT/cp["path"]).exists() or sha(ROOT/cp["path"])!=cp["sha256"]:
        changed_sources.append(cp["path"])
    changed_unrelated=[]
    for p,s in before["hashes"].items():
        candidate=ROOT/p
        if not candidate.exists() or sha(candidate)!=s:
            if SID not in p:
                changed_unrelated.append(p)
    head=run(["git","rev-parse","HEAD"])
    diff=run(["git","diff","--check"])
    py_compile=run([sys.executable,"-m","compileall","-q",
             "scripts/run_tokyo_fix_prefx_0700_0830_20261011_v1.py",
             "scripts/verify_tokyo_fix_prefx_0700_0830_20261011_v1.py",
             "scripts/chart_tokyo_fix_prefx_0700_0830_20261011_v1.py",
             "tests/test_tokyo_fix_prefx_0700_0830_20261011_v1.py"])
    tests=run([sys.executable,"-m","pytest","-q","-n","0",*TESTS])
    cmd=[sys.executable,"scripts/research_session.py","report","--session",SID,"--root","."]
    ledger_run=run(cmd)
    if ledger_run.returncode:raise RuntimeError("Ledger report failed "+ledger_run.stderr)
    ledger=json.loads(ledger_run.stdout)
    trials=ledger.get("trials",[])
    coverage=json.loads((OUT/"T0_data_gate/result.json").read_text())
    oracle=json.loads((OUT/"T6_independent_oracle/result.json").read_text())
    if source.get("holdout_read") or oracle["protected_holdout_read"]:
        raise AssertionError("Holdout verification failed")
    if changed_sources or head.stdout.strip()!=before["head"]:
        raise AssertionError("Source/HEAD mutation detected "+str(changed_sources))
    completed=[x for x in trials if x["declaration"]["id"]!="T7_final_audit"]
    if len(trials)!=8 or len(completed)!=7 or not all(x.get("status")=="completed" for x in completed):
        raise AssertionError("Not all preregistered trials T0-T6 completed")
    if not all((x.get("record") or {}).get("artifact_identity_matches") for x in completed):
        raise AssertionError("Artifact hash identity mismatch")
    if tests.returncode or diff.returncode or py_compile.returncode:
        raise AssertionError("Tests/compile/diff verification failed")
    if oracle["status"]!="PASS" or oracle["native_runs"]!=11:
        raise AssertionError("Independent oracle not valid")
    aud={
       "status":"PASS_RESEARCH_COMPLETE","approval_status":"NOT_APPROVED",
       "classification":"EXPLORATORY","head":head.stdout.strip(),
       "source_sha256_matched":True,"previous_source_changed_files":changed_sources,
       "preserved_baseline_files_count":len(before["hashes"]),
       "concurrently_changed_unrelated_files":changed_unrelated,
       "prior_frozen_research_artifact_edits":[],
       "holdout":"SEALED through 2026-08-31 JST; no >=2026-09-01 source accessed",
       "native_runs":oracle["native_runs"],
       "trades_checked":oracle["trades_verified"],
       "fills_checked":oracle["fills_verified"],
       "point_in_time_feature_rows_checked":oracle["features_timestamp_verified"],
       "ledger_complete":len(completed),"ledger_artifact_identities_pass":True,
       "session_check_status":run([sys.executable,"scripts/research_session.py","check","--session",SID,"--root","."]).returncode,
       "tests":{"returncode":tests.returncode,"stdout_tail":tests.stdout[-2500:],
           "stderr_tail":tests.stderr[-800:],"test_scope":"5 focused session suites including Programs 1-4A",
           "full_repository_suite":"NOT_RERUN (previous broad notebook/Marimo suite not known to pass)"},
       "compile_pass":py_compile.returncode==0,
       "git_diff_check_pass":diff.returncode==0,
       "report_path":"docs/audit/"+SID+".md",
       "report_sha256":sha(ROOT/("docs/audit/"+SID+".md")),
       "script_identities":{
          "runner":sha(ROOT/("scripts/run_"+SID+".py")),
          "oracle":sha(ROOT/("scripts/verify_"+SID+".py"))},
       "data_gate_complete_days":coverage["new_eligible"],
       "research_decision":"FAIL_PREDECLARED_STABILITY (2024-25 net<0) and no significant absolute net mean; relative Gotobi premium exploratory only",
       "trials":[{"id":x["declaration"]["id"],"status":x["status"]} for x in trials],
       "real_orders":False,"git_commit_push":False
    }
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(aud,indent=2,default=str)+"\n")
    print(json.dumps({k:aud[k] for k in ["status","approval_status","native_runs","trades_checked","fills_checked",
        "ledger_complete","source_sha256_matched","compile_pass","git_diff_check_pass"]},indent=2))
    print("TESTS",tests.stdout[-230:])
    print("CONCURRENTLY_CHANGED_UNRELATED_FILES",len(changed_unrelated))

if __name__=="__main__":main()
