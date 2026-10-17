"""Typed, effect-free ATS-6 inputs. All money risk is integer currency quanta.

These contracts describe synthetic shadow decisions, never account authority.
ATS-4 owns sleeve identity; ATS-5 owns rule interpretation; ATS-2 owns grants.
"""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    model_validator,
)

from src.account_rules import (
    AccountBinding,
    AccountEvent,
    ObservationCoverage,
    TermAssignment,
    money,
    replay,
    rule_from_dict,
    timestamp,
)
from src.portfolio_evidence import SleeveIdentity
from src.research_control.action_authorization import canonical_json, sha256_json

MAX_UNITS = 2**62 - 1


class RouterError(ValueError):
    """Invalid input or corrupted durable evidence; no implicit repair."""


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Leg(Model):
    leg_id: StrictStr = Field(min_length=1, max_length=80)
    instrument: StrictStr = Field(pattern=r"^[^: ]+:[^: ]+:[^: ]+$")
    side: Literal["buy", "sell"]
    quantity_lots: StrictInt = Field(ge=1, le=10**9)
    lot_size: StrictStr
    stress_units_per_lot: StrictInt = Field(ge=1, le=10**12)
    margin_units_per_lot: StrictInt = Field(ge=1, le=10**12)

    @model_validator(mode="after")
    def numbers(self):
        if money(self.lot_size) <= 0:
            raise RouterError("LOT_SIZE_INVALID")
        if max(self.stress_units_per_lot, self.margin_units_per_lot) * self.quantity_lots > MAX_UNITS:
            raise RouterError("RISK_RANGE_EXCEEDED")
        return self


class Intent(Model):
    intent_id: StrictStr = Field(min_length=1, max_length=120)
    sleeve: SleeveIdentity
    family: StrictStr = Field(min_length=1, max_length=100)
    source_ref: StrictStr = Field(min_length=1)
    created_at: AwareDatetime
    valid_until: AwareDatetime
    legs: tuple[Leg, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def identities(self):
        if self.valid_until <= self.created_at:
            raise RouterError("INTENT_WINDOW_INVALID")
        if len({leg.leg_id for leg in self.legs}) != len(self.legs):
            raise RouterError("DUPLICATE_LEG_ID")
        return self


class Obligation(Model):
    obligation_id: StrictStr = Field(min_length=1)
    kind: Literal["position", "unknown"]
    family: StrictStr = Field(min_length=1)
    risk_units: StrictInt = Field(ge=1, le=MAX_UNITS)
    margin_units: StrictInt = Field(ge=0, le=MAX_UNITS)
    evidence_ref: StrictStr = Field(min_length=1)


class AccountSnapshot(Model):
    account_id: StrictStr = Field(pattern=r"^shadow:[A-Za-z0-9_.-]+$")
    revision: StrictInt = Field(ge=1)
    at: AwareDatetime
    valid_until: AwareDatetime
    source_ref: StrictStr = Field(min_length=1)
    venue: StrictStr = Field(min_length=1)
    currency: StrictStr = Field(min_length=1)
    permitted_instruments: tuple[StrictStr, ...]
    risk_limit_units: StrictInt = Field(ge=0, le=MAX_UNITS)
    margin_capacity_units: StrictInt | None = Field(default=None, ge=0, le=MAX_UNITS)
    margin_at: AwareDatetime | None = None
    marks_complete: StrictBool = False
    lifecycle: Literal["active", "payout_pending", "suspended", "closed"] = "suspended"
    lifecycle_priority: StrictInt = Field(ge=0, le=100)
    stress_multiplier_bps: StrictInt = Field(ge=10000, le=1000000)
    cost_units_per_lot: StrictInt = Field(ge=0, le=10**12)
    cost_evidence_ref: StrictStr = Field(min_length=1)
    binding: dict[str, Any]
    rules: tuple[dict[str, Any], ...] = Field(min_length=1)
    events: tuple[dict[str, Any], ...] = Field(min_length=1)
    opening_obligations: tuple[Obligation, ...] = ()

    @model_validator(mode="after")
    def interval(self):
        if self.valid_until <= self.at:
            raise RouterError("ACCOUNT_WINDOW_INVALID")
        if self.binding.get("account_id") != self.account_id:
            raise RouterError("ACCOUNT_BINDING_MISMATCH")
        if len({o.obligation_id for o in self.opening_obligations}) != len(self.opening_obligations):
            raise RouterError("DUPLICATE_OBLIGATION")
        return self


class PortfolioSnapshot(Model):
    revision: StrictInt = Field(ge=1)
    at: AwareDatetime
    valid_until: AwareDatetime
    evidence_ref: StrictStr = Field(min_length=1)
    sleeves: tuple[SleeveIdentity, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def interval(self):
        if self.valid_until <= self.at:
            raise RouterError("PORTFOLIO_WINDOW_INVALID")
        if len({s.strategy_id for s in self.sleeves}) != len(self.sleeves):
            raise RouterError("DUPLICATE_SLEEVE")
        return self


class DomainPolicy(Model):
    domain_id: StrictStr = Field(pattern=r"^shadow:[A-Za-z0-9_.-]+$")
    revision: StrictInt = Field(ge=1)
    currency: StrictStr = Field(min_length=1)
    units_per_currency: StrictInt = Field(ge=1, le=10**8)
    shared_limit_units: StrictInt = Field(ge=0, le=MAX_UNITS)
    family_limit_units: StrictInt = Field(ge=0, le=MAX_UNITS)
    max_source_age_seconds: StrictInt = Field(ge=1, le=3600)
    allocation_policy: Literal["cushion", "first_fit", "least_used"]
    evidence_ref: StrictStr = Field(min_length=1)


class Execution(Model):
    execution_id: StrictStr = Field(min_length=1, max_length=160)
    leg_id: StrictStr = Field(min_length=1)
    role: Literal["open", "close"]
    lots: StrictInt = Field(ge=1, le=10**9)
    price: StrictStr
    fee_units: StrictInt = Field(ge=0, le=MAX_UNITS)

    @model_validator(mode="after")
    def price_valid(self):
        if money(self.price) <= 0:
            raise RouterError("FILL_PRICE_INVALID")
        return self


class Observation(Model):
    event_id: StrictStr = Field(min_length=1, max_length=160)
    source_sequence: StrictInt = Field(ge=1)
    at: AwareDatetime
    kind: Literal["ack", "unknown", "cancel", "reject", "fill", "reconcile"]
    evidence_ref: StrictStr = Field(min_length=1)
    executions: tuple[Execution, ...] = ()
    terminal: Literal["completed", "canceled", "rejected"] | None = None
    coverage_complete: StrictBool = False

    @model_validator(mode="after")
    def semantics(self):
        if self.kind == "fill" and not self.executions:
            raise RouterError("FILL_EVIDENCE_MISSING")
        if self.kind not in ("fill", "reconcile") and self.executions:
            raise RouterError("UNEXPECTED_EXECUTIONS")
        if self.kind != "reconcile" and (self.terminal is not None or self.coverage_complete):
            raise RouterError("RECONCILIATION_REQUIRED")
        if len({e.execution_id for e in self.executions}) != len(self.executions):
            raise RouterError("DUPLICATE_EXECUTION_IN_OBSERVATION")
        return self


def plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return plain(asdict(value))
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        values = sorted(value) if isinstance(value, (set, frozenset)) else value
        return [plain(v) for v in values]
    return value


def data(value: Any) -> Any:
    """Round-trip without shared mutable references or NaN."""
    return json.loads(canonical_json(plain(value)))


def clock(value: datetime | str) -> datetime:
    item = timestamp(value) if isinstance(value, str) else value
    if item.tzinfo is None or item.utcoffset() is None:
        raise RouterError("NAIVE_CLOCK")
    return item.astimezone(UTC)


def rule_decision(snapshot: AccountSnapshot, now: datetime):
    """Delegate every account-rule transition to the existing ATS-5 evaluator."""
    b = snapshot.binding
    binding = AccountBinding(
        account_id=b["account_id"], program_id=b["program_id"],
        created_at=timestamp(b["created_at"]), initial_capital=money(b["initial_capital"]),
        first_phase=b["first_phase"],
        assignments=tuple(TermAssignment(
            timestamp(a["at"]), a["version_id"], a["applicability_reference"],
            a.get("grandfathered", False),
        ) for a in b["assignments"]),
        coverage=tuple(ObservationCoverage(
            timestamp(c["start"]), timestamp(c["end"]),
            c["events_complete"], c["marks_complete"],
        ) for c in b.get("coverage", ())),
        agreement_verified=b.get("agreement_verified", False),
    )
    rules = {r["version_id"]: rule_from_dict(r) for r in snapshot.rules}
    if len(rules) != len(snapshot.rules):
        raise RouterError("DUPLICATE_RULE_VERSION")
    if any(r.source.captured_at > now for r in rules.values()):
        raise RouterError("FUTURE_RULE_SOURCE")
    events = tuple(AccountEvent(
        e["event_id"], timestamp(e["at"]), e["sequence"], e["kind"],
        money(e.get("amount", "0")), e.get("reference"),
    ) for e in snapshot.events)
    if any(e.at > now for e in events):
        raise RouterError("FUTURE_ACCOUNT_EVENT")
    if events[-1].at < now:
        events += (AccountEvent("ats6-observation:" + now.isoformat(), now, 0, "observation"),)
    return replay(binding, rules, events).last


def action_for(state: dict, intent: Intent) -> dict:
    """Freeze source versions, not the transient availability of shared cushion."""
    action = {
        "schema_version": 1, "operation": "shadow_route",
        "session_id": state["policy"]["domain_id"], "trial_id": intent.intent_id,
        "intent": data(intent),
        "accounts": {key: sha256_json(row) for key, row in sorted(state["accounts"].items())},
        "portfolio": sha256_json(state["portfolio"]),
        "policy": sha256_json(state["policy"]),
        "authority": sha256_json(state["authority"]),
        "runtime": state["runtime"],
    }
    action["identity"] = {
        "source_sha256": sha256_json(action["accounts"]),
        "data_sha256": action["portfolio"],
        "spec_sha256": sha256_json(action["intent"]),
        "config_sha256": sha256_json({
            "policy": action["policy"], "authority": action["authority"],
            "runtime": action["runtime"],
        }),
    }
    action["contract_sha256"] = sha256_json(action)
    return action
