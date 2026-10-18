"""ATS-0/1 read-only projection over Git, trial ledger, receipts and tmux.

No market Parquet, provider data, protected results, credentials or order paths.
Large factory Casefiles are SHA-verified as byte streams; their bulky JSON is
not parsed. Small stage receipts supply independently cross-checked metadata.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
import subprocess
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.engine.common import beneath, digest, file_hash, safe_name
from src.research_control.job_inspector import observe_jobs

SCHEMA = "ats-read-v1"
_HEX = re.compile(r"^[0-9a-f]{64}$")
_TERMINAL = {"FALSIFIED_STAGE_2", "FALSIFIED_STAGE_3", "HOLDOUT_EVALUATED",
             "ENGINEERING_ERROR", "BLOCKED_DATA", "BLOCKED_EXECUTION",
             "INCONCLUSIVE_STAGE_3", "INVALID_EVIDENCE", "INVALID_SPEC",
             "INVALID_ALLOCATION", "ISOLATION_UNAVAILABLE", "HOLDOUT_DENIED"}
_EXPECTED_STAGE = {"FALSIFIED_STAGE_2": 2, "FALSIFIED_STAGE_3": 3,
                   "HOLDOUT_EVALUATED": 3}
_MAX_ARTIFACT = 64 * 1024 * 1024
_READ_BUDGET = 65_536
_SOURCES = {
    "factory": ("scripts/quant.py", "src/engine/funnel.py",
                "tests/test_dual_mode_funnel.py"),
    "workbench": ("src/workbench.py", "src/data_vault/vault.py",
                  "tests/test_dual_mode_workbench.py"),
    "legacy": ("scripts/research.py", "src/research_control/casefile.py",
               "tests/test_casefile.py"),
    "ats_read": ("src/research_control/agent_interface.py",
                 "src/research_control/job_inspector.py",
                 "tests/test_ats_read_interface.py"),
    "native_execution": ("src/engine/backtest_runner.py",
                          "src/engine/common.py",
                          "tests/test_dual_mode_native_backtest.py"),
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _shell(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(["git", "-C", str(root), *args],
                                capture_output=True, text=True, check=False, timeout=8)
        return result.stdout.strip() if result.returncode == 0 else "UNKNOWN"
    except (OSError, subprocess.TimeoutExpired):
        return "UNKNOWN"


def _git(root: Path) -> dict[str, Any]:
    raw = _shell(root, "status", "--porcelain=v1", "-uall")
    head = _shell(root, "rev-parse", "HEAD")
    if raw == "UNKNOWN" or head == "UNKNOWN":
        return {"head": head, "branch": "UNKNOWN", "dirty": None,
                "tracked_modified_count": None, "untracked_count": None,
                "visibility": "UNKNOWN", "source": "git local checkout"}
    changes = raw.splitlines()
    tracked = sum(bool(x) and not x.startswith("??") for x in changes)
    untracked = sum(x.startswith("??") for x in changes)
    return {"head": head, "branch": _shell(root, "branch", "--show-current"),
            "dirty": bool(changes), "tracked_modified_count": tracked,
            "untracked_count": untracked, "visibility": "OBSERVED",
            "source": "git local checkout"}


def capability_inventory(root: Path) -> dict[str, Any]:
    """ATS-0 source/installed capability probes, never model or broker calls."""
    root = Path(root).resolve()
    capabilities = {}
    for name, paths in _SOURCES.items():
        state = {p: ("PRESENT" if (root / p).is_file() else "MISSING") for p in paths}
        # Existence and a deterministic code digest are not a qualification pass.
        source_hashes = {p: file_hash(root / p) for p in paths[:2] if state[p] == "PRESENT"}
        capabilities[name] = {"source_paths": list(paths), "source_status": state,
                              "source_hashes": source_hashes,
                              "availability": "SOURCE_PRESENT" if all(
                                  state[p] == "PRESENT" for p in paths[:2]) else "UNVERIFIED",
                              "qualification": "REQUIRES_EXTERNAL_TEST_EVIDENCE",
                              "effects": ["READ_ONLY_METADATA"] if name == "ats_read"
                                         else ["NOT_INVOKED"]}
    versions = {}
    for package in ("ml4t-engineer", "ml4t-diagnostic", "ml4t-backtest"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "UNAVAILABLE"
    git = _git(root)
    ledger_rows, ledger_error, ledger_hash = _ledger(root / "run_log")
    tmux = observe_jobs(root)
    worktrees = _shell(root, "worktree", "list", "--porcelain")
    worktree_count = (sum(s.startswith("worktree ") for s in worktrees.splitlines())
                      if worktrees != "UNKNOWN" else None)
    return {"schema_version": SCHEMA, "operation": "capabilities",
            "observed_at": _utc_now().isoformat(),
            "interfaces": capabilities, "installed_versions": versions,
            "tested_tools": {
                "git_local_read": {"status": "WORKING" if git["visibility"] == "OBSERVED"
                                   else "UNKNOWN", "head": git["head"]},
                "trial_ledger_read": {"status": "WORKING" if ledger_error is None else "BLOCKED",
                                      "reason": ledger_error, "record_count": len(ledger_rows),
                                      "cursor": ledger_hash},
                "tmux_process_inspection": {"status": "WORKING" if tmux["visibility"] == "OBSERVED"
                                            else "UNKNOWN", "session_count": tmux["total"],
                                            "reason": tmux.get("reason_code")},
                "worktree_metadata_read": {"status": "WORKING" if worktree_count is not None
                                           else "UNKNOWN", "count": worktree_count},
                "native_package_metadata": {"status": "WORKING" if all(
                    v != "UNAVAILABLE" for v in versions.values()) else "PARTIAL"},
            },
            "historical_mapping": {"scripts/research.py": "v1 legacy compatibility",
                                   "scripts/quant.py": "dual-mode factory",
                                   "src.workbench.Workbench": "interactive development only"},
            "provider_status": "NOT_INSPECTED_NO_CREDENTIAL_ACCESS",
            "protected_read_capability": "NOT_EXPOSED",
            "broker_order_capability": "NOT_EXPOSED",
            "limitations": ["Tool probes establish metadata access only",
                            "Code and package presence do not qualify execution",
                            "No provider request, data acquisition, broker or protected read executed"],
            "effects": ["READ_ONLY"]}


def _small_json(root: Path, reference: str, *, max_bytes: int = _READ_BUDGET) -> dict[str, Any]:
    path = beneath(root, reference, must_exist=True)
    if path.suffix != ".json" or not path.is_file():
        raise ValueError("EVIDENCE_SCOPE_DENIED")
    if path.stat().st_size > max_bytes:
        raise ValueError("EVIDENCE_TOO_LARGE")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("EVIDENCE_SCHEMA_INVALID")
    return data


def _ledger(root: Path) -> tuple[list[dict[str, Any]], str | None, str | None]:
    """Validate the native hash chain before trusting *any* projected terminal status."""
    path = root / "trial_ledger.jsonl"
    if not path.exists():
        return [], "LEDGER_ABSENT", None
    if path.is_symlink() or path.stat().st_size > 8_000_000:
        return [], "LEDGER_UNSAFE_OR_OVER_BUDGET", None
    previous, records = "0" * 64, []
    try:
        with path.open(encoding="utf-8") as source:
            for line in source:
                event = json.loads(line)
                actual = event.pop("record_hash")
                if (event.get("previous_hash") != previous or digest(event) != actual
                    or not _HEX.fullmatch(str(actual))):
                    return [], "LEDGER_INTEGRITY_FAILURE", None
                previous = actual
                records.append({k: event.get(k) for k in
                                ("candidate_id", "attempt_id", "event", "status",
                                 "spec_hash", "code_hash", "panel_hash", "run_path",
                                 "recorded_at", "casefile", "holdout_access")})
        return records, None, previous
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return [], "LEDGER_UNREADABLE", None


def _case_path(base: Path, reference: str, candidate: str, attempt: str) -> Path:
    safe_name(candidate)
    safe_name(attempt)
    if reference != f"dual_mode/{candidate}/{attempt}/casefile.json":
        raise ValueError("ARTIFACT_REFERENCE_CONFLICT")
    path = beneath(base, reference)
    if not path.is_file():
        raise ValueError("ARTIFACT_MISSING")
    return path


def _integrity(path: Path, expected: str, *, max_size: int = _MAX_ARTIFACT) -> dict[str, Any]:
    if not isinstance(expected, str) or not _HEX.fullmatch(expected):
        raise ValueError("REGISTERED_HASH_MISSING")
    before = path.stat()
    if not path.is_file() or before.st_size > max_size:
        raise ValueError("ARTIFACT_OVER_HASH_BUDGET")
    # file_hash streams the file; it never parses outcome fields or large arrays.
    actual = file_hash(path)
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_ino, after.st_size, after.st_mtime_ns
    ):
        raise ValueError("SOURCE_CHANGED_DURING_READ")
    if actual != expected:
        raise ValueError("ARTIFACT_HASH_MISMATCH")
    return {"sha256": actual, "bytes": before.st_size,
            "source_observed_at": datetime.fromtimestamp(before.st_mtime, UTC).isoformat(),
            "method": "STREAMING_SHA256_MATCHES_TRIAL_LEDGER"}


def _stage_status(base: Path, row: dict[str, Any]) -> dict[str, Any]:
    folder = f"dual_mode/{row['candidate_id']}/{row['attempt_id']}"
    found: dict[str, Any] = {}
    panel_hash: str | None = None
    for stage in (1, 2, 3):
        name = f"{folder}/stage{stage}.json"
        path = beneath(base, name)
        if not path.is_file():
            found[str(stage)] = {"status": "NOT_RUN", "verification": "NO_RECEIPT"}
            continue
        receipt = _small_json(base, name)
        checksum = receipt.pop("receipt_hash", None)
        if not _HEX.fullmatch(str(checksum)) or digest(receipt) != checksum:
            raise ValueError("STAGE_RECEIPT_TAMPERED")
        if (receipt.get("stage") != stage or
            receipt.get("candidate_id") != row["candidate_id"] or
            receipt.get("spec_hash") != row["spec_hash"] or
            receipt.get("code_hash") != row["code_hash"]):
            raise ValueError("STAGE_IDENTITY_CONFLICT")
        if panel_hash is not None and receipt.get("panel_hash") != panel_hash:
            raise ValueError("STAGE_PANEL_CONFLICT")
        panel_hash = receipt.get("panel_hash")
        evidence = receipt.get("artifacts")
        expected_evidence = f"stage{stage}_evidence.json"
        if not isinstance(evidence, dict) or expected_evidence not in evidence:
            raise ValueError("STAGE_EVIDENCE_MISSING")
        src = beneath(base, f"{folder}/{expected_evidence}", must_exist=True)
        # Verify the stage evidence hash without parsing feature/return payloads.
        _integrity(src, evidence[expected_evidence])
        found[str(stage)] = {
            "status": receipt.get("status", "UNKNOWN"),
            "verification": "RECEIPT_AND_EVIDENCE_HASH_VERIFIED",
            "receipt_ref": name, "receipt_sha256": checksum,
        }
    found["4"] = {"status": "NOT_INSPECTED_PROTECTED_BOUNDARY",
                  "verification": "FORBIDDEN"}
    required = _EXPECTED_STAGE.get(row["status"], 0)
    for stage in range(1, required + 1):
        if found[str(stage)]["status"] == "NOT_RUN":
            raise ValueError("REQUIRED_STAGE_RECEIPT_MISSING")
        if stage < required and found[str(stage)]["status"] != "PASS":
            raise ValueError("STAGE_SEQUENCE_CONFLICT")
    if (required and row["status"] != "HOLDOUT_EVALUATED"
        and found[str(required)]["status"] != row["status"]):
        raise ValueError("STAGE_TERMINAL_CONFLICT")
    if row["status"] == "FALSIFIED_STAGE_2" and found["3"]["status"] != "NOT_RUN":
        raise ValueError("STAGE_AFTER_REJECTION")
    return {"records": found, "panel_hash": panel_hash}


def _projection(base: Path, row: dict[str, Any]) -> dict[str, Any]:
    result = {"candidate_id": row["candidate_id"], "attempt_id": row["attempt_id"],
              "status": row["status"], "status_authority": "TRIAL_LEDGER_VERIFIED",
              "spec_hash": row["spec_hash"], "code_hash": row["code_hash"],
              "ledger_observed_at": row["recorded_at"]}
    if row["event"] != "completed":
        return {**result, "evidence_access": "IN_PROGRESS_NOT_FINAL",
                "stages": {}, "source_ref": None}
    if row["status"] not in _TERMINAL:
        raise ValueError("UNRECOGNIZED_TERMINAL_STATUS")
    if row["status"] == "HOLDOUT_EVALUATED" or row.get("holdout_access") is True:
        return {**result, "evidence_access": "PROTECTED_OUTCOME_NOT_OPENED",
                "stages": {"4": {"status": "REDACTED"}}, "source_ref": None}
    reference = row.get("casefile")
    if not isinstance(reference, dict) or not isinstance(reference.get("path"), str):
        raise TypeError("ARTIFACT_NOT_REGISTERED")
    if (row.get("run_path") and
        row["run_path"] != f"dual_mode/{row['candidate_id']}/{row['attempt_id']}"):
        raise ValueError("RUN_PATH_IDENTITY_CONFLICT")
    path = _case_path(base, reference["path"], row["candidate_id"], row["attempt_id"])
    check = _integrity(path, reference.get("sha256"))
    if (row.get("recorded_at") and
        datetime.fromisoformat(check["source_observed_at"]) >
        datetime.fromisoformat(row["recorded_at"]) + timedelta(seconds=60)):
        raise ValueError("SOURCE_CHANGED_AFTER_LEDGER")
    stage = _stage_status(base, row)
    if row["status"] in _TERMINAL and not row.get("recorded_at"):
        raise ValueError("LEDGER_TIMESTAMP_MISSING")
    return {**result, "evidence_access": "INTEGRITY_VERIFIED",
            "source_ref": reference["path"], "source_sha256": check["sha256"],
            "source_bytes": check["bytes"],
            "source_observed_at": check["source_observed_at"],
            "stages": stage["records"], "panel_hash": stage["panel_hash"],
            "verification_scope": "CRYPTOGRAPHIC_INTEGRITY_ONLY_NOT_NUMERICAL_REVALIDATION"}


def _legacy_jobs(root: Path, list_jobs: Callable[[], set[str] | None]) -> dict[str, Any]:
    """Compatibility injection for old tests; never upgrades names to process proof."""
    names = list_jobs()
    if names is None:
        return {"visibility": "UNKNOWN", "reason_code": "JOB_VISIBILITY_UNKNOWN",
                "jobs": [], "total": None}
    return {"visibility": "NAMES_ONLY", "jobs": [
        {"name": name, "panes": [], "binding": {"authority": "UNATTRIBUTED"},
         "checkpoint": {"state": "UNKNOWN", "freshness": "UNKNOWN"},
         "worker_status": "UNVERIFIED", "completion_verified": False}
        for name in sorted(names)], "total": len(names), "source_observed_at": None}


def inspect_case(
    root: str | Path, *, candidate_id: str | None = None,
    limit: int = 10, cursor: int = 0, jobs_cursor: int = 0,
    list_jobs: Callable[[], set[str] | None] | None = None,
    job_probe: Callable[[Path], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Read-only decision frontier with per-source provenance and fail-closed claims."""
    root = Path(root).resolve()
    if candidate_id is not None:
        safe_name(candidate_id)
    if not 1 <= limit <= 50 or min(cursor, jobs_cursor) < 0:
        raise ValueError("INVALID_PAGINATION")
    now = _utc_now()
    git = _git(root)
    base = root / "run_log"
    rows, ledger_error, ledger_cursor = _ledger(base)
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    regressions = []
    for row in rows:
        if row.get("candidate_id") and row.get("attempt_id"):
            key = (row["candidate_id"], row["attempt_id"])
            if key in latest and latest[key]["event"] == "completed":
                regressions.append(key)
            latest[key] = row
    selected = sorted((v for v in latest.values()
                       if candidate_id is None or v["candidate_id"] == candidate_id),
                      key=lambda v: (v.get("recorded_at") or "", v["attempt_id"]),
                      reverse=True)
    if job_probe is not None:
        jobs = job_probe(root)
    elif list_jobs is not None:
        jobs = _legacy_jobs(root, list_jobs)
    else:
        jobs = observe_jobs(root)
    all_jobs = jobs.get("jobs", [])
    observations, unknowns = [], []
    for row in selected[cursor:cursor + limit]:
        try:
            result = _projection(base, row)
            observations.append(result)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            observations.append({"candidate_id": row["candidate_id"],
                                 "attempt_id": row["attempt_id"], "status": row["status"],
                                 "status_authority": "LEDGER_ONLY",
                                 "stages": {}, "source_ref": None,
                                 "evidence_access": "NOT_VERIFIED"})
            unknowns.append({"attempt_id": row["attempt_id"], "reason_code": str(exc),
                             "authority": "trial_ledger.jsonl"})
    if ledger_error:
        unknowns.append({"reason_code": ledger_error, "authority": "trial_ledger.jsonl"})
    if git["visibility"] != "OBSERVED":
        unknowns.append({"reason_code": "GIT_STATE_UNKNOWN", "authority": "git"})
    omitted_evidence = max(len(selected) - cursor - len(observations), 0)
    if omitted_evidence:
        unknowns.append({"reason_code": "OMITTED_EVIDENCE_NOT_VERIFIED",
                         "count": omitted_evidence, "next_cursor": cursor + limit})
    if regressions:
        unknowns.append({"reason_code": "LEDGER_ATTEMPT_REGRESSION",
                         "affected_count": len(regressions)})
    if jobs.get("visibility") == "UNKNOWN":
        unknowns.append({"reason_code": jobs.get("reason_code", "JOB_VISIBILITY_UNKNOWN"),
                         "authority": "tmux"})
    if jobs.get("binding_errors"):
        unknowns.append({"reason_code": "V1_BINDING_EVIDENCE_UNREADABLE",
                         "count": len(jobs["binding_errors"])})
    if any(v["event"] != "completed" for v in selected):
        unknowns.append({"reason_code": "ATTEMPT_NOT_TERMINAL",
                         "attempt_count": sum(v["event"] != "completed" for v in selected)})
    if any(v["status"] == "RUNNING" for v in observations):
        unknowns.append({"reason_code": "WORKER_DONE_NOT_VERIFIED",
                         "authority": "trial_ledger.jsonl"})
    engineering_blockers = sorted({v["status"] for v in observations
                                   if v["status"] in {"ENGINEERING_ERROR", "BLOCKED_DATA",
                                                       "BLOCKED_EXECUTION", "INCONCLUSIVE_STAGE_3",
                                                       "INVALID_EVIDENCE", "INVALID_SPEC",
                                                       "INVALID_ALLOCATION", "ISOLATION_UNAVAILABLE",
                                                       "HOLDOUT_DENIED"}})
    if engineering_blockers:
        unknowns.append({"reason_code": "ENGINEERING_OR_DATA_BLOCKER",
                         "statuses": engineering_blockers,
                         "action": "inspect failure evidence; not economic falsification"})
    stale = [x["name"] for x in all_jobs if x.get("checkpoint", {}).get("freshness")
             in ("STALE", "CLOCK_CONFLICT")]
    if stale:
        unknowns.append({"reason_code": "WORKER_PROGRESS_STALE",
                         "count": len(stale), "scope": "bound v1 job checkpoints"})
    bound_unverifiable = [x["name"] for x in all_jobs
                          if x.get("binding", {}).get("authority") == "V1_JOB_NAME_MATCH_ONLY"
                          and not any(p.get("process", {}).get("status") == "PROCESS_PRESENT"
                                      and p.get("process", {}).get("same_uid") is True
                                      for p in x.get("panes", []))]
    if bound_unverifiable:
        unknowns.append({"reason_code": "BOUND_WORKER_PROCESS_UNVERIFIED",
                         "count": len(bound_unverifiable)})
    checkpoint_invalid = [x["name"] for x in all_jobs
                          if x.get("binding", {}).get("authority") == "V1_JOB_NAME_MATCH_ONLY"
                          and x.get("checkpoint", {}).get("state") == "INVALID"]
    if checkpoint_invalid:
        unknowns.append({"reason_code": "BOUND_CHECKPOINT_INVALID",
                         "count": len(checkpoint_invalid)})
    expired_leases = [x["name"] for x in all_jobs
                      if x.get("binding", {}).get("authority") == "V1_JOB_NAME_MATCH_ONLY"
                      and x.get("binding", {}).get("lease_status") == "EXPIRED"]
    if expired_leases:
        unknowns.append({"reason_code": "WORKER_LEASE_EXPIRED_UNRECONCILED",
                         "count": len(expired_leases)})
    conflicts = [x["name"] for x in all_jobs if x.get("binding", {}).get("authority")
                 == "CONFLICTING_ATTEMPT_CLAIMS"]
    if conflicts:
        unknowns.append({"reason_code": "CONFLICTING_JOB_OWNERSHIP",
                         "count": len(conflicts)})
    if unknowns:
        status, action = "BLOCKED", {
            "kind": "inspect_evidence", "permission": "metadata_read",
            "reason": "Reconcile evidence, process, checkpoint or source conflict; never relaunch blindly"}
    elif observations:
        status, action = "REVIEW", {
            "kind": "review_research", "permission": "scoped_evidence_read",
            "reason": "Scientific review of recorded stages; no authorization implied"}
    else:
        status, action = "UNKNOWN", {
            "kind": "register_development_candidate", "permission": "human_scoped_research",
            "reason": "No inspected factory attempt in this scope"}
    unresolved_names = sum(x.get("binding", {}).get("authority") == "UNATTRIBUTED"
                           for x in all_jobs)
    job_page = all_jobs[jobs_cursor:jobs_cursor + limit]
    dimension = {"source_quality": "NOT_REVALIDATED",
                 "scientific_evidence": "INTEGRITY_ONLY" if observations else "UNKNOWN",
                 "execution_qualification": "NOT_VERIFIED",
                 "job_visibility": jobs.get("visibility", "UNKNOWN"),
                 "approval": "NOT_GRANTED", "live": "NOT_VERIFIED"}
    version = digest({"git": git, "ledger": ledger_cursor,
                      "jobs": [(x["name"], x.get("panes"),
                                x.get("checkpoint"), x.get("binding"))
                               for x in all_jobs]})
    return {
        "schema_version": SCHEMA, "operation": "inspect_case",
        "scope": candidate_id or "all", "status": status,
        "state_revision": version, "view_rendered_at": now.isoformat(),
        "git": git, "source_cursors": {"ledger_hash": ledger_cursor,
                                      "git_head": git["head"],
                                      "tmux_observed_at": jobs.get("source_observed_at"),
                                      "snapshot_consistency": "NON_ATOMIC"},
        "authorities": {"research": "run_log/trial_ledger.jsonl",
                        "stages": "run_log/dual_mode/*/*/stage[1-3].json",
                        "attempts": "run_log/dual_mode/*/*/casefile.json",
                        "legacy": "src.research_control.casefile.build_casefile",
                        "data": "DataVault manifest authority (not opened)",
                        "jobs": "tmux pane + Linux process metadata",
                        "approval": "NONE_FOR_LIVE"},
        "dimensions": dimension,
        "actual_jobs": [x["name"] for x in job_page],
        "job_details": job_page,
        "job_reconciliation": {"name_matched_only_count": sum(
            x.get("binding", {}).get("authority") == "V1_JOB_NAME_MATCH_ONLY" for x in all_jobs),
            "process_identity_bound_count": 0,
            "unattributed_count": unresolved_names,
            "stale_checkpoint_count": len(stale),
            "process_unverified_bound_count": len(bound_unverifiable),
            "checkpoint_invalid_count": len(checkpoint_invalid),
            "expired_lease_count": len(expired_leases),
            "completion_inferred_from_session_names": False},
        "jobs_pagination": {"total": jobs.get("total"), "returned": len(job_page),
                            "offset": jobs_cursor, "omitted": max(len(all_jobs) - jobs_cursor - len(job_page), 0),
                            "next_cursor": jobs_cursor + limit if jobs_cursor + limit < len(all_jobs) else None},
        "research": observations,
        "pagination": {"total": len(selected), "returned": len(observations), "offset": cursor,
                       "omitted": max(len(selected) - cursor - len(observations), 0),
                       "next_cursor": cursor + limit if cursor + limit < len(selected) else None},
        "unknowns": unknowns, "unknown_summary": dict(Counter(
            item["reason_code"] for item in unknowns)),
        "next_action": action, "alternatives": [],
        "permissions": {"metadata_read": True, "scoped_evidence_read": True,
                        "development_compute": False, "protected_read": False,
                        "broker_orders": False, "deploy": False},
        "claims": {"observed": "git, hash-chain ledger, verified stage receipts, tmux/proc",
                   "inference": "next bounded evidence action (advisory only)",
                   "hypotheses": [], "unknown_count": len(unknowns)},
        "limitations": [
            "No global atomic snapshot across Git, files and tmux",
            "A process identity or tmux pane alone does not prove progress or completion",
            "Unattributed jobs have no verified checkpoint ownership",
            "Cryptographic integrity is not independent scientific verification",
            "No broker, market rows, holdout outcomes or credential access",
            "Previously exposed history never becomes unseen",
        ],
        "effects": ["READ_ONLY"],
    }


def read_evidence(root: str | Path, reference: str, *, max_bytes: int = 16_384) -> dict[str, Any]:
    """Expand a registered, SHA-verified *non-protected* Casefile metadata reference."""
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 256 <= max_bytes <= 65_536:
        raise ValueError("INVALID_READ_BUDGET")
    root = Path(root).resolve()
    relative = Path(reference)
    parts = relative.parts
    if (relative.is_absolute() or len(parts) != 4 or parts[0] != "dual_mode" or
        parts[-1] != "casefile.json" or any(x.startswith(".") or x == ".." for x in parts)):
        raise ValueError("EVIDENCE_SCOPE_DENIED")
    safe_name(parts[1])
    safe_name(parts[2])
    base = root / "run_log"
    rows, error, ledger_hash = _ledger(base)
    if error:
        raise ValueError(error)
    matching = [v for v in rows if v.get("candidate_id") == parts[1] and
                v.get("attempt_id") == parts[2]]
    if not matching or matching[-1]["event"] != "completed":
        raise ValueError("UNREGISTERED_OR_INCOMPLETE_EVIDENCE")
    record = matching[-1]
    if record["status"] == "HOLDOUT_EVALUATED" or record.get("holdout_access") is True:
        raise ValueError("PROTECTED_OUTCOME_ACCESS_DENIED")
    if not isinstance(record.get("casefile"), dict) or record["casefile"].get("path") != str(relative):
        raise ValueError("ARTIFACT_REFERENCE_CONFLICT")
    projected = _projection(base, record)
    result = {"schema_version": SCHEMA, "operation": "read_evidence",
              "scope": projected["candidate_id"], "source": projected["source_ref"],
              "source_observed_at": projected["source_observed_at"],
              "view_rendered_at": _utc_now().isoformat(), "status": projected["status"],
              "stages": projected["stages"], "digest": projected["source_sha256"],
              "registered_ledger_hash": ledger_hash,
              "verification_scope": projected["verification_scope"],
              "effects": ["READ_ONLY"],
              "limitations": ["No protected outcomes or stage numerical values opened",
                              "Registered checksum does not prove economic validity"]}
    if len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > max_bytes:
        raise ValueError("RESPONSE_BUDGET_EXCEEDED")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("inspect_case", "read_evidence", "capabilities"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--candidate")
    parser.add_argument("--reference")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--cursor", type=int, default=0)
    parser.add_argument("--jobs-cursor", type=int, default=0)
    parser.add_argument("--max-bytes", type=int, default=16_384)
    args = parser.parse_args(argv)
    try:
        if args.operation == "inspect_case":
            result = inspect_case(args.root, candidate_id=args.candidate, limit=args.limit,
                                  cursor=args.cursor, jobs_cursor=args.jobs_cursor)
        elif args.operation == "read_evidence":
            if not args.reference:
                raise ValueError("EVIDENCE_REF_REQUIRED")
            result = read_evidence(args.root, args.reference, max_bytes=args.max_bytes)
        else:
            result = capability_inventory(args.root)
    except (ValueError, OSError, TypeError) as exc:
        result = {"schema_version": SCHEMA, "status": "BLOCKED",
                  "reason_code": str(exc), "effects": ["READ_ONLY"]}
        print(json.dumps(result, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
