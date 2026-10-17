"""Registration and source-inventory invariants; no trading simulation."""
from datetime import datetime, timezone
from pathlib import Path
import json
import sys

import polars as pl
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import audit_one_bar_b0_cross_indices_20261012 as audit


def test_frozen_original_b0_and_zero_new_backtests():
    cfg = yaml.safe_load((ROOT / "config/research_sessions/one_bar_b0_cross_indices_20261012.yaml").read_text())
    ledger = json.loads((audit.OUT / "trial_ledger.json").read_text())
    assert cfg["core_B0_rules"]["protective_stop_index_points"] == 50
    assert cfg["core_B0_rules"]["maximum_entries_per_chicago_session"] == 2
    assert cfg["core_B0_rules"]["added_filters"] == []
    assert cfg["phases"]["phase4_native_ml4t"] == "NOT_STARTED"
    assert ledger["new_backtest_trials_executed"] == 0
    assert len(ledger["trials"]) == 5


def test_no_quality_scan_past_stated_cutoff_and_nq_original_identity():
    stats = json.loads((audit.OUT / "phase2_quality.json").read_text())
    manifest = json.loads((audit.OUT / "source_manifest.json").read_text())
    assert manifest["NQ"]["same_partition_paths_as_frozen_control"] is True
    for instrument in ("NQ", "ES", "DAX", "NIKKEI225"):
        row = stats[instrument]
        assert row["rows"] > 1000000
        assert datetime.fromisoformat(row["last_utc"]) < audit.END
        assert datetime.fromisoformat(row["first_utc"]) >= audit.BEGIN
        assert row["duplicated_timestamps"] == 0
        assert row["invalid_ohlc"] == 0
        assert row["null_ohlc"] == 0


def test_es_schema_drift_is_normalized_read_only():
    es = audit.STORE / "index_minute_ES"
    old = es / "year=2012/month=10/data.parquet"
    later = es / "year=2013/month=1/data.parquet"
    assert "year" not in pl.read_parquet_schema(old)
    assert "year" in pl.read_parquet_schema(later)
    normalized = audit.scan_index([old, later])
    assert normalized.height > 0
    assert set(normalized.columns) == set(audit.COLUMNS)
    assert normalized["timestamp"].dtype == pl.Datetime("us", "UTC")
    assert normalized["timestamp"].min() >= audit.BEGIN
    assert normalized["timestamp"].max() < audit.END


def test_hang_seng_available_only_at_different_frequency():
    quality = json.loads((audit.OUT / "phase2_quality.json").read_text())
    manifest = json.loads((audit.OUT / "source_manifest.json").read_text())
    assert quality["HSI"]["status"] == "BLOCKED_1M_NOT_FOUND_5M_AVAILABLE"
    assert quality["HSI"]["alternate_frequency"] == "5m"
    assert manifest["HSI"]["one_minute_source"] is None
    assert Path(manifest["HSI"]["five_minute_source"]).is_file()
