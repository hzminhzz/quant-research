"""ATS-0/1: bounded, read-only projection of existing research authorities.

Only metadata JSON from the declared run_log is read. Never read market rows,
protected partitions, credentials, order endpoints or execute research code.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.engine.common import beneath, digest, file_hash, safe_name
from src.research_control.attempts import tmux_sessions

SCHEMA = "ats-read-v1"
TERMINAL = {"FALSIFIED_STAGE_2", "FALSIFIED_STAGE_3", "HOLDOUT_EVALUATED",
            "ENGINEERING_ERROR", "BLOCKED_DATA", "INCONCLUSIVE_STAGE_3"}
DENIED_NAMES = ("holdout", "protected", "credential", "secret", "token", "key", ".env")


def _git(root: Path) -> dict[str, Any]:
    def run(*args: str) -> str:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                                text=True, timeout=8, check=False)
        return result.stdout.strip() if result.returncode == 0 else "UNKNOWN"
    changes = run("status", "--porcelain", "--untracked-files=no").splitlines()
    return {"head": run("rev-parse", "HEAD"), "branch": run("branch", "--show-current"),
            "dirty": bool(changes), "tracked_modified_count": len(changes),
            "source": "git local checkout"}


def _safe_json(root: Path, rel: str, *, max_bytes: int = 256_000) -> dict[str, Any]:
    path = beneath(root, rel, must_exist=True)
    if path.suffix != ".json" or any(word in part.lower() for part in path.relative_to(root).parts
                                      for word in DENIED_NAMES):
        raise ValueError("EVIDENCE_SCOPE_DENIED")
    if path.stat().st_size > max_bytes:
        raise ValueError("EVIDENCE_TOO_LARGE")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("EVIDENCE_SCHEMA_INVALID")
    return value


def _record(root: Path, path: Path) -> dict[str, Any]:
    rel = str(path.relative_to(root))
    data = _safe_json(root, rel)
    if not all(k in data for k in ("candidate_id", "attempt_id", "status", "stages")):
        raise ValueError("EVIDENCE_SCHEMA_INVALID")
    # Return only interpreted metadata; protected result metrics never leave this adapter.
    stages = {str(n): {"status": v.get("status", "UNKNOWN")} for n, v in data["stages"].items()
              if str(n) in ("1", "2", "3", "4") and isinstance(v, dict)}
    return {"candidate_id": data["candidate_id"], "attempt_id": data["attempt_id"],
            "status": data["status"], "stages": stages, "spec_hash": data.get("spec_hash"),
            "code_hash": data.get("code_hash"), "panel_hash": data.get("panel_hash"),
            "holdout_access": bool(data.get("holdout_access", False)),
            "source_ref": rel, "source_sha256": file_hash(path),
            "source_observed_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()}


def _ledger(root: Path) -> tuple[list[dict[str, Any]], str | None]:
    path = root / "trial_ledger.jsonl"
    if not path.exists():
        return [], "LEDGER_ABSENT"
    previous, records = "0" * 64, []
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                checksum = row.pop("record_hash")
                if row.get("previous_hash") != previous or digest(row) != checksum:
                    return [], "LEDGER_INTEGRITY_FAILURE"
                previous = checksum
                records.append({k: row.get(k) for k in
                                ("candidate_id", "attempt_id", "event", "status",
                                 "spec_hash", "run_path", "recorded_at", "casefile")})
    except (OSError, ValueError, KeyError, TypeError):
        return [], "LEDGER_UNREADABLE"
    return records, None


def inspect_case(root: str | Path, *, candidate_id: str | None = None,
                 limit: int = 10, cursor: int = 0, list_jobs=tmux_sessions) -> dict[str, Any]:
    """Derive a decision frontier; no cache, no provider, no protected research reads."""
    root = Path(root).resolve()
    if candidate_id is not None:
        safe_name(candidate_id)
    if not 1 <= limit <= 50 or cursor < 0:
        raise ValueError("INVALID_PAGINATION")
    now = datetime.now(UTC).isoformat()
    git = _git(root)
    base = root / "run_log"
    rows, ledger_error = _ledger(base)
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if row["candidate_id"] and row["attempt_id"]:
            latest[(row["candidate_id"], row["attempt_id"])] = row
    matched = sorted((v for v in latest.values()
                      if candidate_id is None or v["candidate_id"] == candidate_id),
                     key=lambda v: (v.get("recorded_at") or "", v["attempt_id"]), reverse=True)
    jobs = list_jobs()
    observed = []
    unknowns = []
    for row in matched[cursor:cursor + limit]:
        try:
            relative = row.get("casefile")
            if isinstance(relative, dict):
                relative = relative.get("path")
            expected = base / str(relative) if relative else None
            if expected is None or not expected.is_file() or expected.name != "casefile.json":
                raise ValueError("ARTIFACT_MISSING")
            if row["status"] == "HOLDOUT_EVALUATED":
                observed.append({"candidate_id": row["candidate_id"],
                                 "attempt_id": row["attempt_id"], "status": row["status"],
                                 "stages": {"4": {"status": "REDACTED"}},
                                 "source_ref": None, "source_sha256": None,
                                 "source_observed_at": row.get("recorded_at"),
                                 "evidence_access": "PROTECTED_OUTCOME_NOT_OPENED"})
                continue
            record = _record(base, expected)
            if (isinstance(row.get("casefile"), dict)
                and file_hash(expected) != row["casefile"].get("sha256")):
                raise ValueError("ARTIFACT_HASH_MISMATCH")
            observed.append(record)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            unknowns.append({"attempt_id": row["attempt_id"],
                             "reason_code": str(exc), "authority": "trial_ledger.jsonl"})
    if ledger_error:
        unknowns.append({"reason_code": ledger_error, "authority": "trial_ledger.jsonl"})
    if jobs is None:
        unknowns.append({"reason_code": "JOB_VISIBILITY_UNKNOWN", "authority": "tmux"})
    unfinished = [v for v in matched if v["event"] != "completed"]
    if unfinished:
        unknowns.append({"reason_code": "ATTEMPT_NOT_TERMINAL",
                         "attempt_count": len(unfinished), "authority": "trial_ledger.jsonl"})
    if observed and any(v["status"] == "RUNNING" for v in observed):
        unknowns.append({"reason_code": "WORKER_DONE_NOT_VERIFIED", "authority": "casefile"})
    if unknowns:
        action = {"kind": "inspect_evidence", "permission": "metadata_read",
                  "reason": "Resolve missing, running or contradictory authority; never relaunch automatically"}
        status = "BLOCKED"
    elif observed:
        action = {"kind": "review_research", "permission": "scoped_evidence_read",
                  "reason": "Review stage evidence and outstanding scientific gates"}
        status = "REVIEW"
    else:
        action = {"kind": "register_development_candidate", "permission": "approval_required",
                  "reason": "No verified candidate evidence in selected scope"}
        status = "UNKNOWN"
    # All source watermarks are separate; rendering now cannot freshen a file.
    return {"schema_version": SCHEMA, "operation": "inspect_case", "scope": candidate_id or "all",
            "status": status,
            "state_revision": digest({"head": git["head"], "ledger": rows,
                                      "jobs": sorted(jobs) if jobs is not None else None}),
            "view_rendered_at": now, "git": git,
            "authorities": {"research": "run_log/trial_ledger.jsonl",
                            "attempts": "run_log/dual_mode/*/*/casefile.json",
                            "legacy": "src.research_control.casefile.build_casefile",
                            "data": "DataVault manifest metadata (not inspected)",
                            "jobs": "tmux", "approval": "NONE_FOR_LIVE"},
            "dimensions": {"source_quality": "NOT_REVALIDATED",
                           "scientific_evidence": "PARTIAL" if observed else "UNKNOWN",
                           "execution_qualification": "NOT_VERIFIED",
                           "job_visibility": "UNKNOWN" if jobs is None else "OBSERVED",
                           "approval": "NOT_GRANTED", "live": "NOT_VERIFIED"},
            "actual_jobs": sorted(jobs)[:10] if jobs is not None else [],
            "jobs_pagination": {"total": len(jobs) if jobs is not None else None,
                                "returned": min(len(jobs), 10) if jobs is not None else 0,
                                "omitted": max(len(jobs) - 10, 0) if jobs is not None else None,
                                "next_cursor": 10 if jobs is not None and len(jobs) > 10 else None},
            "research": observed, "unknowns": unknowns,
            "pagination": {"total": len(matched), "returned": len(observed),
                           "offset": cursor, "next_cursor": cursor + limit if cursor + limit < len(matched) else None},
            "next_action": action, "alternatives": [],
            "permissions": {"metadata_read": True, "scoped_evidence_read": True,
                            "development_compute": False, "protected_read": False,
                            "broker_orders": False, "deploy": False},
            "limitations": ["Historical exposure cannot become unseen",
                            "Unknown job ownership blocks automatic restart",
                            "No runtime/broker permission inferred from research results",
                            "Unscanned source and provider state are unknown",
                            "File mtimes are source timestamps, not evidence of freshness"],
            "effects": ["READ_ONLY"]}


def read_evidence(root: str | Path, reference: str, *, max_bytes: int = 16_384) -> dict[str, Any]:
    """Expand only an issued factory casefile reference, never arbitrary filesystem paths."""
    root = Path(root).resolve()
    rel = Path(reference)
    parts = rel.parts
    if (rel.is_absolute() or len(parts) != 4 or parts[0] != "dual_mode"
        or parts[-1] != "casefile.json" or any(part.startswith(".") or part == ".." for part in parts)):
        raise ValueError("EVIDENCE_SCOPE_DENIED")
    safe_name(parts[1])
    safe_name(parts[2])
    # A full casefile can contain holdout metrics: consult only the ledger first.
    rows, error = _ledger(root / "run_log")
    if error:
        raise ValueError(error)
    matches = [r for r in rows if r.get("casefile") and
               isinstance(r["casefile"], dict) and r["casefile"].get("path") == str(rel)]
    if not matches or matches[-1]["status"] == "HOLDOUT_EVALUATED":
        raise ValueError("PROTECTED_OR_UNREGISTERED_EVIDENCE_DENIED")
    data = _record(root / "run_log", (root / "run_log" / rel).resolve())
    return {"schema_version": SCHEMA, "operation": "read_evidence",
            "scope": data["candidate_id"], "source": data["source_ref"],
            "source_observed_at": data["source_observed_at"],
            "view_rendered_at": datetime.now(UTC).isoformat(),
            "status": data["status"], "stages": data["stages"],
            "digest": data["source_sha256"], "effects": ["READ_ONLY"],
            "limitations": ["Stage metrics and protected outcomes intentionally omitted"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("inspect_case", "read_evidence"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--candidate")
    parser.add_argument("--reference")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--cursor", type=int, default=0)
    args = parser.parse_args()
    try:
        if args.operation == "inspect_case":
            result = inspect_case(args.root, candidate_id=args.candidate,
                                  limit=args.limit, cursor=args.cursor)
        else:
            if not args.reference:
                raise ValueError("EVIDENCE_REF_REQUIRED")
            result = read_evidence(args.root, args.reference)
    except (ValueError, OSError) as exc:
        result = {"schema_version": SCHEMA, "status": "BLOCKED",
                  "reason_code": str(exc), "effects": ["READ_ONLY"]}
        print(json.dumps(result, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
