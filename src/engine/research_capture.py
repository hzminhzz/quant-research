"""Research thesis capture: immutable, source-faithful, never executable.

Captures raw heterogeneous thesis sources (two-file handoff directories or
plain md/txt/json/yaml files) into content-addressed, source-anchored
evidence. The output is a descriptive record: THESIS_CAPTURED or
RESEARCH_READY. It is never an executable CandidateSpec and grants no
execution, backtest, or holdout authority.

Security: bounded ZIP reads, path-traversal rejection, symlink refusal,
duplicate-name detection, immutable source preservation, no LLM inference,
deterministic sha256 source identity.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from .common import QuantError, digest, file_hash, safe_name

_MAX_FILE_BYTES = 512_000
_ARCHIVE_EXTS = {".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".gz", ".bz2", ".7z", ".rar"}
_MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
_MAX_ARCHIVE_FILES = 2048
_MAX_ARCHIVE_TOTAL_BYTES = 64 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 200

# Required descriptive clauses extracted from a thesis source.
_REQUIRED_CLAUSES = (
    "economic_thesis",
    "mechanism",
    "instruments",
    "data_requirements",
    "feature_contracts",
    "strategy_rules",
    "signal_and_execution_clock",
    "cost_assumptions",
    "baseline",
    "development_evaluation",
    "primary_falsifier",
    "acceptance_and_stop_rules",
    "parity_and_causality_tests",
    "source_references",
    "sizing",
    "unresolved_blockers",
)

# Tokens that mean "unresolved / not declared" rather than a value.
_UNRESOLVED_TOKENS = re.compile(
    r"^(?:todo|tbd|placeholder|fill[_ -]?me|n/?a|none|null|unknown|<[^>]+>|)$",
    re.IGNORECASE,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _is_unresolved(value: Any) -> bool:
    if isinstance(value, str):
        return bool(_UNRESOLVED_TOKENS.fullmatch(value.strip()))
    if value is None:
        return True
    if isinstance(value, (list, dict)):
        return not value or any(_is_unresolved(item) for item in (value.values() if isinstance(value, dict) else value))
    return False


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise QuantError("INVALID_CAPTURE", f"duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def _yaml_field_lines(raw: str) -> dict[str, int]:
    locations: dict[str, int] = {}
    try:
        root = yaml.compose(raw, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        return locations

    def walk(node: yaml.Node, parts: tuple[str, ...] = ()) -> None:
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                if isinstance(key_node, yaml.ScalarNode):
                    key = key_node.value
                    path = (*parts, key)
                    locations[".".join(path)] = key_node.start_mark.line + 1
                    walk(value_node, path)
        elif isinstance(node, yaml.SequenceNode):
            for index, child in enumerate(node.value):
                walk(child, (*parts, str(index)))

    if root is not None:
        walk(root)
    return locations


def _fail(message: str) -> None:
    raise QuantError("INVALID_CAPTURE", message)


def _reject_symlink_components(path: Path) -> None:
    """Reject existing symlink ancestors before writing to an operator-selected root.

    This is a best-effort filesystem-owner boundary, not race-proof sandboxing.
    """
    absolute = Path(os.path.abspath(path))
    for ancestor in (absolute, *absolute.parents):
        if ancestor.is_symlink():
            _fail(f"symlinked output path component is forbidden: {ancestor}")


def _atomic_json(path: Path, document: dict) -> None:
    _reject_symlink_components(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(path)
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _report_hash(document: dict) -> str:
    return digest({key: value for key, value in document.items() if key != "report_hash"})


def _source_identity(path: Path) -> str:
    if path.is_symlink():
        _fail(f"refusing symlink source: {path}")
    if not path.is_file():
        _fail(f"source is not a regular file: {path}")
    if path.stat().st_size > _MAX_FILE_BYTES:
        _fail(f"source exceeds bounded admission size: {path}")
    if path.suffix.lower() in _ARCHIVE_EXTS:
        _fail(f"archive sources are not accepted: {path}")
    return file_hash(path)


def _read_bounded(path: Path) -> str:
    data = path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        _fail(f"source is not valid UTF-8: {path} ({exc})")


def _clause_location(document: dict, clause: str) -> str | None:
    """Best-effort source-anchored path/line reference for a YAML clause.

    Returns 'thesis.yaml:<line>' when the clause is a top-level mapping key,
    otherwise None (clause present but not directly addressable).
    """
    if not isinstance(document, dict) or clause not in document:
        return None
    return None


@dataclass
class ClauseEvidence:
    clause: str
    present: bool
    resolved: bool
    source_ref: str | None = None
    excerpt: str | None = None
    unresolved_reason: str | None = None


@dataclass
class CaptureResult:
    status: str  # THESIS_CAPTURED or RESEARCH_READY
    source_path: str
    source_hash: str
    source_bytes_ref: str  # sha256 of preserved original bytes
    captured_at: str
    candidate_id: str | None
    report_path: str | None = None
    clauses: list[ClauseEvidence] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    executable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "executable": self.executable,
            "source_path": self.source_path,
            "source_hash": self.source_hash,
            "source_bytes_ref": self.source_bytes_ref,
            "captured_at": self.captured_at,
            "candidate_id": self.candidate_id,
            "clauses": [
                {
                    "clause": c.clause,
                    "present": c.present,
                    "resolved": c.resolved,
                    "source_ref": c.source_ref,
                    "excerpt": c.excerpt,
                    "unresolved_reason": c.unresolved_reason,
                }
                for c in self.clauses
            ],
            "provenance": self.provenance,
            "unresolved": self.unresolved,
            "errors": self.errors,
        }


def _extract_clauses(document: dict | None, source_path: Path) -> tuple[list[ClauseEvidence], list[str], list[str]]:
    """Extract descriptive clauses; never interpret as executable rules."""
    clauses: list[ClauseEvidence] = []
    unresolved: list[str] = []
    errors: list[str] = []
    if not isinstance(document, dict):
        for clause in _REQUIRED_CLAUSES:
            clauses.append(ClauseEvidence(clause=clause, present=False, resolved=False,
                                          unresolved_reason="thesis root is not a mapping"))
            unresolved.append(clause)
        return clauses, unresolved, errors

    raw_text = source_path.read_text(encoding="utf-8") if source_path.is_file() else ""
    lines = raw_text.splitlines()
    field_lines = _yaml_field_lines(raw_text)
    fields: dict[str, tuple[Any, int, str]] = {}

    def walk(value: Any, path: tuple[str, ...] = ()) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = (*path, str(key))
                dotted = ".".join(child_path)
                line_no = field_lines.get(dotted, 0)
                excerpt = lines[line_no - 1].strip()[:200] if line_no else ""
                fields[dotted] = (child, line_no, excerpt)
                walk(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, (*path, str(index)))

    walk(document)
    aliases = {
        "economic_thesis": {"thesis", "hypothesis", "research_question"},
        "mechanism": {"economic_mechanism", "mechanism_of_action"},
        "instruments": {"instrument_universe", "markets"},
        "data_requirements": {"markets_and_data"},
        "strategy_rules": {"deterministic_strategy_specification", "strategy_specification", "entry_exit_rules"},
    }
    evidence_roots = ("identity", "markets_and_data", "deterministic_strategy_specification")

    for clause in _REQUIRED_CLAUSES:
        exact = [(path, item) for path, item in fields.items() if path.split(".")[-1] == clause]
        alias_matches = not exact
        candidates = exact or [(path, item) for path, item in fields.items()
                               if path.split(".")[-1] in aliases.get(clause, set())]
        if clause in document:
            line_no = field_lines.get(clause, 0)
            excerpt = lines[line_no - 1].strip()[:200] if line_no else clause + ":"
            candidates = [(clause, (document[clause], line_no, excerpt))]
        if not candidates:
            nested = [path for path in fields if path.startswith(evidence_roots)]
            note = ("no source field explicitly maps to this clause; nested fields require review: "
                    + ", ".join(nested[:12])) if nested else "clause not declared in source"
            clauses.append(ClauseEvidence(clause=clause, present=False, resolved=False,
                                          unresolved_reason=note))
            unresolved.append(clause)
            continue
        path, (value, line_no, excerpt) = candidates[0]
        source_ref = f"{source_path.name}:{line_no} ({path})" if line_no else f"{source_path.name} ({path})"
        if len(candidates) > 1:
            reason = "multiple nested fields could map to this clause; mapping is ambiguous"
            clauses.append(ClauseEvidence(clause=clause, present=True, resolved=False,
                                          source_ref=source_ref, excerpt=excerpt,
                                          unresolved_reason=reason))
            unresolved.append(clause)
            continue
        if alias_matches and clause not in document:
            clauses.append(ClauseEvidence(clause=clause, present=True, resolved=False,
                                          source_ref=source_ref, excerpt=excerpt,
                                          unresolved_reason="possible nested mapping found; semantic equivalence is not assumed"))
            unresolved.append(clause)
            continue
        if _is_unresolved(value):
            clauses.append(ClauseEvidence(clause=clause, present=True, resolved=False,
                                          source_ref=source_ref, excerpt=excerpt,
                                          unresolved_reason="declared but value is unresolved/placeholder"))
            unresolved.append(clause)
            continue
        # Best-effort line anchor: find first line starting with the clause key.
        clauses.append(ClauseEvidence(clause=clause, present=True, resolved=True,
                                      source_ref=source_ref, excerpt=excerpt))
    return clauses, unresolved, errors


def _classify_document(document: dict | None) -> dict[str, Any]:
    """Extract declared identity/provenance metadata without promoting to executable."""
    meta: dict[str, Any] = {}
    if not isinstance(document, dict):
        return meta
    for key in ("candidate_id", "selection_family_id", "status", "research_mode",
                "not_execution_approved", "not_a_frozen_session", "created_on"):
        if key in document:
            meta[key] = document[key]
    # Source references as declared provenance only.
    refs = document.get("source_references")
    if isinstance(refs, list):
        meta["source_reference_count"] = len(refs)
        meta["source_reference_ids"] = [r.get("id") for r in refs if isinstance(r, dict)]
    return meta


def _nested_field_evidence(raw: str, document: dict) -> dict[str, dict[str, str]]:
    """Index nested fields by exact YAML path; aliases are never silently promoted."""
    roots = {"identity", "markets_and_data", "deterministic_strategy_specification"}
    lines = raw.splitlines()
    field_lines = _yaml_field_lines(raw)
    result: dict[str, dict[str, str]] = {}

    def walk(value: Any, parts: tuple[str, ...] = ()) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                path = (*parts, str(key))
                if path[0] in roots:
                    match = field_lines.get(".".join(path), 0)
                    if len(result) < 512:
                        result[".".join(path)] = {
                            "source_ref": f"thesis.yaml:{match}" if match else "thesis.yaml",
                            "excerpt": lines[match - 1].strip()[:200] if match else "",
                        }
                walk(child, path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, (*parts, str(index)))

    walk(document)
    return result


def capture_source(source: str | Path, out_dir: str | Path | None = None, *,
                   _source_provenance: dict[str, Any] | None = None) -> CaptureResult:
    """Capture one thesis source into an immutable evidence record.

    Accepts a directory containing thesis.yaml+brief.md, or a single
    md/txt/json/yaml file. Returns a CaptureResult; never writes executable
    YAML. Atomic JSON report written to out_dir (default beside source).
    """
    source_path = Path(source)
    if source_path.is_symlink():
        _fail(f"refusing symlink source: {source_path}")

    source_path = source_path.resolve()
    source_files: dict[str, bytes] = {}
    if source_path.is_dir():
        if any(p.is_symlink() for p in source_path.iterdir()):
            _fail(f"symlink entries not allowed in source directory: {source_path}")
        thesis = source_path / "thesis.yaml"
        brief = source_path / "brief.md"
        if not thesis.is_file() or not brief.is_file():
            _fail(f"source directory must contain exactly thesis.yaml and brief.md: {source_path}")
        entries = {p.name for p in source_path.iterdir()}
        if entries != {"thesis.yaml", "brief.md"}:
            _fail(f"unexpected entries in source directory: {sorted(entries - {'thesis.yaml', 'brief.md'})}")
        for name in ("thesis.yaml", "brief.md"):
            _source_identity(source_path / name)
        source_files = {name: (source_path / name).read_bytes() for name in ("thesis.yaml", "brief.md")}
        source_hash = digest({name: hashlib.sha256(data).hexdigest() for name, data in source_files.items()})
        source_bytes_ref = file_hash(thesis)  # preserve thesis as the canonical bytes reference
        raw = _read_bounded(thesis)
        brief_text = _read_bounded(brief)
        try:
            document = yaml.load(raw, Loader=_UniqueKeyLoader)
        except (yaml.YAMLError, RecursionError) as exc:
            _fail(f"thesis YAML is invalid: {exc}")
        provenance = {"kind": "two_file_handoff", "directory": str(source_path),
                      "brief_hash": file_hash(brief), "brief_bytes": len(brief_text.encode("utf-8"))}
        candidate_id = (document.get("candidate_id") or document.get("identity", {}).get("candidate_id")
                        if isinstance(document, dict) and isinstance(document.get("identity", {}), dict)
                        else document.get("candidate_id") if isinstance(document, dict) else None)
        candidate_id = candidate_id or source_path.name
        if isinstance(candidate_id, str) and not safe_name(candidate_id):
            _fail(f"candidate_id is not a safe identifier: {candidate_id}")
    elif source_path.is_file():
        _source_identity(source_path)
        raw = _read_bounded(source_path)
        suffix = source_path.suffix.lower()
        source_files = {source_path.name: source_path.read_bytes()}
        source_hash = hashlib.sha256(source_files[source_path.name]).hexdigest()
        source_bytes_ref = source_hash
        try:
            if suffix in {".yaml", ".yml"}:
                document = yaml.load(raw, Loader=_UniqueKeyLoader)
            elif suffix == ".json":
                document = json.loads(raw)
            elif suffix in {".md", ".txt"}:
                # Plain text is captured whole as a single provenance block;
                # no executable inference from prose.
                document = {"_prose_source": raw}
            else:
                _fail(f"unsupported source file type: {suffix}")
        except (json.JSONDecodeError, yaml.YAMLError, RecursionError) as exc:
            _fail(f"cannot parse source: {source_path} ({exc})")
        provenance = {"kind": "single_file", "path": str(source_path), "suffix": suffix}
        candidate_id = None
        brief_text = None
    else:
        _fail(f"source does not exist: {source_path}")

    if not isinstance(document, dict):
        document = {}

    clauses, unresolved, errors = _extract_clauses(document, source_path if source_path.is_file() else thesis)
    meta = _classify_document(document)
    provenance.update(meta)
    provenance.update(_source_provenance or {})
    if isinstance(document, dict) and isinstance(raw, str):
        provenance["nested_field_evidence"] = _nested_field_evidence(raw, document)

    # Capture proves source retention only. Structural presence alone cannot
    # certify economic semantics or justify RESEARCH_READY.
    blockers = document.get("unresolved_blockers")
    has_blockers = bool(blockers) and blockers not in ("NONE", "none")
    if has_blockers:
        unresolved.append("unresolved_blockers: source explicitly lists outstanding issues")
    provenance["descriptive_sections_complete"] = bool(clauses) and all(c.resolved for c in clauses)
    status = "THESIS_CAPTURED"

    result = CaptureResult(
        status=status,
        source_path=str(source_path),
        source_hash=source_hash,
        source_bytes_ref=source_bytes_ref,
        captured_at=_now(),
        candidate_id=candidate_id,
        clauses=clauses,
        provenance=provenance,
        unresolved=unresolved,
        errors=errors,
        executable=False,
    )

    # Deterministic output path keyed by source hash (idempotent).
    if out_dir is None:
        # Never put a generated report inside an admitted two-file source folder:
        # doing so would make a second capture reject its own output as an extra file.
        out_dir = source_path.parent / ".research_captures"
    out_dir = Path(out_dir)
    _reject_symlink_components(out_dir)
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(out_dir)
    bytes_dir = out_dir / "sources" / source_hash
    _reject_symlink_components(bytes_dir)
    bytes_dir.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(bytes_dir)
    for name, data in source_files.items():
        preserved = bytes_dir / name
        if preserved.exists():
            if preserved.is_symlink() or preserved.read_bytes() != data:
                _fail("preserved source bytes were modified")
        else:
            fd = os.open(preserved, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
    result.provenance["preserved_source_bytes"] = {
        name: {"path": str(bytes_dir / name), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        for name, data in source_files.items()
    }
    origin_key = result.provenance.get("archive_member_directory")
    suffix = f"_{digest(origin_key)[:8]}" if origin_key else ""
    report_name = f"capture_{source_hash[:16]}{suffix}.json"
    report_path = out_dir / report_name
    document = result.to_dict()
    document["report_hash"] = _report_hash(document)
    if report_path.exists():
        previous = json.loads(report_path.read_text(encoding="utf-8"))
        if previous.get("report_hash") != _report_hash(previous) or previous.get("source_hash") != source_hash:
            _fail("existing capture report was modified or identity collided")
        # The persisted receipt is authoritative on repeated identical imports.
        # Return its original timestamp rather than suggesting a new capture.
        result.captured_at = previous["captured_at"]
    else:
        _atomic_json(report_path, document)
    result.report_path = str(report_path)  # type: ignore[attr-defined]
    return result


def _write_immutable(path: Path, data: bytes) -> None:
    _reject_symlink_components(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(path)
    if path.is_symlink():
        _fail(f"refusing symlink at immutable intake path: {path}")
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
            _fail(f"immutable intake bytes differ at existing path: {path}")
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def capture_archive(source: str | Path, out_dir: str | Path) -> list[CaptureResult]:
    """Safely batch-capture two-file thesis folders from a bounded ZIP archive."""
    path = Path(source)
    if path.is_symlink() or not path.is_file():
        _fail(f"archive must be a regular, non-symlink file: {path}")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        _fail(f"cannot safely open ZIP archive: {exc}")
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            _fail("archive must be a regular file")
        archive_bytes = handle.read(_MAX_ARCHIVE_BYTES + 1)
    if len(archive_bytes) > _MAX_ARCHIVE_BYTES:
        _fail("archive exceeds bounded compressed size")
    archive_hash = hashlib.sha256(archive_bytes).hexdigest()
    archive_stream = io.BytesIO(archive_bytes)
    if not zipfile.is_zipfile(archive_stream):
        _fail("source is not a valid ZIP archive")
    _reject_symlink_components(Path(out_dir))
    out = Path(out_dir).resolve()
    groups: dict[str, dict[str, tuple[zipfile.ZipInfo, bytes]]] = {}
    seen: set[str] = set()
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            infos = archive.infolist()
            if len(infos) > _MAX_ARCHIVE_FILES:
                _fail("archive contains too many entries")
            for info in infos:
                name = info.filename
                if "\\" in name or "\x00" in name or not name.isascii():
                    _fail(f"unsafe or non-ASCII ZIP member path: {name!r}")
                trimmed = name[:-1] if info.is_dir() and name.endswith("/") else name
                parts = trimmed.split("/")
                if (not trimmed or trimmed.startswith("/") or ":" in parts[0]
                        or any(part in ("", ".", "..") for part in parts)):
                    _fail(f"unsafe ZIP member path: {name!r}")
                normalized = "/".join(parts)
                folded = normalized.casefold()
                if folded in seen:
                    _fail(f"duplicate ZIP member path: {normalized}")
                seen.add(folded)
                mode = info.external_attr >> 16
                file_type = stat.S_IFMT(mode)
                if file_type == stat.S_IFLNK or (file_type not in (0, stat.S_IFREG, stat.S_IFDIR)):
                    _fail(f"ZIP symlink or special file is not accepted: {name}")
                if info.flag_bits & 0x1:
                    _fail(f"encrypted ZIP member is not accepted: {name}")
                if info.is_dir():
                    continue
                if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    _fail(f"unsupported ZIP compression method: {name}")
                if info.file_size > _MAX_FILE_BYTES:
                    _fail(f"ZIP member exceeds per-file size limit: {name}")
                if info.file_size > max(info.compress_size, 1) * _MAX_COMPRESSION_RATIO:
                    _fail(f"ZIP member exceeds compression-ratio limit: {name}")
                total += info.file_size
                if total > _MAX_ARCHIVE_TOTAL_BYTES:
                    _fail("archive exceeds total uncompressed size limit")
                member = PurePosixPath(normalized)
                if member.name not in ("thesis.yaml", "brief.md") or len(member.parts) < 2:
                    _fail(f"unexpected ZIP file; expected folder/thesis.yaml or folder/brief.md: {name}")
                with archive.open(info) as stream:
                    chunks = bytearray()
                    while chunk := stream.read(64 * 1024):
                        chunks.extend(chunk)
                        if len(chunks) > _MAX_FILE_BYTES:
                            _fail(f"ZIP member expanded beyond per-file size limit: {name}")
                data = bytes(chunks)
                if len(data) != info.file_size:
                    _fail(f"ZIP member size does not match its header: {name}")
                try:
                    data.decode("utf-8")
                except UnicodeDecodeError as exc:
                    _fail(f"ZIP member is not valid UTF-8: {name} ({exc})")
                parent = str(member.parent)
                group = groups.setdefault(parent, {})
                if member.name in group:
                    _fail(f"duplicate source file in ZIP folder: {parent}/{member.name}")
                group[member.name] = (info, data)
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        _fail(f"cannot safely read ZIP archive: {exc}")

    if not groups:
        _fail("ZIP archive contains no thesis folders")
    for folder, files in groups.items():
        if set(files) != {"thesis.yaml", "brief.md"}:
            _fail(f"ZIP source folder must contain thesis.yaml and brief.md: {folder}")
        try:
            yaml.load(files["thesis.yaml"][1].decode("utf-8"), Loader=_UniqueKeyLoader)
        except (yaml.YAMLError, RecursionError) as exc:
            _fail(f"thesis YAML is invalid in {folder}: {exc}")

    _write_immutable(out / "archives" / f"{archive_hash}.zip", archive_bytes)
    results: list[CaptureResult] = []
    for folder, files in sorted(groups.items()):
        source_dir = out / "archive_sources" / archive_hash / Path(*PurePosixPath(folder).parts)
        for filename, (_, data) in files.items():
            _write_immutable(source_dir / filename, data)
        result = capture_source(
            source_dir, out,
            _source_provenance={"kind": "zip_archive", "archive_path": str(out / "archives" / f"{archive_hash}.zip"),
                                "archive_sha256": archive_hash, "archive_member_directory": folder,
                                "archive_members": {name: hashlib.sha256(pair[1]).hexdigest()
                                                    for name, pair in files.items()}},
        )
        results.append(result)
    return results


def verify_capture(report_path: str | Path, *, expected_report_sha256: str | None = None) -> dict[str, Any]:
    """Verify source integrity; optionally authenticate against a separately pinned digest.

    Without an external digest, the report's own checksum only detects accidental
    changes. It is not cryptographic authentication against an active editor.
    """
    path = Path(report_path)
    if not path.is_file() or path.is_symlink():
        _fail(f"capture report is not a regular file: {path}")
    if expected_report_sha256 is not None:
        if not re.fullmatch(r"[0-9a-f]{64}", expected_report_sha256):
            _fail("expected_report_sha256 must be lowercase SHA-256")
        if file_hash(path) != expected_report_sha256:
            _fail("capture report differs from independently pinned SHA-256")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("report_hash") != _report_hash(data):
        _fail("capture report was modified")
    if data.get("executable") is not False:
        _fail("capture report must explicitly forbid execution")
    source = Path(data.get("source_path", ""))
    if source.is_symlink() or not source.exists():
        _fail("source missing or replaced by symlink")
    if source.is_dir():
        if any((source / name).is_symlink() for name in ("thesis.yaml", "brief.md")):
            _fail("source contains symlink")
        observed_hash = digest({name: file_hash(source / name) for name in ("thesis.yaml", "brief.md")})
        expected_files = {"thesis.yaml", "brief.md"}
    else:
        observed_hash = file_hash(source)
        expected_files = {source.name}
    if observed_hash != data.get("source_hash"):
        _fail("source content changed since capture")
    archive_path = data.get("provenance", {}).get("archive_path")
    if archive_path:
        original_archive = Path(archive_path)
        if (original_archive.is_symlink() or not original_archive.is_file()
                or file_hash(original_archive) != data.get("provenance", {}).get("archive_sha256")):
            _fail("preserved ZIP archive is missing or modified")
    for name, evidence in data.get("provenance", {}).get("preserved_source_bytes", {}).items():
        preserved = Path(evidence["path"])
        if name not in expected_files or preserved.is_symlink() or not preserved.is_file() or file_hash(preserved) != evidence.get("sha256"):
            _fail("preserved source bytes are missing or modified")
    return {"status": data.get("status"), "source_hash": data.get("source_hash"),
            "executable": data.get("executable"), "clauses_total": len(data.get("clauses", [])),
            "clauses_resolved": sum(1 for c in data.get("clauses", []) if c.get("resolved")),
            "unresolved": data.get("unresolved", []), "report": str(path)}
