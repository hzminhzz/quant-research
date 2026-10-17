"""Fail-closed evidence boundary for promoted-strategy qualification.

This module never computes fills or PnL.  It converts already reconciled native
account records into ATS-5 events and verifies immutable external registrations.
Coverage remains a separate attestation: event conversion cannot certify it.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from src.account_rules import AccountEvent, RuleError, aware, money


class PromotedEvidenceError(ValueError):
    """Evidence is missing, changed, ambiguous, or unsupported."""


NativeKind = Literal[
    "mark", "position_opened", "position_closed", "realized_pnl",
    "commission", "swap", "observation",
]


@dataclass(frozen=True)
class NativeAccountRecord:
    """One reconciled native account fact, not a price-derived reconstruction."""

    source_event_id: str
    at: datetime
    sequence: int
    kind: NativeKind
    amount: Decimal
    source_sha256: str
    certainty: Literal["observed", "uncertain"] = "observed"
    reference: str | None = None


def account_events_from_native(
    records: tuple[NativeAccountRecord, ...] | list[NativeAccountRecord],
) -> tuple[AccountEvent, ...]:
    """Convert exact native facts to ATS-5 events without deriving cash or PnL.

    Uncertain fills and marks are refused.  Caller must represent resulting
    evidence gap through absent independent coverage, yielding INCONCLUSIVE.
    """
    events: list[AccountEvent] = []
    expected_source: str | None = None
    last_key: tuple[datetime, int] | None = None
    seen: set[str] = set()
    for record in records:
        at = aware(record.at)
        if record.certainty != "observed":
            raise PromotedEvidenceError("UNCERTAIN_NATIVE_EVENT")
        if len(record.source_sha256) != 64:
            raise PromotedEvidenceError("INVALID_NATIVE_SOURCE_IDENTITY")
        try:
            int(record.source_sha256, 16)
        except ValueError as exc:
            raise PromotedEvidenceError("INVALID_NATIVE_SOURCE_IDENTITY") from exc
        if expected_source is None:
            expected_source = record.source_sha256
        elif record.source_sha256 != expected_source:
            raise PromotedEvidenceError("MIXED_NATIVE_SOURCE_IDENTITY")
        if record.source_event_id in seen:
            raise PromotedEvidenceError("DUPLICATE_NATIVE_EVENT_ID")
        key = (at, record.sequence)
        if last_key is not None and key <= last_key:
            raise PromotedEvidenceError("OUT_OF_ORDER_NATIVE_EVENT")
        try:
            amount = money(record.amount)
            event = AccountEvent(
                event_id=f"native:{record.source_event_id}", at=at,
                sequence=record.sequence, kind=record.kind, amount=amount,
                reference=record.reference,
            )
        except RuleError as exc:
            raise PromotedEvidenceError(str(exc)) from exc
        events.append(event)
        seen.add(record.source_event_id)
        last_key = key
    return tuple(events)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_registration(registration: dict[str, Any], source_root: Path) -> dict[str, Any]:
    """Verify frozen source identity; never accept positive authorization claims."""
    _validate_non_authoritative_verdict(registration.get("verdict"))
    source_root = source_root.resolve(strict=True)
    checked: list[dict[str, Any]] = []
    failures: list[str] = []
    source_files = registration.get("source_files", [])
    if not source_files:
        failures.append("EMPTY_SOURCE_REGISTRATION")
    paths = [item.get("path") for item in source_files]
    if len(paths) != len(set(paths)):
        failures.append("DUPLICATE_SOURCE_PATH")
    for item in source_files:
        relative = item["path"]
        lexical = source_root / relative
        candidate = lexical.resolve()
        try:
            candidate.relative_to(source_root)
        except ValueError:
            failures.append(f"PATH_ESCAPE:{relative}")
            continue
        if not candidate.is_file() or lexical.is_symlink():
            failures.append(f"MISSING_OR_SYMLINK:{relative}")
            continue
        actual = sha256_file(candidate)
        checked.append({"path": relative, "sha256": actual})
        if actual != item["sha256"]:
            failures.append(f"HASH_MISMATCH:{relative}")
    return {
        "candidate_id": registration["candidate_id"],
        "source_identity": "VERIFIED" if not failures else "REJECTED",
        "checked": checked,
        "failures": failures,
        "verdict": registration["verdict"] if not failures else "BLOCKED_SOURCE_DRIFT",
        "barriers": registration.get("barriers", []),
        "cross_gates": registration.get("cross_gates", {}),
    }


def _validate_non_authoritative_verdict(verdict: Any) -> None:
    allowed = {
        "INCONCLUSIVE", "BLOCKED_EXTERNAL_DATA",
        "INCONCLUSIVE_MARGIN_LIQUIDATION_AND_EXACT_FUNDING",
        "RESTRUCTURE", "SHELVE",
    }
    if verdict not in allowed:
        raise PromotedEvidenceError("REGISTRATION_CANNOT_MINT_POSITIVE_QUALIFICATION")


def load_registration(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    required = {"schema_version", "candidate_id", "source_files", "verdict"}
    if value.get("schema_version") != 1 or not required <= value.keys():
        raise PromotedEvidenceError("UNSUPPORTED_REGISTRATION")
    if not value["source_files"]:
        raise PromotedEvidenceError("EMPTY_SOURCE_REGISTRATION")
    _validate_non_authoritative_verdict(value["verdict"])
    return value
