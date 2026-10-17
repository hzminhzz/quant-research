"""ATS-6: single-host transactional shadow routing, with no broker transport.

One SQLite transaction serializes source revisions, reservations, routes and the
outbox in a bounded risk domain. The durable sink contains shadow messages only.
The append-only command journal can reconstruct the projection after a crash.
This is cooperative same-UID storage, not protection against the filesystem owner.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import sqlite3
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal
from fractions import Fraction
from pathlib import Path

from pydantic import ValidationError

from src.account_rules import RuleError
from src.research_control.action_authorization import (
    SignedGrantV1,
    TrustPolicyV1,
    canonical_json,
    sha256_json,
    validate_grant,
)
from src.research_control.ats3_audit import AuditEvent
from src.shadow_contracts import (
    MAX_UNITS,
    AccountSnapshot,
    DomainPolicy,
    Intent,
    Observation,
    PortfolioSnapshot,
    RouterError,
    action_for,
    clock,
    data,
    rule_decision,
)

SCHEMA = 1
FAULTS = {
    "admit:before_commit", "admit:after_commit",
    "publish:before_commit", "publish:after_commit",
}


def runtime_identity() -> str:
    root = Path(__file__).resolve().parent
    files = ("shadow_router.py", "shadow_contracts.py", "account_rules.py",
             "portfolio_evidence.py", "research_control/action_authorization.py",
             "research_control/ats3_audit.py")
    return sha256_json({
        "files": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files},
        "sqlite": sqlite3.sqlite_version,
        "packages": {name: importlib.metadata.version(name) for name in ("pydantic", "cryptography")},
    })


def _usage(state: dict) -> dict:
    accounts = {key: {"reserved": 0, "recognized": 0, "margin": 0, "unknown": 0,
                      "families": {}} for key in state["accounts"]}
    for key, snapshot in state["accounts"].items():
        a = accounts[key]
        for o in snapshot["opening_obligations"]:
            a["reserved" if o["kind"] == "unknown" else "recognized"] += o["risk_units"]
            a["margin"] += o["margin_units"]
            a["unknown"] += o["risk_units"] if o["kind"] == "unknown" else 0
            a["families"][o["family"]] = a["families"].get(o["family"], 0) + o["risk_units"]
    for r in state["routes"].values():
        if r["account_id"] is None:
            continue
        a = accounts[r["account_id"]]
        reserved = recognized = margin = 0
        for key, leg in r["legs"].items():
            opened = sum(e["lots"] for e in r["executions"].values()
                         if e["leg_id"] == key and e["role"] == "open")
            closed = sum(e["lots"] for ident, e in r["executions"].items()
                         if ident in r["closed_ids"] and e["leg_id"] == key)
            pending = 0 if r["terminal"] else max(0, leg["quantity_lots"] - opened)
            current = max(0, opened - closed)
            reserved += pending * leg["unit_risk"]
            recognized += current * leg["unit_risk"]
            margin += (pending + current) * leg["unit_margin"]
        reserved += r["disputed_risk"]
        margin += r["disputed_margin"]
        a["reserved"] += reserved
        a["recognized"] += recognized
        a["margin"] += margin
        if r["unknown"] or (r["published"] and not r["ack"]):
            a["unknown"] += reserved
        family = r["intent"]["family"]
        a["families"][family] = a["families"].get(family, 0) + reserved + recognized
    total = {"reserved": 0, "recognized": 0, "margin": 0, "unknown": 0, "families": {}}
    for a in accounts.values():
        a["used"] = a["reserved"] + a["recognized"]
        for key in ("reserved", "recognized", "margin", "unknown"):
            total[key] += a[key]
        for family, value in a["families"].items():
            total["families"][family] = total["families"].get(family, 0) + value
    total["used"] = total["reserved"] + total["recognized"]
    total["remaining"] = state["policy"]["shared_limit_units"] - total["used"]
    # Python integer arithmetic and JSON storage retain even an unexpected
    # overfill beyond the admission range; never discard observed exposure.
    return {"accounts": accounts, "shared": total}


def _fresh(at, until, now, age):
    a, u = clock(at), clock(until)
    return a <= now < u and (now - a).total_seconds() <= age


def _floor_capacity(snapshot, decision, policy):
    current = next(r for r in snapshot.rules if r["version_id"] == decision.version_id)
    if decision.minimum_headroom is None:
        return 0
    scaled = decision.minimum_headroom * policy.units_per_currency
    headroom = int(scaled.to_integral_value(rounding=ROUND_FLOOR))
    if current.get("breach_on_touch") and scaled == headroom:
        headroom -= 1
    return min(snapshot.risk_limit_units, max(0, headroom))


def _active_source_blocks(state, now, usage):
    """A stale holder cannot donate apparently free shared capacity."""
    p = DomainPolicy.model_validate(state["policy"])
    reasons = []
    for key, used in usage["accounts"].items():
        if not used["used"]:
            continue
        a = AccountSnapshot.model_validate(state["accounts"][key])
        decision = rule_decision(a, now)
        if (not _fresh(a.at, a.valid_until, now, p.max_source_age_seconds)
                or not a.marks_complete or a.margin_at is None
                or a.margin_capacity_units is None
                or not _fresh(a.margin_at, a.valid_until, now, p.max_source_age_seconds)
                or decision.uncertainty or decision.minimum_headroom is None):
            reasons.append("ACTIVE_ACCOUNT_SOURCE_UNCERTAIN:" + key)
        if (decision.state == "BREACHED"
                or used["used"] > _floor_capacity(a, decision, p)
                or (a.margin_capacity_units is not None and used["margin"] > a.margin_capacity_units)):
            reasons.append("ACTIVE_ACCOUNT_RISK_BREACH:" + key)
    if any(value > p.family_limit_units for value in usage["shared"]["families"].values()):
        reasons.append("ACTIVE_FAMILY_RISK_BREACH")
    return reasons


def _quoted(intent: Intent, snapshot: AccountSnapshot) -> dict:
    return {leg.leg_id: {
        **data(leg),
        "unit_risk": ((leg.stress_units_per_lot * snapshot.stress_multiplier_bps + 9999)
                      // 10000 + snapshot.cost_units_per_lot),
        "unit_margin": leg.margin_units_per_lot,
    } for leg in intent.legs}


def _assess(state, intent, key, now, usage):
    a = AccountSnapshot.model_validate(state["accounts"][key])
    p = DomainPolicy.model_validate(state["policy"])
    reasons = []
    if not _fresh(a.at, a.valid_until, now, p.max_source_age_seconds):
        reasons.append("ACCOUNT_SNAPSHOT_STALE")
    if not a.marks_complete:
        reasons.append("MARK_COVERAGE_MISSING")
    if a.margin_capacity_units is None or a.margin_at is None:
        reasons.append("MARGIN_UNKNOWN")
    elif not _fresh(a.margin_at, a.valid_until, now, p.max_source_age_seconds):
        reasons.append("MARGIN_STALE")
    if a.lifecycle != "active":
        reasons.append("ACCOUNT_LIFECYCLE_BLOCKED")
    if a.currency != p.currency:
        reasons.append("CURRENCY_MISMATCH")
    if any(leg.instrument.split(":")[0] != a.venue for leg in intent.legs):
        reasons.append("VENUE_MISMATCH")
    if any(leg.instrument not in a.permitted_instruments for leg in intent.legs):
        reasons.append("INSTRUMENT_NOT_PERMITTED")
    decision = rule_decision(a, now)
    if not decision.eligible_for_shadow or decision.uncertainty:
        reasons.append("ACCOUNT_RULES_INELIGIBLE")
    current_rules = next(r for r in a.rules if r["version_id"] == decision.version_id)
    if current_rules.get("unknown_rules"):
        reasons.append("RULE_COVERAGE_MISSING")
    capacity = _floor_capacity(a, decision, p)
    legs = _quoted(intent, a)
    risk = sum(x["quantity_lots"] * x["unit_risk"] for x in legs.values())
    margin = sum(x["quantity_lots"] * x["unit_margin"] for x in legs.values())
    used = usage["accounts"][key]
    if risk > MAX_UNITS or margin > MAX_UNITS:
        reasons.append("RISK_RANGE_EXCEEDED")
    if used["used"] + risk > capacity:
        reasons.append("ACCOUNT_RISK_LIMIT")
    if a.margin_capacity_units is not None and used["margin"] + margin > a.margin_capacity_units:
        reasons.append("ACCOUNT_MARGIN_LIMIT")
    if usage["shared"]["used"] + risk > p.shared_limit_units:
        reasons.append("SHARED_RISK_LIMIT")
    family_used = usage["shared"]["families"].get(intent.family, 0)
    if family_used + risk > p.family_limit_units:
        reasons.append("FAMILY_RISK_LIMIT")
    return {
        "account_id": key, "reasons": sorted(set(reasons)), "risk": risk, "margin": margin,
        "capacity": capacity, "remaining_after": capacity - used["used"] - risk,
        "family_after": used["families"].get(intent.family, 0) + risk,
        "lifecycle_priority": a.lifecycle_priority, "legs": legs,
        "snapshot_sha256": sha256_json(data(a)),
        "rule_decision": data(decision),
    }


def _status(r):
    if r["account_id"] is None:
        return "SKIPPED"
    if r["unknown"] or r["conflicts"]:
        return "UNKNOWN"
    if r["terminal"]:
        return "RECONCILED"
    if r["cancel_observed"]:
        return "CANCELED_AWAITING_RECONCILIATION"
    if r["reject_observed"]:
        return "REJECTED_AWAITING_RECONCILIATION"
    opened = sum(e["lots"] for e in r["executions"].values() if e["role"] == "open")
    requested = sum(leg["quantity_lots"] for leg in r["legs"].values())
    if opened >= requested:
        return "COMPLETED"
    if opened:
        return "PARTIALLY_FILLED"
    if r["ack"]:
        return "ACKNOWLEDGED"
    return "SHADOW_DISPATCHED" if r["published"] else "ADMITTED"


def _route_result(r, reason=""):
    return {"status": _status(r), "reason": reason, "intent_id": r["intent"]["intent_id"],
            "account_id": r["account_id"], "route_revision": r["revision"],
            "reasons": r["reasons"]}


def _authorize(state, action, grant, now):
    intent = Intent.model_validate(action["intent"])
    return validate_grant(
        grant, action, window_start=intent.created_at, window_end=intent.valid_until,
        selection_sha256=action["portfolio"], now=now, shadow=True,
        trusted_policy=TrustPolicyV1.model_validate_json(canonical_json(state["authority"])),
    )


def _admit(state, d, now):
    action, grant = d["action"], d["grant"]
    intent = Intent.model_validate(action["intent"])
    existing = state["routes"].get(intent.intent_id)
    if existing:
        if sha256_json(existing["intent"]) != sha256_json(data(intent)):
            return {"status": "DENIED", "reason": "INTENT_ID_CONFLICT"}
        return _route_result(existing, "EXISTING_DECISION")
    if action != action_for(state, intent):
        return {"status": "DENIED", "reason": "STALE_OR_ALTERED_BINDINGS"}
    auth = _authorize(state, action, grant, now)
    if auth.status != "AUTHORIZED":
        return {"status": "DENIED", "reason": auth.reason_code}
    if auth.grant_id in state["grant_uses"]:
        return {"status": "DENIED", "reason": "GRANT_REPLAY"}
    reasons = []
    policy = DomainPolicy.model_validate(state["policy"])
    if not intent.created_at <= now < intent.valid_until:
        reasons.append("INTENT_EXPIRED_OR_FUTURE")
    if state["halted"]:
        reasons.append("INTEGRITY_HALT")
    if len({leg.instrument.split(":")[0] for leg in intent.legs}) != 1:
        reasons.append("CROSS_VENUE_ATOMICITY_UNQUALIFIED")
    portfolio = state["portfolio"]
    if portfolio is None:
        reasons.append("PORTFOLIO_EVIDENCE_MISSING")
    else:
        ps = PortfolioSnapshot.model_validate(portfolio)
        if not _fresh(ps.at, ps.valid_until, now, policy.max_source_age_seconds):
            reasons.append("PORTFOLIO_EVIDENCE_STALE")
        if intent.sleeve not in ps.sleeves:
            reasons.append("SLEEVE_IDENTITY_NOT_IN_PORTFOLIO")
    usage = _usage(state)
    reasons.extend(_active_source_blocks(state, now, usage))
    candidates = [_assess(state, intent, key, now, usage) for key in sorted(state["accounts"])]
    feasible = [c for c in candidates if not c["reasons"]]
    if not candidates:
        reasons.append("NO_ACCOUNT_SNAPSHOT")
    if not feasible:
        reasons.append("NO_FEASIBLE_ACCOUNT")
    if policy.allocation_policy == "cushion":
        feasible.sort(key=lambda c: (
            c["lifecycle_priority"], -Fraction(c["remaining_after"], max(1, c["risk"])),
            Fraction(c["family_after"], max(1, c["capacity"])), c["account_id"],
        ))
    elif policy.allocation_policy == "least_used":
        feasible.sort(key=lambda c: (usage["accounts"][c["account_id"]]["used"], c["account_id"]))
    else:
        feasible.sort(key=lambda c: c["account_id"])
    chosen = feasible[0] if feasible and not reasons else None
    route = {
        "intent": data(intent), "action": action, "grant": grant,
        "account_id": chosen["account_id"] if chosen else None,
        "revision": 1, "reasons": sorted(set(reasons)),
        "candidates": candidates, "admitted_at": now.isoformat(),
        "admission_state_revision": state["revision"],
        "selected": chosen, "legs": chosen["legs"] if chosen else {},
        "executions": {}, "execution_clocks": {}, "closed_ids": [], "seen": {}, "sequences": {},
        "max_source_sequence": 0, "max_event_at": now.isoformat(),
        "ack": False, "ack_clock": None, "published": False, "published_at": None,
        "unknown": False, "terminal": None,
        "cancel_observed": False, "reject_observed": False,
        "conflicts": [], "disputed_risk": 0, "disputed_margin": 0,
    }
    state["routes"][intent.intent_id] = route
    state["grant_uses"][auth.grant_id] = intent.intent_id
    if chosen:
        client_ids = {key: "ats6-" + sha256_json({
            "domain": policy.domain_id, "intent": intent.intent_id,
            "account": chosen["account_id"], "leg": key,
        })[:40] for key in route["legs"]}
        payload = {
            "environment": "shadow", "effect": "LOCAL_EVIDENCE_ONLY",
            "intent_id": intent.intent_id, "account_id": chosen["account_id"],
            "client_order_ids": client_ids, "legs": route["legs"],
            "grant_id": auth.grant_id, "action_sha256": sha256_json(action),
        }
        message_id = sha256_json(payload)
        state["outbox"][intent.intent_id] = {
            "message_id": message_id, "payload": payload, "status": "PENDING",
        }
    return _route_result(route, "ADMISSION_COMMITTED" if chosen else "SKIP_COMMITTED")


def _dispatch(state, d, now):
    r = state["routes"][d["intent_id"]]
    box = state["outbox"].get(d["intent_id"])
    if box is None:
        return {"status": "DENIED", "reason": "NO_ADMITTED_ROUTE"}
    if box["message_id"] in state["sink"]:
        return _route_result(r, "EXISTING_SHADOW_PUBLICATION")
    if r["revision"] != d["expected_revision"]:
        return {"status": "DENIED", "reason": "STALE_ROUTE_REVISION"}
    auth = _authorize(state, r["action"], r["grant"], now)
    reasons = []
    if auth.status != "AUTHORIZED":
        reasons.append(auth.reason_code)
    if r["terminal"] or r["cancel_observed"] or r["reject_observed"]:
        reasons.append("ROUTE_NO_LONGER_OPEN")
    if state["halted"]:
        reasons.append("INTEGRITY_HALT")
    action = r["action"]
    a = state["accounts"][r["account_id"]]
    if (sha256_json(a) != action["accounts"][r["account_id"]]
            or sha256_json(state["portfolio"]) != action["portfolio"]
            or sha256_json(state["policy"]) != action["policy"]
            or sha256_json(state["authority"]) != action["authority"]):
        reasons.append("DISPATCH_BINDINGS_CHANGED")
    intent = Intent.model_validate(r["intent"])
    # Remove this route's commitment only from the *assessment view*, never storage.
    # The transaction still holds its entire reservation until publication finishes.
    view = data(state)
    view["routes"].pop(intent.intent_id)
    c = _assess(view, intent, r["account_id"], now, _usage(view))
    reasons.extend(c["reasons"])
    reasons.extend(_active_source_blocks(state, now, _usage(state)))
    ps = PortfolioSnapshot.model_validate(state["portfolio"])
    if not _fresh(ps.at, ps.valid_until, now, state["policy"]["max_source_age_seconds"]):
        reasons.append("PORTFOLIO_EVIDENCE_STALE")
    if reasons:
        box["status"] = "BLOCKED"
        box["reasons"] = sorted(set(reasons))
        return {"status": "DISPATCH_BLOCKED", "reason": "PRECONDITIONS_CHANGED",
                "reasons": box["reasons"]}
    state["sink"][box["message_id"]] = data(box["payload"])
    box["status"] = "PUBLISHED_UNCONFIRMED"
    r["published"] = True
    r["published_at"] = now.isoformat()
    r["revision"] += 1
    return _route_result(r, "SHADOW_PUBLICATION_COMMITTED")


def _conflict(state, r, reason, observations=()):
    if reason in r["conflicts"]:
        return
    r["conflicts"].append(reason)
    r["unknown"] = True
    # Retain an explicit conservative bound for disputed additional opening fills.
    for e in observations:
        if e["role"] == "open" and e["leg_id"] in r["legs"]:
            leg = r["legs"][e["leg_id"]]
            r["disputed_risk"] += e["lots"] * leg["unit_risk"]
            r["disputed_margin"] += e["lots"] * leg["unit_margin"]
    key = r["intent"]["intent_id"] + ":" + reason
    if key not in state["halted"]:
        state["halted"].append(key)


def _observe(state, d, now):
    r = state["routes"][d["intent_id"]]
    if r["account_id"] is None:
        return {"status": "DENIED", "reason": "NO_ADMITTED_ROUTE"}
    obs = Observation.model_validate(d["observation"])
    payload = data(obs)
    fingerprint = sha256_json(payload)
    if obs.event_id in r["seen"]:
        if r["seen"][obs.event_id] == fingerprint:
            return _route_result(r, "DUPLICATE_OBSERVATION")
        _conflict(state, r, "EVENT_ID_CONFLICT:" + obs.event_id, payload["executions"])
        r["revision"] += 1
        return _route_result(r, "CONFLICT_RETAINED")
    if r["revision"] != d["expected_revision"]:
        return {"status": "DENIED", "reason": "STALE_ROUTE_REVISION"}
    if obs.at > now:
        return {"status": "DENIED", "reason": "FUTURE_EXECUTION_EVENT"}
    if (obs.kind in ("ack", "unknown", "cancel", "reject")
            and (obs.source_sequence < r["max_source_sequence"] or obs.at < clock(r["max_event_at"]))):
        return {"status": "DENIED", "reason": "STALE_EXECUTION_CONTROL_EVENT"}
    r["seen"][obs.event_id] = fingerprint
    seq = str(obs.source_sequence)
    if seq in r["sequences"] and r["sequences"][seq] != fingerprint:
        _conflict(state, r, "SOURCE_SEQUENCE_CONFLICT:" + seq)
    r["sequences"][seq] = fingerprint
    previous_sequence = r["max_source_sequence"]
    previous_at = clock(r["max_event_at"])
    r["max_source_sequence"] = max(previous_sequence, obs.source_sequence)
    r["max_event_at"] = max(previous_at, obs.at).isoformat()
    for execution in payload["executions"]:
        eid, leg_id = execution["execution_id"], execution["leg_id"]
        if leg_id not in r["legs"]:
            _conflict(state, r, "UNKNOWN_LEG:" + leg_id)
            continue
        global_id = r["account_id"] + ":" + eid
        known = state["execution_owners"].get(global_id)
        if known is not None and known != r["intent"]["intent_id"]:
            _conflict(state, r, "EXECUTION_SCOPE_CONFLICT:" + eid, (execution,))
            continue
        previous = r["executions"].get(eid)
        if previous is not None:
            if previous != execution:
                _conflict(state, r, "EXECUTION_ID_CONFLICT:" + eid, (execution,))
            continue
        if r["terminal"] and execution["role"] == "open":
            _conflict(state, r, "LATE_EXECUTION_AFTER_TERMINAL:" + eid)
            r["terminal"] = None
        r["executions"][eid] = execution
        r["execution_clocks"][eid] = {"event_at": obs.at.isoformat(),
                                      "observed_at": now.isoformat(), "source_event_id": obs.event_id}
        state["execution_owners"][global_id] = r["intent"]["intent_id"]
        if not r["published"]:
            _conflict(state, r, "EXECUTION_WITHOUT_PUBLICATION")
    for leg_id, leg in r["legs"].items():
        opened = sum(e["lots"] for e in r["executions"].values()
                     if e["leg_id"] == leg_id and e["role"] == "open")
        closed = sum(e["lots"] for e in r["executions"].values()
                     if e["leg_id"] == leg_id and e["role"] == "close")
        if opened > leg["quantity_lots"]:
            _conflict(state, r, "OVERFILL:" + leg_id)
        if closed > opened:
            _conflict(state, r, "CLOSE_EXCEEDS_OPEN:" + leg_id)
    if obs.kind == "ack":
        if not r["ack"]:
            r["ack_clock"] = {"event_at": obs.at.isoformat(), "observed_at": now.isoformat(),
                              "source_event_id": obs.event_id}
        r["ack"] = True
        if not r["conflicts"]:
            r["unknown"] = False
    elif obs.kind == "unknown":
        r["unknown"] = True
    elif obs.kind == "cancel":
        r["cancel_observed"] = True
    elif obs.kind == "reject":
        r["reject_observed"] = True
    elif obs.kind == "reconcile":
        supplied = {e["execution_id"]: e for e in payload["executions"]}
        missing = supplied != r["executions"]
        stale = obs.source_sequence < previous_sequence or obs.at < previous_at
        incomplete = not obs.coverage_complete or missing or stale or bool(r["conflicts"])
        opened_by_leg = {key: sum(e["lots"] for e in r["executions"].values()
                                  if e["leg_id"] == key and e["role"] == "open")
                         for key in r["legs"]}
        if obs.terminal == "completed" and any(
            opened_by_leg[key] != leg["quantity_lots"] for key, leg in r["legs"].items()
        ):
            incomplete = True
        if obs.terminal == "rejected" and any(opened_by_leg.values()):
            incomplete = True
        if incomplete:
            r["unknown"] = True
            r["last_reconciliation"] = {"status": "INCOMPLETE", "event_id": obs.event_id,
                                         "missing_executions": missing, "stale": stale}
        else:
            r["closed_ids"] = sorted(eid for eid, e in r["executions"].items() if e["role"] == "close")
            r["terminal"] = obs.terminal
            r["unknown"] = False
            r["last_reconciliation"] = {"status": "VERIFIED_SYNTHETIC", "event_id": obs.event_id,
                                         "source_ref": obs.evidence_ref}
    r["revision"] += 1
    return _route_result(r, "OBSERVATION_COMMITTED")


def _update_account(state, d, now):
    snapshot = AccountSnapshot.model_validate(d["snapshot"])
    old = state["accounts"].get(snapshot.account_id)
    if snapshot.at > now:
        raise RouterError("FUTURE_ACCOUNT_SNAPSHOT")
    if old:
        if snapshot.revision != old["revision"] + 1 or snapshot.at < clock(old["at"]):
            raise RouterError("STALE_ACCOUNT_REVISION")
        raw = data(snapshot)
        for field in ("opening_obligations", "venue", "currency"):
            if raw[field] != old[field]:
                raise RouterError("EXISTING_OBLIGATIONS_OR_SCOPE_IMMUTABLE")
        if raw["events"][:len(old["events"])] != old["events"]:
            raise RouterError("HISTORICAL_ACCOUNT_EVENTS_IMMUTABLE")
        old_rules = {r["version_id"]: r for r in old["rules"]}
        new_rules = {r["version_id"]: r for r in raw["rules"]}
        if any(new_rules.get(key) != value for key, value in old_rules.items()):
            raise RouterError("HISTORICAL_RULE_VERSIONS_IMMUTABLE")
        if raw["binding"]["assignments"][:len(old["binding"]["assignments"])] != old["binding"]["assignments"]:
            raise RouterError("HISTORICAL_ASSIGNMENTS_IMMUTABLE")
        for key in ("account_id", "program_id", "created_at", "initial_capital", "first_phase"):
            if raw["binding"][key] != old["binding"][key]:
                raise RouterError("ACCOUNT_GENESIS_IMMUTABLE")
    elif snapshot.revision != 1:
        raise RouterError("INITIAL_ACCOUNT_REVISION_REQUIRED")
    rule_decision(snapshot, now)  # Invalid source history cannot become current.
    state["accounts"][snapshot.account_id] = data(snapshot)
    # New stress/cost information can increase obligations; it cannot free risk.
    for r in state["routes"].values():
        if r["account_id"] == snapshot.account_id:
            quoted = _quoted(Intent.model_validate(r["intent"]), snapshot)
            for key, leg in r["legs"].items():
                leg["unit_risk"] = max(leg["unit_risk"], quoted[key]["unit_risk"])
                leg["unit_margin"] = max(leg["unit_margin"], quoted[key]["unit_margin"])
    return {"status": "UPDATED", "reason": "ACCOUNT_SOURCE_COMMITTED",
            "account_id": snapshot.account_id, "account_revision": snapshot.revision}


def _transition(original, command):
    """Deterministic reducer: original command evidence is sufficient for replay."""
    state = data(original)
    op, d = command["operation"], command["data"]
    now = clock(command["at"])
    if op == "initialize":
        if state:
            raise RouterError("ALREADY_INITIALIZED")
        p = DomainPolicy.model_validate(d["policy"])
        authority = TrustPolicyV1.model_validate_json(canonical_json(d["authority"]))
        if authority.trust_domain != "SYNTHETIC_ONLY":
            raise RouterError("ONLY_SYNTHETIC_SHADOW_AUTHORITY_SUPPORTED")
        state = {
            "schema": SCHEMA, "runtime": d["runtime"], "revision": 0,
            "epoch": 0, "owner": None, "last_at": now.isoformat(),
            "policy": data(p), "authority": data(authority), "authority_revision": 1,
            "portfolio": None, "accounts": {}, "routes": {}, "grant_uses": {},
            "outbox": {}, "sink": {}, "execution_owners": {}, "halted": [],
        }
        return state, {"status": "CREATED", "reason": "SYNTHETIC_SHADOW_ONLY"}
    if now < clock(state["last_at"]):
        return state, {"status": "DENIED", "reason": "STALE_WRITER_CLOCK"}
    if op == "claim":
        if type(d["expected_epoch"]) is not int or d["expected_epoch"] != state["epoch"]:
            return state, {"status": "DENIED", "reason": "STALE_OWNER_EPOCH"}
        if not isinstance(d["owner"], str) or not d["owner"]:
            raise RouterError("OWNER_ID_REQUIRED")
        state["epoch"] += 1
        state["owner"] = d["owner"]
        result = {"status": "CLAIMED", "epoch": state["epoch"], "owner": d["owner"]}
    else:
        if (type(d.get("epoch")) is not int or d["epoch"] != state["epoch"]
                or state["epoch"] == 0):
            return state, {"status": "DENIED", "reason": "STALE_OWNER_FENCE"}
        try:
            if op == "account":
                result = _update_account(state, d, now)
            elif op == "portfolio":
                ps = PortfolioSnapshot.model_validate(d["snapshot"])
                old = state["portfolio"]
                expected = old["revision"] + 1 if old else 1
                if ps.revision != expected or ps.at > now:
                    raise RouterError("STALE_PORTFOLIO_REVISION")
                state["portfolio"] = data(ps)
                result = {"status": "UPDATED", "reason": "PORTFOLIO_SOURCE_COMMITTED"}
            elif op == "policy":
                p = DomainPolicy.model_validate(d["policy"])
                if p.revision != state["policy"]["revision"] + 1:
                    raise RouterError("STALE_POLICY_REVISION")
                if any(getattr(p, k) != state["policy"][k]
                       for k in ("domain_id", "currency", "units_per_currency", "allocation_policy")):
                    raise RouterError("RISK_DOMAIN_OR_RANKING_IMMUTABLE")
                state["policy"] = data(p)
                result = {"status": "UPDATED", "reason": "RISK_POLICY_COMMITTED"}
            elif op == "authority":
                a = TrustPolicyV1.model_validate_json(canonical_json(d["policy"]))
                if a.trust_domain != "SYNTHETIC_ONLY" or d["expected_revision"] != state["authority_revision"]:
                    raise RouterError("AUTHORITY_REVISION_OR_DOMAIN_INVALID")
                if not set(state["authority"]["revoked_grant_ids"]) <= set(a.revoked_grant_ids):
                    raise RouterError("REVOCATION_CANNOT_BE_UNDONE")
                state["authority"] = data(a)
                state["authority_revision"] += 1
                result = {"status": "UPDATED", "reason": "AUTHORITY_COMMITTED"}
            elif op == "admit":
                result = _admit(state, d, now)
            elif op == "publish":
                result = _dispatch(state, d, now)
            elif op == "confirm_publication":
                r = state["routes"][d["intent_id"]]
                box = state["outbox"][d["intent_id"]]
                if box["message_id"] not in state["sink"]:
                    raise RouterError("PUBLICATION_NOT_VISIBLE")
                box["status"] = "DELIVERED"
                result = _route_result(r, "OUTBOX_DELIVERY_CONFIRMED")
            elif op == "observe":
                result = _observe(state, d, now)
            else:
                raise RouterError("UNSUPPORTED_OPERATION")
            _usage(state)
        except (RouterError, RuleError, ValidationError, KeyError) as exc:
            state = data(original)
            result = {"status": "DENIED", "reason": str(exc).split("\n", 1)[0],
                      "error_type": type(exc).__name__}
    state["revision"] += 1
    state["last_at"] = now.isoformat()
    return state, result


class ShadowRouter:
    """Public API. No callback, URL, broker, exchange client or credential argument."""

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise RouterError("ROUTER_STORE_MISSING")

    @classmethod
    def create(cls, path: str | Path, policy: DomainPolicy, authority: TrustPolicyV1,
               *, now: datetime):
        path = Path(path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        con = sqlite3.connect(path, isolation_level=None)
        try:
            # SQLite 3.45.3 has the upstream WAL-reset race. Rollback mode
            # avoids that code path without changing the installed runtime.
            assert con.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
            con.execute("PRAGMA synchronous=EXTRA")
            con.executescript("""
                CREATE TABLE projection(id INTEGER PRIMARY KEY CHECK(id=1),
                    body TEXT NOT NULL, sha256 TEXT NOT NULL);
                CREATE TABLE journal(seq INTEGER PRIMARY KEY, command TEXT NOT NULL,
                    result TEXT NOT NULL, state_sha256 TEXT NOT NULL,
                    previous_sha256 TEXT NOT NULL, record_sha256 TEXT NOT NULL);
                PRAGMA user_version=1;
            """)
            con.execute("INSERT INTO projection VALUES(1,?,?)", ("{}", sha256_json({})))
        finally:
            con.close()
        router = cls(path)
        router._submit("initialize", {"policy": data(policy), "authority": data(authority),
                                      "runtime": runtime_identity()}, now=now)
        return router

    def _connect(self):
        con = sqlite3.connect(self.path, timeout=20, isolation_level=None)
        con.execute("PRAGMA synchronous=EXTRA")
        con.execute("PRAGMA busy_timeout=20000")
        if con.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
            con.close()
            raise RouterError("JOURNAL_MODE_UNQUALIFIED")
        if con.execute("PRAGMA user_version").fetchone()[0] != SCHEMA:
            con.close()
            raise RouterError("SCHEMA_VERSION_UNSUPPORTED")
        return con

    @staticmethod
    def _state(con):
        row = con.execute("SELECT body,sha256 FROM projection WHERE id=1").fetchone()
        if row is None:
            raise RouterError("PROJECTION_MISSING")
        state = json.loads(row[0])
        if sha256_json(state) != row[1]:
            raise RouterError("PROJECTION_HASH_MISMATCH")
        return state

    def _submit(self, operation, payload, *, now, fault=None):
        if fault is not None and fault not in FAULTS:
            raise RouterError("UNKNOWN_FAULT_POINT")
        command = {"operation": operation, "at": clock(now).isoformat(), "data": data(payload)}
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            state = self._state(con)
            if state and state["runtime"] != runtime_identity():
                raise RouterError("RUNTIME_DRIFT_REQUIRES_ORIGINAL_IMPLEMENTATION")
            new, result = _transition(state, command)
            tail = con.execute("SELECT seq,record_sha256 FROM journal ORDER BY seq DESC LIMIT 1").fetchone()
            seq, previous = (tail[0] + 1, tail[1]) if tail else (1, "0" * 64)
            record = {"seq": seq, "command": command, "result": result,
                      "state_sha256": sha256_json(new), "previous_sha256": previous}
            con.execute("INSERT INTO journal VALUES(?,?,?,?,?,?)", (
                seq, canonical_json(command).decode(), canonical_json(result).decode(),
                record["state_sha256"], previous, sha256_json(record),
            ))
            con.execute("UPDATE projection SET body=?,sha256=? WHERE id=1",
                        (canonical_json(new).decode(), record["state_sha256"]))
            if fault == operation + ":before_commit":
                os._exit(91)
            con.execute("COMMIT")
            if fault == operation + ":after_commit":
                os._exit(92)
            return result
        except BaseException:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    def snapshot(self):
        con = self._connect()
        try:
            state = self._state(con)
            return {**state, "usage": _usage(state)}
        finally:
            con.close()

    def claim(self, owner, expected_epoch, *, now):
        return self._submit("claim", {"owner": owner, "expected_epoch": expected_epoch}, now=now)

    def update_account(self, snapshot, epoch, *, now):
        return self._submit("account", {"snapshot": data(snapshot), "epoch": epoch}, now=now)

    def update_portfolio(self, snapshot, epoch, *, now):
        return self._submit("portfolio", {"snapshot": data(snapshot), "epoch": epoch}, now=now)

    def update_policy(self, policy, epoch, *, now):
        return self._submit("policy", {"policy": data(policy), "epoch": epoch}, now=now)

    def update_authority(self, policy, expected_revision, epoch, *, now):
        return self._submit("authority", {"policy": data(policy), "expected_revision": expected_revision,
                                          "epoch": epoch}, now=now)

    def prepare(self, intent: Intent):
        state = self.snapshot()
        if state["runtime"] != runtime_identity():
            raise RouterError("RUNTIME_DRIFT_REQUIRES_ORIGINAL_IMPLEMENTATION")
        return action_for(state, Intent.model_validate(intent))

    def admit(self, action, grant: SignedGrantV1 | dict, epoch, *, now, fault=None):
        return self._submit("admit", {"action": data(action), "grant": data(grant), "epoch": epoch},
                            now=now, fault=fault)

    def publish(self, intent_id, expected_revision, epoch, *, now, fault=None):
        return self._submit("publish", {"intent_id": intent_id, "expected_revision": expected_revision,
                                       "epoch": epoch}, now=now, fault=fault)

    def confirm_publication(self, intent_id, epoch, *, now):
        return self._submit("confirm_publication", {"intent_id": intent_id, "epoch": epoch}, now=now)

    def observe(self, intent_id, observation, expected_revision, epoch, *, now):
        return self._submit("observe", {"intent_id": intent_id, "observation": data(observation),
                                       "expected_revision": expected_revision, "epoch": epoch}, now=now)

    def recover(self, *, repair_projection=False):
        """Replay original commands; never expire reservations or republish messages.

        Repair holds the same SQLite writer lock. It restores only the derived
        projection and cannot erase or reinterpret a conflicting journal.
        """
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE" if repair_projection else "BEGIN")
            state, previous = {}, "0" * 64
            rows = con.execute("SELECT * FROM journal ORDER BY seq").fetchall()
            for expected_seq, row in enumerate(rows, 1):
                seq, cmd, result, state_hash, prev_hash, record_hash = row
                command, saved_result = json.loads(cmd), json.loads(result)
                record = {"seq": seq, "command": command, "result": saved_result,
                          "state_sha256": state_hash, "previous_sha256": prev_hash}
                if seq != expected_seq or prev_hash != previous or sha256_json(record) != record_hash:
                    raise RouterError("JOURNAL_CHAIN_INVALID")
                state, replay_result = _transition(state, command)
                if replay_result != saved_result or sha256_json(state) != state_hash:
                    raise RouterError("JOURNAL_REPLAY_MISMATCH")
                previous = record_hash
            if not state or state["runtime"] != runtime_identity():
                raise RouterError("RUNTIME_DRIFT_REQUIRES_ORIGINAL_IMPLEMENTATION")
            if repair_projection:
                con.execute("UPDATE projection SET body=?,sha256=? WHERE id=1",
                            (canonical_json(state).decode(), sha256_json(state)))
            elif self._state(con) != state:
                raise RouterError("PROJECTION_REPLAY_MISMATCH")
            con.execute("COMMIT")
            return {"status": "RECOVERED", "journal_records": len(rows),
                    "state_sha256": sha256_json(state), "usage": _usage(state),
                    "unresolved_outbox": sorted(key for key, value in state["outbox"].items()
                                                if value["status"] != "DELIVERED")}
        finally:
            if con.in_transaction:
                con.execute("ROLLBACK")
            con.close()

    def audit_events(self, intent_id):
        """Read-only ATS-3 identity bridge. Shadow events are never real fills."""
        state = self.snapshot()
        r = state["routes"][intent_id]
        if r["account_id"] is None:
            return []
        at = clock(r["admitted_at"])
        box = state["outbox"][intent_id]
        events = []
        for key, leg in r["legs"].items():
            order_id = box["payload"]["client_order_ids"][key]
            common = {"source": "ats6-synthetic-shadow", "environment": "shadow",
                      "account": r["account_id"], "strategy": r["intent"]["sleeve"]["strategy_id"],
                      "instrument": leg["instrument"], "event_at": at, "available_at": at,
                      "observed_at": at, "execution_id": order_id}
            qty = Decimal(leg["lot_size"]) * leg["quantity_lots"]
            events.append(AuditEvent(event_id=intent_id + ":" + key + ":intent", kind="intent",
                                     payload={"quantity": str(qty)}, **common))
            events.append(AuditEvent(event_id=intent_id + ":" + key + ":route", kind="route",
                                     payload={"effect": "LOCAL_EVIDENCE_ONLY"}, **common))
            if r["published"]:
                published_at = clock(r["published_at"])
                publication = {**common, "event_at": published_at,
                               "available_at": published_at, "observed_at": published_at}
                events.append(AuditEvent(event_id=intent_id + ":" + key + ":order", kind="order",
                                         payload={"quantity": str(qty)}, **publication))
            if r["ack"]:
                ack = r["ack_clock"]
                acknowledgment = {**common, "event_at": clock(ack["event_at"]),
                                  "available_at": clock(ack["observed_at"]),
                                  "observed_at": clock(ack["observed_at"])}
                events.append(AuditEvent(event_id=intent_id + ":" + key + ":ack", kind="ack",
                                         payload={}, **acknowledgment))
            for eid, e in r["executions"].items():
                if e["leg_id"] != key:
                    continue
                clocks = r["execution_clocks"][eid]
                fill_common = {**common, "event_at": clock(clocks["event_at"]),
                               "available_at": clock(clocks["observed_at"]),
                               "observed_at": clock(clocks["observed_at"])}
                side = leg["side"] if e["role"] == "open" else ("sell" if leg["side"] == "buy" else "buy")
                if e["role"] == "close":
                    # The closing fill is evidence; an absent source order/ACK
                    # stays absent and remains an ATS-3 integrity gap.
                    fill_common["execution_id"] = order_id + ":close:" + eid
                events.append(AuditEvent(event_id=eid, kind="fill", payload={
                    "side": side, "quantity": str(Decimal(leg["lot_size"]) * e["lots"]),
                    "price": e["price"], "hypothetical": True,
                }, **fill_common))
                events.append(AuditEvent(event_id=eid + ":fee", kind="commission", payload={
                    "amount": str(Decimal(e["fee_units"]) / state["policy"]["units_per_currency"]),
                    "fill_event_id": eid, "hypothetical": True,
                }, **fill_common))
        return events
