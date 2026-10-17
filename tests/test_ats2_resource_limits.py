"""Fail-closed ATS-2 kernel memory boundary regression cases."""
from __future__ import annotations

import json

import pytest

from src.research_control.ats2 import start_action, verify_result
from src.research_control.attempts import AttemptLedger
from src.research_control.resource_cgroup import (
    final_scope,
    sample_scope,
    unit_for_attempt,
)
from tests.test_ats2 import authorization, prepared


def test_unavailable_cgroup_does_not_consume_admission(tmp_path, monkeypatch):
    from src.research_control import ats2

    action, intent, data, contract, computation = prepared(tmp_path)
    grant, policy = authorization(tmp_path, action, intent)
    monkeypatch.setattr(ats2, "hard_memory_supported", lambda: False)
    denied = start_action(
        tmp_path, action, intent, computation, data, contract,
        grant=grant, trusted_policy_path=policy, list_jobs=lambda: set(),
    )
    assert denied == {"status": "BLOCKED", "reason_code": "HARD_MEMORY_ISOLATION_UNAVAILABLE"}
    ledger = AttemptLedger(tmp_path, action.session_id, list_jobs=lambda: set())
    assert ledger.events() == []
    assert not (tmp_path / "run_log/ats2/accepted").exists()


def test_corrupted_memory_attestation_cannot_be_verified(tmp_path):
    action, intent, data, contract, computation = prepared(tmp_path)
    grant, policy = authorization(tmp_path, action, intent)
    result = start_action(
        tmp_path, action, intent, computation, data, contract,
        grant=grant, trusted_policy_path=policy, list_jobs=lambda: set(),
    )
    assert result["status"] == "OUTPUT_READY", result
    path = tmp_path / result["resource_evidence"]
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["scope_verified"] is True
    assert document["terminal_scope"]["result"] in ("success", "COLLECTED")
    document["last_verified_scope"]["memory_swap_max_bytes"] = 1024**3
    path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    with pytest.raises(ValueError, match="OUTPUT_CHECKPOINT_INVALID|HARD_MEMORY_EVIDENCE_INVALID"):
        verify_result(tmp_path, action.session_id, result["attempt_id"])
    assert not (tmp_path / "run_log/ats2/accepted" /
                action.session_id / result["run_id"] / "verification.json").exists()


def test_cgroup_unit_names_and_unknown_membership_fail_closed():
    assert sample_scope("ats2-" + "0" * 32 + ".scope", 512) is None
    assert final_scope("ats2-" + "0" * 32 + ".scope")["result"] == "COLLECTED"
    with pytest.raises(ValueError, match="INVALID_RESOURCE_ATTEMPT_ID"):
        unit_for_attempt("not-an-attempt")
