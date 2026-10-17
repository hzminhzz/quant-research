"""Run the frozen 2013-2024 Mechanical Premia native matrix serially and resumably.

One independent year per child process to bound RAM use. No duplicate jobs.
Always log failures as failures and continue other preregistered cells.
Do not access >2024 partitions. This deterministic worker owns no research
selection decisions and must not change strategy rules or input sources.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from scripts.run_mechanicalpremia_extended_2013 import OUT, ROOT

CELLS = [
    ("H1-SOURCE-3", 1.0),
    ("D1-SOURCE-4", 1.0),
    ("EQUAL-RISK-7", 1.0),
    ("SOURCE-RISK-7", 1.0),
    ("COST-STRESS", 1.5),
    ("COST-STRESS", 2.0),
]
LOG = OUT.parent / "batch_log.jsonl"
STATE = OUT.parent / "batch_state.json"

def event(payload):
    payload = {"at":datetime.now(timezone.utc).isoformat(), **payload}
    with LOG.open("a",encoding="utf-8") as handle:
        handle.write(json.dumps(payload,allow_nan=False,default=str)+"\n")
    print(json.dumps(payload,default=str),flush=True)

def available_gib():
    with open("/proc/meminfo",encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024 / 1024
    return None

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    successful = 0
    failed = 0
    for year in range(2013,2025):
        for trial,cost in CELLS:
            target=OUT/f"year={year}"/trial/f"cost_{cost:g}x"
            summary=target/"summary.json"
            if summary.exists():
                try:
                    report=json.loads(summary.read_text())
                    if report.get("year")==year and report.get("trial")==trial and report.get("cash_plus_positions_reconciles"):
                        successful+=1
                        event({"cell":f"{year}:{trial}:{cost}","state":"ALREADY_VALID_SUMMARY"})
                        continue
                except Exception as exc:
                    event({"cell":f"{year}:{trial}:{cost}","state":"EXISTING_ARTIFACT_UNVERIFIED","error":str(exc)})
                    failed+=1
                    continue
            a=available_gib()
            if a is not None and a < 2.5:
                event({"state":"RESOURCE_BLOCKED","cell":f"{year}:{trial}:{cost}","available_gib":a})
                raise SystemExit(24)
            command=[sys.executable,"-m","scripts.run_mechanicalpremia_extended_2013",
                     "--year",str(year),"--trial",trial,"--cost-multiplier",str(cost)]
            event({"cell":f"{year}:{trial}:{cost}","state":"START","command":command,
                   "available_gib":a})
            start=time.monotonic()
            try:
                result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=1800)
                t=time.monotonic()-start
                if result.returncode!=0 or not summary.exists():
                    failed+=1
                    event({"cell":f"{year}:{trial}:{cost}","state":"FAILED",
                           "exit":result.returncode,"duration_s":round(t,1),
                           "stdout_tail":result.stdout[-800:],"stderr_tail":result.stderr[-1200:]})
                    # Do not overwrite a failed artifact as if successful.
                else:
                    successful+=1
                    record=json.loads(summary.read_text())
                    event({"cell":f"{year}:{trial}:{cost}","state":"COMPLETE",
                           "duration_s":round(t,1),
                           "return_pct":record["native"]["final_value"]/100000*100-100,
                           "closed":record["closed_trades"],
                           "daily_sharpe":record["daily"].get("sharpe_ratio")})
            except Exception as exc:
                failed+=1
                event({"cell":f"{year}:{trial}:{cost}","state":"EXECUTION_ERROR","error":str(exc),
                       "trace":traceback.format_exc()[-800:]})
            STATE.write_text(json.dumps({"completed":successful,"failed":failed,
                                          "total_planned":len(CELLS)*12,
                                          "last_year":year,"last_trial":trial,
                                          "last_cost":cost,"updated_at":datetime.now(timezone.utc).isoformat()},indent=2)+"\n")
    event({"state":"ALL_TERMINAL","completed":successful,"failed":failed,"total":len(CELLS)*12})
    if failed:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
