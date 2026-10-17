"""Independent static price oracle for native Gotobi fill timing and cost accounting.

This checks the Engine output against exact documented minute opens. It never
fills positions itself and never constructs a second trade simulator.
"""
from __future__ import annotations
import json
from pathlib import Path
import polars as pl

ROOT=Path(__file__).resolve().parents[1]
SID="usdjpy_tokyo_fix_gotobi_engine_20261010_v1"
OUT=ROOT/"run_log"/SID
EVENTS=pl.read_parquet(ROOT/"data/features/usdjpy_tokyo_fix_gotobi_20261010_continuous.parquet")
FIN=ROOT/"run_log"/SID/"independent_fill_oracle.json"

def verify(arm, costed):
    trial=f"P4_{arm}_{'costed' if costed else 'zero_cost'}"
    body=json.loads((OUT/trial/"result.json").read_text())
    selected=(EVENTS.filter(pl.col("gotobi")) if arm=="H1"
              else EVENTS.filter(pl.col("gotobi") & pl.col("h2_gate").fill_null(False)))
    ref={str(x["session"]):x for x in selected.to_dicts()}
    rows=body["orders"]
    assert len(rows)==len(ref)*2
    pairs={}
    for row in rows:
        assert row["status"]=="OrderStatus.FILLED"
        key=row["session"]
        assert key in ref
        assert row["role"] not in pairs.setdefault(key,{})
        pairs[key][row["role"]]=float(row["fill_price"])
    slip=.005 if costed else 0.
    pnl=0.
    for day,e in ref.items():
        if arm=="H1":
            expected_entry=e["p0830"]+slip
            expected_exit=e["p0954"]-slip
            signed=1
        else:
            expected_entry=e["p0956"]-slip
            expected_exit=e["p1030"]+slip
            signed=-1
        got=pairs[day]
        assert abs(got["entry"]-expected_entry)<1e-8, (trial,day,"entry",got,expected_entry)
        assert abs(got["exit"]-expected_exit)<1e-8, (trial,day,"exit",got,expected_exit)
        pnl+=signed*1000.*(expected_exit-expected_entry)
    actual=float(body["engine_metrics"]["final_value"])-1_000_000.
    assert abs(pnl-actual)<1e-5, (trial,pnl,actual)
    assert body["status"]=="PASS_IMPLEMENTATION"
    return {"trial":trial,"status":"ORACLE_PASS","trades":len(ref),
            "expected_pnl_jpy":pnl,"engine_pnl_jpy":actual,
            "expected_mean_pips":pnl/1000./len(ref)*100.}

def main():
    if FIN.exists():
        raise RuntimeError("Oracle evidence already exists")
    results=[verify(a,c) for a in ("H1","H2") for c in (False,True)]
    FIN.write_text(json.dumps({"method":"Exact open price fill comparison; independent of Engine accounting","result":results},indent=2)+"\n")
    print(json.dumps(results,indent=2))
if __name__=="__main__":
    main()
