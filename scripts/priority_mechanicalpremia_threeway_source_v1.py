"""Complete missing source-weighted annual C2/C3 native ML4T runs first.

Pure scheduling priority, no new strategy/parameter trials. Idempotent:
never repeats a verified summary, refuses malformed prior artifacts, uses
native Engine entrypoints and preserved frozen identities. Resource-gated.
"""
from __future__ import annotations
import json
import subprocess
import sys
import time
from datetime import datetime,timezone
from pathlib import Path

from scripts.run_mechanicalpremia_us2_2013_2026_v1 import OUT as C3_OUT, ROOT
from scripts.run_mechanicalpremia_jp225_substitution_v1 import OUT as C2_OUT

LOG = ROOT/"docs/audit/mechanicalpremia_threeway_priority_log.jsonl"
QUEUE = [
  (name,base,trial,module)
  for name,base,trial,module in [
     ("C3",C3_OUT,"SOURCE-US2","scripts.run_mechanicalpremia_us2_2013_2026_v1"),
     ("C2",C2_OUT,"SOURCE-JP225-7","scripts.run_mechanicalpremia_jp225_substitution_v1")]
]
def avail():
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1])/1024**2
    raise RuntimeError("Cannot verify memory reserve")
def emit(**kw):
    item={"at":datetime.now(timezone.utc).isoformat(),**kw}
    with LOG.open("a") as f:f.write(json.dumps(item,default=str)+"\n")
    print(json.dumps(item,default=str),flush=True)

def main():
    for year in range(2013,2027):
        for name,base,trial,module in QUEUE:
            path=base/f"year={year}"/trial/"cost_1x"/"summary.json"
            if path.exists():
                record=json.loads(path.read_text())
                if record.get("cash_plus_positions_reconciles") and record.get("year")==year and record.get("trial")==trial:
                    emit(state="ALREADY_COMPLETE",candidate=name,year=year)
                    continue
                emit(state="BLOCKED_CORRUPT_ARTIFACT",candidate=name,year=year,path=str(path))
                return 2
            while avail()<2.6:
                emit(state="RESOURCE_WAIT",year=year,candidate=name,available_gib=round(avail(),3))
                time.sleep(60)
            cmd=[sys.executable,"-m",module,"--year",str(year),"--trial",trial]
            emit(state="START",candidate=name,year=year,command=cmd)
            proc=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=1800)
            if proc.returncode or not path.exists():
                emit(state="FAILED",candidate=name,year=year,returncode=proc.returncode,stderr=proc.stderr[-1300:])
                return 1
            rec=json.loads(path.read_text())
            if not rec.get("cash_plus_positions_reconciles"):
                emit(state="FAILED_RECONCILIATION",candidate=name,year=year)
                return 1
            emit(state="COMPLETE",candidate=name,year=year,
                 return_pct=100*(rec["native"]["final_value"]/rec["native"]["initial_cash"]-1),
                 sharpe=rec["daily"].get("sharpe_ratio"),
                 closed=rec["closed_trades"],open=rec["open_trades"])
    emit(state="SOURCE_MATRIX_COMPLETE",years=14,candidates=2)
    return 0
if __name__=="__main__":
    raise SystemExit(main())
