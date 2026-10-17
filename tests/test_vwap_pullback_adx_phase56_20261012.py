"""Phase5/6 regression: source quality, protected boundaries, audit, robustness."""
import json
from pathlib import Path
import polars as pl
from scripts import run_vwap_pullback_adx_phase5_20261012 as p5
from scripts import run_vwap_pullback_adx_phase6_20261012 as p6
from scripts import run_vwap_pullback_adx_phase4_20261012 as p4

ROOT=Path(__file__).resolve().parents[1]
V4=ROOT/"run_log/vwap_pullback_adx_nq_20261012_proxy_v4_phase56"
V5=ROOT/"run_log/vwap_pullback_adx_nas100_20261012_cross_source/phase5_cross_source"


def test_primary_nqf_data_incomplete_and_no_august_sessions():
    feed,qa=p5.build()
    assert qa["calendar_valid_sessions"]==64
    assert qa["accepted_count"]==19
    assert feed.height==19*446
    assert not any(str(d).startswith("2026-08") for d in feed["day"].unique().to_list())
    assert qa["excluded_due_to_quality"]


def test_secondary_index_complete_but_not_cme():
    original_path, original_sha = p5.FILE,p5.SHA
    try:
        p5.FILE=ROOT/"data/processed/vwap_adx_nas100_2026h2_1m.parquet"
        p5.SHA="da3891d4ae7d686da6832081f322c7b2571bcc92e0e0ce5581b860a7e9d66e17"
        feed,qa=p5.build()
    finally:
        p5.FILE,p5.SHA=original_path,original_sha
    assert qa["accepted_count"]==64
    assert feed.height==64*446
    assert feed["day"].max().isoformat()=="2026-09-30"
    assert qa["proxy_not_actual_CME"]


def test_sealed_november_and_october_not_in_results():
    for folder in (V4/"phase5_incomplete_nqf_19sessions",V5):
        for mode in ("B1","B2","B3"):
            d=pl.read_parquet(folder/f"{mode}_cost/daily_equity.parquet")
            assert str(d["day"].min())>="2026-07-01"
            assert str(d["day"].max())<="2026-09-30"


def test_four_tick_stress_cost_and_queue_scenarios():
    report=json.loads((V4/"phase6/all_trials.json").read_text())
    by={(x["mode"],x["cost"]):x for x in report}
    assert len(by)==6
    for mode in ("B1","B2","B3"):
        a=by[(mode,"stress4tick")]
        q=by[(mode,"limit_queue1tick")]
        assert a["fee_per_side_usd"]==2.5
        assert a["adverse_slippage_points_per_side"]==1.0
        assert q["adverse_slippage_points_per_side"]==.25
        assert a["trades"]>=0 and q["trades"]>=0


def test_all_native_audits_and_dsr_limitation_retained():
    report=json.loads((V4/"phase56_independent_audit_v2.json").read_text())
    assert report["all_native_execution_audits_pass"]
    assert report["errors"]==[]
    assert report["trials_dsr_status"].startswith("UNREPRODUCIBLE")
    assert report["no_november_holdout_used"]
    for key in ("primary_nqf_subset","secondary_nas100_cross_source","phase6_dev"):
        assert all(not x["errors"] for x in report[key]["audits"].values())


def test_primary_gate_explicitly_fails_closed():
    a=json.loads((V4/"phase5_primary_blocker.json").read_text())
    assert a["classification"]=="BLOCKED_INCOMPLETE_PRIMARY_NQF"
    assert not a["primary_phase5_pass"]
    assert a["coverage_rate"]<0.5
