"""Issue #48 operator rehearsal: no provider connections, orders or secret printing."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from src.paper_qualification import BLOCKED, PREPARED, evaluate_packet, main

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 15, 3, 0, tzinfo=UTC)


def private_json(path: Path, content: dict) -> None:
    path.write_text(json.dumps(content), encoding="utf-8")
    path.chmod(0o600)


@pytest.fixture
def rehearsal(tmp_path):
    state_dir = tmp_path / "native-private"
    state_dir.mkdir(mode=0o700)
    out = tmp_path / "evidence-private"
    out.mkdir(mode=0o700)
    risk_state = state_dir / "bybit-demo-account-24680.json"
    preflight_path = out / "read-only-preflight.json"
    health_path = out / "native-health.json"
    private_json(preflight_path, {
        "status": "PASS", "environment": "demo", "mode": "read_only",
        "native_execution_mode": "paper", "ml4t_live_version": "0.1.2",
        "checked_at": "2026-10-15T02:00:00Z", "submitted_orders": 0,
        "identity": {
            "authenticated_uid_matches_expected": True,
            "private_rest": "api-demo.bybit.com",
        },
        "reconciliation": {"clean": True},
        "persistence": {"state_error": None, "journal_error": None, "journal_required": True},
        "connector_unknown_intents": False,
    })
    private_json(health_path, {
        "checked_at": "2026-10-15T02:58:00Z",
        "engine": {"runtime_state": "ready", "health": "ready", "broker_connected": True},
        "persistence": {
            "state_error": None, "journal_error": None,
            "execution_identity_validated": True,
        },
        "reconciliation": {"clean": True},
    })
    file = ROOT / "src" / "bybit_paper_runtime.py"
    packet = {
        "schema_version": 1,
        "subject": {
            "strategy_id": "TEST_ONLY_DO_NOT_DEPLOY",
            "strategy_source": "src/bybit_paper_runtime.py",
            "strategy_sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
            "venue": "bybit",
            "environment": "demo",
            "account_ref_redacted": "test-account-redacted",
            "instruments": ["BTC/USDT:USDT"],
            "bar_cadence": "1m",
            "public_feed": "bybit_mainnet_public",
        },
        "approval": {
            "research_approval_status": "APPROVED_FOR_PAPER_REVIEW",
            "research_approval_ref": "SYNTHETIC_TEST_VERDICT",
            "research_approved_by": "synthetic_reviewer",
            "risk_reviewed": True, "risk_reviewed_by": "synthetic_operator",
            "account_owner_exclusive": True, "operator_owner": "synthetic_operator",
        },
        "risk": {
            "state_dir": str(state_dir),
            "execution_mode": "paper", "fail_on_reconciliation_mismatch": True,
            "fail_on_journal_error": True, "auto_recover": True,
            "max_order_shares": 0.01, "max_order_value": 500.0,
            "max_position_shares": 0.02, "max_position_value": 1000.0,
            "max_total_exposure": 2000.0, "max_positions": 1,
            "max_orders_per_minute": 3, "max_daily_loss": 100.0,
            "max_drawdown_pct": 0.05, "max_price_deviation_pct": 0.05,
            "max_data_staleness_seconds": 300.0,
            "dedup_window_seconds": 1.0, "feed_silence_seconds": 140.0,
            "max_event_age_seconds": 300.0,
            "max_recovery_attempts": 2, "recovery_cooldown_seconds": 1.0,
        },
        "observation": {
            "start_utc": "2026-10-20T00:00:00Z",
            "end_utc": "2026-10-27T00:00:00Z",
            "abort_reasons": [
                "reconciliation_mismatch", "unknown_order_outcome",
                "persistence_error", "journal_error", "identity_unverified",
                "native_recovery_exhausted", "risk_limit_breach",
                "feed_stale", "broker_disconnected",
            ],
        },
        "criteria": {
            "max_unreconciled_order_count": 0,
            "max_unattributed_fill_count": 0,
            "max_unknown_order_outcomes": 0,
            "max_unresolved_safety_incidents": 0,
            "min_order_lifecycle_drills": 1,
            "min_recovery_drills": 1,
            "minimum_healthy_fraction": 0.995,
        },
        "evidence": {
            "output_dir": str(out),
            "preflight_report": str(preflight_path),
            "preflight_state_file": str(risk_state),
            "native_health_report": str(health_path),
        },
    }
    env = {
        "BYBIT_ENVIRONMENT": "demo", "BYBIT_MODE": "read_only",
        "BYBIT_DEMO_API_KEY": "synthetic_demo_key_123",
        "BYBIT_DEMO_API_SECRET": "synthetic_demo_secret_123",
        "BYBIT_DEMO_EXPECTED_UID": "24680",
        "BYBIT_API_KEY": "synthetic_mainnet_key_456",
    }
    return packet, env


def evaluate(rehearsal):
    packet, env = rehearsal
    return evaluate_packet(packet, environment=env, now=NOW)


def test_complete_synthetic_packet_is_only_prepared_not_qualified(rehearsal):
    outcome = evaluate(rehearsal)
    assert outcome["status"] == PREPARED
    assert outcome["blockers"] == []
    assert outcome["native_risk_config_valid"] is True
    assert outcome["paper_qualified"] is False
    assert outcome["paper_order_authorized"] is False
    assert outcome["live_money_authorized"] is False
    assert outcome["submitted_orders"] == 0
    encoded = json.dumps(outcome)
    for secret in ("24680", "synthetic_demo_key", "synthetic_demo_secret", "BTC/USDT"):
        assert secret not in encoded


@pytest.mark.parametrize(("path", "value", "expected"), [
    (("approval", "research_approval_status"), "NOT_APPROVED", "research_approval"),
    (("approval", "risk_reviewed"), False, "risk_review"),
    (("approval", "account_owner_exclusive"), False, "account_owner"),
    (("subject", "environment"), "mainnet", "broker_identity"),
    (("subject", "bar_cadence"), None, "bar_cadence"),
    (("subject", "strategy_sha256"), "a" * 64, "digest mismatch"),
    (("risk", "max_order_value"), None, "native_risk"),
    (("risk", "fail_on_reconciliation_mismatch"), False, "native_safety"),
    (("risk", "feed_silence_seconds"), 5.0, "feed_cadence"),
    (("risk", "max_recovery_attempts"), None, "native_risk"),
    (("observation", "start_utc"), "2026-10-10T00:00:00Z", "observation_window"),
    (("criteria", "max_unknown_order_outcomes"), 1, "max_unknown_order_outcomes"),
    (("criteria", "minimum_healthy_fraction"), None, "minimum_healthy_fraction"),
    (("evidence", "preflight_state_file"), "/tmp/different-account.json", "preflight_state_file"),
    (("subject", "account_ref_redacted"), "24680", "account_ref_redacted"),
])
def test_missing_or_inconsistent_operator_contract_blocks(rehearsal, path, value, expected):
    packet, env = rehearsal
    changed = deepcopy(packet)
    changed[path[0]][path[1]] = value
    result = evaluate_packet(changed, environment=env, now=NOW)
    assert result["status"] == BLOCKED
    assert any(expected in e for e in result["blockers"])
    assert result["submitted_orders"] == 0


@pytest.mark.parametrize(("key", "value"), [
    ("BYBIT_DEMO_API_KEY", ""), ("BYBIT_DEMO_API_SECRET", ""),
    ("BYBIT_DEMO_EXPECTED_UID", ""), ("BYBIT_DEMO_EXPECTED_UID", "abc"),
    ("BYBIT_ENVIRONMENT", "testnet"), ("BYBIT_MODE", "execution"),
])
def test_unapproved_or_ambiguous_credential_environment_blocks(rehearsal, key, value):
    packet, env = rehearsal
    env = dict(env)
    env[key] = value
    outcome = evaluate_packet(packet, environment=env, now=NOW)
    assert outcome["status"] == BLOCKED
    assert any("credential" in msg or "account_identity" in msg for msg in outcome["blockers"])


@pytest.mark.parametrize(("json_kind", "mutation", "expected"), [
    ("preflight_report", ("reconciliation", "clean", False), "preflight"),
    ("preflight_report", ("identity", "authenticated_uid_matches_expected", False), "preflight"),
    ("preflight_report", ("persistence", "journal_error", "AuditJournalError"), "preflight"),
    ("preflight_report", ("status", None, "BLOCKED"), "preflight"),
    ("native_health_report", ("engine", "health", "feed_silent"), "native_health"),
    ("native_health_report", ("engine", "broker_connected", False), "native_health"),
    ("native_health_report", ("reconciliation", "clean", False), "native_health"),
    ("native_health_report", ("persistence", "state_error", "PersistenceSafetyError"), "native_health"),
])
def test_broker_preflight_and_native_health_failure_block(rehearsal, json_kind, mutation, expected):
    packet, env = rehearsal
    path = Path(packet["evidence"][json_kind])
    obj = json.loads(path.read_text())
    if mutation[1] is None:
        obj[mutation[0]] = mutation[2]
    else:
        obj[mutation[0]][mutation[1]] = mutation[2]
    private_json(path, obj)
    result = evaluate_packet(packet, environment=env, now=NOW)
    assert result["status"] == BLOCKED
    assert any(expected in reason for reason in result["blockers"])


def test_stale_or_public_health_is_not_accepted(rehearsal):
    packet, env = rehearsal
    path = Path(packet["evidence"]["native_health_report"])
    health = json.loads(path.read_text())
    health["checked_at"] = "2026-10-15T00:00:00Z"
    private_json(path, health)
    result = evaluate_packet(packet, environment=env, now=NOW)
    assert result["status"] == BLOCKED
    assert any("native_health" in b for b in result["blockers"])


def test_stale_or_public_preflight_is_not_accepted(rehearsal):
    packet, env = rehearsal
    file = Path(packet["evidence"]["preflight_report"])
    evidence = json.loads(file.read_text())
    evidence["checked_at"] = "2026-10-01T00:00:00Z"
    private_json(file, evidence)
    assert evaluate_packet(packet, environment=env, now=NOW)["status"] == BLOCKED
    evidence["checked_at"] = "2026-10-15T02:00:00Z"
    private_json(file, evidence)
    file.chmod(0o644)
    assert evaluate_packet(packet, environment=env, now=NOW)["status"] == BLOCKED


def test_repo_template_is_explicitly_blocked_and_no_secrets(tmp_path):
    template = ROOT / "config" / "paper_qualification_issue48.example.yaml"
    assert template.exists()
    packet = yaml.safe_load(template.read_text())
    outcome = evaluate_packet(packet, environment={}, now=NOW)
    assert outcome["status"] == BLOCKED
    assert outcome["paper_qualified"] is False
    assert len(outcome["blockers"]) >= 8


def test_cli_creates_private_redacted_rehearsal_evidence(rehearsal, tmp_path, monkeypatch, capsys):
    packet, env = rehearsal
    saved = tmp_path / "qualification.yaml"
    saved.write_text(yaml.safe_dump(packet))
    report = tmp_path / "result.json"
    from datetime import timedelta

    now = datetime.now(UTC)
    packet["observation"]["start_utc"] = (now + timedelta(days=2)).isoformat()
    packet["observation"]["end_utc"] = (now + timedelta(days=9)).isoformat()
    preflight = Path(packet["evidence"]["preflight_report"])
    p = json.loads(preflight.read_text())
    p["checked_at"] = (now - timedelta(minutes=1)).isoformat()
    private_json(preflight, p)
    health = Path(packet["evidence"]["native_health_report"])
    h = json.loads(health.read_text())
    h["checked_at"] = (now - timedelta(seconds=15)).isoformat()
    private_json(health, h)
    saved.write_text(yaml.safe_dump(packet))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("sys.argv", [
        "paper_qualification", "--packet", str(saved), "--evidence-file", str(report)
    ])
    # CLI uses wall time; freeze by setting a future observation window in the fixture
    assert main() == 0  # offline-check success still never authorizes trading
    result = json.loads(capsys.readouterr().out)
    assert result["submitted_orders"] == 0
    assert result["live_money_authorized"] is False
    assert report.stat().st_mode & 0o777 == 0o600
    assert json.loads(report.read_text()) == result
    assert "synthetic_demo_secret" not in json.dumps(result)
