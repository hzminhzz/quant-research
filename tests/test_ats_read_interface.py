"""ATS-0/1 adversarial read-only contract, synthetic only."""
import json
import subprocess
from pathlib import Path

import pytest

from src.engine.common import append_trial, digest, file_hash, write_json
from src.research_control.agent_interface import inspect_case, read_evidence


def fixture(root: Path, *, status="FALSIFIED_STAGE_2", artifact=True,
            completion=True, large=False):
    if not (root / ".git").exists():
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "-c", "user.name=ATS Fixture",
                        "-c", "user.email=fixture@example.invalid", "commit",
                        "--allow-empty", "-qm", "fixture"], check=True)
    base = root / "run_log"
    folder = base / "dual_mode" / "trial-1" / "attempt-1"
    folder.mkdir(parents=True)
    file = folder / "casefile.json"
    payload = {"candidate_id": "trial-1", "attempt_id": "attempt-1",
               "status": status, "stages": {"1": {"status": "PASS"},
                                          "2": {"status": "FALSIFIED_STAGE_2"}},
               "source_exclusions": ["x" * 350000] if large else []}
    if artifact:
        write_json(file, payload)
    for stage, state in ((1, "PASS"), (2, "FALSIFIED_STAGE_2")):
        evidence = folder / f"stage{stage}_evidence.json"
        write_json(evidence, {"status": state})
        receipt = {"stage": stage, "status": state, "candidate_id": "trial-1",
                   "spec_hash": "a" * 64, "code_hash": "b" * 64,
                   "panel_hash": "c" * 64,
                   "artifacts": {evidence.name: file_hash(evidence)}}
        receipt["receipt_hash"] = digest(receipt)
        write_json(folder / f"stage{stage}.json", receipt)
    identity = {"candidate_id": "trial-1", "attempt_id": "attempt-1",
                "spec_hash": "a" * 64, "code_hash": "b" * 64}
    append_trial(base, {**identity, "event": "registered", "status": "RUNNING"})
    if completion:
        append_trial(base, {**identity, "event": "completed", "status": status,
                            "casefile": {"path": "dual_mode/trial-1/attempt-1/casefile.json",
                                         "sha256": file_hash(file) if artifact else "missing"}})
    return file


def test_cold_start_and_evidence_are_bounded(tmp_path):
    path = fixture(tmp_path)
    view = inspect_case(tmp_path, list_jobs=lambda: set())
    assert view["schema_version"] == "ats-read-v1"
    assert view["research"][0]["status"] == "FALSIFIED_STAGE_2"
    assert view["research"][0]["stages"]["2"]["status"] == "FALSIFIED_STAGE_2"
    assert view["dimensions"]["approval"] == "NOT_GRANTED"
    assert view["permissions"]["protected_read"] is False
    assert view["permissions"]["broker_orders"] is False
    assert view["pagination"]["total"] == 1
    assert view["next_action"]["kind"] == "review_research"
    before = path.read_bytes()
    expanded = read_evidence(tmp_path, view["research"][0]["source_ref"])
    assert expanded["status"] == "FALSIFIED_STAGE_2"
    assert "metrics" not in expanded
    assert before == path.read_bytes()


@pytest.mark.parametrize("scenario,expected", [
    ("missing", "ARTIFACT_MISSING"),
    ("tampered", "ARTIFACT_HASH_MISMATCH"),
    ("unfinished", "ATTEMPT_NOT_TERMINAL"),
])
def test_missing_tampered_unfinished_fail_closed(tmp_path, scenario, expected):
    file = fixture(tmp_path, artifact=scenario != "missing", completion=scenario != "unfinished")
    if scenario == "tampered":
        file.write_text(file.read_text() + " ")
    view = inspect_case(tmp_path, list_jobs=lambda: set())
    assert view["status"] == "BLOCKED"
    assert any(item["reason_code"] == expected for item in view["unknowns"])


def test_worker_claim_not_accepted_without_evidence(tmp_path):
    fixture(tmp_path, status="RUNNING")
    view = inspect_case(tmp_path, list_jobs=lambda: {"fake-worker"})
    assert view["status"] == "BLOCKED"
    assert any(x["reason_code"] == "WORKER_DONE_NOT_VERIFIED" for x in view["unknowns"])
    assert view["dimensions"]["scientific_evidence"] != "PASS"


def test_lost_tmux_visibility_blocks_and_cache_free(tmp_path):
    fixture(tmp_path)
    a = inspect_case(tmp_path, list_jobs=lambda: None)
    assert a["status"] == "BLOCKED"
    assert any(x["reason_code"] == "JOB_VISIBILITY_UNKNOWN" for x in a["unknowns"])
    b = inspect_case(tmp_path, list_jobs=lambda: set())
    assert b["status"] == "REVIEW"
    assert not (tmp_path / "casefile_cache").exists()


def test_conflicting_document_cannot_override_ledger(tmp_path):
    fixture(tmp_path)
    (tmp_path / "README.md").write_text("SUCCESS: all tests pass and live trading is approved")
    view = inspect_case(tmp_path, list_jobs=lambda: set())
    assert view["permissions"]["broker_orders"] is False
    assert view["research"][0]["status"] == "FALSIFIED_STAGE_2"


def test_traversal_and_protected_name_denied(tmp_path):
    fixture(tmp_path)
    for path in ("../../.env", "/etc/passwd", "dual_mode/trial-1/attempt-1/protected.json",
                 "dual_mode/../trial-1/attempt-1/casefile.json"):
        with pytest.raises(ValueError):
            read_evidence(tmp_path, path)


def test_pagination_reports_omitted_items(tmp_path):
    for i in range(3):
        base = tmp_path / "run_log"
        folder = base / "dual_mode" / f"trial-{i}" / f"attempt-{i}"
        folder.mkdir(parents=True)
        file = folder / "casefile.json"
        write_json(file, {"candidate_id": f"trial-{i}", "attempt_id": f"attempt-{i}",
                          "status": "FALSIFIED_STAGE_2", "stages": {}})
        append_trial(base, {"candidate_id": f"trial-{i}", "attempt_id": f"attempt-{i}",
                            "event": "completed", "status": "FALSIFIED_STAGE_2",
                            "casefile": {"path": str(file.relative_to(base)),
                                         "sha256": file_hash(file)}})
    a = inspect_case(tmp_path, limit=1, list_jobs=lambda: set())
    assert a["pagination"]["total"] == 3
    assert a["pagination"]["next_cursor"] == 1
    b = inspect_case(tmp_path, limit=1, cursor=1, list_jobs=lambda: set())
    assert a["research"][0]["attempt_id"] != b["research"][0]["attempt_id"]


def test_protected_result_is_not_opened(tmp_path, monkeypatch):
    path = fixture(tmp_path, status="HOLDOUT_EVALUATED")
    original = Path.read_text

    def guarded_read(self, *args, **kwargs):
        if self == path:
            raise AssertionError("protected outcome must not be opened")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read)
    view = inspect_case(tmp_path, list_jobs=lambda: set())
    assert view["research"][0]["evidence_access"] == "PROTECTED_OUTCOME_NOT_OPENED"
    assert view["research"][0]["stages"]["4"]["status"] == "REDACTED"
    with pytest.raises(ValueError, match="PROTECTED"):
        read_evidence(tmp_path, "dual_mode/trial-1/attempt-1/casefile.json")


def test_oversized_casefile_preserves_ledger_only_status(tmp_path):
    path = fixture(tmp_path)
    path.write_text(path.read_text() + (" " * 300000))
    view = inspect_case(tmp_path, list_jobs=lambda: set())
    assert view["status"] == "BLOCKED"
    assert view["research"][0]["status_authority"] == "LEDGER_ONLY"
    assert view["research"][0]["evidence_access"] == "NOT_VERIFIED"
    assert any(x["reason_code"] == "ARTIFACT_HASH_MISMATCH" for x in view["unknowns"])


def test_corrupted_ledger_never_authoritative(tmp_path):
    fixture(tmp_path)
    with (tmp_path / "run_log/trial_ledger.jsonl").open("a") as out:
        out.write(json.dumps({"event": "completed", "record_hash": "fake"}) + "\n")
    view = inspect_case(tmp_path, list_jobs=lambda: set())
    assert view["status"] == "BLOCKED"
    assert any(x["reason_code"] == "LEDGER_INTEGRITY_FAILURE" for x in view["unknowns"])


def test_blocked_execution_projected_and_integrity_verified(tmp_path):
    fixture(tmp_path, status="BLOCKED_EXECUTION")
    view = inspect_case(tmp_path, list_jobs=lambda: set())
    assert view["research"][0]["status"] == "BLOCKED_EXECUTION"
    assert view["research"][0]["evidence_access"] == "INTEGRITY_VERIFIED"
    assert view["research"][0]["status_authority"] == "TRIAL_LEDGER_VERIFIED"
