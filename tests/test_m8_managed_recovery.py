"""Real tmux interruption and successor replay using synthetic files only."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import shlex
import shutil
import signal
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.research_control.attempts import (
    AttemptLedger,
    launch_managed_worker,
    tmux_sessions,
)
from src.research_control.casefile import inspect_resume
from tests.test_run_permit import gate, setup_trial

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "scripts/managed_recovery_fixture.py"
pytestmark = pytest.mark.slow


def _wait_for(predicate, *, timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("timed out waiting for managed test worker")


def _start_tmux(name: str, cwd: Path, args: list[str], log_path: Path) -> str:
    sessions = tmux_sessions()
    assert sessions is not None, "tmux visibility must be available before launch"
    assert name not in sessions, "test-owned tmux name must be unused"
    command = (shlex.join([sys.executable, str(WORKER), *args])
               + " >> " + shlex.quote(str(log_path)) + " 2>&1")
    started = launch_managed_worker(
        name, cwd, [sys.executable, str(WORKER), *args], log_path=log_path
    )
    assert (started.status, started.reason_code) == ("LAUNCH", "JOB_LAUNCHED"), started.detail
    assert name in (tmux_sessions() or set())
    return command


def _stop_owned_worker(name: str, pid_file: Path) -> None:
    sessions = tmux_sessions()
    assert sessions is not None and name in sessions
    pid = int(pid_file.read_text(encoding="utf-8"))
    os.kill(pid, signal.SIGKILL)
    _wait_for(lambda: name not in (tmux_sessions() or set()))


def _write_durable_evidence(path: Path, *, tmp_path: Path, ledger: AttemptLedger,
                            first_id: str, successor_id: str, job: str,
                            original_pid: str, partial: Path, result: Path,
                            worker_log: Path, tmux_before: set[str],
                            permit, started_at: str, killed_at: str, completed_at: str,
                            launch_commands: list[str]) -> None:
    outdir = path.parent / "recovery_qualification_artifacts" / f"{first_id}-{successor_id}"
    outdir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for attempt_id in (first_id, successor_id):
        for event in ledger.path.glob("*.json"):
            try:
                value = json.loads(event.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if value.get("attempt_id") == attempt_id:
                target = outdir / "events" / event.name
                target.parent.mkdir(exist_ok=True)
                shutil.copy2(event, target)
                files.append(target)
        for checkpoint in (ledger.path / "checkpoints").glob(f"{attempt_id}.*.json"):
            target = outdir / "checkpoints" / checkpoint.name
            target.parent.mkdir(exist_ok=True)
            shutil.copy2(checkpoint, target)
            files.append(target)
    for source in (partial, result, worker_log,
                   ledger.worker_lock_path(first_id),
                   ledger.worker_lock_path(successor_id)):
        target = outdir / source.name
        shutil.copy2(source, target)
        files.append(target)
    input_paths = [
        tmp_path / "session.yaml",
        tmp_path / "bars.parquet",
        tmp_path / "feature-contract.yaml",
        tmp_path / "costs.json",
        tmp_path / "multiplier.json",
        tmp_path / "audit.py",
        tmp_path / "run_log/research_sessions" / ledger.session_id / "frozen_spec.json",
    ]
    input_dir = outdir / "fixture_inputs"
    input_dir.mkdir(exist_ok=True)
    for source in input_paths:
        target = input_dir / source.name
        shutil.copy2(source, target)
        files.append(target)
    permit_path = input_dir / "run_permit.json"
    permit_path.write_text(permit.model_dump_json(indent=2) + "\n", encoding="utf-8")
    files.append(permit_path)
    code_paths = [
        "src/research_control/attempts.py",
        "src/research_control/casefile.py",
        "scripts/run_m8_cash_session.py",
        "scripts/run_m8_n8.py",
        "scripts/managed_recovery_fixture.py",
        "tests/test_m8_managed_recovery.py",
    ]
    code_hashes = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in code_paths
    }
    head = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    (outdir / "worker_pid.txt").write_text(original_pid + "\n", encoding="utf-8")
    files.append(outdir / "worker_pid.txt")
    observed = {}
    for file in sorted(files):
        observed[file.relative_to(outdir).as_posix()] = hashlib.sha256(file.read_bytes()).hexdigest()
    data = {
        "schema_version": 1,
        "test": "test_managed_worker_death_replays_under_successor_attempt",
        "evidence_directory": outdir.as_posix() + "/",
        "started_at_utc": started_at,
        "killed_at_utc": killed_at,
        "completed_at_utc": completed_at,
        "task_owned_tmux_session": job,
        "launch_commands": launch_commands,
        "permit_sha256": permit.permit_sha256,
        "permit_identity": permit.identity.model_dump(mode="json"),
        "workspace_head": head,
        "code_sha256": code_hashes,
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "ml4t_backtest": importlib.metadata.version("ml4t-backtest"),
        },
        "tmux_session_absent_before_launch": job not in tmux_before,
        "killed_worker_pid": int(original_pid),
        "parent_attempt_id": first_id,
        "successor_attempt_id": successor_id,
        "parent_status": ledger.latest()[first_id]["status"],
        "successor_status": ledger.latest()[successor_id]["status"],
        "successor_parent_attempt_id": ledger.latest()[successor_id]["parent_attempt_id"],
        "reason_codes": [
            "ATTEMPT_RESERVED",
            "WORKER_CONFIRMED_ACTIVE",
            "LEASE_UNCERTAIN",
            "SUCCESSOR_REPLAY_RESERVED",
            "ATTEMPT_ALREADY_TERMINAL",
        ],
        "worker_lock_released_after_kill": ledger.worker_lock_status(first_id) == "WORKER_LOCK_RELEASED",
        "partial_progress_retained": partial.is_file(),
        "complete_runs": sum(item["status"] == "COMPLETED" for item in ledger.latest().values()),
        "strategy_execution": False,
        "protected_holdout_accessed": False,
        "broker_execution": False,
        "same_attempt_continuation_claimed": False,
        "artifacts": observed,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_managed_worker_death_replays_under_successor_attempt(tmp_path):
    """Kill one owned worker at a checkpoint; replay once with preserved lineage."""
    data, contract, computation, evidence = setup_trial(tmp_path)
    permit = gate(tmp_path, data, contract, computation, evidence)
    now = [datetime.now(UTC)]
    ledger = AttemptLedger(
        tmp_path,
        contract.session_id,
        list_jobs=tmux_sessions,
        clock=lambda: now[0],
    )
    suffix = uuid.uuid4().hex[:10]
    job = f"ml4t-m8c-recovery-{suffix}"
    ready = tmp_path / "worker.ready"
    release = tmp_path / "worker.release"
    pid_file = tmp_path / "worker.pid"
    partial = tmp_path / "run_log/m8/recovery-fixture/parent/partial.json"
    result_path = tmp_path / "run_log/m8/recovery-fixture/successor/result.json"
    worker_log = tmp_path / "worker.log"

    # Check all current sessions before creating the one task-owned session.
    initial_sessions = tmux_sessions()
    assert initial_sessions is not None and job not in initial_sessions
    started_at = datetime.now(UTC).isoformat()
    first = ledger.claim(
        permit, job_name=job, command="synthetic managed worker",
        lease_seconds=60, managed_worker=True,
    )
    assert (first.status, first.reason_code) == ("LAUNCH", "ATTEMPT_RESERVED")
    pause_command = _start_tmux(job, tmp_path, [
        "pause", "--root", str(tmp_path), "--session-id", contract.session_id,
        "--attempt-id", first.attempt_id, "--ready", str(ready),
        "--partial", str(partial), "--release", str(release),
        "--pid-file", str(pid_file),
    ], worker_log)
    try:
        try:
            _wait_for(ready.exists)
            original_pid = pid_file.read_text(encoding="utf-8")
        except AssertionError:
            pane = subprocess.run(
                ["tmux", "capture-pane", "-p", "-t", job],
                capture_output=True, text=True, check=False,
            )
            raise AssertionError(f"test worker did not checkpoint: {pane.stdout}{pane.stderr}")
        assert ledger.worker_lock_status(first.attempt_id) == "WORKER_LOCK_HELD"
        status = inspect_resume(tmp_path, contract.session_id, first.attempt_id,
                                list_jobs=tmux_sessions)
        assert (status["status"], status["reason_code"]) == (
            "RUNNING", "WORKER_CONFIRMED_ACTIVE"
        )
        duplicate = ledger.claim(
            permit, job_name=job, command="synthetic managed worker",
            lease_seconds=60, managed_worker=True,
        )
        assert (duplicate.status, duplicate.reason_code, duplicate.attempt_id) == (
            "RESUME", "WORKER_CONFIRMED_ACTIVE", first.attempt_id
        )

        # Terminate only the PID written by this uniquely named test worker.
        _stop_owned_worker(job, pid_file)
        killed_at = datetime.now(UTC).isoformat()
        assert ledger.worker_lock_status(first.attempt_id) == "WORKER_LOCK_RELEASED"
        now[0] += timedelta(seconds=61)

        successor = ledger.claim(
            permit, job_name=job, command="synthetic managed worker",
            lease_seconds=60, managed_worker=True,
        )
        assert (successor.status, successor.reason_code) == (
            "LAUNCH", "SUCCESSOR_REPLAY_RESERVED"
        )
        assert successor.attempt_id != first.attempt_id
        old = ledger.latest()[first.attempt_id]
        new = ledger.latest()[successor.attempt_id]
        assert old["status"] == "ABORTED"
        assert new["status"] == "PLANNED"
        assert new["parent_attempt_id"] == first.attempt_id
        assert new["checkpoint_sha256"] == old["checkpoint_sha256"]
        assert partial.exists(), "parent partial output must remain intact"
        parent_checkpoint = tmp_path / old["checkpoint_path"]
        parent_checkpoint_data = json.loads(parent_checkpoint.read_text(encoding="utf-8"))
        assert hashlib.sha256(parent_checkpoint.read_bytes()).hexdigest() == old["checkpoint_sha256"]
        assert parent_checkpoint_data["attempt_id"] == first.attempt_id
        assert parent_checkpoint_data["run_id"] == old["run_id"]
        assert parent_checkpoint_data["fingerprints"] == old["fingerprints"]
        assert parent_checkpoint_data["progress"] == 1
        assert parent_checkpoint_data["artifacts"][partial.relative_to(tmp_path).as_posix()] == hashlib.sha256(partial.read_bytes()).hexdigest()

        second_claim = ledger.claim(
            permit, job_name=job, command="synthetic managed worker",
            lease_seconds=60, managed_worker=True,
        )
        assert (second_claim.status, second_claim.reason_code) == (
            "BLOCKED", "LEASE_UNCERTAIN"
        )
        finish_command = _start_tmux(job, tmp_path, [
            "finish", "--root", str(tmp_path), "--session-id", contract.session_id,
            "--attempt-id", successor.attempt_id, "--partial", str(partial),
            "--result", str(result_path),
        ], worker_log)
        _wait_for(lambda: ledger.latest()[successor.attempt_id]["status"] == "COMPLETED")
        _wait_for(lambda: job not in (tmux_sessions() or set()))
        completed_at = datetime.now(UTC).isoformat()

        stored = json.loads(result_path.read_text(encoding="utf-8"))
        assert stored == {
            "fixture": "m8-c-recovery-result-v1",
            "attempt_id": successor.attempt_id,
            "parent_attempt_id": first.attempt_id,
            "run_id": new["run_id"],
            "fingerprints": new["fingerprints"],
            "completed_units": 2,
        }
        successor_record = ledger.latest()[successor.attempt_id]
        successor_checkpoint = tmp_path / successor_record["checkpoint_path"]
        successor_checkpoint_data = json.loads(successor_checkpoint.read_text(encoding="utf-8"))
        assert hashlib.sha256(successor_checkpoint.read_bytes()).hexdigest() == successor_record["checkpoint_sha256"]
        assert successor_checkpoint_data["attempt_id"] == successor.attempt_id
        assert successor_checkpoint_data["run_id"] == new["run_id"]
        assert successor_checkpoint_data["fingerprints"] == new["fingerprints"]
        assert successor_checkpoint_data["artifacts"][result_path.relative_to(tmp_path).as_posix()] == hashlib.sha256(result_path.read_bytes()).hexdigest()
        states = ledger.latest()
        assert sum(item["status"] == "COMPLETED" for item in states.values()) == 1
        assert states[first.attempt_id]["status"] == "ABORTED"
        assert ledger.transition(first.attempt_id, "COMPLETED").reason_code == "ATTEMPT_ALREADY_TERMINAL"
        evidence_path = os.environ.get("M8_RECOVERY_EVIDENCE_PATH")
        if evidence_path:
            _write_durable_evidence(
                Path(evidence_path), tmp_path=tmp_path, ledger=ledger,
                first_id=first.attempt_id, successor_id=successor.attempt_id,
                job=job, original_pid=original_pid, partial=partial,
                result=result_path, worker_log=worker_log,
                tmux_before=initial_sessions,
                permit=permit.permit,
                started_at=started_at, killed_at=killed_at,
                completed_at=completed_at,
                launch_commands=[pause_command, finish_command],
            )
    finally:
        sessions = tmux_sessions()
        if sessions is not None and job in sessions:
            if pid_file.exists():
                _stop_owned_worker(job, pid_file)
            else:
                subprocess.run(["tmux", "kill-session", "-t", job], check=False)


def test_managed_recovery_rejects_checkpoint_tamper_and_lease_uncertainty(tmp_path):
    data, contract, computation, evidence = setup_trial(tmp_path)
    permit = gate(tmp_path, data, contract, computation, evidence)
    now = [datetime.now(UTC)]
    ledger = AttemptLedger(
        tmp_path, contract.session_id, list_jobs=lambda: set(), clock=lambda: now[0]
    )
    job = "ml4t-m8c-checkpoint"
    first = ledger.claim(
        permit, job_name=job, command="synthetic", lease_seconds=60,
        managed_worker=True,
    )
    assert ledger.transition(first.attempt_id, "RUNNING").reason_code == "ATTEMPT_STATE_RECORDED"
    partial = tmp_path / "partial.json"
    partial.write_text('{"ok": true}\n', encoding="utf-8")
    digest = hashlib.sha256(partial.read_bytes()).hexdigest()
    with ledger.worker_lease(first.attempt_id):
        ledger.record_checkpoint(first.attempt_id, progress=1,
                                 artifacts={"partial.json": digest})
        assert ledger.claim(
            permit, job_name=job, command="synthetic", lease_seconds=60,
            managed_worker=True,
        ).reason_code == "LEASE_UNCERTAIN"
        now[0] += timedelta(seconds=61)
        held = ledger.claim(
            permit, job_name=job, command="synthetic", lease_seconds=60,
            managed_worker=True,
        )
        assert (held.status, held.reason_code) == ("BLOCKED", "WORKER_LOCK_HELD")
    checkpoint = tmp_path / ledger.latest()[first.attempt_id]["checkpoint_path"]
    checkpoint.write_text("tampered\n", encoding="utf-8")
    blocked = ledger.claim(
        permit, job_name=job, command="synthetic", lease_seconds=60,
        managed_worker=True,
    )
    assert (blocked.status, blocked.reason_code) == (
        "BLOCKED", "RECOVERY_CHECKPOINT_INVALID"
    )
    assert ledger.latest()[first.attempt_id]["status"] == "RUNNING"


def test_parallel_managed_claims_reserve_only_one_attempt(tmp_path):
    data, contract, computation, evidence = setup_trial(tmp_path)
    permit = gate(tmp_path, data, contract, computation, evidence)
    ledger = AttemptLedger(tmp_path, contract.session_id, list_jobs=lambda: set())
    kwargs = {
        "job_name": "ml4t-m8c-parallel",
        "command": "synthetic managed worker",
        "lease_seconds": 60,
        "managed_worker": True,
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: ledger.claim(permit, **kwargs), range(2)))
    assert sorted((item.status, item.reason_code) for item in results) == [
        ("BLOCKED", "LEASE_UNCERTAIN"),
        ("LAUNCH", "ATTEMPT_RESERVED"),
    ]
    alternate_job = ledger.claim(
        permit,
        **{**kwargs, "job_name": "ml4t-m8c-parallel-alternate"},
    )
    assert (alternate_job.status, alternate_job.reason_code) == (
        "BLOCKED", "ACTIVE_RUN_EXISTS"
    )
    assert len(ledger.latest()) == 1
    assert len([item for item in ledger.events() if item["status"] == "PLANNED"]) == 1
