"""Priority N01/N02/N03 concurrent native ML4T 2017-2026, idempotent.

Separate processes per VARIANT; at most TWO concurrently compute/run via
flock slots to protect shared memory. Reuse successful previously completed
2017-2026 annual cells from the original frozen 10-rule experiment.
Nothing is simulated here; execute() uses native ML4T Engine.
"""
from __future__ import annotations
import argparse
import fcntl
import json
import os
import time
import gc
from datetime import datetime,timezone
from pathlib import Path
from scripts.batch_mechanicalpremia_c3_d1_naive_ten_20261014 import valid_cell,memory_available_gib
from scripts.run_mechanicalpremia_c3_d1_naive_ten_20261014 import ROOT, OUT, prepare_year, execute

WORKERS=("N01-LV-PB35","N02-LV-PB50","N03-LV-PB80")
YEARS=tuple(range(2017,2027))
STRESS=(2021,2024,2025,2026)
ARTIFACT_DIR=ROOT/"docs/audit/mechanicalpremia_c3_d1_2017_2026_priority"
ARTIFACT_DIR.mkdir(parents=True,exist_ok=True)


def emit(worker,**kwargs):
    msg={"utc":datetime.now(timezone.utc).isoformat(),"worker":worker,**kwargs}
    with (ARTIFACT_DIR/(worker+".jsonl")).open("a") as f:
        f.write(json.dumps(msg,default=str)+"\n")
    print(json.dumps(msg,default=str),flush=True)


def acquire_slot(worker):
    while True:
        for j in range(2):
            lock=ARTIFACT_DIR/f"slot{j}.lock"
            f=lock.open("a+")
            try:
                fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                f.close()
                continue
            available=memory_available_gib()
            if available>=2.7:
                return f,j
            fcntl.flock(f.fileno(),fcntl.LOCK_UN)
            f.close()
        emit(worker,state="MEMORY_OR_CONCURRENCY_WAIT",available_gib=round(memory_available_gib(),2))
        time.sleep(25)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--trial",choices=WORKERS,required=True)
    a=parser.parse_args()
    trial=a.trial
    expected=14
    complete=0
    emit(trial,state="PRIORITY_STARTED",years=list(YEARS),expected=expected)
    try:
        for year in YEARS:
            costs=(1.0,2.0) if year in STRESS else (1.0,)
            missing=[c for c in costs if not valid_cell(year,trial,c)]
            if not missing:
                complete+=len(costs)
                emit(trial,state="REUSED_VERIFIED_YEAR",year=year,costs=list(costs),complete=complete)
                continue
            slot,slot_num=acquire_slot(trial)
            try:
                emit(trial,state="PREPARE",year=year,slot=slot_num,mem_gib=round(memory_available_gib(),2))
                year_data=prepare_year(year)
                for cost in missing:
                    if valid_cell(year,trial,cost):
                        continue
                    emit(trial,state="CELL_START",year=year,cost=cost,slot=slot_num)
                    result=execute(year,trial,cost,prepared=year_data)
                    if not valid_cell(year,trial,cost):
                        raise RuntimeError(f"Native artifact failed verification: {year}/{trial}/{cost}")
                    emit(trial,state="CELL_COMPLETE",year=year,cost=cost,slot=slot_num,
                         ret_pct=100*(result["native"]["final_value"]/result["native"]["initial_cash"]-1),
                         sharpe=result["daily"].get("sharpe_ratio"),
                         d1_closed=result["d1_closed_trades"],
                         d1_fills=result["d1_entry_fills"])
                del year_data
                gc.collect()
            finally:
                fcntl.flock(slot.fileno(),fcntl.LOCK_UN)
                slot.close()
            complete+=len(costs)
            emit(trial,state="YEAR_COMPLETE",year=year,complete=complete)
        n=sum(valid_cell(y,trial,c) for y in YEARS for c in ((1.,2.) if y in STRESS else (1.,)))
        if n!=expected: raise RuntimeError(f"Incomplete {trial}: {n}/{expected}")
        emit(trial,state="TRIAL_COMPLETE",verified=n)
        (ARTIFACT_DIR/(trial+".complete.json")).write_text(json.dumps({
            "trial":trial,"native_year_cost_cells_verified":n,"years":"2017-2026 YTD",
            "status":"VERIFIED","scientific_status":"EXPLORATORY_NOT_APPROVED",
        },indent=2)+"\n")
    except Exception as exc:
        emit(trial,state="BLOCKED",error=repr(exc))
        raise


if __name__=="__main__":
    main()
