"""Tests for ATS-3 standalone read-only metrics service."""
from __future__ import annotations

import json
from pathlib import Path

from src.research_control.ats3_metrics_service import render_metrics


def test_render_metrics_valid_state_dir():
    state_dir = Path("/home/quant/.local/state/quant-research")
    metrics_text = render_metrics(state_dir, state="stopped")
    assert "ml4t_live_snapshot_ok 1" in metrics_text
    assert 'ml4t_live_engine_state{state="stopped"} 1' in metrics_text
    assert 'ml4t_live_engine_health{health="stopped"} 1' in metrics_text
    assert "ml4t_live_broker_connected 0" in metrics_text
    assert "ml4t_live_audit_evidence_available 1" in metrics_text
    assert "ml4t_live_native_event_count 115" in metrics_text
    assert "ml4t_live_audit_mode 1" in metrics_text


def test_render_metrics_missing_journal_fails_closed(tmp_path: Path):
    health = {
        "engine": {"health": "stopped", "broker_connected": False},
        "persistence": {"execution_identity_validated": True},
        "reconciliation": {"clean": True},
    }
    (tmp_path / "bybit-demo-native-health.json").write_text(json.dumps(health))
    metrics_text = render_metrics(tmp_path, state="stopped")
    assert "ml4t_live_snapshot_ok 1" in metrics_text
    assert "ml4t_live_audit_evidence_available 0" in metrics_text
    assert "ml4t_live_native_event_count 0" in metrics_text


def test_render_metrics_malformed_journal_fails_closed(tmp_path: Path):
    health = {
        "engine": {"health": "stopped", "broker_connected": False},
        "persistence": {"execution_identity_validated": True},
        "reconciliation": {"clean": True},
    }
    (tmp_path / "bybit-demo-native-health.json").write_text(json.dumps(health))
    (tmp_path / "bybit-demo-account-593641111-journal.jsonl").write_text("NOT_VALID_JSON\n")
    metrics_text = render_metrics(tmp_path, state="stopped")
    assert "ml4t_live_snapshot_ok 1" in metrics_text
    assert "ml4t_live_audit_evidence_available 0" in metrics_text
    assert "ml4t_live_native_event_count 0" in metrics_text


def test_render_metrics_missing_health_fails_closed(tmp_path: Path):
    metrics_text = render_metrics(tmp_path, state="stopped")
    assert "ml4t_live_snapshot_ok 0" in metrics_text
    assert "ml4t_live_state_known 0" in metrics_text
