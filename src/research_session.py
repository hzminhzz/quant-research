"""Thesis declarations and append-only exploratory evidence, not a strategy gate.

JSON contract v1: every result has schema_version, session_id, status,
classification=EXPLORATORY and approval_status=NOT_APPROVED. Frozen documents
contain spec, spec_sha256, created_at and identity (source, config, data,
historical evidence and git dirty provenance). Trial documents contain trial_id,
kind, terminal status, artifact identity and recorded_at. Reports include every
declared trial, including pending and failed outcomes. No metrics are inferred.

YAML requires session_id, thesis, mechanism, falsifier, market, instruments,
data, evaluation, baseline, costs and trials. Instruments contain symbol/kind;
data contains id/path/role (prices or funding) and optional symbol; trials contain
id/kind/description. Kinds are preregistered, diagnostic or historical_review; the latter
requires artifact. Optional config and evidence reference root-relative files.
All paths must remain inside root without symlinks or parent traversal.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import NotRequired, TypeAlias, TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import polars as pl
import yaml

JSON: TypeAlias = str | int | float | bool | None | list["JSON"] | dict[str, "JSON"]
Document: TypeAlias = dict[str, JSON]
SCHEMA_VERSION = 1
MAX_DATA_BYTES = 100 * 1024 * 1024
MAX_DATA_ROWS = 1_000_000
MAX_DIAGNOSTIC_ROWS = 100_000


class Instrument(TypedDict):
    symbol: str
    kind: str
    venue: NotRequired[str]
    identity: NotRequired[str]
    session: NotRequired[str]
    timezone: NotRequired[str]


class Dataset(TypedDict):
    id: str
    path: str
    role: str
    symbol: NotRequired[str]


class Trial(TypedDict):
    id: str
    kind: str
    description: str
    artifact: NotRequired[str]


class Spec(TypedDict):
    session_id: str
    thesis: str
    mechanism: str
    falsifier: str
    market: str
    instruments: list[Instrument]
    data: list[Dataset]
    evaluation: Document
    baseline: str
    costs: Document
    trials: list[Trial]
    config: NotRequired[str]
    evidence: NotRequired[list[str]]


class FileIdentity(TypedDict):
    path: str
    exists: bool
    sha256: str | None
    size_bytes: int | None


class Provenance(TypedDict):
    input_spec: Document
    config: FileIdentity | None
    source: list[FileIdentity]
    source_sha256: str
    data: list[FileIdentity]
    evidence: list[FileIdentity]
    git: Document
    runner: list[FileIdentity]


class Envelope(TypedDict):
    schema_version: int
    session_id: str
    status: str
    classification: str
    approval_status: str


class Frozen(Envelope):
    spec: Spec
    spec_sha256: str
    identity: Provenance
    created_at: str
    artifact_generation_verified: bool
    frozen_sha256: NotRequired[str]


class DataAudit(TypedDict):
    id: str
    identity: FileIdentity
    issues: list[str]
    rows: NotRequired[int]
    columns: NotRequired[list[str]]
    missing_columns: NotRequired[list[str]]
    error: NotRequired[str]
    start: NotRequired[str]
    end: NotRequired[str]


class Check(Envelope):
    data_audits: list[DataAudit]
    issues: list[str]
    metrics_computed: bool
    scope: str
    limitations: list[str]


class TrialRecord(Envelope):
    trial_id: str
    kind: str
    artifact: FileIdentity
    recorded_at: str
    artifact_generation_verified: bool
    evidence_type: str
    artifact_identity_matches: NotRequired[bool]


class Diagnostic(Envelope):
    trial_id: str
    evidence_type: str
    metrics_computed: bool
    strategy_evidence: bool
    holdout_scored: bool
    development_start: str
    development_end: str
    max_rows_per_dataset: int
    summaries: list[Document]
    issues: list[str]
    audit: NotRequired[Check]
    limitations: list[str]


class Diagnosis(TrialRecord):
    diagnostic: Diagnostic


class Outcome(TypedDict):
    declaration: Trial
    status: str
    record: TrialRecord | None


class Evidence(FileIdentity):
    approval_status: str
    kind: str


class Report(Envelope):
    spec: Spec
    spec_sha256: str
    identity: Provenance
    trials: list[Outcome]
    audit: Check
    evidence: list[Evidence]
    metrics_computed: bool
    artifact_generation_verified: bool


class ResearchSessionError(RuntimeError):
    """A specification or filesystem boundary violated the session contract."""


class _UniqueLoader(yaml.SafeLoader):
    """Reject duplicate YAML keys instead of silently replacing declarations."""


def _mapping(loader: _UniqueLoader, node: yaml.MappingNode) -> Document:
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if not isinstance(key, str) or key in result:
            raise ResearchSessionError("YAML mapping keys must be unique strings")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def _id(value: JSON, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value):
        raise ResearchSessionError(f"{label} must be a safe ID (letters, digits, _ or -)")
    return value


def _text(value: JSON, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResearchSessionError(f"{label} must be a nonempty string")
    return value


def _dict(value: JSON, label: str) -> Document:
    if not isinstance(value, dict) or not value:
        raise ResearchSessionError(f"{label} must be a nonempty mapping")
    return value


def _items(value: JSON, label: str) -> list[Document]:
    if not isinstance(value, list) or not value:
        raise ResearchSessionError(f"{label} must be a nonempty list")
    return [_dict(item, label) for item in value]


def _path(root: Path, value: str | Path) -> Path:
    """Resolve a root-bound path without accepting symlink components."""
    candidate = Path(value)
    if ".." in candidate.parts:
        raise ResearchSessionError(f"parent traversal forbidden: {value}")
    candidate = candidate if candidate.is_absolute() else root / candidate
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ResearchSessionError(f"path outside root: {value}") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ResearchSessionError(f"symlink forbidden: {value}")
    if not candidate.resolve().is_relative_to(root):
        raise ResearchSessionError(f"path outside root: {value}")
    return candidate


def _root(value: str | Path) -> Path:
    root = Path(value).resolve(strict=True)
    if not root.is_dir():
        raise ResearchSessionError("root must be an existing directory")
    return root


def _hash[T](payload: T) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _identity(root: Path, value: str | Path) -> FileIdentity:
    path = _path(root, value)
    result: FileIdentity = {
        "path": path.relative_to(root).as_posix(), "exists": path.is_file(),
        "sha256": None, "size_bytes": None,
    }
    if path.is_file():
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        result.update(sha256=digest.hexdigest(), size_bytes=path.stat().st_size)
    else:
        result.update(sha256=None, size_bytes=None)
    return result


def _validate(raw: JSON, root: Path) -> Spec:
    spec = _dict(raw, "spec")
    allowed = {
        "session_id", "thesis", "mechanism", "falsifier", "market", "instruments",
        "data", "evaluation", "baseline", "costs", "trials", "config", "evidence",
    }
    if set(spec) - allowed:
        raise ResearchSessionError(f"unknown spec keys: {sorted(set(spec) - allowed)}")
    _id(spec.get("session_id"), "session_id")
    for key in ("thesis", "mechanism", "falsifier", "baseline"):
        _text(spec.get(key), key)
    if spec.get("market") not in ("crypto", "indices", "fx", "equities", "futures"):
        raise ResearchSessionError("market must be crypto, indices, fx, equities or futures")
    _dict(spec.get("evaluation"), "evaluation")
    costs = _dict(spec.get("costs"), "costs")
    for key in ("commission_bps", "slippage_bps"):
        value = costs.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ResearchSessionError(f"costs.{key} must be finite and nonnegative")
    symbols = set()
    instruments: list[Instrument] = []
    for item in _items(spec.get("instruments"), "instruments"):
        symbol = _text(item.get("symbol"), "instrument.symbol")
        if symbol in symbols:
            raise ResearchSessionError(f"duplicate instrument symbol: {symbol}")
        symbols.add(symbol)
        kind = _text(item.get("kind"), "instrument.kind")
        if kind not in ("spot", "perpetual", "future", "futures", "cfd", "cash_index", "equity", "fx", "etf"):
            raise ResearchSessionError(f"unknown instrument kind: {kind}")
        if spec["market"] == "crypto" and kind not in ("spot", "perpetual", "future", "futures"):
            raise ResearchSessionError("crypto instrument kind must be spot, perpetual or future(s)")
        instrument: Instrument = {"symbol": symbol, "kind": kind}
        for field in ("venue", "identity", "session", "timezone"):
            if field in item:
                instrument[field] = _text(item[field], field)
        instruments.append(instrument)
    data_ids = set()
    datasets: list[Dataset] = []
    for item in _items(spec.get("data"), "data"):
        data_id = _id(item.get("id"), "data.id")
        if data_id in data_ids:
            raise ResearchSessionError(f"duplicate data ID: {data_id}")
        data_ids.add(data_id)
        _path(root, _text(item.get("path"), "data.path"))
        if item.get("role") not in ("prices", "funding"):
            raise ResearchSessionError("data.role must be prices or funding")
        if item.get("symbol") is not None:
            if _text(item["symbol"], "data.symbol") not in symbols:
                raise ResearchSessionError("data.symbol must name a declared instrument")
        if len(symbols) > 1 and item.get("symbol") is None:
            raise ResearchSessionError("multi-instrument data requires data.symbol")
        dataset: Dataset = {
            "id": data_id, "path": _text(item["path"], "path"),
            "role": _text(item["role"], "role"),
        }
        if "symbol" in item:
            dataset["symbol"] = _text(item["symbol"], "symbol")
        datasets.append(dataset)
    trial_ids = set()
    trials: list[Trial] = []
    for trial in _items(spec.get("trials"), "trials"):
        trial_id = _id(trial.get("id"), "trial.id")
        if trial_id in trial_ids:
            raise ResearchSessionError(f"duplicate trial ID: {trial_id}")
        trial_ids.add(trial_id)
        _text(trial.get("description"), "trial.description")
        if trial.get("kind") not in ("preregistered", "historical_review", "diagnostic"):
            raise ResearchSessionError("trial.kind must be preregistered, diagnostic or historical_review")
        if trial["kind"] == "historical_review":
            _path(root, _text(trial.get("artifact"), "historical trial.artifact"))
        elif "artifact" in trial:
            raise ResearchSessionError("preregistered trials cannot declare historical artifacts")
        declaration: Trial = {
            "id": trial_id, "kind": _text(trial["kind"], "kind"),
            "description": _text(trial["description"], "description"),
        }
        if "artifact" in trial:
            declaration["artifact"] = _text(trial["artifact"], "artifact")
        trials.append(declaration)
    evaluation = _dict(spec["evaluation"], "evaluation")
    if any(trial["kind"] == "diagnostic" for trial in trials) or any(
        key in evaluation for key in ("development_start", "development_end", "holdout_start")
    ):
        _development_interval(evaluation)
    if "config" in spec:
        _path(root, _text(spec["config"], "config"))
    if "evidence" in spec:
        if not isinstance(spec["evidence"], list):
            raise ResearchSessionError("evidence must be a list of paths")
        for value in spec["evidence"]:
            _path(root, _text(value, "evidence path"))
    try:
        _hash(spec)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ResearchSessionError("spec must contain finite JSON-compatible values; quote YAML dates") from exc
    parsed: Spec = {
        "session_id": _id(spec["session_id"], "session_id"),
        "thesis": _text(spec["thesis"], "thesis"),
        "mechanism": _text(spec["mechanism"], "mechanism"),
        "falsifier": _text(spec["falsifier"], "falsifier"),
        "market": _text(spec["market"], "market"),
        "baseline": _text(spec["baseline"], "baseline"),
        "evaluation": _dict(spec["evaluation"], "evaluation"), "costs": costs,
        "instruments": instruments, "data": datasets, "trials": trials,
    }
    if "config" in spec:
        parsed["config"] = _text(spec["config"], "config")
    if "evidence" in spec:
        values = spec["evidence"]
        if isinstance(values, list):
            parsed["evidence"] = [_text(value, "evidence") for value in values]
    return parsed


def _envelope(session_id: str, status: str) -> Envelope:
    return {
        "schema_version": SCHEMA_VERSION, "session_id": session_id, "status": status,
        "classification": "EXPLORATORY", "approval_status": "NOT_APPROVED",
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _exclusive[T](path: Path, payload: T) -> None:
    """Create once, flush to disk, and make accidental edits read-only."""
    encoded = json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n"
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        path.chmod(0o444)
    except FileExistsError as exc:
        raise ResearchSessionError(f"immutable record already exists: {path.name}") from exc


def _git(root: Path) -> Document:
    """Only fixed read-only git commands; never execute specification content."""
    def command(*args: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", *args], cwd=root, capture_output=True, check=False, timeout=30,
        )

    head = command("rev-parse", "HEAD")
    if head.returncode:
        return {"available": False, "head": None, "dirty": None}
    status = command("status", "--porcelain=v1", "--untracked-files=all")
    diff = command("diff", "--binary", "HEAD")
    if status.returncode or diff.returncode:
        raise ResearchSessionError("git provenance could not be captured")
    return {
        "available": True, "head": head.stdout.decode().strip(),
        "dirty": bool(status.stdout), "status_porcelain": status.stdout.decode(),
        "dirty_diff_sha256": hashlib.sha256(diff.stdout).hexdigest(),
    }


def _runner_identity() -> list[FileIdentity]:
    """Hash the actual implementation even when root is a separate workspace."""
    repository = Path(__file__).resolve().parents[1]
    return [
        _identity(repository, "src/research_session.py"),
        _identity(repository, "scripts/research_session.py"),
    ]


def init_session(spec_path: str | Path, root: str | Path) -> Frozen:
    """Freeze a declaration and its observed identities without running trials."""
    root = _root(root)
    path = _path(root, spec_path)
    source_bytes = path.read_bytes()
    try:
        raw = yaml.load(source_bytes, Loader=_UniqueLoader)
    except (yaml.YAMLError, RecursionError) as exc:
        raise ResearchSessionError(f"malformed YAML: {exc}") from exc
    spec = _validate(raw, root)
    session_id = spec["session_id"]
    output = _path(root, f"run_log/research_sessions/{session_id}")
    # Hash source contents, including dirty and untracked Python, independently of HEAD.
    source = []
    for folder in ("src", "scripts"):
        directory = _path(root, folder)
        if directory.exists():
            source.extend(_identity(root, item) for item in sorted(directory.rglob("*.py")))
    evidence_paths = list(spec.get("evidence", []))
    evidence_paths.extend(
        trial.get("artifact", "") for trial in spec["trials"] if trial["kind"] == "historical_review"
    )
    identity: Provenance = {
        "input_spec": {"path": path.relative_to(root).as_posix(),
                       "sha256": hashlib.sha256(source_bytes).hexdigest()},
        "config": _identity(root, spec["config"]) if "config" in spec else None,
        "source": source, "source_sha256": _hash(source),
        "data": [_identity(root, item["path"]) for item in spec["data"]],
        "evidence": [_identity(root, value) for value in dict.fromkeys(evidence_paths)],
        "git": _git(root),
        "runner": _runner_identity(),
    }
    frozen: Frozen = {
        **_envelope(session_id, "FROZEN"),
        "spec": spec, "spec_sha256": _hash(spec), "identity": identity,
        "created_at": _now(), "artifact_generation_verified": False,
    }
    frozen["frozen_sha256"] = _hash(frozen)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        output.mkdir()
    except FileExistsError as exc:
        raise ResearchSessionError(f"session already exists: {session_id}") from exc
    (output / "trials").mkdir()
    _exclusive(output / "frozen_spec.json", frozen)
    return frozen


def _load(root: Path, session_id: str) -> tuple[Path, Frozen]:
    session_id = _id(session_id, "session")
    output = _path(root, f"run_log/research_sessions/{session_id}")
    frozen: Frozen = json.loads(_path(root, output / "frozen_spec.json").read_text(encoding="utf-8"))
    if type(frozen) is not dict or frozen.get("schema_version") != SCHEMA_VERSION:
        raise ResearchSessionError("invalid frozen session contract")
    if frozen.get("frozen_sha256") != _hash({
        key: value for key, value in frozen.items() if key != "frozen_sha256"
    }):
        raise ResearchSessionError("frozen document identity mismatch")
    spec = _validate(frozen.get("spec"), root)
    if frozen.get("session_id") != session_id or frozen.get("spec_sha256") != _hash(spec):
        raise ResearchSessionError("frozen specification identity mismatch")
    return output, frozen


def _audit_data(root: Path, item: Dataset, frozen: FileIdentity) -> DataAudit:
    current = _identity(root, item["path"])
    audit: DataAudit = {"id": item["id"], "identity": current, "issues": []}
    issues = audit["issues"]
    if not current["exists"]:
        issues.append("missing_data")
    elif not frozen["exists"]:
        issues.append("data_missing_at_freeze")
    elif current["sha256"] != frozen["sha256"]:
        issues.append("data_identity_changed")
    if not current["exists"]:
        return audit
    path = _path(root, item["path"])
    if path.suffix != ".parquet":
        issues.append("unsupported_data_format")
        return audit
    try:
        rows = pl.scan_parquet(path).select(pl.len()).collect().item()
        size = current["size_bytes"]
        if (size is not None and size > MAX_DATA_BYTES) or rows > MAX_DATA_ROWS:
            issues.append("data_exceeds_audit_bound")
            audit["rows"] = rows
            return audit
        frame = pl.read_parquet(path)
    except (pl.exceptions.PolarsError, OSError) as exc:
        issues.append("unreadable_parquet")
        audit["error"] = str(exc)
        return audit
    required = {"timestamp", "funding_rate"} if item["role"] == "funding" else {
        "timestamp", "open", "high", "low", "close",
    }
    missing = sorted(required - set(frame.columns))
    audit.update(rows=frame.height, columns=frame.columns, missing_columns=missing)
    if missing:
        issues.append("missing_columns")
        return audit
    if not frame.height:
        issues.append("empty_data")
    if frame.select(pl.col(sorted(required)).null_count()).sum_horizontal().sum():
        issues.append("null_required_values")
    timestamp = frame["timestamp"]
    if not isinstance(timestamp.dtype, pl.Datetime) or timestamp.dtype.time_zone is None:
        issues.append("timestamp_not_timezone_aware")
    elif timestamp.null_count() == 0:
        if not timestamp.is_sorted():
            issues.append("timestamps_not_sorted")
        if timestamp.n_unique() != frame.height:
            issues.append("duplicate_timestamps")
        audit.update(start=str(timestamp.min()), end=str(timestamp.max()))
    symbol = item.get("symbol")
    if symbol is not None and "symbol" in frame.columns:
        if set(frame["symbol"].to_list()) != {symbol}:
            issues.append("instrument_symbol_mismatch")
    numeric = sorted(required - {"timestamp"})
    if any(not frame[column].dtype.is_numeric() for column in numeric):
        issues.append("nonnumeric_values")
    elif frame.select(
        pl.any_horizontal([~pl.col(column).is_finite() for column in numeric]).any()
    ).item():
        issues.append("nonfinite_values")
    if item["role"] == "prices" and all(frame[column].dtype.is_numeric() for column in numeric):
        if frame.select(
            ((pl.col("low") > pl.col("high")) |
             (pl.col("open") < pl.col("low")) | (pl.col("open") > pl.col("high")) |
             (pl.col("close") < pl.col("low")) | (pl.col("close") > pl.col("high")) |
             (pl.col("low") <= 0)).any()
        ).item():
            issues.append("invalid_ohlc")
    return audit


def check_session(session_id: str, root: str | Path) -> Check:
    """Audit identity and declared data requirements, never score a holdout."""
    root = _root(root)
    _, frozen = _load(root, session_id)
    spec = frozen["spec"]
    audits = [
        _audit_data(root, item, identity)
        for item, identity in zip(spec["data"], frozen["identity"]["data"], strict=True)
    ]
    issues: list[str] = []
    for instrument in spec["instruments"]:
        symbol = instrument["symbol"]
        references = [
            item for item in spec["data"]
            if item.get("symbol") == symbol or len(spec["instruments"]) == 1
        ]
        if not any(item["role"] == "prices" for item in references):
            issues.append(f"{symbol}:missing_prices")
        if spec["market"] == "crypto" and instrument["kind"] == "perpetual":
            if not instrument.get("venue"):
                issues.append(f"{symbol}:missing_venue")
            if spec["costs"].get("funding_included") is not False and not any(
                item["role"] == "funding" for item in references
            ):
                issues.append(f"{symbol}:missing_perpetual_funding")
        if spec["market"] == "indices":
            for field in ("identity", "session", "timezone"):
                value = instrument.get(field)
                if not isinstance(value, str) or not value.strip():
                    issues.append(f"{symbol}:missing_{field}")
            timezone_name = instrument.get("timezone")
            if timezone_name:
                try:
                    ZoneInfo(timezone_name)
                except (ZoneInfoNotFoundError, ValueError, TypeError):
                    issues.append(f"{symbol}:invalid_timezone")
    for label, identities in (
        ("config", [frozen["identity"]["config"]] if frozen["identity"]["config"] else []),
        ("evidence", frozen["identity"]["evidence"]),
    ):
        for identity in identities:
            current = _identity(root, identity["path"])
            if not identity["exists"] or not current["exists"]:
                issues.append(f"{label}:missing:{identity['path']}")
            elif current["sha256"] != identity["sha256"]:
                issues.append(f"{label}:identity_changed:{identity['path']}")
    blocked = bool(issues) or any(item["issues"] for item in audits)
    result: Check = {
        **_envelope(session_id, "BLOCKED" if blocked else "PASS"),
        "data_audits": audits, "issues": issues, "metrics_computed": False,
        "scope": "file_identity_and_declared_requirements",
        "limitations": [
            "Observed file bounds and timestamps do not prove calendar-complete coverage.",
            "No vendor identity, missing-session or expected bar-frequency verification.",
            "No funding-to-price alignment or point-in-time correctness certification.",
            "PASS means input audit passed, never strategy approval.",
        ],
    }
    return result


def record_trial(
    session_id: str, trial_id: str, status: str, artifact: str | Path, root: str | Path,
) -> TrialRecord:
    """Record one completed or failed attempt, exclusively and without promotion."""
    root = _root(root)
    output, frozen = _load(root, session_id)
    trial_id = _id(trial_id, "trial")
    if status not in ("completed", "failed"):
        raise ResearchSessionError("trial status must be completed or failed")
    declarations = {trial["id"]: trial for trial in frozen["spec"]["trials"]}
    if trial_id not in declarations:
        raise ResearchSessionError(f"undeclared trial: {trial_id}")
    trial = declarations[trial_id]
    identity = _identity(root, artifact)
    if not identity["exists"]:
        raise ResearchSessionError("result artifact must be an existing regular file")
    if _path(root, artifact).is_relative_to(output) and not (
        trial["kind"] == "diagnostic" and
        _path(root, artifact) == output / "diagnostics" / f"{trial_id}.json"
    ):
        raise ResearchSessionError("result artifact cannot be a session control file")
    if trial["kind"] == "historical_review":
        historical = next(
            item for item in frozen["identity"]["evidence"]
            if item["path"] == _path(root, trial.get("artifact", "")).relative_to(root).as_posix()
        )
        if identity != historical:
            raise ResearchSessionError("historical artifact must match the frozen identity")
    record: TrialRecord = {
        **_envelope(session_id, status),
        "trial_id": trial_id, "kind": trial["kind"], "artifact": identity,
        "recorded_at": _now(), "artifact_generation_verified": False,
        "evidence_type": "descriptive_diagnostic" if trial["kind"] == "diagnostic" else "linked_artifact",
    }
    path = _path(root, output / "trials" / f"{trial_id}.json")
    _exclusive(path, record)
    return record


def _development_interval(evaluation: Document) -> tuple[datetime, datetime]:
    """Require explicit development bounds; never substitute a holdout interval."""
    values = []
    for key in ("development_start", "development_end"):
        text = _text(evaluation.get(key), f"evaluation.{key}")
        try:
            value = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ResearchSessionError(f"invalid {key}") from exc
        if value.tzinfo is None:
            raise ResearchSessionError(f"{key} must be timezone-aware")
        values.append(value.astimezone(timezone.utc))
    if values[0] >= values[1]:
        raise ResearchSessionError("development_start must precede development_end")
    if "holdout_start" in evaluation:
        try:
            holdout = datetime.fromisoformat(
                _text(evaluation["holdout_start"], "holdout_start").replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ResearchSessionError("invalid holdout_start") from exc
        if holdout.tzinfo is None or values[1] > holdout.astimezone(timezone.utc):
            raise ResearchSessionError("development interval overlaps holdout")
    return values[0], values[1]


def _number[T](value: T) -> float | None:
    """Normalize numeric Polars scalars to finite JSON numbers."""
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        numeric = float(value)
        if math.isfinite(numeric):
            return numeric
    raise ResearchSessionError("descriptive summary is not a finite number")


def diagnose_trial(session_id: str, trial_id: str, root: str | Path) -> Diagnosis:
    """Execute bounded descriptive development returns, not a backtest or a score.

    Window is [development_start, development_end); at most 100,000 rows per
    dataset. A blocked audit or runtime data failure is itself a terminal failed
    attempt with an immutable diagnostic artifact.
    """
    root = _root(root)
    output, frozen = _load(root, session_id)
    trial_id = _id(trial_id, "trial")
    trial = next((item for item in frozen["spec"]["trials"] if item["id"] == trial_id), None)
    if trial is None or trial["kind"] != "diagnostic":
        raise ResearchSessionError("diagnose requires a declared diagnostic trial")
    record_path = _path(root, output / "trials" / f"{trial_id}.json")
    if record_path.exists():
        raise ResearchSessionError(f"immutable record already exists: {record_path.name}")
    # Validate selection before any execution. Invalid bounds are specification errors.
    start, end = _development_interval(frozen["spec"]["evaluation"])
    artifact = _path(root, output / "diagnostics" / f"{trial_id}.json")
    artifact.parent.mkdir(exist_ok=True)
    # Reserve execution exclusively, so concurrent reruns cannot replace evidence.
    reservation = _path(root, output / "diagnostics" / f"{trial_id}.started.json")
    _exclusive(reservation, {"trial_id": trial_id, "started_at": _now()})
    diagnostic: Diagnostic = {
        **_envelope(session_id, "completed"),
        "trial_id": trial_id, "evidence_type": "descriptive_diagnostic", "metrics_computed": True,
        "strategy_evidence": False, "holdout_scored": False, "development_start": start.isoformat(),
        "development_end": end.isoformat(), "max_rows_per_dataset": MAX_DIAGNOSTIC_ROWS,
        "summaries": [], "issues": [],
        "limitations": [
            "Observed gaps only; no claim that all expected sessions or bars exist.",
            "Gross price changes are descriptive, not cost-adjusted strategy returns.",
            "No strategy, signal, baseline, profitability or holdout evaluation.",
        ],
    }
    audit = check_session(session_id, root)
    diagnostic["audit"] = audit
    if audit["status"] == "BLOCKED":
        diagnostic.update(status="failed", metrics_computed=False, issues=["data_audit_blocked"])
    else:
        try:
            for item in frozen["spec"]["data"]:
                frame = (
                    pl.scan_parquet(_path(root, item["path"]))
                    .filter((pl.col("timestamp") >= start) & (pl.col("timestamp") < end))
                    .limit(MAX_DIAGNOSTIC_ROWS + 1).collect()
                )
                if not frame.height or frame.height > MAX_DIAGNOSTIC_ROWS:
                    raise ResearchSessionError(f"{item['id']}: empty or oversized development window")
                gaps = frame["timestamp"].diff().dt.total_seconds().drop_nulls()
                summary: Document = {
                    "data_id": item["id"], "role": item["role"], "rows": frame.height,
                    "first_timestamp": str(frame["timestamp"].min()),
                    "last_timestamp": str(frame["timestamp"].max()),
                    "largest_observed_gap_seconds": _number(gaps.max()),
                    "median_observed_gap_seconds": _number(gaps.median()),
                }
                if item["role"] == "prices":
                    returns = frame["close"].pct_change().drop_nulls()
                    summary.update(
                        return_observations=len(returns),
                        mean_bar_return=_number(returns.mean()),
                        cumulative_price_return=frame["close"][-1] / frame["close"][0] - 1,
                    )
                else:
                    summary["mean_observed_funding_rate"] = _number(frame["funding_rate"].mean())
                diagnostic["summaries"].append(summary)
        except (ResearchSessionError, pl.exceptions.PolarsError, OSError) as exc:
            diagnostic.update(status="failed", issues=[str(exc)])
    _exclusive(artifact, diagnostic)
    record = record_trial(session_id, trial_id, diagnostic["status"], artifact, root)
    return {**record, "diagnostic": diagnostic}


def report_session(session_id: str, root: str | Path) -> Report:
    """Reconstruct all outcomes and linked evidence without changing any records."""
    root = _root(root)
    output, frozen = _load(root, session_id)
    outcomes: list[Outcome] = []
    for trial in frozen["spec"]["trials"]:
        path = _path(root, output / "trials" / f"{trial['id']}.json")
        record: TrialRecord | None = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        if record is not None:
            if not isinstance(record, dict) or record.get("trial_id") != trial["id"] or record.get("status") not in ("completed", "failed"):
                raise ResearchSessionError(f"invalid terminal trial record: {trial['id']}")
            current = _identity(root, record["artifact"]["path"])
            record["artifact_identity_matches"] = current == record["artifact"]
            record.update(classification="EXPLORATORY", approval_status="NOT_APPROVED")
        outcomes.append({"declaration": trial, "status": record["status"] if record else "pending",
                         "record": record})
    result: Report = {
        **_envelope(session_id, "REPORT"),
        "spec": frozen["spec"], "spec_sha256": frozen["spec_sha256"], "identity": frozen["identity"],
        "trials": outcomes, "audit": check_session(session_id, root),
        "evidence": [
            {**item, "approval_status": "NOT_APPROVED", "kind": "historical_evidence"}
            for item in frozen["identity"]["evidence"]
        ],
        "metrics_computed": False, "artifact_generation_verified": False,
    }
    return result
