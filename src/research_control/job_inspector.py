"""Read-only tmux + v1 attempt reconciliation for ATS-0/1.

A tmux pane proves neither worker ownership nor progress. No capture-pane,
command-line arguments, credentials, signals or workers are accessed.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.engine.common import beneath, file_hash
from src.research_control.attempts import AttemptLedger

_JOB = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
_ACTIVE = {"PLANNED", "RUNNING"}


def _process_identity(pid: int, proc_root: Path = Path("/proc")) -> dict[str, Any]:
    """Observe PID, kernel start ticks, owner and comm, never /proc/cmdline."""
    if pid <= 0:
        return {"status": "PROCESS_ID_INVALID"}
    try:
        directory = proc_root / str(pid)
        stat = (directory / "stat").read_text(encoding="utf-8")
        fields = stat[stat.rfind(")") + 2:].split()
        start_ticks = int(fields[19])  # Linux proc stat field 22, after pid/comm
        name = (directory / "comm").read_text(encoding="utf-8").strip()[:64]
        uid = directory.stat().st_uid
        return {"status": "PROCESS_PRESENT", "pid": pid, "start_ticks": start_ticks,
                "comm": name, "same_uid": uid == os.getuid()}
    except (OSError, ValueError, IndexError):
        return {"status": "PROCESS_UNKNOWN_OR_EXITED", "pid": pid}


def _attempt_bindings(root: Path, job_names: set[str]) -> tuple[dict[str, list[dict]], list[str]]:
    """Read current v1 attempt events; do not execute legacy workers or inspect data."""
    sessions = root / "run_log" / "research_sessions"
    if not sessions.is_dir() or sessions.is_symlink():
        return {}, []
    bindings: dict[str, list[dict]] = {}
    problems: list[str] = []
    directories = sorted(p for p in sessions.iterdir() if p.is_dir() and not p.is_symlink())
    if len(directories) > 256:
        return {}, ["V1_SESSION_INVENTORY_OVER_BUDGET"]
    for folder in directories:
        if not _JOB.fullmatch(folder.name) or not (folder / "attempts").is_dir():
            continue
        try:
            ledger = AttemptLedger(root, folder.name, list_jobs=lambda: job_names)
            latest = ledger.latest()
            for event in latest.values():
                job = event.get("job_name")
                if job not in job_names:
                    continue
                bindings.setdefault(job, []).append({
                    "session_id": folder.name,
                    "attempt_id": event.get("attempt_id"),
                    "status": event.get("status"),
                    "event_observed_at": event.get("observed_at"),
                    "lease_until": event.get("lease_until"),
                    "run_id": event.get("run_id"),
                    "checkpoint_path": event.get("checkpoint_path"),
                    "checkpoint_sha256": event.get("checkpoint_sha256"),
                    "fingerprints": event.get("fingerprints"),
                })
        except (OSError, ValueError, TypeError, KeyError):
            problems.append("V1_ATTEMPT_METADATA_UNREADABLE")
    return bindings, sorted(set(problems))


def _checkpoint(root: Path, bound: dict, *, now: datetime,
                stale_seconds: int = 1800) -> dict[str, Any]:
    relative, expected = bound.get("checkpoint_path"), bound.get("checkpoint_sha256")
    if not relative:
        return {"state": "UNKNOWN_NO_CHECKPOINT", "progress": None, "freshness": "UNKNOWN"}
    try:
        path = beneath(root, relative, must_exist=True)
        expected_dir = root / "run_log" / "research_sessions" / bound["session_id"] / "attempts" / "checkpoints"
        if (path.parent != expected_dir or path.suffix != ".json" or
            not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected)):
            raise ValueError("CHECKPOINT_SCOPE_INVALID")
        if path.stat().st_size > 65_536:
            raise ValueError("CHECKPOINT_TOO_LARGE")
        if file_hash(path) != expected:
            raise ValueError("CHECKPOINT_HASH_MISMATCH")
        record = json.loads(path.read_text(encoding="utf-8"))
        progress = record.get("progress")
        if (record.get("schema_version") != 1 or record.get("attempt_id") != bound["attempt_id"]
            or record.get("run_id") != bound["run_id"] or
            record.get("fingerprints") != bound["fingerprints"] or
            type(progress) is not int or progress < 0):
            raise ValueError("CHECKPOINT_IDENTITY_INVALID")
        source_time = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        elapsed = (now - source_time).total_seconds()
        freshness = ("CLOCK_CONFLICT" if elapsed < -60 else
                     "STALE" if elapsed > stale_seconds else "RECENT")
        artifacts = record.get("artifacts")
        if not isinstance(artifacts, dict):
            raise TypeError("CHECKPOINT_IDENTITY_INVALID")
        return {"state": "CHECKPOINT_RECORD_HASH_VERIFIED", "progress": progress,
                "freshness": freshness, "observed_at": source_time.isoformat(),
                "age_seconds": round(elapsed, 1),
                "referenced_artifacts_not_opened": len(artifacts)}
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else "CHECKPOINT_UNAVAILABLE"
        return {"state": "INVALID", "reason_code": reason,
                "progress": None, "freshness": "UNKNOWN"}


def observe_jobs(
    root: str | Path, *, pane_lines: list[str] | None = None,
    process_probe: Callable[[int], dict[str, Any]] = _process_identity,
    now: datetime | None = None, stale_seconds: int = 1800,
) -> dict[str, Any]:
    """Observe all panes and registered checkpoints without touching live workers."""
    root = Path(root).resolve()
    now = now or datetime.now(UTC)
    if pane_lines is None:
        try:
            proc = subprocess.run(
                ["tmux", "list-panes", "-a", "-F",
                 "#{session_name}\t#{pane_pid}\t#{pane_dead}\t#{pane_current_command}"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            if proc.returncode != 0 or len(proc.stdout) > 131_072:
                return {"visibility": "UNKNOWN", "reason_code": "TMUX_UNREACHABLE",
                        "jobs": [], "total": None}
            pane_lines = proc.stdout.splitlines()
        except (OSError, subprocess.TimeoutExpired):
            return {"visibility": "UNKNOWN", "reason_code": "TMUX_UNREACHABLE",
                    "jobs": [], "total": None}
    if len(pane_lines) > 512:
        return {"visibility": "UNKNOWN", "reason_code": "TMUX_INVENTORY_TOO_LARGE",
                "jobs": [], "total": None}
    job_names = {line.split("\t", 1)[0] for line in pane_lines if "\t" in line}
    bindings, binding_errors = _attempt_bindings(root, job_names)
    by_name: dict[str, list[dict[str, Any]]] = {}
    for line in pane_lines:
        fields = line.split("\t")
        if len(fields) != 4 or not _JOB.fullmatch(fields[0]):
            return {"visibility": "UNKNOWN", "reason_code": "TMUX_PANE_INVALID",
                    "jobs": [], "total": None}
        name, pid_str, dead, comm = fields
        try:
            pid = int(pid_str)
        except ValueError:
            pid = -1
        identity = process_probe(pid) if dead == "0" else {"status": "PANE_DEAD"}
        by_name.setdefault(name, []).append({
            "pane_state": "DEAD" if dead == "1" else "VISIBLE",
            "process": identity, "pane_command": Path(comm).name[:48],
        })
    jobs = []
    for name, panes in sorted(by_name.items()):
        matches = bindings.get(name, [])
        active = [b for b in matches if b.get("status") in _ACTIVE]
        if len(active) == 1:
            bound = active[0]
            checkpoint = _checkpoint(root, bound, now=now, stale_seconds=stale_seconds)
            try:
                deadline = datetime.fromisoformat(bound["lease_until"]).astimezone(UTC)
                lease = "EXPIRED" if now > deadline else "CURRENT"
            except (TypeError, ValueError, KeyError):
                lease = "UNKNOWN"
            binding = {"authority": "V1_JOB_NAME_MATCH_ONLY",
                       "session_id": bound["session_id"],
                       "attempt_id": bound["attempt_id"], "status": bound["status"],
                       "lease_status": lease,
                       "pid_start_ticks_bound_by_attempt": False}
        elif len(active) > 1:
            checkpoint = {"state": "UNKNOWN", "freshness": "UNKNOWN"}
            binding = {"authority": "CONFLICTING_ATTEMPT_CLAIMS", "count": len(active)}
        else:
            checkpoint = {"state": "UNKNOWN", "freshness": "UNKNOWN"}
            binding = {"authority": "V1_TERMINAL_NAME_MATCH_ONLY" if matches else "UNATTRIBUTED",
                       "pid_start_ticks_bound_by_attempt": False}
        jobs.append({"name": name, "panes": panes, "binding": binding,
                     "checkpoint": checkpoint, "completion_verified": False,
                     "worker_status": "IDENTITY_UNBOUND",
                     "source_observed_at": now.isoformat()})
    return {"visibility": "OBSERVED", "jobs": jobs, "total": len(jobs),
            "binding_errors": binding_errors, "source_observed_at": now.isoformat()}
