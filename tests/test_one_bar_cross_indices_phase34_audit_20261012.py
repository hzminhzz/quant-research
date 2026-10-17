"""Independent invariants for the B0 cross-index Phase 3-4 evidence."""
from __future__ import annotations
import json
import sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"run_log/one_bar_b0_cross_indices_20261012/phase34"
sys.path.insert(0,str(ROOT/"scripts"))
import report_one_bar_cross_indices_20261012 as reporter

def read(name):
    return json.loads((OUT/name).read_text())

def test_frozen_protocol_and_six_native_trials_complete():
    frozen=json.loads((ROOT/"run_log/one_bar_b0_cross_indices_20261012/phase34_frozen_spec.json").read_text())
    ledger=read("trial_ledger.json")
    assert frozen["core_rules"]["stop_points"]==50
    assert frozen["trial_count"]==6
    assert frozen["param_tuning"] is False
    assert len(ledger["trials"])==6
    assert all(x["years_completed"]==14 for x in ledger["trials"])
    assert all(x["phase4"]=="COMPLETED_NATIVE_ML4T_ENGINE" for x in ledger["trials"])
    assert ledger["excluded_market"]["HSI"].startswith("1m data not found")

def test_dax_rejected_after_2023_regardless_of_profit():
    source=read("extreme_price_jump_audit.json")
    years=source["DAX"]["extreme_by_year"]
    assert source["DAX"]["extreme_discontinuities"]==1000
    assert {(x["year"],x["len"]) for x in years}=={(2024,447),(2025,334),(2026,219)}
    assert all(source[x]["extreme_discontinuities"]==0 for x in ("ES","NQ","NIKKEI225"))
    result=read("final_research_metrics.json")
    assert "DATA_BLOCKED" in result["status"]
    assert "INVALID" in result["instrument_decisions"]["DAX"]

def test_nikkei_2026_intraminute_sensitivity_not_native_result():
    r=read("intraminute_ambiguity_sensitivity.json")
    a=r["results"]["NIKKEI225"]["groups"]["2026"]
    assert a["trades"]==251 and a["ambiguous_trades"]==91
    assert abs(a["native_total_R"]-64.11)<.1
    assert a["pessimistic_sensitivity_total_R"] < 0
    assert r["status"].startswith("NON_NATIVE")

def test_native_trade_reconciliation_and_nq_control():
    r=read("final_research_metrics.json")
    assert r["audit"]["status"]=="PASS"
    assert r["metrics"]["full"]["NQ"]["closed_trades"]==5462
    assert abs(r["metrics"]["full"]["NQ"]["net_R"]-166.10792)<.00001
    for x in ("ES","DAX","NIKKEI225"):
        assert (OUT/x/"summary.json").is_file()
        assert json.loads((OUT/x/"summary.json").read_text())["status"]=="completed"

def test_paired_moving_block_bootstrap_reproducible():
    import numpy as np
    panel={"NQ":np.array([0.,1.,0.,-1.,2.,0.,0.,1.]),
           "ES":np.array([1.,-1.,0.,-2.,0.,1.,0.,0.])}
    x=reporter.bootstrap(panel,nrep=8,block=2)
    y=reporter.bootstrap(panel,nrep=8,block=2)
    assert x==y
    assert x["NQ"]["iterations"]==8
    assert "paired_delta_sharpe_vs_NQ_p05_p50_p95" in x["ES"]
