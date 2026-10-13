"""Regenerable agent Casefile: authoritative frozen facts, append-only attempts and status.

No heavy market-data scans, no provider fetches, no re-hashing large artifacts.
This is a derived read model, not a new research or live execution authority.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.research_session import ResearchSessionError, session_status

from .attempts import AttemptDecision, AttemptLedger, tmux_sessions

_ATTEMPT = re.compile(r"^[0-9a-fA-F-]{32,40}$")


def explain_blocker(value: Any) -> dict[str, Any]:
    """Normalize fail-closed gate/attempt/error into one actionable reason object."""
    if isinstance(value, dict):
        record = value
    elif hasattr(value, "model_dump"):
        record = value.model_dump(mode="json")
    elif isinstance(value, AttemptDecision):
        record = {
            "status": value.status,
            "reason_code": value.reason_code,
            "observed": value.detail,
            "where_found": value.evidence_path,
        }
    else:
        return {
            "status": "BLOCKED",
            "reason_code": "EVIDENCE_MISSING",
            "expected": "typed gate/attempt record",
            "observed": str(type(value)),
            "where_found": "casefile blocker input",
            "next_safe_action": "Capture and verify the original typed failure.",
        }
    asserted_success = record.get("status") in ("PASS", "COMPLETED", "SUCCESS")
    reason = (
        "ASSERTED_SUCCESS_NOT_EVIDENCE"
        if asserted_success
        else str(record.get("reason_code") or "UNKNOWN_EVIDENCE")
    )
    return {
        "status": "BLOCKED",
        "reason_code": reason,
        "expected": record.get("expected", "verified authority for this operation"),
        "observed": record.get("observed", record.get("detail", record.get("status"))),
        "where_found": record.get(
            "where_found", record.get("evidence_path", "attempt/gate record")
        ),
        "next_safe_action": record.get("next_safe_action")
        or {
            "JOB_VISIBILITY_UNKNOWN": "Restore tmux visibility; never start a duplicate job.",
            "LEASE_UNCERTAIN": "Inspect existing worker, log, lease and tmux before retry.",
            "IDENTITY_DRIFT": "Revalidate or create a new frozen research session, do not reuse stale permit.",
            "HOLDOUT_EXPOSED": "Keep the observed holdout sealed for future scoring.",
            "ENGINE_EXECUTION_INVALID": "Review native fill ledger and conservative OCO ordering.",
            "FEATURE_NUMERICAL_MISMATCH": "Check independent numerical oracle, not only gateway output.",
            "SOURCE_IDENTITY_CONFLICT": "Resolve exact catalog/vendor identity before feature execution.",
            "ASSERTED_SUCCESS_NOT_EVIDENCE": "Verify original worker logs, artifacts and gate proofs.",
        }.get(
            reason,
            "Inspect the linked evidence and clear this blocker before execution.",
        ),
    }


def build_casefile(
    root: str | Path,
    session_id: str,
    *,
    list_jobs: Callable[[], set[str] | None] = tmux_sessions,
) -> dict[str, Any]:
    """Cold/warm read-only view, derived from verified v1 + append-only attempts."""
    root = Path(root).resolve()
    report = session_status(session_id, root)
    ledger = AttemptLedger(root, session_id, list_jobs=list_jobs)
    attempts = list(ledger.latest().values())
    attempts.sort(key=lambda event: (event["trial_id"], event["attempt_id"]))
    trials = report["trials"]
    identity = report["identity"]
    jobs = list_jobs()
    running = [a for a in attempts if a["status"] == "RUNNING"]
    unknown = jobs is None
    active = [a for a in attempts if a["status"] in ("PLANNED", "RUNNING")]
    uncertain = (
        unknown
        or bool(active)
        or any(a["status"] in ("BLOCKED", "FAILED", "ABORTED") for a in attempts)
    )
    terminal = [t for t in trials if t["status"] in ("completed", "failed")]
    if unknown:
        status, reason = "BLOCKED", "JOB_VISIBILITY_UNKNOWN"
        action = "Restore tmux visibility before any run or resume."
    elif any(a["job_name"] not in jobs for a in running):
        status, reason = "BLOCKED", "RUNNING_JOB_UNVERIFIED"
        action = "Inspect attempt log and process before retry; do not infer success."
    elif active:
        status, reason = "RUNNING", "ATTEMPT_IN_PROGRESS"
        action = "Inspect the existing attempt and its job; use resume without launching a duplicate."
    elif uncertain:
        status, reason = "BLOCKED", "ATTEMPT_REVIEW_REQUIRED"
        action = "Review failed or aborted attempts before selecting another registered trial."
    elif any(t["status"] == "pending" for t in trials):
        status, reason = "IN_PROGRESS", "TRIALS_PENDING"
        action = (
            "Obtain a new verified RunPermit for the next declared development trial."
        )
    else:
        status, reason = "REVIEW", "TRIALS_RECORDED_NOT_APPROVED"
        action = (
            "Review verified evidence and limitations; no production authorization."
        )
    return {
        "schema_version": 1,
        "scope": "research_casefile",
        "status": status,
        "reason_code": reason,
        "session_id": session_id,
        "hypothesis": report["spec"]["thesis"],
        "falsifier": report["spec"]["falsifier"],
        "source": {
            "declared_instruments": report["spec"]["instruments"],
            "data": report["spec"]["data"],
            "frozen_data_identities": identity["data"],
            "spec_sha256": report["spec_sha256"],
            "catalog_authority": "frozen_source_only",
        },
        "plan": {
            "evaluation": report["spec"]["evaluation"],
            "baseline": report["spec"]["baseline"],
            "costs": report["spec"]["costs"],
            "declared_trials": [trial["declaration"] for trial in trials],
        },
        "trial_status": {
            "declared": len(trials),
            "terminal": len(terminal),
            "pending": sum(t["status"] == "pending" for t in trials),
            "records": [
                {
                    "trial_id": t["declaration"]["id"],
                    "status": t["status"],
                    "record": t["record"],
                }
                for t in trials
            ],
        },
        "attempts": attempts,
        "runtime": {
            "visibility": "available" if not unknown else "unknown",
            "matching_live_jobs": sorted(
                jobs.intersection({a["job_name"] for a in attempts})
            )
            if jobs is not None
            else [],
            "active_attempts": [a["attempt_id"] for a in active],
        },
        "exposure": {
            "classification": report.get("classification", "EXPLORATORY"),
            "holdout_start": report["spec"]["evaluation"].get("holdout_start"),
            "holdout_verified_unseen": False,
            "prior_observations_cannot_become_unseen": True,
            "approval_status": "NOT_APPROVED",
        },
        "limitations": [
            "This derived view does not scan market data or independently rehash artifacts.",
            "A terminal or cached attempt is not a valid trading approval.",
            "Missing independent evidence, unknown tmux or failed jobs never imply PASS.",
        ],
        "evidence_refs": [
            *(item["path"] for item in identity.get("evidence", [])),
            *(
                item["record"]["artifact"]["path"]
                for item in terminal
                if item["record"] and item["record"].get("artifact")
            ),
            *(
                str((ledger.path / (a["event_id"] + ".json")).relative_to(root))
                for a in attempts
            ),
        ],
        "next_safe_action": action,
        "effects": ["READ_ONLY"],
    }


def inspect_resume(
    root: str | Path,
    session_id: str,
    attempt_id: str,
    *,
    list_jobs: Callable[[], set[str] | None] = tmux_sessions,
) -> dict[str, Any]:
    """Idempotent, read-only resume decision, not a job launcher or trust promotion."""
    if not _ATTEMPT.fullmatch(attempt_id):
        return explain_blocker(
            {"reason_code": "ATTEMPT_UNKNOWN", "observed": attempt_id}
        )
    try:
        ledger = AttemptLedger(root, session_id, list_jobs=list_jobs)
        record = ledger.latest().get(attempt_id)
    except (ResearchSessionError, ValueError, OSError, KeyError) as exc:
        return explain_blocker(
            {"reason_code": "SESSION_IDENTITY_INVALID", "observed": str(exc)}
        )
    if record is None:
        return explain_blocker(
            {"reason_code": "ATTEMPT_UNKNOWN", "observed": attempt_id}
        )
    jobs = list_jobs()
    if jobs is None:
        return explain_blocker(
            {"reason_code": "JOB_VISIBILITY_UNKNOWN", "observed": attempt_id}
        )
    status = record["status"]
    if status in ("PLANNED", "RUNNING") and record["job_name"] in jobs:
        return {
            "status": "RUNNING",
            "reason_code": "ATTEMPT_PRESENT",
            "attempt_id": attempt_id,
            "job_name": record["job_name"],
            "evidence_ref": str(
                (ledger.path / (record["event_id"] + ".json")).relative_to(ledger.root)
            ),
            "next_safe_action": "Inspect current job log and process. Never launch a second worker.",
            "effects": ["READ_ONLY"],
        }
    if status in ("PLANNED", "RUNNING"):
        return explain_blocker(
            {
                "reason_code": "LEASE_UNCERTAIN",
                "observed": f"{status}; named job currently absent",
                "where_found": str(ledger.path),
            }
        )
    return {
        "status": "REVIEW",
        "reason_code": "ATTEMPT_TERMINAL_EVIDENCE",
        "attempt_id": attempt_id,
        "terminal_status": status,
        "next_safe_action": "Verify logs, hashes and artifacts before interpreting terminal status.",
        "effects": ["READ_ONLY"],
    }
