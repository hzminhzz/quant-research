from __future__ import annotations

import json

from src.validation_status import approval_status, load_validation_status


def test_missing_status_fails_closed(tmp_path):
    assert approval_status(tmp_path / "missing.json") == "NOT_APPROVED"


def test_blocking_gate_overrides_approved_label(tmp_path):
    path = tmp_path / "status.json"
    path.write_text(
        json.dumps({"status": "APPROVED", "blocking_gates": ["input_data_unavailable"]}),
        encoding="utf-8",
    )
    status = load_validation_status(path)
    assert status["status"] == "NOT_APPROVED"


def test_empty_gate_list_does_not_approve_without_explicit_status(tmp_path):
    path = tmp_path / "status.json"
    path.write_text(json.dumps({"blocking_gates": []}), encoding="utf-8")
    assert approval_status(path) == "NOT_APPROVED"
