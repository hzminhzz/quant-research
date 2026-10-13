"""Append-only native research attempt lifecycle with fail-closed tmux recovery.

Separate from SessionSpecV1 terminal records. Never runs shell jobs or trades.
"""
from __future__ import annotations

import fcntl
import hashlib
import importlib.metadata
import json
import re
import subprocess
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from src.research_session import _identity, _load

from .run_permit import GateReport, RunPermitV1, _identity_hashes

_STATES = {"PLANNED", "RUNNING", "COMPLETED", "FAILED", "BLOCKED", "ABORTED"}
_TERMINAL = {"COMPLETED", "FAILED", "BLOCKED", "ABORTED"}
_SESSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")


@dataclass(frozen=True)
class AttemptDecision:
    status: Literal["LAUNCH", "RESUME", "REUSE", "BLOCKED"]
    reason_code: str
    attempt_id: str | None = None
    run_id: str | None = None
    detail: str = ""
    evidence_path: str | None = None


def tmux_sessions() -> set[str] | None:
    """Return None on any failure; never mistake broken tmux for no jobs."""
    try:
        run = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    # tmux 'no server running' has status 1 and no known job; treat unknown.
    if run.returncode != 0:
        return None
    return set(run.stdout.splitlines())


class AttemptLedger:
    """Each event is an immutable file, no update-in-place state or trial deletion."""

    def __init__(self, root: str | Path, session_id: str,
                 *, list_jobs: Callable[[], set[str] | None] = tmux_sessions,
                 clock: Callable[[], datetime] | None = None):
        if not _SESSION.fullmatch(session_id):
            raise ValueError("invalid session_id")
        self.root = Path(root).resolve()
        self.session_id = session_id
        self.path = self.root / "run_log" / "research_sessions" / session_id / "attempts"
        self.list_jobs = list_jobs
        self.clock = clock or (lambda: datetime.now(UTC))
        frozen = self.path.parent / "frozen_spec.json"
        if not frozen.is_file():
            raise ValueError("frozen session is required")
        if self.path.is_symlink() or frozen.is_symlink():
            raise ValueError("symlinked session path prohibited")

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.mkdir(parents=True, exist_ok=True)
        lock = self.path / ".lock"
        if lock.is_symlink():
            raise ValueError("unsafe ledger lock")
        with lock.open("a+") as file:
            fcntl.flock(file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)

    def events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        results = []
        for path in sorted(self.path.glob("*.json")):
            if path.is_symlink():
                raise ValueError("symlinked attempt event prohibited")
            obj = json.loads(path.read_text(encoding="utf-8"))
            if obj.get("event_id") != path.stem or obj.get("schema_version") != 1:
                raise ValueError("untrusted attempt event")
            results.append(obj)
        return sorted(results, key=lambda item: (item["attempt_id"], item["revision"]))

    def latest(self) -> dict[str, dict[str, Any]]:
        current: dict[str, dict[str, Any]] = {}
        for event in self.events():
            current[event["attempt_id"]] = event
        return current

    def _append(self, *, attempt_id: str, run_id: str, trial_id: str,
                state: str, fingerprints: dict[str, Any], job_name: str,
                lease_until: str, command: str, detail: str = "") -> dict[str, Any]:
        if state not in _STATES:
            raise ValueError("unsupported attempt state")
        event_id = uuid.uuid4().hex
        revision = 1 + max((item["revision"] for item in self.events()
                            if item["attempt_id"] == attempt_id), default=0)
        payload = {
            "schema_version": 1, "event_id": event_id, "revision": revision,
            "attempt_id": attempt_id, "run_id": run_id, "trial_id": trial_id,
            "status": state, "fingerprints": fingerprints, "job_name": job_name,
            "lease_until": lease_until, "command": command,
            "detail": detail, "observed_at": self.clock().astimezone(UTC).isoformat(),
        }
        # Atomic exclusive create. A duplicated UUID fails; do not overwrite evidence.
        with (self.path / (event_id + ".json")).open("x", encoding="utf-8") as out:
            json.dump(payload, out, sort_keys=True)
        return payload

    def _permit_still_current(self, permit: RunPermitV1) -> bool:
        try:
            _, frozen = _load(self.root, self.session_id)
            hashes = _identity_hashes(self.root, frozen)
            if isinstance(hashes, GateReport):
                return False
            data_hash, frozen_source_hash, config_hash, current_source_hash = hashes
            digest = hashlib.sha256(json.dumps({
                "frozen_source_sha256": frozen_source_hash,
                "current_source_sha256": current_source_hash,
                "runner": frozen["identity"].get("runner", []),
            }, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
            repo = Path(__file__).resolve().parents[2]
            runner_intact = all(
                _identity(repo, i["path"]) == i
                for i in frozen["identity"].get("runner", [])
            )
            return (
                runner_intact
                and permit.identity.frozen_session_sha256 == frozen["frozen_sha256"]
                and permit.identity.spec_sha256 == frozen["spec_sha256"]
                and permit.identity.data_sha256 == data_hash
                and permit.identity.config_sha256 == config_hash
                and permit.identity.code_sha256 == digest
                and permit.identity.engine_version == importlib.metadata.version("ml4t-backtest")
            )
        except (OSError, ValueError, KeyError, TypeError, ImportError, RuntimeError):
            return False

    def claim(self, gate: GateReport, *, job_name: str, command: str,
              lease_seconds: int = 3600) -> AttemptDecision:
        if (gate.status != "PASS" or gate.permit is None or
            gate.permit.session_id != self.session_id):
            return AttemptDecision("BLOCKED", "PERMIT_REQUIRED")
        if not re.fullmatch(r"ml4t-[A-Za-z0-9_-]+", job_name):
            return AttemptDecision("BLOCKED", "JOB_NAME_INVALID")
        if not command or lease_seconds <= 0:
            return AttemptDecision("BLOCKED", "ATTEMPT_INVALID")
        permit = RunPermitV1.model_validate(gate.permit.model_dump(mode="json"))
        if not self._permit_still_current(permit):
            return AttemptDecision("BLOCKED", "IDENTITY_DRIFT")
        fingerprints = permit.identity.model_dump(mode="json")
        run_id = hashlib.sha256(json.dumps(
            {"permit_sha256": permit.permit_sha256, "command": command,
             "job_name": job_name}, sort_keys=True).encode()).hexdigest()
        now = self.clock().astimezone(UTC)
        until = (now + timedelta(seconds=lease_seconds)).isoformat()
        with self._locked():
            attempts = self.latest()
            matching = [v for v in attempts.values() if v["run_id"] == run_id]
            other_active = [v for v in attempts.values() if v["job_name"] == job_name
                            and v["status"] not in _TERMINAL]
            if any(item["fingerprints"] != fingerprints for item in matching + other_active):
                return AttemptDecision("BLOCKED", "IDENTITY_DRIFT", run_id=run_id)
            jobs = self.list_jobs()
            if jobs is None:
                return AttemptDecision("BLOCKED", "JOB_VISIBILITY_UNKNOWN", run_id=run_id)
            for record in other_active:
                if record["run_id"] != run_id:
                    return AttemptDecision("BLOCKED", "ACTIVE_RUN_EXISTS",
                                           record["attempt_id"], run_id)
            for record in matching:
                if record["status"] in _TERMINAL:
                    if record["status"] == "COMPLETED":
                        return AttemptDecision("REUSE", "EVIDENCE_REUSABLE",
                                               record["attempt_id"], run_id)
                    # Failed attempts are retained, but new attempt may be made.
                elif record["job_name"] in jobs:
                    return AttemptDecision("RESUME", "ACTIVE_RUN_EXISTS",
                                           record["attempt_id"], run_id)
                elif now <= datetime.fromisoformat(record["lease_until"]):
                    return AttemptDecision("BLOCKED", "LEASE_UNCERTAIN",
                                           record["attempt_id"], run_id)
                else:
                    self._append(
                        attempt_id=record["attempt_id"], run_id=run_id,
                        trial_id=permit.trial_id, state="ABORTED",
                        fingerprints=fingerprints, job_name=job_name,
                        lease_until=record["lease_until"], command=command,
                        detail="expired lease, verified absent from tmux"
                    )
            if job_name in jobs:
                return AttemptDecision("BLOCKED", "ACTIVE_UNOWNED_JOB", run_id=run_id)
            attempt_id = str(uuid.uuid4())
            event = self._append(
                attempt_id=attempt_id, run_id=run_id,
                trial_id=permit.trial_id, state="PLANNED",
                fingerprints=fingerprints, job_name=job_name,
                lease_until=until, command=command,
                detail="reserved; executor must launch and confirm process separately",
            )
            return AttemptDecision("LAUNCH", "ATTEMPT_RESERVED", attempt_id, run_id,
                                   evidence_path=str((self.path / (event["event_id"] + ".json")).relative_to(self.root)))

    def transition(self, attempt_id: str, state: str, *, detail: str = "") -> AttemptDecision:
        if state not in _STATES - {"PLANNED"}:
            return AttemptDecision("BLOCKED", "ATTEMPT_STATE_INVALID")
        with self._locked():
            latest = self.latest()
            if attempt_id not in latest:
                return AttemptDecision("BLOCKED", "ATTEMPT_UNKNOWN")
            old = latest[attempt_id]
            if old["status"] in _TERMINAL:
                return AttemptDecision("BLOCKED", "ATTEMPT_ALREADY_TERMINAL", attempt_id)
            if state == "RUNNING" and old["status"] != "PLANNED":
                return AttemptDecision("BLOCKED", "ATTEMPT_STATE_INVALID", attempt_id)
            if state == "COMPLETED" and old["status"] != "RUNNING":
                return AttemptDecision("BLOCKED", "ATTEMPT_STATE_INVALID", attempt_id)
            self._append(
                attempt_id=attempt_id, run_id=old["run_id"],
                trial_id=old["trial_id"], state=state,
                fingerprints=old["fingerprints"], job_name=old["job_name"],
                lease_until=old["lease_until"], command=old["command"], detail=detail
            )
            return AttemptDecision("RESUME", "ATTEMPT_STATE_RECORDED",
                                   attempt_id, old["run_id"])
