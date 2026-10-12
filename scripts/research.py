#!/usr/bin/env python3
"""Read-only research control-plane checks and live Engineer feature discovery."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml4t.engineer import feature_catalog

from src.catalog import (
    CatalogResolutionError,
    load_dataset_catalog,
    load_readiness_audit,
)
from src.research_control.feature_gateway import discover_feature
from src.research_session import ResearchSessionError, session_status


def _json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _git_state(root: Path) -> dict[str, Any]:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if head.returncode:
        return {
            "head": None,
            "dirty": None,
            "dirty_file_count": None,
            "dirty_identity": None,
        }
    entries = [
        entry.decode(errors="replace") for entry in status.stdout.split(b"\0") if entry
    ]
    names = sorted(entry[3:] for entry in entries)
    return {
        "head": head.stdout.strip(),
        "dirty": bool(entries),
        "dirty_file_count": len(entries),
        "dirty_identity": hashlib.sha256(status.stdout).hexdigest(),
        "dirty_paths": names[:100],
        "dirty_paths_truncated": len(names) > 100,
    }


def _runtime_jobs(root: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                "tmux",
                "list-panes",
                "-a",
                "-F",
                "#{session_name}\t#{pane_current_path}\t#{pane_current_command}\t#{pane_pid}",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"visibility": "unavailable", "active_jobs": [], "error": str(exc)}
    if result.returncode and "no server running" in result.stderr.lower():
        return {"visibility": "available", "active_jobs": []}
    if result.returncode:
        return {
            "visibility": "unavailable",
            "active_jobs": [],
            "error": result.stderr.strip(),
        }
    jobs = []
    for line in result.stdout.splitlines():
        session, cwd, command, pid = (line.split("\t", 3) + [""] * 4)[:4]
        safe_session = re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", session)
        log_candidates = (
            [
                root / "run_log" / "research_sessions" / session,
                root / "run_log" / session,
            ]
            if safe_session
            else []
        )
        log_ref = next(
            (
                path.relative_to(root).as_posix()
                for path in log_candidates
                if path.is_dir()
            ),
            None,
        )
        jobs.append(
            {
                "session": session,
                "state": "RUNNING",
                "cwd": cwd,
                "command": command,
                "pid": pid,
                "log_ref": log_ref,
            }
        )
    return {"visibility": "available", "active_jobs": jobs}


def _find_exit_clock(spec: dict[str, Any]) -> str | None:
    text = " ".join(
        str(instrument.get("session", "")) for instrument in spec.get("instruments", [])
    )
    matches = re.findall(r"\b(\d{1,2}:\d{2})\b", text)
    return "15:55" if "15:55" in matches else (matches[-1] if matches else None)


def _coverage(root: Path, item: dict[str, Any], timezone: str) -> dict[str, Any]:
    path = Path(item["path"])
    path = path if path.is_absolute() else root / path
    resolved_root = root.resolve()
    try:
        relative = path.relative_to(resolved_root)
    except ValueError:
        relative = Path("..")
    current = resolved_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            relative = Path("..")
            break
    if ".." in relative.parts:
        return {"path": str(item["path"]), "exists": False, "error": "data path is outside the workspace or uses a symlink"}
    if not path.is_file():
        return {"path": str(path), "exists": False}
    try:
        frame = pl.scan_parquet(path)
        names = frame.collect_schema().names()
        if "timestamp" not in names:
            return {
                "path": str(path),
                "exists": True,
                "error": "timestamp column missing",
            }
        row = (
            frame.select(
                pl.len().alias("rows"),
                pl.col("timestamp").min().alias("first"),
                pl.col("timestamp").max().alias("last"),
            )
            .collect()
            .row(0, named=True)
        )
        last = row["last"]
        if last is not None and last.tzinfo is not None:
            local_last = last.astimezone(ZoneInfo(timezone))
            available = local_last + timedelta(minutes=1)
            row.update(
                last_bar_open_local=local_last.isoformat(),
                last_bar_available_local=available.isoformat(),
            )
        return {
            "path": str(path.relative_to(root))
            if path.is_relative_to(root)
            else str(path),
            "exists": True,
            **row,
        }
    except (OSError, pl.exceptions.PolarsError, ValueError) as exc:
        return {"path": str(path), "exists": True, "error": str(exc)}


def _source_findings(
    spec: dict[str, Any], catalog: dict[str, Any] | None
) -> list[dict[str, Any]]:
    if catalog is None:
        return []
    resolutions = catalog.get("resolutions", {})
    entries = {entry.get("dataset_key"): entry for entry in catalog.get("entries", [])}
    findings = []
    for instrument in spec.get("instruments", []):
        symbol = str(instrument.get("symbol", "")).upper()
        requested = " ".join(
            str(instrument.get(key, "")) for key in ("symbol", "venue", "identity")
        ).lower()
        is_dukascopy = "usatech" in requested or "dukascopy" in requested
        if symbol not in ("NQ", "MNQ") and not is_dukascopy:
            continue
        alias = "NQ" if is_dukascopy else symbol
        resolution = resolutions.get(alias, {})
        candidates = resolution.get("candidate_dataset_keys", [])
        candidate_rows = [
            {
                "dataset_key": key,
                "source_symbol": entries.get(key, {}).get("source_symbol"),
                "authority": entries.get(key, {}).get("authority"),
                "qualification": entries.get(key, {}).get("qualification"),
            }
            for key in candidates
        ]
        if is_dukascopy:
            findings.append(
                {
                    "reason_code": "SOURCE_IDENTITY_CONFLICT",
                    "requested": "Dukascopy USATECH.IDX/USD",
                    "observed_catalog_candidates": candidate_rows,
                    "summary": "The NQ alias points to LSE NQ.F candidates; it does not identify Dukascopy USATECH.IDX/USD.",
                    "next_action": "Use an exact Dukascopy source identity with a reviewed, frozen proxy exception; do not resolve through NQ.",
                }
            )
        elif not candidates:
            findings.append(
                {
                    "reason_code": "SOURCE_IDENTITY_UNRESOLVED",
                    "requested": symbol,
                    "observed_catalog_candidates": [],
                    "summary": f"The catalog has no source candidates for {symbol}.",
                    "next_action": "Register and qualify an exact source before feature execution.",
                }
            )
        elif "cme" in requested or instrument.get("kind") == "futures":
            findings.append(
                {
                    "reason_code": "SOURCE_IDENTITY_UNQUALIFIED",
                    "requested": requested,
                    "observed_catalog_candidates": candidate_rows,
                    "summary": f"The {symbol} alias candidates are unqualified and do not establish a dated contract.",
                    "next_action": "Provide a qualified dated-contract source or freeze an explicitly labeled proxy variant.",
                }
            )
    return findings


def status(session_id: str, root: Path) -> dict[str, Any]:
    report = session_status(session_id, root)
    git = _git_state(root)
    trials = report["trials"]
    jobs = _runtime_jobs(root)
    actions = []
    if any(item["status"] == "pending" for item in trials):
        actions.append(
            "Review pending preregistered trials and their declared inputs before selecting one."
        )
    if jobs["visibility"] != "available":
        actions.append(
            "Confirm tmux state manually before starting any process; runtime visibility is unavailable."
        )
    if jobs["active_jobs"]:
        actions.append(
            "Inspect the listed active job and its log before considering a retry."
        )
    if not actions:
        actions.append(
            "Review the last recorded evidence; this report does not authorize a new run or live trading."
        )
    return {
        "schema_version": 1,
        "status": "IN_PROGRESS"
        if any(item["status"] == "pending" for item in trials)
        else "READY",
        "reason_code": "TRIALS_PENDING"
        if any(item["status"] == "pending" for item in trials)
        else "SESSION_STATUS",
        "summary": "Read-only view of frozen declarations, recorded trials, and active tmux panes; this command does not scan data or rehash artifacts.",
        "scope": "research_session_status",
        "session": {
            "session_id": session_id,
            "classification": report["classification"],
            "approval_status": report["approval_status"],
            "spec_sha256": report["spec_sha256"],
            "thesis": report["spec"]["thesis"],
            "falsifier": report["spec"]["falsifier"],
            "instruments": report["spec"]["instruments"],
            "data": report["spec"]["data"],
        },
        "trials": {
            "declared": len(trials),
            "completed": sum(item["status"] == "completed" for item in trials),
            "failed": sum(item["status"] == "failed" for item in trials),
            "pending": sum(item["status"] == "pending" for item in trials),
            "records": trials,
        },
        "audit": {
            "status": "NOT_RUN",
            "data_audit_performed": False,
            "artifact_generation_verified": False,
            "next_action": f"Run scripts/research_session.py report --session {session_id} --root . for full input and artifact checks.",
        },
        "runtime": jobs,
        "repository": git,
        "evidence_refs": [item["path"] for item in report["evidence"]],
        "next_actions": actions,
        "effects": ["READ_ONLY"],
        "approval_status": "NOT_APPROVED",
    }


def doctor(root: Path, session_id: str | None) -> dict[str, Any]:
    names = feature_catalog.list()
    features = [feature_catalog.describe(name) for name in names]
    registry_sha = _json_hash(sorted(features, key=lambda feature: feature["name"]))
    packages = {}
    for name in ("ml4t-engineer", "ml4t-backtest", "pydantic", "polars", "ruff"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    findings = []
    catalog = None
    readiness = None
    catalog_error = None
    try:
        catalog = load_dataset_catalog()
        readiness = load_readiness_audit()
    except (CatalogResolutionError, OSError, ValueError, json.JSONDecodeError) as exc:
        catalog_error = str(exc)
    session_detail = None
    if session_id:
        report = session_status(session_id, root)
        spec = report["spec"]
        findings.extend(_source_findings(spec, catalog))
        exit_clock = _find_exit_clock(spec)
        timezone = next(
            (
                item.get("timezone")
                for item in spec.get("instruments", [])
                if item.get("timezone")
            ),
            "UTC",
        )
        coverage = [
            _coverage(root, item, timezone)
            for item in spec.get("data", [])
            if item.get("role") == "prices"
        ]
        for item in coverage:
            if (
                item.get("last_bar_available_local")
                and exit_clock
                and exit_clock > item["last_bar_available_local"][11:16]
            ):
                findings.append(
                    {
                        "reason_code": "DATA_SESSION_MISMATCH",
                        "expected": f"required exit at {exit_clock} {timezone}",
                        "observed": f"last bar becomes available at {item['last_bar_available_local']}",
                        "evidence_ref": item["path"],
                        "summary": "The declared input ends before the required exit time.",
                        "next_actions": [
                            "Provide qualified source bars through the declared exit time.",
                            "Register a separate, explicitly shortened proxy strategy and session.",
                        ],
                    }
                )
        session_detail = status(session_id, root)
    runtime = _runtime_jobs(root)
    actions = [
        finding.get(
            "next_action",
            finding.get(
                "next_actions", ["Review the evidence and resolve the stated blocker."]
            )[0],
        )
        for finding in findings
    ]
    if runtime["visibility"] != "available":
        actions.append(
            "Confirm tmux state manually before starting a process; runtime visibility is unavailable."
        )
        findings.append(
            {
                "reason_code": "TMUX_VISIBILITY_UNAVAILABLE",
                "summary": runtime.get("error", "tmux state is unavailable"),
            }
        )
    if catalog_error:
        findings.append(
            {
                "reason_code": "DATA_CATALOG_UNAVAILABLE",
                "summary": catalog_error,
                "next_action": "Restore the canonical ml4t-data catalog before qualifying a data source.",
            }
        )
        actions.append(findings[-1]["next_action"])
    if not actions:
        actions = [
            "Use discover to inspect an installed feature, or status --session to inspect a frozen session."
        ]
    return {
        "schema_version": 1,
        "status": "BLOCKED" if findings else "READY",
        "reason_code": findings[0]["reason_code"] if findings else "DOCTOR_CLEAR",
        "summary": "Read-only installed-capability, data-catalog, source, session-clock, and active-job inspection.",
        "scope": "doctor",
        "repository": _git_state(root),
        "environment": {"packages": packages},
        "engineer": {
            "feature_count": len(names),
            "registry_sha256": registry_sha,
            "features": names,
        },
        "data_catalog": {
            "identity": catalog.get("catalog_identity") if catalog else None,
            "readiness_identity": _json_hash(readiness) if readiness else None,
            "nq_resolution": (catalog or {}).get("resolutions", {}).get("NQ"),
            "error": catalog_error,
        },
        "runtime": runtime,
        "session": session_detail,
        "findings": findings,
        "evidence_refs": [
            finding["evidence_ref"]
            for finding in findings
            if finding.get("evidence_ref")
        ],
        "next_actions": actions,
        "effects": ["READ_ONLY"],
        "approval_status": "NOT_APPROVED",
    }


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    sub = command.add_subparsers(dest="command", required=True)
    doctor_parser = sub.add_parser(
        "doctor", help="inspect installed capabilities and source/session gates"
    )
    doctor_parser.add_argument("--root", type=Path, default=ROOT)
    doctor_parser.add_argument("--session")
    status_parser = sub.add_parser(
        "status", help="show a frozen session and its recorded trials"
    )
    status_parser.add_argument("--root", type=Path, default=ROOT)
    status_parser.add_argument("--session", required=True)
    discover_parser = sub.add_parser(
        "discover", help="query the installed Engineer feature registry"
    )
    discover_parser.add_argument("--root", type=Path, default=ROOT)
    discover_parser.add_argument("--feature", required=True)
    return command


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "doctor":
            result = doctor(args.root.resolve(), args.session)
        elif args.command == "status":
            result = status(args.session, args.root.resolve())
        else:
            metadata = discover_feature(args.feature.lower())
            if metadata is None:
                result = {
                    "schema_version": 1,
                    "status": "BLOCKED",
                    "reason_code": "FEATURE_NOT_INSTALLED",
                    "summary": f"Engineer feature {args.feature!r} is not present in the installed registry.",
                    "scope": "feature_discovery",
                    "feature": args.feature,
                    "alternatives": feature_catalog.search(args.feature)[:20],
                    "effects": ["READ_ONLY"],
                    "next_actions": [
                        "Select a feature returned by the installed registry or request an approved extension."
                    ],
                    "approval_status": "NOT_APPROVED",
                }
            else:
                result = {
                    "schema_version": 1,
                    "status": "READY",
                    "reason_code": "FEATURE_FOUND",
                    "summary": "Metadata returned by the installed Engineer registry; discovery alone is not an execution proof.",
                    "scope": "feature_discovery",
                    "feature": metadata,
                    "effects": ["READ_ONLY"],
                    "next_actions": [
                        "Check the feature inputs, parameters, and lookback against a strict ResearchContractV1."
                    ],
                    "approval_status": "NOT_APPROVED",
                }
    except (
        ResearchSessionError,
        OSError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
        ValueError,
    ) as exc:
        result = {
            "schema_version": 1,
            "status": "ERROR",
            "reason_code": "INSPECTION_ERROR",
            "summary": str(exc),
            "scope": args.command,
            "effects": ["READ_ONLY"],
            "next_actions": [
                "Correct the reported input or restore the required read-only authority."
            ],
            "approval_status": "NOT_APPROVED",
        }
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 2 if result["status"] in ("BLOCKED", "ERROR") else 0


if __name__ == "__main__":
    raise SystemExit(main())
