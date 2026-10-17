"""Evidence gates for approved DAX/Nikkei follow-up. No simulation."""
import json
import hashlib
from pathlib import Path

HERE=Path(__file__).resolve().parents[1]
ROOT=HERE/"run_log/one_bar_b0_cross_indices_20261012"
DIR=ROOT/"followup_dax_nikkei_20261012"

def read(name):
    return json.loads((DIR/name).read_text())

def test_pre_refresh_archive_has_same_broken_price_data():
    info=read("dax_source_comparison.json")
    for x in info["samples"]:
        assert x["live"]["exists"]
        assert x["pre_refresh"]["exists"]
        assert x["paired"]["overlap"]>0
        assert x["paired"]["big_close_disagreement"]==0
        assert x["paired"]["close_equal"]==x["paired"]["overlap"]
    assert any(x["live"]["lt3000"]>10000 for x in info["samples"] if x["year"]>=2024)

def test_quarantine_cannot_make_2024_2025_usable():
    r=read("dax_quality_repair_gate.json")
    assert r["status"]=="DIAGNOSTIC_QUARANTINE_ONLY_NOT_REPAIRED"
    assert r["years"]["2024"]["retained_complete_bin_fraction_of_original"]<0.3
    assert r["years"]["2025"]["retained_complete_bin_fraction_of_original"]<0.16
    assert r["years"]["2026"]["retained_complete_bin_fraction_of_original"]<0.75
    assert r["daily_reference"]["source_provenance_verified"] is False
    for i in ("2024","2025","2026"):
        v=r["years"][i]
        assert v["raw_rows"]==v["all_OHLC_above_floor_rows"]+v["quarantined_rows"]
        assert v["safe_30m"]["complete_30m_bins"]<=v["raw_30m"]["complete_30m_bins"]
    for x in r["source_sample_sha256"]:
        assert hashlib.sha256(Path(x["file"]).read_bytes()).hexdigest()==x["sha256"]

def test_nikkei_5m_source_is_aggregated_one_minute_data():
    x=read("nikkei_execution_validation.json")
    r=x["five_minute_crosscheck"]
    assert r["overlap"]==36447
    assert all(r[z]==r["overlap"] for z in ("matching_open","matching_high","matching_low","matching_close"))
    assert x["source_independence_not_established"] is True

def test_nikkei_2026_execution_cannot_be_certified():
    r=read("nikkei_execution_validation.json")
    m=r["metrics"]
    assert r["status"]=="EXECUTION_VALIDATION_INCONCLUSIVE"
    assert m["native_closed_evaluation_trades"]==251
    assert m["matched_evaluation_trade_ambiguous"]==91
    assert m["matched_ambiguous_source_minute_count"]>=91
    assert 0.06<m["stop_distance_pct_of_entry"]["median"]<0.12
    assert r["pessimistic_R"] < 0 < m["observed_native_total_R"]
    assert not r["pessimistic_is_native_replay"]

def test_unchanged_original_source_and_research_only():
    status=json.loads((ROOT/"status.json").read_text())
    assert status["approved_for_live"] is False
    assert status["original_promote_checksum_verified"]
    q=json.loads((ROOT/"phase34/final_research_metrics.json").read_text())
    assert q["audit"]["status"]=="PASS"
