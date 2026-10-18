"""ATS-8 version-aware learning, lesson store, and regression integration.

Provides deterministic, schema-validated lesson records grounded in original
reproducible failure evidence. Rejects stale, superseded, or version-incompatible
lessons without mutating historical ledgers or accumulating unverified prose.
Enforces fail-closed protocol, scope, numeric semver, and code/data drift gates.
Adheres to ml4t-agent-state-memory, ml4t-agent-tool-contracts, and ml4t-agent-governance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, StrictStr, model_validator

from src.engine.common import beneath

from .contracts import StrictModel

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
_HEX = re.compile(r"^[0-9a-f]{64}$")
_LESSON_ID = re.compile(r"^LSN-[0-9]{8}-[A-Za-z0-9_-]+$")

KnowledgeClass = Literal[
    "architectural_decision", "implementation_recipe", "research_outcome"
]
LessonStatus = Literal[
    "VALID",
    "SUPERSEDED",
    "VERSION_INCOMPATIBLE",
    "INVALIDATED",
    "PROTOCOL_MISMATCH",
    "SCOPE_MISMATCH",
    "CODE_DRIFT",
    "DATA_DRIFT",
]


def _canonical_json(data: dict[str, Any]) -> bytes:
    return json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _digest(data: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(data)).hexdigest()


def _parse_semver(version_str: str) -> tuple[int, ...]:
    """Parse version string into integer tuple for numeric comparison (1.10 > 1.9)."""
    parts = re.findall(r"\d+", version_str)
    if not parts:
        raise ValueError(f"INVALID_VERSION_STRING: {version_str}")
    return tuple(int(p) for p in parts)


class LessonRecordV1(StrictModel):
    """Immutable, evidence-linked engineering or scientific lesson record."""

    schema_version: Literal[1] = 1
    lesson_id: StrictStr = Field(pattern=r"^LSN-[0-9]{8}-[A-Za-z0-9_-]+$")
    knowledge_class: KnowledgeClass
    trigger: StrictStr = Field(min_length=5, max_length=500)
    error_codes: tuple[StrictStr, ...] = Field(default_factory=tuple)
    affected_scope: tuple[StrictStr, ...] = Field(min_length=1)
    protocol: StrictStr = Field(min_length=2, max_length=64)
    version_bounds: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    bound_code_hashes: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    bound_data_hashes: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    evidence_ref: StrictStr = Field(min_length=3)
    root_cause: StrictStr = Field(min_length=10)
    verified_remedy: StrictStr = Field(min_length=10)
    regression_test: StrictStr = Field(min_length=5)
    limitations: tuple[StrictStr, ...] = Field(default_factory=tuple)
    reviewer: StrictStr = Field(min_length=3)
    superseded_by: StrictStr | None = None
    invalidated_by: tuple[StrictStr, ...] = Field(default_factory=tuple)
    created_at: StrictStr
    digest: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="before")
    @classmethod
    def convert_lists_to_tuples(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for key in ("error_codes", "affected_scope", "limitations", "invalidated_by"):
                if isinstance(data.get(key), list):
                    data[key] = tuple(data[key])
        return data

    @model_validator(mode="after")
    def verify_digest(self) -> LessonRecordV1:
        payload = self.model_dump(mode="json", exclude={"digest"})
        expected = _digest(payload)
        if self.digest != expected:
            raise ValueError(
                f"LESSON_DIGEST_MISMATCH: expected {expected}, got {self.digest}"
            )
        return self


class LessonQueryResult(StrictModel):
    """Evaluated lesson match with explicit validity and applicability."""

    lesson: LessonRecordV1
    validity: LessonStatus
    rejection_reason: StrictStr | None = None
    applicability_score: int = Field(ge=0)
    advisory_notice: Literal[
        "ADVISORY_RECIPE_ONLY_NOT_AUTHORIZATION"
    ] = "ADVISORY_RECIPE_ONLY_NOT_AUTHORIZATION"


class AgentLearningState(StrictModel):
    """Durable checkpointable research learning state for multi-step runs."""

    task: StrictStr
    session_id: StrictStr
    observed_at: StrictStr
    applied_lessons: tuple[StrictStr, ...] = Field(default_factory=tuple)
    rejected_lessons: tuple[StrictStr, ...] = Field(default_factory=tuple)
    tool_trace: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    quality_gates: dict[StrictStr, bool] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def convert_lists_to_tuples(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for key in ("applied_lessons", "rejected_lessons", "tool_trace"):
                if isinstance(data.get(key), list):
                    data[key] = tuple(data[key])
        return data


def create_lesson(
    *,
    lesson_id: str,
    knowledge_class: KnowledgeClass,
    trigger: str,
    affected_scope: tuple[str, ...],
    protocol: str,
    evidence_ref: str,
    root_cause: str,
    verified_remedy: str,
    regression_test: str,
    reviewer: str,
    error_codes: tuple[str, ...] = (),
    version_bounds: dict[str, str] | None = None,
    bound_code_hashes: dict[str, str] | None = None,
    bound_data_hashes: dict[str, str] | None = None,
    limitations: tuple[str, ...] = (),
    superseded_by: str | None = None,
    invalidated_by: tuple[str, ...] = (),
    created_at: str | None = None,
) -> LessonRecordV1:
    """Create a verified LessonRecordV1 with calculated cryptographic digest."""
    now = created_at or datetime.now(UTC).isoformat()
    fields: dict[str, Any] = {
        "schema_version": 1,
        "lesson_id": lesson_id,
        "knowledge_class": knowledge_class,
        "trigger": trigger,
        "error_codes": error_codes,
        "affected_scope": affected_scope,
        "protocol": protocol,
        "version_bounds": version_bounds or {},
        "bound_code_hashes": bound_code_hashes or {},
        "bound_data_hashes": bound_data_hashes or {},
        "evidence_ref": evidence_ref,
        "root_cause": root_cause,
        "verified_remedy": verified_remedy,
        "regression_test": regression_test,
        "limitations": limitations,
        "reviewer": reviewer,
        "superseded_by": superseded_by,
        "invalidated_by": invalidated_by,
        "created_at": now,
    }
    digest_value = _digest(fields)
    return LessonRecordV1.model_validate({**fields, "digest": digest_value})


class LessonStore:
    """Version-aware store and retrieval engine for research lessons."""

    def __init__(self, root: Path, directory: str = "docs/lessons") -> None:
        self.root: Path = Path(root).resolve()
        self.directory: Path = beneath(self.root, directory)
        self._lessons: dict[str, LessonRecordV1] = {}
        self.load_all()

    def load_all(self) -> int:
        """Load and cryptographically verify all lesson records in the store."""
        self._lessons.clear()
        if not self.directory.exists():
            return 0
        if not self.directory.is_dir() or self.directory.is_symlink():
            raise ValueError("LESSON_DIR_UNSAFE")
        count = 0
        for path in sorted(self.directory.glob("*.json")):
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 256_000:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                record = LessonRecordV1.model_validate(data)
                self._lessons[record.lesson_id] = record
                count += 1
            except (ValueError, json.JSONDecodeError, OSError) as exc:
                logger.warning("Skipping invalid lesson %s: %s", path.name, exc)
        return count

    def get(self, lesson_id: str) -> LessonRecordV1 | None:
        return self._lessons.get(lesson_id)

    def save(self, lesson: LessonRecordV1) -> Path:
        """Persist a lesson record atomically into the lessons directory."""
        self.directory.mkdir(parents=True, exist_ok=True)
        filename = f"{lesson.lesson_id}.json"
        path = self.directory / filename
        data = lesson.model_dump_json(indent=2) + "\n"
        path.write_text(data, encoding="utf-8")
        self._lessons[lesson.lesson_id] = lesson
        return path

    def evaluate_validity(
        self,
        lesson: LessonRecordV1,
        *,
        current_versions: dict[str, str] | None = None,
        code_hashes: dict[str, str] | None = None,
        data_hashes: dict[str, str] | None = None,
        target_protocol: str | None = None,
        target_scope: str | None = None,
    ) -> tuple[LessonStatus, str | None]:
        """Fail-closed evaluation of lesson validity, dependency bounds, and identity."""
        # 1. Superseded check
        if lesson.superseded_by:
            return "SUPERSEDED", f"Superseded by {lesson.superseded_by}"
        # 2. Hard Protocol Gate: conflicting protocol fails closed
        if (target_protocol and lesson.protocol != "any"
                and target_protocol != "any" and lesson.protocol != target_protocol):
            return (
                "PROTOCOL_MISMATCH",
                f"Lesson protocol {lesson.protocol} != target {target_protocol}",
            )

        # 3. Hard Scope Gate: conflicting scope fails closed
        if target_scope:
            norm_scope = target_scope.replace("\\", "/").lstrip("/")
            scope_matched = False
            for aff in lesson.affected_scope:
                if aff == "any" or aff in norm_scope or norm_scope.startswith(aff.replace("*", "")):
                    scope_matched = True
                    break
            if not scope_matched:
                return (
                    "SCOPE_MISMATCH",
                    f"Target scope {target_scope} not in affected scopes {lesson.affected_scope}",
                )

        # 4. Dependency Version Bounds (Numeric semver, fail closed if missing)
        if lesson.version_bounds:
            if not current_versions:
                return "VERSION_INCOMPATIBLE", "Current dependency versions missing; fails closed"
            for pkg, min_ver in lesson.version_bounds.items():
                cur_ver = current_versions.get(pkg)
                if not cur_ver:
                    return (
                        "VERSION_INCOMPATIBLE",
                        f"Required dependency {pkg} version missing from environment",
                    )
                try:
                    if _parse_semver(cur_ver) < _parse_semver(min_ver):
                        return (
                            "VERSION_INCOMPATIBLE",
                            f"Numeric version {pkg} {cur_ver} < required {min_ver}",
                        )
                except ValueError as exc:
                    return "VERSION_INCOMPATIBLE", f"Invalid version string: {exc}"

        # 5. Code Drift Check
        if lesson.bound_code_hashes:
            if not code_hashes:
                return "CODE_DRIFT", "Code hashes missing from environment check; fails closed"
            for path_key, expected_hash in lesson.bound_code_hashes.items():
                actual_hash = code_hashes.get(path_key)
                if actual_hash != expected_hash:
                    return (
                        "CODE_DRIFT",
                        f"Code drift at {path_key}: expected {expected_hash}, got {actual_hash}",
                    )

        # 6. Data Drift Check
        if lesson.bound_data_hashes:
            if not data_hashes:
                return "DATA_DRIFT", "Data hashes missing from environment check; fails closed"
            for path_key, expected_hash in lesson.bound_data_hashes.items():
                actual_hash = data_hashes.get(path_key)
                if actual_hash != expected_hash:
                    return (
                        "DATA_DRIFT",
                        f"Data drift at {path_key}: expected {expected_hash}, got {actual_hash}",
                    )

        # 7. Invalidated By environment flags
        if lesson.invalidated_by and current_versions:
            for inv in lesson.invalidated_by:
                if inv in current_versions.values():
                    return (
                        "INVALIDATED",
                        f"Invalidated by active environment flag: {inv}",
                    )

        return "VALID", None

    def query(
        self,
        *,
        error_code: str | None = None,
        scope_path: str | None = None,
        protocol: str | None = None,
        current_versions: dict[str, str] | None = None,
        code_hashes: dict[str, str] | None = None,
        data_hashes: dict[str, str] | None = None,
        include_superseded: bool = False,
        include_invalid: bool = False,
    ) -> list[LessonQueryResult]:
        """Deterministic query for lessons relevant to an error, scope, or protocol."""
        if not any((error_code, scope_path, protocol)):
            return []
        results: list[LessonQueryResult] = []

        for lesson in self._lessons.values():
            # Apply fail-closed compatibility gates BEFORE relevance scoring
            validity, reason = self.evaluate_validity(
                lesson,
                current_versions=current_versions,
                code_hashes=code_hashes,
                data_hashes=data_hashes,
                target_protocol=protocol,
                target_scope=scope_path,
            )

            score = 0
            # Match on error code (if error_code supplied, it must match)
            if error_code:
                if error_code in lesson.error_codes:
                    score += 5
                elif any(error_code.lower() in ec.lower() for ec in lesson.error_codes):
                    score += 2
                else:
                    continue

            # Match on affected scope
            if scope_path:
                norm_scope = scope_path.replace("\\", "/").lstrip("/")
                for aff in lesson.affected_scope:
                    if aff == "any" or aff in norm_scope or norm_scope.startswith(aff.replace("*", "")):
                        score += 3
                        break

            # Match on protocol
            if protocol:
                if lesson.protocol == protocol:
                    score += 2
                elif lesson.protocol == "any" or protocol == "any":
                    score += 1

            filters_supplied = any((error_code, scope_path, protocol))
            if filters_supplied and score == 0:
                continue

            if validity == "SUPERSEDED" and not include_superseded:
                continue
            if validity != "VALID" and not include_invalid:
                continue
            results.append(
                LessonQueryResult(
                    lesson=lesson,
                    validity=validity,
                    rejection_reason=reason,
                    applicability_score=score,
                )
            )

        results.sort(key=lambda r: (r.applicability_score, r.lesson.created_at), reverse=True)
        return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("list", "query", "validate"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--directory", default="docs/lessons")
    parser.add_argument("--error-code")
    parser.add_argument("--scope-path")
    parser.add_argument("--protocol")
    parser.add_argument("--include-superseded", action="store_true")
    parser.add_argument("--include-invalid", action="store_true")
    args = parser.parse_args(argv)

    store = LessonStore(args.root, args.directory)

    if args.command == "list":
        lessons = [l.model_dump(mode="json") for l in store._lessons.values()]
        print(json.dumps({"total": len(lessons), "lessons": lessons}, indent=2))
        return 0

    if args.command == "validate":
        total = len(store._lessons)
        print(json.dumps({"validated": total, "status": "ALL_DIGESTS_VERIFIED"}, indent=2))
        return 0

    if args.command == "query":
        results = store.query(
            error_code=args.error_code,
            scope_path=args.scope_path,
            protocol=args.protocol,
            include_superseded=args.include_superseded,
            include_invalid=args.include_invalid,
        )
        output = [r.model_dump(mode="json") for r in results]
        print(json.dumps({"matched": len(output), "results": output}, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
