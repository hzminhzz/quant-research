"""Resumable ten-rule sensitivity matrix, native ML4T event-driven Engine ONLY.

Single tmux worker by year. Build costly causal Engineer features once per
year/asset, then execute all ten predeclared variants and 2x cost stresses.
No other run, tmux or instrument is modified. Never overwrite existing
successful cells. Failed trial attempts remain in append-only batch JSONL.
"""
from __future__ import annotations
import gc
import json
import sys
import time
from datetime import datetime,timezone
from pathlib import Path

from scripts.run_mechanicalpremia_c3_d1_naive_ten_20261014 import (
    ROOT, OUT, prepare_year, execute, VARIANTS, STRESS_YEARS
)

LOG=OUT.parent/"batch_log.jsonl"
STATE=OUT.parent/"batch_state.json"
YEARS=(2025,2026,2023,2024,*range(2013,2023))
EXPECTED=14*10+4*10
def emit(**kw):
    entry={"utc":datetime.now(timezone.utc).isoformat(),**kw}
    LOG.parent.mkdir(parents=True,exist_ok=True)
    with LOG.open("a") as f:f.write(json.dumps(entry,default=str)+"\n")
    print(json.dumps(entry,default=str),flush=True)
def memory_available_gib():
    p=Path("/proc/meminfo")
    for l in p.read_text().splitlines():
        if l.startswith("MemAvailable:"):
            return int(l.split()[1])/1024**2
    raise RuntimeError("Cannot verify system memory reserve")
def valid_cell(year,trial,cost):
    file=OUT/f"year={year}"/trial/f"cost_{cost:g}x"/"summary.json"
    if not file.exists():return False
    try:
        x=json.loads(file.read_text())
        if x.get("session")!=OUT.parent.name or x.get("year")!=year or x.get("trial")!=trial or float(x.get("cost_multiplier",-1))!=cost:
            raise ValueError("identity mismatch")
        if x.get("cash_plus_positions_reconciles") is not True or x["native"].get("num_rejected_orders",0)!=0:
            raise ValueError("invalid native terminal result")
        for name in ("fills.parquet","trades.parquet","daily_equity.parquet"):
            if not (file.parent/name).is_file():raise ValueError("missing "+name)
        return True
    except Exception as e:
        raise RuntimeError(f"Existing artifact corrupt; refusing overwrite: {file}: {e}") from e
def progress():
    complete=0
    for y in YEARS:
        for variant in VARIANTS:
            for cost in ((1.0,2.0) if y in STRESS_YEARS else (1.0,)):
                if valid_cell(y,variant,cost):complete+=1
    return complete
def main():
    emit(state="BOOT",expected=EXPECTED,already_complete=progress(),trials=list(VARIANTS))
    for year in YEARS:
        jobs=[(v,cost) for v in VARIANTS for cost in ((1.,2.) if year in STRESS_YEARS else (1.,))
              if not valid_cell(year,v,cost)]
        if not jobs:
            emit(state="YEAR_ALREADY_COMPLETE",year=year,done=progress())
            continue
        mem=memory_available_gib()
        while mem<3.3:
            emit(state="RESOURCE_WAIT",year=year,available_gib=round(mem,2),retry_sec=90)
            time.sleep(90)
            mem=memory_available_gib()
        emit(state="PREPARE_YEAR",year=year,available_gib=round(mem,2),pending=len(jobs))
        try:
            prepared=prepare_year(year)
        except Exception as e:
            emit(state="FAILED_PREPARE",year=year,error=repr(e))
            raise
        emit(state="FEATURES_READY",year=year,rows=prepared[0].height)
        for trial,cost in jobs:
            mem=memory_available_gib()
            # Prepared DataFrame owns some memory; avoid starting with dangerously low reserve.
            if mem<1.25:
                emit(state="RESOURCE_UNSAFE_MIDYEAR",year=year,trial=trial,cost=cost,available_gib=round(mem,2))
                return 25
            emit(state="CELL_START",year=year,trial=trial,cost=cost)
            try:
                result=execute(year,trial,cost,prepared=prepared)
                assert valid_cell(year,trial,cost)
            except Exception as e:
                emit(state="CELL_FAILED",year=year,trial=trial,cost=cost,error=repr(e))
                raise
            emit(state="CELL_DONE",year=year,trial=trial,cost=cost,
                 ret_pct=100*(result["native"]["final_value"]/result["native"]["initial_cash"]-1),
                 daily_sharpe=result["daily"].get("sharpe_ratio"),
                 closed=result["closed_trades"],d1_closed=result["d1_closed_trades"],
                 d1_entries=result["d1_entry_fills"],done=progress())
            gc.collect()
        del prepared
        gc.collect()
        emit(state="YEAR_COMPLETE",year=year,done=progress())
    n=progress()
    STATE.write_text(json.dumps({"status":"ALL_TERMINAL" if n==EXPECTED else "INCOMPLETE",
                                 "completed":n,"expected":EXPECTED},indent=2)+"\n")
    emit(state="ALL_TERMINAL" if n==EXPECTED else "INCOMPLETE",completed=n,expected=EXPECTED)
    return 0 if n==EXPECTED else 2
if __name__=="__main__":
    raise SystemExit(main())
