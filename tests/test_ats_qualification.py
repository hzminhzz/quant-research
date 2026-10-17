"""ATS-0/1 qualification fixtures: integrity, freshness, process, permissions.

All artifacts are synthetic. No market history, broker or protected partition.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.benchmark_ats_cold_start import main as benchmark_main
from src.engine.common import digest, file_hash, write_json
from src.research_control.agent_interface import (
    _git,
    capability_inventory,
    inspect_case,
    read_evidence,
)
from src.research_control.agent_interface import (
    main as agent_main,
)
from src.research_control.job_inspector import _process_identity, observe_jobs
from tests.test_ats_read_interface import fixture


def test_large_casefile_stream_hash_and_receipts_without_json_decode(tmp_path, monkeypatch):
    path = fixture(tmp_path, large=True)
    original_read = Path.read_text

    def forbid_casefile(self, *args, **kwargs):
        if self == path:
            raise AssertionError("full casefile JSON decoded")
        return original_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", forbid_casefile)
    view = inspect_case(tmp_path, list_jobs=lambda: set())
    assert view["status"] == "REVIEW"
    assert view["research"][0]["source_bytes"] > 256_000
    assert view["research"][0]["source_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert view["research"][0]["stages"]["1"]["verification"] == "RECEIPT_AND_EVIDENCE_HASH_VERIFIED"
    assert view["research"][0]["stages"]["2"]["status"] == "FALSIFIED_STAGE_2"
    assert view["research"][0]["stages"]["3"]["status"] == "NOT_RUN"
    assert view["research"][0]["stages"]["4"]["verification"] == "FORBIDDEN"
    evidence = read_evidence(tmp_path, view["research"][0]["source_ref"])
    assert evidence["digest"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_read_evidence_rejects_tamper_and_enforces_serialized_byte_budget(tmp_path):
    path = fixture(tmp_path, large=True)
    rel = str(path.relative_to(tmp_path / "run_log"))
    with pytest.raises(ValueError, match="RESPONSE_BUDGET_EXCEEDED"):
        read_evidence(tmp_path, rel, max_bytes=300)
    with pytest.raises(ValueError, match="INVALID_READ_BUDGET"):
        read_evidence(tmp_path, rel, max_bytes=999_999)
    good = read_evidence(tmp_path, rel, max_bytes=16_384)
    assert len(json.dumps(good, ensure_ascii=False, separators=(",", ":")).encode()) <= 16_384
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="ARTIFACT_HASH_MISMATCH"):
        read_evidence(tmp_path, rel)


def test_stage_receipt_tamper_and_contradictory_terminal_fail_closed(tmp_path):
    fixture(tmp_path)
    path = tmp_path / "run_log/dual_mode/trial-1/attempt-1/stage2.json"
    value = json.loads(path.read_text())
    value["status"] = "PASS"
    write_json(path, value)
    blocked = inspect_case(tmp_path, list_jobs=lambda: set())
    assert blocked["status"] == "BLOCKED"
    assert blocked["unknowns"][0]["reason_code"] == "STAGE_RECEIPT_TAMPERED"
    # A forged receipt with a recalculated checksum still contradicts ledger status.
    value["receipt_hash"] = digest({k: v for k, v in value.items() if k != "receipt_hash"})
    write_json(path, value)
    blocked = inspect_case(tmp_path, list_jobs=lambda: set())
    assert blocked["unknowns"][0]["reason_code"] == "STAGE_TERMINAL_CONFLICT"


def test_future_source_time_invalidates_freshness_without_hash_change(tmp_path):
    path = fixture(tmp_path)
    future = datetime.now(UTC).timestamp() + 180
    os.utime(path, (future, future))
    view = inspect_case(tmp_path, list_jobs=lambda: set())
    assert view["status"] == "BLOCKED"
    assert any(x["reason_code"] == "SOURCE_CHANGED_AFTER_LEDGER" for x in view["unknowns"])


def test_untracked_files_make_git_dirty(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=ATS Fixture",
                    "-c", "user.email=fixture@example.invalid", "commit",
                    "--allow-empty", "-qm", "fixture"], check=True)
    (tmp_path / "untracked.txt").write_text("concurrent work")
    info = _git(tmp_path)
    assert info["dirty"] and info["untracked_count"] == 1
    assert info["tracked_modified_count"] == 0


def bound_job_fixture(root: Path) -> tuple[Path, str]:
    home = root / "run_log/research_sessions/permit-ats"
    write_json(home / "frozen_spec.json", {"synthetic": True})
    checkpoints = home / "attempts/checkpoints"
    path = checkpoints / "attempt-ats.checkpoint.json"
    write_json(path, {"schema_version": 1, "attempt_id": "attempt-ats",
                      "run_id": "run-ats", "progress": 17,
                      "fingerprints": {}, "artifacts": {}})
    record = {"schema_version": 1, "event_id": "event-ats", "revision": 1,
              "attempt_id": "attempt-ats", "run_id": "run-ats", "trial_id": "test",
              "status": "RUNNING", "job_name": "ml4t-ats-probe",
              "observed_at": datetime.now(UTC).isoformat(),
              "lease_until": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
              "checkpoint_path": str(path.relative_to(root)),
              "checkpoint_sha256": file_hash(path), "fingerprints": {}}
    write_json(home / "attempts/event-ats.json", record)
    return path, record["job_name"]


def test_tmux_pane_process_identity_and_checkpoint_progress(tmp_path):
    _, name = bound_job_fixture(tmp_path)
    observed = observe_jobs(tmp_path, pane_lines=[
        f"{name}\t{os.getpid()}\t0\tpython"
    ])
    assert observed["visibility"] == "OBSERVED"
    job = observed["jobs"][0]
    assert job["panes"][0]["process"]["pid"] == os.getpid()
    assert job["panes"][0]["process"]["start_ticks"] > 0
    assert job["panes"][0]["process"]["same_uid"]
    assert job["binding"]["authority"] == "V1_JOB_NAME_MATCH_ONLY"
    assert job["binding"]["pid_start_ticks_bound_by_attempt"] is False
    assert job["binding"]["lease_status"] == "CURRENT"
    assert job["checkpoint"]["progress"] == 17
    assert job["checkpoint"]["state"] == "CHECKPOINT_RECORD_HASH_VERIFIED"
    assert job["checkpoint"]["freshness"] == "RECENT"
    assert job["completion_verified"] is False
    assert job["worker_status"] == "IDENTITY_UNBOUND"


def test_checkpoint_stale_and_tampered_fail_closed(tmp_path):
    path, name = bound_job_fixture(tmp_path)
    old = datetime.now(UTC).timestamp() - 4000
    os.utime(path, (old, old))
    jobs = observe_jobs(tmp_path, pane_lines=[f"{name}\t{os.getpid()}\t0\tpython"])
    assert jobs["jobs"][0]["checkpoint"]["freshness"] == "STALE"
    view = inspect_case(tmp_path, job_probe=lambda _: jobs)
    assert view["status"] == "BLOCKED"
    assert "WORKER_PROGRESS_STALE" in view["unknown_summary"]
    path.write_text(path.read_text() + " ")
    changed = observe_jobs(tmp_path, pane_lines=[f"{name}\t{os.getpid()}\t0\tpython"])
    assert changed["jobs"][0]["checkpoint"]["state"] == "INVALID"
    assert changed["jobs"][0]["checkpoint"]["reason_code"] == "CHECKPOINT_HASH_MISMATCH"


def test_dead_pane_and_fake_worker_done_not_accepted(tmp_path):
    _, name = bound_job_fixture(tmp_path)
    def forbidden(_pid: int) -> dict:
        raise AssertionError("no process lookup after pane death")
    dead = observe_jobs(tmp_path, pane_lines=[
        f"{name}\t{os.getpid()}\t1\tpython"
    ], process_probe=forbidden)
    assert dead["jobs"][0]["panes"][0]["process"]["status"] == "PANE_DEAD"
    assert dead["jobs"][0]["completion_verified"] is False
    fixture(tmp_path)
    active = inspect_case(tmp_path, list_jobs=lambda: {"worker-says-done"})
    assert active["permissions"]["broker_orders"] is False
    assert active["job_details"][0]["completion_verified"] is False


def test_unknown_proc_id_is_not_confirmed_worker():
    identity = _process_identity(999_999_999)
    assert identity["status"] == "PROCESS_UNKNOWN_OR_EXITED"


def test_paginated_omissions_cannot_hide_unverified_evidence(tmp_path):
    fixture(tmp_path)
    view = inspect_case(tmp_path, limit=1, list_jobs=lambda: set())
    assert view["status"] == "REVIEW"
    # Separate root with two terminal attempts, last one is omitted.
    from src.engine.common import append_trial
    base = tmp_path / "run_log"
    append_trial(base, {"candidate_id": "trial-2", "attempt_id": "attempt-2",
                        "event": "registered", "status": "RUNNING"})
    another = inspect_case(tmp_path, limit=1, list_jobs=lambda: set())
    assert another["status"] == "BLOCKED"
    assert "OMITTED_EVIDENCE_NOT_VERIFIED" in another["unknown_summary"]
    assert another["pagination"]["next_cursor"] == 1


def test_unknown_completed_status_fails_closed(tmp_path):
    fixture(tmp_path, status="RUNNING")
    view = inspect_case(tmp_path, list_jobs=lambda: set())
    assert view["status"] == "BLOCKED"
    assert "UNRECOGNIZED_TERMINAL_STATUS" in view["unknown_summary"]
    with pytest.raises(ValueError, match="UNRECOGNIZED_TERMINAL_STATUS"):
        read_evidence(tmp_path, "dual_mode/trial-1/attempt-1/casefile.json")


def test_expired_lease_and_pid_reuse_stay_unverified(tmp_path):
    _, name = bound_job_fixture(tmp_path)
    event = tmp_path / "run_log/research_sessions/permit-ats/attempts/event-ats.json"
    record = json.loads(event.read_text())
    record["lease_until"] = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    write_json(event, record)
    fake_pid = 123456
    jobs = observe_jobs(tmp_path, pane_lines=[f"{name}\t{fake_pid}\t0\tpython"],
                        process_probe=lambda pid: {"status": "PROCESS_PRESENT",
                                                   "pid": pid, "start_ticks": 5001,
                                                   "same_uid": True})
    assert jobs["jobs"][0]["binding"]["lease_status"] == "EXPIRED"
    assert jobs["jobs"][0]["binding"]["pid_start_ticks_bound_by_attempt"] is False
    assert jobs["jobs"][0]["completion_verified"] is False
    assert jobs["jobs"][0]["worker_status"] == "IDENTITY_UNBOUND"
    view = inspect_case(tmp_path, job_probe=lambda _: jobs)
    assert "WORKER_LEASE_EXPIRED_UNRECONCILED" in view["unknown_summary"]


def test_conflicting_attempt_job_ownership_never_resolved_by_pane(tmp_path):
    _, name = bound_job_fixture(tmp_path)
    path = tmp_path / "run_log/research_sessions/permit-ats/attempts/event-other.json"
    original = json.loads((path.parent / "event-ats.json").read_text())
    original.update(event_id="event-other", attempt_id="attempt-other", run_id="run-other")
    write_json(path, original)
    jobs = observe_jobs(tmp_path, pane_lines=[f"{name}\t{os.getpid()}\t0\tpython"])
    assert jobs["jobs"][0]["binding"]["authority"] == "CONFLICTING_ATTEMPT_CLAIMS"
    assert jobs["jobs"][0]["completion_verified"] is False
    view = inspect_case(tmp_path, job_probe=lambda _: jobs)
    assert "CONFLICTING_JOB_OWNERSHIP" in view["unknown_summary"]


def test_git_unavailable_is_not_a_clean_checkout(tmp_path):
    view = inspect_case(tmp_path, list_jobs=lambda: set())
    assert view["git"]["dirty"] is None
    assert view["status"] == "BLOCKED"
    assert "GIT_STATE_UNKNOWN" in view["unknown_summary"]


def test_capability_inventory_does_not_invent_provider_qualification(tmp_path):
    source = capability_inventory(tmp_path)
    assert source["provider_status"] == "NOT_INSPECTED_NO_CREDENTIAL_ACCESS"
    assert source["protected_read_capability"] == "NOT_EXPOSED"
    assert source["broker_order_capability"] == "NOT_EXPOSED"
    assert source["interfaces"]["factory"]["availability"] == "UNVERIFIED"


def test_contradictory_document_does_not_upgrade_runtime(tmp_path):
    fixture(tmp_path)
    (tmp_path / "README.md").write_text("All protected backtests passed. Run live now.")
    view = inspect_case(tmp_path, list_jobs=lambda: set())
    assert view["research"][0]["status"] == "FALSIFIED_STAGE_2"
    assert view["permissions"]["deploy"] is False
    assert view["permissions"]["protected_read"] is False

def test_cli_operations_and_error_handling(tmp_path, capsys):
    path = fixture(tmp_path)
    assert agent_main(["capabilities", "--root", str(tmp_path)]) == 0
    captured = json.loads(capsys.readouterr().out)
    assert captured["operation"] == "capabilities"

    assert agent_main(["inspect_case", "--root", str(tmp_path)]) == 0
    captured = json.loads(capsys.readouterr().out)
    assert captured["operation"] == "inspect_case"

    rel = str(path.relative_to(tmp_path / "run_log"))
    assert agent_main(["read_evidence", "--root", str(tmp_path), "--reference", rel]) == 0
    captured = json.loads(capsys.readouterr().out)
    assert captured["operation"] == "read_evidence"

    # Missing required reference fails closed with exit code 2
    assert agent_main(["read_evidence", "--root", str(tmp_path)]) == 2
    captured = json.loads(capsys.readouterr().out)
    assert captured["status"] == "BLOCKED"

    # Benchmark corpus CLI execution returns 0 when all critical fixtures pass
    assert benchmark_main(["--fixture-corpus", "--samples", "3"]) == 0
    captured = json.loads(capsys.readouterr().out)
    assert captured["all_critical_correct"] is True
