"""Issue #48: offline-only paper qualification packet validation and rehearsal.

No imports of provider clients, no execution engine construction, no credential
contents, and no trading orders. A READY result is *never* an order permit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from src.bybit_paper_runtime import (
    PaperConfigBlocked,
    ReviewedPaperAccount,
    make_native_risk,
)

REPO = Path(__file__).resolve().parents[1]
CONNECTOR = Path(__import__("connectors.bybit", fromlist=["__file__"]).__file__).resolve().parents[2]
CREDENTIAL_ENV = ("BYBIT_DEMO_API_KEY", "BYBIT_DEMO_API_SECRET", "BYBIT_DEMO_EXPECTED_UID")
BLOCKED = "BLOCKED"
PREPARED = "READY_FOR_MANUAL_REVIEW"  # NOT an order permit or paper qualification.
MANDATORY_ABORT_REASONS = frozenset({
    "reconciliation_mismatch", "unknown_order_outcome", "persistence_error",
    "journal_error", "identity_unverified", "native_recovery_exhausted",
    "risk_limit_breach", "feed_stale", "broker_disconnected",
})
HARD_ZERO = (
    "max_unreconciled_order_count", "max_unattributed_fill_count",
    "max_unknown_order_outcomes", "max_unresolved_safety_incidents",
)
POSITIVE_COUNT = ("min_order_lifecycle_drills", "min_recovery_drills")
POSITIVE_RISK = (
    "max_order_shares", "max_order_value", "max_position_shares",
    "max_position_value", "max_total_exposure", "max_positions",
    "max_orders_per_minute", "max_daily_loss", "max_drawdown_pct",
    "max_price_deviation_pct", "max_data_staleness_seconds",
    "dedup_window_seconds", "feed_silence_seconds", "max_event_age_seconds",
    "max_recovery_attempts", "recovery_cooldown_seconds",
)


def _outside_sources(value: Any) -> Path | None:
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        return None
    path = Path(value).resolve()
    if path.is_relative_to(REPO) or path.is_relative_to(CONNECTOR):
        return None
    return path


def _private_dir(value: Any) -> Path | None:
    path = _outside_sources(value)
    if path is None:
        return None
    try:
        if path.is_dir() and path.stat().st_mode & 0o077 == 0:
            return path
    except OSError:
        pass
    return None


def _time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo is not None else None
    if not isinstance(value, str) or not value or "T" not in value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is not None:
            return parsed.astimezone(UTC)
    except ValueError:
        return None
    return None


def _required_text(root: dict[str, Any], key: str, errors: list[str]) -> str | None:
    value = root.get(key)
    if not isinstance(value, str) or not value.strip() or value.strip().lower() in (
        "tbd", "todo", "unknown", "unselected", "placeholder",
    ):
        errors.append(f"{key}: missing operator-reviewed value")
        return None
    return value


def _read_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        if path.stat().st_size > 1_048_576 or path.stat().st_mode & 0o077:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, UnicodeError):
        return None


def evaluate_packet(
    packet: dict[str, Any], *, environment: dict[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fail-closed rehearsal. Report safe problem codes, never identifying data."""
    env = os.environ if environment is None else environment
    now = (now or datetime.now(UTC)).astimezone(UTC)
    errors: list[str] = []
    if packet.get("schema_version") != 1:
        errors.append("schema_version: expected 1")
    subject = packet.get("subject") if isinstance(packet.get("subject"), dict) else {}
    approval = packet.get("approval") if isinstance(packet.get("approval"), dict) else {}
    risk = packet.get("risk") if isinstance(packet.get("risk"), dict) else {}
    observation = packet.get("observation") if isinstance(packet.get("observation"), dict) else {}
    criteria = packet.get("criteria") if isinstance(packet.get("criteria"), dict) else {}
    evidence = packet.get("evidence") if isinstance(packet.get("evidence"), dict) else {}

    strategy_id = _required_text(subject, "strategy_id", errors)
    strategy_path = _required_text(subject, "strategy_source", errors)
    source_hash = _required_text(subject, "strategy_sha256", errors)
    research_ref = _required_text(approval, "research_approval_ref", errors)
    reviewer = _required_text(approval, "research_approved_by", errors)
    _required_text(approval, "risk_reviewed_by", errors)
    _required_text(approval, "operator_owner", errors)
    _required_text(subject, "account_ref_redacted", errors)

    if subject.get("venue") != "bybit" or subject.get("environment") != "demo":
        errors.append("broker_identity: only Bybit Demo is eligible")
    if subject.get("public_feed") != "bybit_mainnet_public":
        errors.append("feed_identity: mainnet public data source must be explicit")
    if approval.get("research_approval_status") != "APPROVED_FOR_PAPER_REVIEW":
        errors.append("research_approval: explicit paper-review approval missing")
    if not research_ref or not reviewer:
        errors.append("research_approval: signed or traceable decision required")
    if approval.get("risk_reviewed") is not True:
        errors.append("risk_review: unapproved limits")
    if approval.get("account_owner_exclusive") is not True:
        errors.append("account_owner: exclusive native risk owner not attested")

    if not isinstance(source_hash, str) or re.fullmatch("[0-9a-f]{64}", source_hash) is None:
        errors.append("strategy_sha256: valid frozen digest required")
    if strategy_path:
        candidate = (REPO / strategy_path).resolve()
        if not candidate.is_relative_to(REPO) or not candidate.is_file():
            errors.append("strategy_source: accessible repo source file required")
        elif (
            isinstance(source_hash, str)
            and re.fullmatch("[0-9a-f]{64}", source_hash)
            and hashlib.sha256(candidate.read_bytes()).hexdigest() != source_hash
        ):
            errors.append("strategy_source: digest mismatch")
    symbols = subject.get("instruments")
    if (
        not isinstance(symbols, list) or not symbols or len(symbols) != len({str(x) for x in symbols})
        or any(not isinstance(s, str) or not re.fullmatch(r"[A-Z0-9]+/[A-Z0-9]+:[A-Z0-9]+", s) for s in symbols)
    ):
        errors.append("instruments: nonempty venue-qualified list required")
        symbols = []
    cadence = subject.get("bar_cadence")
    match = re.fullmatch(r"([1-9][0-9]*)([mhd])", cadence) if isinstance(cadence, str) else None
    if match is None:
        errors.append("bar_cadence: supported completed-bar interval required")

    if env.get("BYBIT_ENVIRONMENT") != "demo":
        errors.append("credentials: BYBIT_ENVIRONMENT=demo required")
    if env.get("BYBIT_MODE") != "read_only":
        errors.append("credentials: BYBIT_MODE=read_only for this rehearsal")
    if any(not isinstance(env.get(key), str) or not env.get(key) for key in CREDENTIAL_ENV):
        errors.append("credentials: dedicated Demo key, secret and expected UID missing")
    if env.get("BYBIT_DEMO_API_KEY") and env.get("BYBIT_DEMO_API_KEY") == env.get("BYBIT_API_KEY"):
        errors.append("credentials: Demo key matches Mainnet key")
    uid = env.get("BYBIT_DEMO_EXPECTED_UID", "")
    if not isinstance(uid, str) or not uid.isdecimal():
        errors.append("account_identity: independently observed numeric Demo UID required")
        uid = None
    if subject.get("account_ref_redacted") == uid and uid is not None:
        errors.append("account_ref_redacted: cannot equal private Demo UID")

    if risk.get("execution_mode") != "paper" or risk.get("fail_on_reconciliation_mismatch") is not True or risk.get("fail_on_journal_error") is not True or risk.get("auto_recover") is not True:
        errors.append("native_safety: paper mode and strict native reconciliation/journal/recovery are mandatory")
    state_dir = _private_dir(risk.get("state_dir"))
    if state_dir is None:
        errors.append("risk_state: existing private 0700 directory outside repositories required")
    native_config = None
    if uid is not None and state_dir is not None:
        try:
            args = {f.name: risk.get(f.name) for f in fields(ReviewedPaperAccount)}
            args.update(
                account_uid=uid, strategy_id=strategy_id or "",
                allowed_assets=frozenset(symbols), state_dir=state_dir,
                reviewed=approval.get("risk_reviewed") is True,
            )
            reviewed_risk = ReviewedPaperAccount(**args)
            native_config = make_native_risk(reviewed_risk)
            if match is not None:
                bar_seconds = int(match.group(1)) * {"m": 60, "h": 3600, "d": 86400}[match.group(2)]
                if risk.get("feed_silence_seconds", 0) <= bar_seconds:
                    errors.append("feed_cadence: silence must exceed a full completed bar interval")
        except (TypeError, ValueError, PaperConfigBlocked, AttributeError):
            errors.append("native_risk: invalid or incomplete strategy/account-specific caps")

    start = _time(observation.get("start_utc"))
    end = _time(observation.get("end_utc"))
    if start is None or end is None or end <= start or start < now:
        errors.append("observation_window: future predeclared UTC start/end required")
    for key in HARD_ZERO:
        if type(criteria.get(key)) is not int or criteria[key] != 0:
            errors.append(f"criteria.{key}: must explicitly require zero")
    for key in POSITIVE_COUNT:
        if type(criteria.get(key)) is not int or criteria[key] <= 0:
            errors.append(f"criteria.{key}: explicit positive evidence count required")
    healthy = criteria.get("minimum_healthy_fraction")
    if isinstance(healthy, bool) or not isinstance(healthy, (int, float)) or not math.isfinite(healthy) or not 0 < healthy <= 1:
        errors.append("criteria.minimum_healthy_fraction: predeclared (0,1] threshold required")
    aborts = observation.get("abort_reasons")
    if not isinstance(aborts, list) or not MANDATORY_ABORT_REASONS <= {str(x) for x in aborts}:
        errors.append("abort_reasons: mandatory native safety failures must abort")

    evidence_dir = _private_dir(evidence.get("output_dir"))
    if evidence_dir is None:
        errors.append("evidence: existing private 0700 output directory required")
    state_path = _outside_sources(evidence.get("preflight_state_file"))
    if native_config is None or state_path is None or state_path != Path(native_config.state_file):
        errors.append("preflight_state_file: must match exclusive native risk-state path")
    preflight = _read_json(_outside_sources(evidence.get("preflight_report")))
    if preflight is None:
        errors.append("preflight: readable private read-only evidence required")
    else:
        identity = preflight.get("identity", {})
        recon = preflight.get("reconciliation", {})
        persist = preflight.get("persistence", {})
        checked = _time(preflight.get("checked_at"))
        if (
            preflight.get("status") != "PASS" or preflight.get("environment") != "demo"
            or preflight.get("mode") != "read_only" or preflight.get("native_execution_mode") != "paper"
            or preflight.get("submitted_orders") != 0 or preflight.get("ml4t_live_version") != "0.1.2"
            or checked is None or not now - timedelta(hours=24) <= checked <= now
            or not isinstance(identity, dict) or identity.get("authenticated_uid_matches_expected") is not True
            or identity.get("private_rest") != "api-demo.bybit.com"
            or not isinstance(recon, dict) or recon.get("clean") is not True
            or not isinstance(persist, dict) or persist.get("state_error") is not None
            or persist.get("journal_error") is not None or persist.get("journal_required") is not True
            or preflight.get("connector_unknown_intents") is not False
        ):
            errors.append("preflight: Demo identity, freshness, state or reconciliation not verified")
    health = _read_json(_outside_sources(evidence.get("native_health_report")))
    if health is None:
        errors.append("native_health: readable private native status evidence required")
    else:
        engine = health.get("engine")
        persist = health.get("persistence")
        recon = health.get("reconciliation")
        health_checked = _time(health.get("checked_at"))
        if (
            health_checked is None or not now - timedelta(minutes=10) <= health_checked <= now
            or not isinstance(engine, dict) or engine.get("runtime_state") not in ("ready", "running")
            or engine.get("health") not in ("ready", "ok", "healthy")
            or engine.get("broker_connected") is not True
            or not isinstance(persist, dict) or persist.get("state_error") is not None
            or persist.get("journal_error") is not None or persist.get("execution_identity_validated") is not True
            or not isinstance(recon, dict) or recon.get("clean") is not True
        ):
            errors.append("native_health: clean engine, broker, risk and journal status required")

    # The filesystem-based credential and report checks are an offline
    # rehearsal, never proof of independent authenticated operator approval.
    return {
        "issue": "hzminhzz/quant-research#48",
        "status": BLOCKED if errors else PREPARED,
        "blockers": sorted(set(errors)),
        "native_risk_config_valid": native_config is not None,
        "paper_qualified": False,
        "paper_order_authorized": False,
        "live_money_authorized": False,
        "submitted_orders": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--evidence-file", type=Path)
    args = parser.parse_args()
    try:
        raw = yaml.safe_load(args.packet.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raw = {}
        result = evaluate_packet(raw)
    except (OSError, ValueError, yaml.YAMLError):
        result = {
            "issue": "hzminhzz/quant-research#48", "status": BLOCKED,
            "blockers": ["qualification_packet: missing, malformed or unreadable"],
            "paper_qualified": False, "paper_order_authorized": False,
            "live_money_authorized": False, "submitted_orders": 0,
        }
    encoded = json.dumps(result, sort_keys=True, indent=2)
    print(encoded)
    if args.evidence_file is not None:
        path = _outside_sources(str(args.evidence_file))
        if path is None or _private_dir(str(path.parent)) is None:
            return 2
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(encoded + "\n")
        except OSError:
            # Never overwrite append-only operator evidence or disclose private paths.
            return 2
    return 0 if result["status"] == PREPARED else 2


if __name__ == "__main__":
    raise SystemExit(main())
