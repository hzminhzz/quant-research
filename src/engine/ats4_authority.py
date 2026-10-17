"""Hash and verify ATS-4 event runtime and frozen M8 research history."""
from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
from typing import Any

HISTORY_MANIFEST = "docs/audit/ats4_history_authority.json"
HISTORY_MANIFEST_SHA256 = "ab27aa00ef40f3ab4e0b9e13924cd76802d2c9290482d0f00865cf077e217c6f"
PINNED_VERSIONS = {
    "ml4t-backtest": "0.1.7",
    "ml4t-engineer": "0.1.4",
    "ml4t-diagnostic": "0.1.6.post2",
    "exchange-calendars": "4.13.2",
}
HISTORY_SESSIONS = {
    *(f"m8_n8_dukascopy_us_cash_30m_v{i}" for i in range(1, 8)),
    "m8_n8_dukascopy_nas100_cfd_30m_v1",
    "m8_n8_dukascopy_nas100_cfd_30m_v2",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _common_runtime_identity(root: Path) -> str:
    # Load the unchanged common implementation by file so this module adds no eager ML4T imports.
    path = root / "src/engine/common.py"
    spec = importlib.util.spec_from_file_location("_ats4_common_identity", path)
    if spec is None or spec.loader is None:
        raise _quant_error("INVALID_EVIDENCE", f"cannot load common identity: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.runtime_identity()


def _quant_error(status: str, reason: str) -> Exception:
    from src.engine.common import QuantError

    return QuantError(status, reason)


def _installed_versions() -> dict[str, str]:
    try:
        versions = {name: importlib.metadata.version(name) for name in PINNED_VERSIONS}
    except importlib.metadata.PackageNotFoundError as exc:
        raise _quant_error("BLOCKED_RUNTIME", f"required ATS-4 runtime package missing: {exc}") from exc
    mismatches = {name: (versions[name], expected) for name, expected in PINNED_VERSIONS.items()
                  if versions[name] != expected}
    if mismatches:
        raise _quant_error("BLOCKED_RUNTIME", f"ATS-4 requires pinned runtime versions: {mismatches}")
    return versions


def _package_source_hashes(package: str, prefix: str) -> dict[str, str]:
    distribution = importlib.metadata.distribution(package)
    files = distribution.files or ()
    hashes = {}
    for relative in sorted(files, key=str):
        name = str(relative).replace("\\", "/")
        if name.startswith(prefix) and name.endswith(".py"):
            path = Path(distribution.locate_file(relative))
            if path.is_file():
                hashes[name] = _sha256(path)
    if not hashes:
        raise _quant_error("BLOCKED_RUNTIME", f"installed Python sources unavailable for {package}")
    return hashes


def event_runtime_identity(root: str | Path | None = None) -> dict[str, Any]:
    """Return the event dependency content identity; call at run start and end to detect drift."""
    base = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    base = base.resolve()
    required = [base / "src/portfolio_evidence.py", base / "scripts/quant.py", base / "uv.lock"]
    control_sources = sorted((base / "src/research_control").rglob("*.py"))
    if not control_sources:
        raise _quant_error("BLOCKED_RUNTIME", "ATS-4 event dependency sources are missing")
    required.extend(control_sources)
    if any(not path.is_file() for path in required):
        missing = [str(path) for path in required if not path.is_file()]
        raise _quant_error("BLOCKED_RUNTIME", f"ATS-4 runtime source missing: {missing}")
    source_hashes = {path.relative_to(base).as_posix(): _sha256(path) for path in required}
    versions = _installed_versions()
    native_sources = {
        "ml4t-backtest": _package_source_hashes("ml4t-backtest", "ml4t/backtest/"),
        "ml4t-engineer": _package_source_hashes("ml4t-engineer", "ml4t/engineer/"),
        "ml4t-diagnostic": _package_source_hashes("ml4t-diagnostic", "ml4t/diagnostic/"),
        "exchange-calendars": _package_source_hashes("exchange-calendars", "exchange_calendars/"),
    }
    identity = {
        "common_runtime_identity": _common_runtime_identity(base),
        "source_hashes": source_hashes,
        "native_source_hashes": {name: _digest(files) for name, files in native_sources.items()},
        "native_source_file_hashes": native_sources,
        "versions": versions,
    }
    identity["identity_digest"] = _digest(identity)
    return identity


def _discovered_history_paths(root: Path) -> set[str]:
    paths = set()
    for session_id in HISTORY_SESSIONS:
        folder = root / "run_log/research_sessions" / session_id
        for pattern in ("frozen_spec.json", "trials/*.json", "attempts/*.json"):
            paths.update(path.relative_to(root).as_posix() for path in folder.glob(pattern) if path.is_file())
    results = root / "run_log/m8/n8/cash_session/results"
    for pattern in ("*/report.json", "*/manifest.json", "*/*failure.json"):
        paths.update(path.relative_to(root).as_posix() for path in results.glob(pattern) if path.is_file())
    old_attempt = root / "run_log/m8/n8/results/70841083-b113-4319-8981-dfaef88c13ab"
    paths.update(path.relative_to(root).as_posix() for path in old_attempt.glob("*.json") if path.is_file())
    return paths


def _verify_manifest(root: Path, *, expected_manifest_sha256: str) -> dict[str, Any]:
    path = root / HISTORY_MANIFEST
    if not path.is_file():
        raise _quant_error("BLOCKED_HISTORY", f"history manifest missing: {HISTORY_MANIFEST}")
    if _sha256(path) != expected_manifest_sha256:
        raise _quant_error("INVALID_EVIDENCE", "frozen history manifest hash mismatch")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _quant_error("INVALID_EVIDENCE", f"history manifest is unreadable: {exc}") from exc
    authorities = manifest.get("authorities")
    if not isinstance(authorities, list):
        raise _quant_error("INVALID_EVIDENCE", "history authority list is invalid")
    by_path = {item.get("path"): item for item in authorities}
    if len(by_path) != len(authorities):
        raise _quant_error("INVALID_EVIDENCE", "duplicate history authority path")
    discovered = _discovered_history_paths(root)
    session_prefixes = tuple(f"run_log/research_sessions/{session_id}/" for session_id in HISTORY_SESSIONS)
    result_prefixes = ("run_log/m8/n8/cash_session/results/",
                       "run_log/m8/n8/results/70841083-b113-4319-8981-dfaef88c13ab/")
    recorded = {name for name in by_path if name.startswith(session_prefixes + result_prefixes)}
    if discovered != recorded:
        missing, unexpected = sorted(recorded - discovered), sorted(discovered - recorded)
        raise _quant_error("BLOCKED_HISTORY", f"history cardinality drift; missing={missing}, unrecorded={unexpected}")
    for name, item in by_path.items():
        authority = root / name
        if not authority.is_file():
            raise _quant_error("BLOCKED_HISTORY", f"history authority missing: {name}")
        if _sha256(authority) != item.get("sha256"):
            raise _quant_error("INVALID_EVIDENCE", f"history authority hash mismatch: {name}")
    for session_id in HISTORY_SESSIONS:
        frozen_path = root / "run_log/research_sessions" / session_id / "frozen_spec.json"
        try:
            frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise _quant_error("INVALID_EVIDENCE", f"frozen session is unreadable: {session_id}") from exc
        if frozen.get("session_id") != session_id:
            raise _quant_error("INVALID_EVIDENCE", f"frozen session identifier mismatch: {session_id}")
    frozen_records = manifest.get("frozen_sessions")
    observed_freezes = {item.get("session_id"): item for item in frozen_records or ()}
    if len(observed_freezes) != len(HISTORY_SESSIONS) or set(observed_freezes) != HISTORY_SESSIONS:
        raise _quant_error("BLOCKED_HISTORY", "frozen session inventory cardinality or IDs differ")
    actual_freeze_paths = {path.relative_to(root).as_posix()
                           for path in (root / "run_log/research_sessions").glob("m8_n8*/frozen_spec.json")}
    pinned_freeze_paths = {item.get("path") for item in frozen_records}
    if actual_freeze_paths != pinned_freeze_paths:
        raise _quant_error("BLOCKED_HISTORY", "tracked N8 frozen session inventory changed")
    for session_id, item in observed_freezes.items():
        path = root / item["path"]
        frozen = json.loads(path.read_text(encoding="utf-8"))
        current = {"session_id": frozen.get("session_id"),
                   "path": item["path"], "sha256": _sha256(path),
                   "frozen_sha256": frozen.get("frozen_sha256"),
                   "created_at": frozen.get("created_at"),
                   "classification": frozen.get("classification"),
                   "artifact_generation_verified": frozen.get("artifact_generation_verified"),
                   "status": frozen.get("status"), "approval_status": frozen.get("approval_status")}
        if item != current:
            raise _quant_error("INVALID_EVIDENCE", f"frozen session metadata differs: {session_id}")
    records = manifest.get("known_attempts")
    expected_history_ids = {"70841083-b113-4319-8981-dfaef88c13ab",
                             "c0864648-5bfc-491a-a133-295a82d37a94",
                             "67e2d592-4d19-44f9-973b-600c60a2114a",
                             "471ee061-0ae4-4d96-a8c2-60dece7d4401",
                             "5b960023-454b-4d1a-8c28-975e314f9895",
                             "e908ef2f-0d1d-44f4-a484-0203b616cbb4",
                             "freeze-only:m8_n8_dukascopy_nas100_cfd_30m_v1",
                             "preflight:m8_n8_dukascopy_us_cash_30m_v1",
                             "preflight:m8_n8_dukascopy_us_cash_30m_v6"}
    if (not isinstance(records, list) or {item.get("history_id") for item in records} != expected_history_ids
            or len(records) != len(expected_history_ids)):
        raise _quant_error("BLOCKED_HISTORY", "known history cardinality or IDs differ from frozen inventory")
    counts = manifest.get("scope_counts", {})
    actual_counts = {
        "tracked_frozen_session_count": len(HISTORY_SESSIONS),
        "freeze_only_record_count": sum(item.get("kind") == "freeze_only" for item in records),
        "preflight_only_record_count": sum(item.get("kind") == "preflight" for item in records),
        "native_attempt_count": sum(item.get("kind") == "native_attempt" for item in records),
        "trial_record_count": sum(item.get("role") == "trial_record" for item in authorities),
        "lifecycle_event_count": sum(item.get("role") == "lifecycle_event" for item in authorities),
        "missing_outcome_slot_count": sum(item.get("outcome") is None for item in records),
    }
    if counts != actual_counts:
        raise _quant_error("BLOCKED_HISTORY", f"known history scope counts differ: {counts} != {actual_counts}")
    qualification = manifest.get("qualification", {})
    observed_design = manifest.get("observed_design", {})
    if (qualification.get("wider_model_selection_history") != "INCOMPLETE"
            or qualification.get("unknown_count") is not None
            or qualification.get("dsr_status") != "UNAVAILABLE"
            or qualification.get("oos_status") != "UNAVAILABLE"
            or qualification.get("global_selection_adjustment_allowed") is not False
            or observed_design.get("cash_session_2020_2024_history_already_observed") is not True
            or observed_design.get("pristine_oos_claim") is not False):
        raise _quant_error("INVALID_EVIDENCE", "history qualification or exposure disclosure was weakened")
    for item in records:
        if item.get("session_id") not in HISTORY_SESSIONS:
            raise _quant_error("INVALID_EVIDENCE", "history record has unknown session")
        if item.get("kind") == "freeze_only":
            if item.get("attempt_id") is not None or item.get("outcome") is not None or item.get("lifecycle_event_ids"):
                raise _quant_error("INVALID_EVIDENCE", "freeze-only record cannot claim an attempt or outcome")
        elif not item.get("outcome"):
            raise _quant_error("INVALID_EVIDENCE", "attempt history outcome is missing")
        if item.get("kind") in {"preflight", "freeze_only"} and item.get("attempt_id") is not None:
            raise _quant_error("INVALID_EVIDENCE", "preflight-only history cannot claim a native attempt ID")
        if item.get("kind") == "native_attempt" and not item.get("attempt_id"):
            raise _quant_error("INVALID_EVIDENCE", "native history attempt ID is missing")
        if not set(item.get("authority_paths", ())) <= set(by_path):
            raise _quant_error("INVALID_EVIDENCE", "history record references an unpinned authority")
        lifecycle_events = {}
        attempts_dir = root / "run_log/research_sessions" / item["session_id"] / "attempts"
        for attempt_path in attempts_dir.glob("*.json"):
            try:
                event = json.loads(attempt_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise _quant_error("INVALID_EVIDENCE", f"lifecycle event is unreadable: {attempt_path}") from exc
            lifecycle_events[event.get("event_id")] = event.get("attempt_id")
            if event.get("trial_id") != item["trial_id"]:
                raise _quant_error("INVALID_EVIDENCE", f"lifecycle trial identity mismatch: {item['history_id']}")
        if item.get("lifecycle_event_ids"):
            observed = {event_id: lifecycle_events.get(event_id) for event_id in item["lifecycle_event_ids"]}
            if any(value is None for value in observed.values()) or set(observed.values()) != {item["attempt_id"]}:
                raise _quant_error("INVALID_EVIDENCE", f"attempt/event identity mismatch: {item['history_id']}")
        if item["kind"] in {"preflight", "freeze_only"} and lifecycle_events:
            raise _quant_error("INVALID_EVIDENCE", f"non-native session has lifecycle events: {item['session_id']}")
        evidence_statuses = []
        for relative in item["authority_paths"]:
            if not relative.endswith(".json"):
                continue
            try:
                evidence = json.loads((root / relative).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise _quant_error("INVALID_EVIDENCE", f"history evidence is unreadable: {relative}") from exc
            if evidence.get("session_id") not in (None, item["session_id"]):
                raise _quant_error("INVALID_EVIDENCE", f"attempt session identity mismatch: {relative}")
            if evidence.get("trial_id") not in (None, item["trial_id"]):
                raise _quant_error("INVALID_EVIDENCE", f"attempt trial identity mismatch: {relative}")
            if evidence.get("attempt_id") not in (None, item.get("attempt_id")):
                raise _quant_error("INVALID_EVIDENCE", f"attempt identity mismatch: {relative}")
            if isinstance(evidence.get("status"), str):
                evidence_statuses.append(evidence["status"].upper())
        if item["kind"] == "native_attempt":
            outcome = item["outcome"].upper()
            if outcome.startswith("COMPLETED") and not any(status in {"COMPLETED", "REVIEW"} for status in evidence_statuses):
                raise _quant_error("INVALID_EVIDENCE", f"completed outcome lacks completed evidence: {item['history_id']}")
            if outcome.startswith("FAILED") and not any("FAIL" in status for status in evidence_statuses):
                raise _quant_error("INVALID_EVIDENCE", f"technical failure lacks failure evidence: {item['history_id']}")
            if outcome.startswith("BLOCKED") and not any("BLOCK" in status or "FAIL" in status for status in evidence_statuses):
                raise _quant_error("INVALID_EVIDENCE", f"blocked outcome lacks blocked evidence: {item['history_id']}")
    return manifest


def verified_known_history(root: str | Path | None = None, *,
                           current_attempts: tuple[dict[str, Any], ...] = ()) -> dict[str, Any]:
    """Verify frozen M8 evidence; keep new ATS-4 attempts in their append-only lineage."""
    base = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    base = base.resolve()
    manifest = _verify_manifest(base, expected_manifest_sha256=HISTORY_MANIFEST_SHA256)
    attempts = manifest["known_attempts"]
    return {
        "history_authority_id": manifest["authority_id"],
        "frozen_sessions": manifest["frozen_sessions"],
        "known_attempts": attempts,
        "trial_disclosure": {
            "known_trial_ids": [item["history_id"] for item in attempts],
            "outcomes": [item["outcome"] for item in attempts],
            "unknown_count": None,
            "missing_outcome_ids": [item["history_id"] for item in attempts if item["outcome"] is None],
        },
        "scope_counts": manifest["scope_counts"],
        "observed_design": manifest["observed_design"],
        "qualification": manifest["qualification"],
        "current_attempt_lineage": {
            "source": "append-only ATS-4 factory trial ledger",
            "merge_into_frozen_history": False,
            "records": list(current_attempts),
        },
    }
