"""Append-only native research attempt lifecycle with fail-closed tmux recovery.

Separate from SessionSpecV1 terminal records. Never runs shell jobs or trades.
"""
from __future__ import annotations

import errno
import fcntl
import hashlib
import importlib.metadata
import json
import os
import re
import shlex
import subprocess
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from src.engine.common import beneath
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


def launch_managed_worker(job_name: str, cwd: str | Path, command: list[str],
                          *, log_path: str | Path | None = None) -> AttemptDecision:
    """Launch one named worker after a live visibility and ownership check."""
    if not re.fullmatch(r"ml4t-[A-Za-z0-9_-]+", job_name):
        return AttemptDecision("BLOCKED", "JOB_NAME_INVALID")
    if not command or any(not isinstance(part, str) or not part for part in command):
        return AttemptDecision("BLOCKED", "ATTEMPT_INVALID")
    working_dir = Path(cwd).resolve()
    if not working_dir.is_dir():
        return AttemptDecision("BLOCKED", "WORKER_CWD_INVALID")
    jobs = tmux_sessions()
    if jobs is None:
        return AttemptDecision("BLOCKED", "JOB_VISIBILITY_UNKNOWN")
    if job_name in jobs:
        return AttemptDecision("BLOCKED", "ACTIVE_UNOWNED_JOB")
    shell_command = shlex.join(command)
    if log_path is not None:
        logfile = Path(log_path)
        logfile.parent.mkdir(parents=True, exist_ok=True)
        if logfile.is_symlink():
            return AttemptDecision("BLOCKED", "WORKER_LOG_UNSAFE")
        shell_command += f" >> {shlex.quote(str(logfile))} 2>&1"
    try:
        started = subprocess.run(
            ["tmux", "new-session", "-d", "-s", job_name, "-c", str(working_dir), shell_command],
            capture_output=True, text=True, check=False, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return AttemptDecision("BLOCKED", "JOB_LAUNCH_FAILED", detail=str(exc))
    if started.returncode:
        return AttemptDecision("BLOCKED", "JOB_LAUNCH_FAILED", detail=started.stderr.strip())
    visible = tmux_sessions()
    if visible is None or job_name not in visible:
        return AttemptDecision("BLOCKED", "JOB_VISIBILITY_UNKNOWN",
                               detail="launch returned but named session is not verifiably visible")
    return AttemptDecision("LAUNCH", "JOB_LAUNCHED", detail=job_name)


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
        if self.path.is_symlink() or lock.is_symlink():
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
                lease_until: str, command: str, detail: str = "",
                worker_protocol: str | None = None,
                parent_attempt_id: str | None = None,
                checkpoint_path: str | None = None,
                checkpoint_sha256: str | None = None,
                metadata: dict[str, Any] | None = None,
                fencing_token: int | None = None) -> dict[str, Any]:
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
            "worker_protocol": worker_protocol,
            "parent_attempt_id": parent_attempt_id,
            "checkpoint_path": checkpoint_path,
            "checkpoint_sha256": checkpoint_sha256,
            "metadata": metadata or {},
            "fencing_token": fencing_token,
        }
        # Atomic exclusive create. A duplicated UUID fails; do not overwrite evidence.
        event_path = self.path / (event_id + ".json")
        descriptor = os.open(event_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                             getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as out:
            json.dump(payload, out, sort_keys=True)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        directory_fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
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

    def worker_lock_path(self, attempt_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9-]{1,80}", attempt_id):
            raise ValueError("invalid attempt_id")
        return self.path / f"{attempt_id}.worker.lock"

    def worker_lock_status(self, attempt_id: str) -> str:
        """Inspect the exclusive worker lock without trusting tmux visibility."""
        path = self.worker_lock_path(attempt_id)
        if path.is_symlink():
            return "WORKER_LOCK_UNSAFE"
        if not path.is_file():
            return "WORKER_LOCK_MISSING"
        try:
            descriptor = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(descriptor, "a+") as file:
                if not os.path.isfile(path) or not os.path.samestat(os.fstat(file.fileno()), os.stat(path)):
                    return "WORKER_LOCK_UNSAFE"
                try:
                    fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return "WORKER_LOCK_HELD"
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)
        except OSError:
            return "WORKER_LOCK_UNKNOWN"
        return "WORKER_LOCK_RELEASED"

    @contextmanager
    def worker_lease(self, attempt_id: str, *, owner_pid: int | None = None) -> Iterator[None]:
        """Hold an OS lock for the full worker lifetime; death releases it."""
        path = self.worker_lock_path(attempt_id)
        self.path.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink() or path.is_symlink():
            raise RuntimeError("WORKER_LOCK_UNSAFE")
        try:
            descriptor = os.open(
                path,
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
        except OSError as exc:
            reason = "WORKER_LOCK_UNSAFE" if exc.errno == errno.ELOOP else "WORKER_LOCK_UNKNOWN"
            raise RuntimeError(reason) from exc
        with os.fdopen(descriptor, "a+") as file:
            if not os.path.isfile(path) or not os.path.samestat(os.fstat(file.fileno()), os.stat(path)):
                raise RuntimeError("WORKER_LOCK_UNSAFE")
            try:
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("WORKER_LOCK_HELD") from exc
            file.seek(0)
            file.truncate()
            try:
                pid = owner_pid or os.getpid()
                stat = Path(f"/proc/{pid}/stat").read_text()
                start_ticks = stat[stat.rfind(")") + 2:].split()[19]
            except (OSError, IndexError):
                raise RuntimeError("WORKER_IDENTITY_UNKNOWN")
            file.write(json.dumps({"pid": pid, "attempt_id": attempt_id,
                                   "start_ticks": start_ticks, "uid": os.getuid()}))
            file.flush()
            os.fsync(file.fileno())
            try:
                yield
            finally:
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)

    def record_checkpoint(self, attempt_id: str, *, progress: int,
                          artifacts: dict[str, str]) -> dict[str, Any]:
        """Append a checkpoint bound to the RUNNING attempt and its outputs."""
        if (isinstance(progress, bool) or not isinstance(progress, int) or
            progress < 0 or not isinstance(artifacts, dict)):
            raise ValueError("RECOVERY_CHECKPOINT_INVALID")
        with self._locked():
            current = self.latest().get(attempt_id)
            if current is None or current["status"] != "RUNNING":
                raise ValueError("RECOVERY_CHECKPOINT_ATTEMPT_INVALID")
            clean_artifacts: dict[str, str] = {}
            for relative, digest in artifacts.items():
                candidate = Path(relative)
                if (candidate.is_absolute() or ".." in candidate.parts or
                    not re.fullmatch(r"[0-9a-f]{64}", digest)):
                    raise ValueError("RECOVERY_CHECKPOINT_INVALID")
                source_path = self.root / candidate
                path = source_path.resolve()
                if (source_path.is_symlink() or self.root not in path.parents or
                    not path.is_file()):
                    raise ValueError("RECOVERY_CHECKPOINT_INVALID")
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise ValueError("RECOVERY_CHECKPOINT_INVALID")
                clean_artifacts[candidate.as_posix()] = digest
            checkpoint = {
                "schema_version": 1,
                "attempt_id": attempt_id,
                "run_id": current["run_id"],
                "fingerprints": current["fingerprints"],
                "progress": progress,
                "artifacts": clean_artifacts,
            }
            checkpoint_dir = self.path / "checkpoints"
            if checkpoint_dir.is_symlink():
                raise ValueError("RECOVERY_CHECKPOINT_INVALID")
            checkpoint_dir.mkdir(exist_ok=True)
            checkpoint_path = checkpoint_dir / f"{attempt_id}.{uuid.uuid4().hex}.json"
            with checkpoint_path.open("x", encoding="utf-8") as out:
                json.dump(checkpoint, out, sort_keys=True)
                out.write("\n")
            checkpoint_hash = hashlib.sha256(checkpoint_path.read_bytes()).hexdigest()
            return self._append(
                attempt_id=attempt_id, run_id=current["run_id"],
                trial_id=current["trial_id"], state="RUNNING",
                fingerprints=current["fingerprints"], job_name=current["job_name"],
                lease_until=current["lease_until"], command=current["command"],
                detail=f"immutable checkpoint progress={progress}",
                worker_protocol=current.get("worker_protocol"),
                parent_attempt_id=current.get("parent_attempt_id"),
                checkpoint_path=str(checkpoint_path.relative_to(self.root)),
                checkpoint_sha256=checkpoint_hash,
                metadata=current.get("metadata", {}),
                fencing_token=current.get("fencing_token"),
            )

    def _reject_late(self, attempt_id: str, kind: str, detail: str,
                     payload_sha256: str | None = None) -> None:
        folder = self.path / "rejected_late"
        if folder.is_symlink():
            raise ValueError("LATE_EVIDENCE_PATH_UNSAFE")
        folder.mkdir(exist_ok=True)
        path = folder / f"{attempt_id}.{uuid.uuid4().hex}.json"
        record = {"schema_version": 1, "attempt_id": attempt_id,
                  "kind": kind, "detail": detail,
                  "payload_sha256": payload_sha256,
                  "rejected_at": self.clock().astimezone(UTC).isoformat()}
        with path.open("x", encoding="utf-8") as out:
            json.dump(record, out, sort_keys=True)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def publish_fenced(self, attempt_id: str, fencing_token: int, *,
                       relative_path: str, payload: bytes) -> dict[str, Any]:
        """Publish one immutable accepted output only for the live fenced owner."""
        if (not isinstance(payload, bytes) or not payload or
            not relative_path.startswith("run_log/ats2/accepted/") or
            Path(relative_path).is_absolute() or ".." in Path(relative_path).parts):
            raise ValueError("FENCED_OUTPUT_INVALID")
        digest = hashlib.sha256(payload).hexdigest()
        with self._locked():
            current = self.latest().get(attempt_id)
            if current is None or current.get("fencing_token") != fencing_token:
                self._reject_late(attempt_id, "write", "fencing token or owner mismatch", digest)
                raise ValueError("FENCED_WRITE_REJECTED")
            peers = [event for event in self.latest().values()
                     if event["run_id"] == current["run_id"]]
            owner = max(peers, key=lambda event: int(event.get("fencing_token") or 0))
            if owner["attempt_id"] != attempt_id:
                self._reject_late(attempt_id, "write", "worker is not the live fenced owner", digest)
                raise ValueError("FENCED_WRITE_REJECTED")
            if current["status"] not in ("RUNNING", "COMPLETED"):
                self._reject_late(attempt_id, "write", "attempt not in a publishable state", digest)
                raise ValueError("FENCED_WRITE_REJECTED")
            destination = beneath(self.root, relative_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination = beneath(self.root, relative_path)
            try:
                descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                     getattr(os, "O_NOFOLLOW", 0), 0o600)
            except FileExistsError as exc:
                self._reject_late(attempt_id, "write", "accepted output already exists", digest)
                raise ValueError("ACCEPTED_OUTPUT_IMMUTABLE") from exc
            with os.fdopen(descriptor, "wb") as out:
                out.write(payload)
                out.flush()
                os.fsync(out.fileno())
            fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            return {"path": relative_path, "sha256": digest,
                    "fencing_token": fencing_token, "attempt_id": attempt_id}

    def _verified_checkpoint(self, record: dict[str, Any]) -> bool:
        relative = record.get("checkpoint_path")
        expected = record.get("checkpoint_sha256")
        if not relative or not expected:
            return False
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            return False
        path = self.root / candidate
        try:
            resolved = path.resolve()
            expected_dir = self.path / "checkpoints"
            if (self.path.is_symlink() or path.is_symlink() or expected_dir.is_symlink() or
                resolved.parent != expected_dir.resolve() or
                self.root not in resolved.parents or not path.is_file()):
                return False
            raw = resolved.read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected:
                return False
            checkpoint = json.loads(raw)
            if (set(checkpoint) != {
                    "schema_version", "attempt_id", "run_id", "fingerprints",
                    "progress", "artifacts",
                } or checkpoint.get("schema_version") != 1 or
                checkpoint.get("attempt_id") != record["attempt_id"] or
                checkpoint.get("run_id") != record["run_id"] or
                checkpoint.get("fingerprints") != record["fingerprints"] or
                isinstance(checkpoint.get("progress"), bool) or
                not isinstance(checkpoint.get("progress"), int) or
                checkpoint["progress"] < 0 or
                not isinstance(checkpoint.get("artifacts"), dict)):
                return False
            for relative_artifact, digest in checkpoint["artifacts"].items():
                artifact = Path(relative_artifact)
                if artifact.is_absolute() or ".." in artifact.parts:
                    return False
                artifact_path = self.root / artifact
                resolved_artifact = artifact_path.resolve()
                if (artifact_path.is_symlink() or self.root not in resolved_artifact.parents or
                    not artifact_path.is_file() or
                    hashlib.sha256(resolved_artifact.read_bytes()).hexdigest() != digest):
                    return False
        except (OSError, ValueError, TypeError, KeyError):
            return False
        return True

    def claim(self, gate: GateReport, *, job_name: str, command: str,
              lease_seconds: int = 3600,
              managed_worker: bool = False,
              metadata: dict[str, Any] | None = None) -> AttemptDecision:
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
        with self._locked():
            return self._claim_locked(permit, job_name, command,
                                      lease_seconds, managed_worker, metadata)

    def _claim_locked(self, permit: RunPermitV1, job_name: str, command: str,
                      lease_seconds: int, managed_worker: bool,
                      metadata: dict[str, Any] | None) -> AttemptDecision:
        """Core admission logic; caller must hold the ledger lock."""
        fingerprints = permit.identity.model_dump(mode="json")
        run_id = hashlib.sha256(json.dumps(
            {"permit_sha256": permit.permit_sha256, "command": command,
             "job_name": job_name}, sort_keys=True).encode()).hexdigest()
        now = self.clock().astimezone(UTC)
        until = (now + timedelta(seconds=lease_seconds)).isoformat()
        recovery_parent: str | None = None
        recovery_checkpoint_path: str | None = None
        recovery_checkpoint_sha256: str | None = None
        attempts = self.latest()
        matching = [v for v in attempts.values() if v["run_id"] == run_id]
        other_active = [v for v in attempts.values() if v["job_name"] == job_name
                        and v["status"] not in _TERMINAL]
        if managed_worker:
            other_active.extend(
                v for v in attempts.values()
                if v["trial_id"] == permit.trial_id
                and v["status"] not in _TERMINAL
                and v["job_name"] != job_name
            )
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
                if managed_worker:
                    lock_status = self.worker_lock_status(record["attempt_id"])
                    if lock_status != "WORKER_LOCK_HELD":
                        return AttemptDecision("BLOCKED", "WORKER_ALIVE_UNVERIFIED",
                                               record["attempt_id"], run_id,
                                               detail=lock_status)
                    return AttemptDecision("RESUME", "WORKER_CONFIRMED_ACTIVE",
                                           record["attempt_id"], run_id)
                return AttemptDecision("RESUME", "ACTIVE_RUN_EXISTS",
                                       record["attempt_id"], run_id)
            elif now <= datetime.fromisoformat(record["lease_until"]):
                return AttemptDecision("BLOCKED", "LEASE_UNCERTAIN",
                                       record["attempt_id"], run_id)
            else:
                if managed_worker:
                    lock_status = self.worker_lock_status(record["attempt_id"])
                    if lock_status != "WORKER_LOCK_RELEASED":
                        reason = ("WORKER_LOCK_HELD" if lock_status == "WORKER_LOCK_HELD"
                                  else "RECOVERY_EVIDENCE_MISSING")
                        return AttemptDecision("BLOCKED", reason,
                                               record["attempt_id"], run_id,
                                               detail=lock_status)
                    if not self._verified_checkpoint(record):
                        return AttemptDecision("BLOCKED", "RECOVERY_CHECKPOINT_INVALID",
                                               record["attempt_id"], run_id)
                    recovery_parent = record["attempt_id"]
                    recovery_checkpoint_path = record.get("checkpoint_path")
                    recovery_checkpoint_sha256 = record.get("checkpoint_sha256")
                self._append(
                    attempt_id=record["attempt_id"], run_id=run_id,
                    trial_id=permit.trial_id, state="ABORTED",
                    fingerprints=fingerprints, job_name=job_name,
                    lease_until=record["lease_until"], command=command,
                    detail=("expired lease, worker lock released, checkpoint verified"
                            if managed_worker else "expired lease, verified absent from tmux"),
                    worker_protocol="flock-v1" if managed_worker else None,
                    checkpoint_path=record.get("checkpoint_path"),
                    checkpoint_sha256=record.get("checkpoint_sha256"),
                    metadata=record.get("metadata", {}),
                    fencing_token=record.get("fencing_token"),
                )
        if job_name in jobs:
            return AttemptDecision("BLOCKED", "ACTIVE_UNOWNED_JOB", run_id=run_id)
        attempt_id = str(uuid.uuid4())
        fencing_token = 1 + max((int(value.get("fencing_token") or 0)
                                 for value in attempts.values()), default=0)
        event = self._append(
            attempt_id=attempt_id, run_id=run_id,
            trial_id=permit.trial_id, state="PLANNED",
            fingerprints=fingerprints, job_name=job_name,
            lease_until=until, command=command,
            detail=(
                f"successor replay of {recovery_parent}; parent artifacts retained, "
                "native replay starts from the beginning"
                if recovery_parent else
                "reserved; executor must launch and confirm process separately"
            ),
            worker_protocol="flock-v1" if managed_worker else None,
            parent_attempt_id=recovery_parent,
            checkpoint_path=recovery_checkpoint_path,
            checkpoint_sha256=recovery_checkpoint_sha256,
            metadata=metadata,
            fencing_token=fencing_token,
        )
        return AttemptDecision(
            "LAUNCH",
            "SUCCESSOR_REPLAY_RESERVED" if recovery_parent else "ATTEMPT_RESERVED",
            attempt_id, run_id,
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
                if state == "COMPLETED":
                    self._reject_late(
                        attempt_id, "completion",
                        f"late completion rejected after {old['status']}: {detail}",
                        hashlib.sha256(detail.encode()).hexdigest(),
                    )
                return AttemptDecision("BLOCKED", "ATTEMPT_ALREADY_TERMINAL", attempt_id)
            if state == "RUNNING" and old["status"] != "PLANNED":
                return AttemptDecision("BLOCKED", "ATTEMPT_STATE_INVALID", attempt_id)
            if state == "COMPLETED" and old["status"] != "RUNNING":
                return AttemptDecision("BLOCKED", "ATTEMPT_STATE_INVALID", attempt_id)
            self._append(
                attempt_id=attempt_id, run_id=old["run_id"],
                trial_id=old["trial_id"], state=state,
                fingerprints=old["fingerprints"], job_name=old["job_name"],
                lease_until=old["lease_until"], command=old["command"], detail=detail,
                worker_protocol=old.get("worker_protocol"),
                parent_attempt_id=old.get("parent_attempt_id"),
                checkpoint_path=old.get("checkpoint_path"),
                checkpoint_sha256=old.get("checkpoint_sha256"),
                metadata=old.get("metadata", {}),
                fencing_token=old.get("fencing_token"),
            )
            return AttemptDecision("RESUME", "ATTEMPT_STATE_RECORDED",
                                   attempt_id, old["run_id"])
