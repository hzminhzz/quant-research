"""Fixed synthetic ATS-6 evidence and explicit test issuer. Never imported by runtime."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.account_rules import (
    AccountBinding,
    AccountEvent,
    ObservationCoverage,
    PhaseRule,
    RuleSource,
    RuleVersion,
    TermAssignment,
)
from src.portfolio_evidence import SleeveIdentity
from src.research_control.action_authorization import (
    TrustedIssuerV1,
    TrustPolicyV1,
    build_scope,
    issue_synthetic_grant,
    public_key_b64,
)
from src.shadow_contracts import (
    AccountSnapshot,
    DomainPolicy,
    Intent,
    Leg,
    Obligation,
    PortfolioSnapshot,
    data,
)
from src.shadow_router import ShadowRouter

START = datetime(2026, 10, 17, 3, 30, tzinfo=UTC)
END = START + timedelta(hours=1)
SYMBOL = "fixture:perpetual:ALPHAUSD"
SECOND = "fixture:perpetual:BETAUSD"


def sleeve(name="alpha"):
    return SleeveIdentity(name, "synthetic-v1", name + "-spec", "fixture-code",
                          "fixed-engineering-events", "declared-costs", "UTC",
                          "ATS6_ENGINEERING_ONLY")


def intent(name, lots=6, *, family="trend", symbols=(SYMBOL,), stress=100):
    return Intent(
        intent_id=name, sleeve=sleeve(), family=family, source_ref="fixture://intent/" + name,
        created_at=START, valid_until=END,
        legs=tuple(Leg(leg_id="leg-" + str(i), instrument=symbol, side="buy",
                       quantity_lots=lots, lot_size="0.01", stress_units_per_lot=stress,
                       margin_units_per_lot=20) for i, symbol in enumerate(symbols)),
    )


def rules():
    return RuleVersion(
        "synthetic-v1", "fixture-program",
        RuleSource("SYNTHETIC-AGREEMENT-NOT-REAL", "fixture://ats6/agreement",
                   START, "account_agreement"),
        (PhaseRule("evaluation", "evaluation", Decimal(".1"), 1),),
        "UTC", 0, Decimal(".05"), Decimal(".10"), mark_max_age_seconds=60,
    )


def account(name, cap=800, *, cost=0, obligations=()):
    rule = rules()
    binding = AccountBinding(
        name, rule.program_id, START, Decimal(100000), "evaluation",
        (TermAssignment(START, rule.version_id, "SYNTHETIC-ACCOUNT-ASSIGNMENT"),),
        (ObservationCoverage(START, END, True, True),), agreement_verified=True,
    )
    return AccountSnapshot(
        account_id=name, revision=1, at=START, valid_until=END,
        source_ref="fixture://account/" + name, venue="fixture", currency="USD",
        permitted_instruments=(SYMBOL, SECOND), risk_limit_units=cap,
        margin_capacity_units=100000, margin_at=START, marks_complete=True,
        lifecycle="active", lifecycle_priority=0, stress_multiplier_bps=10000,
        cost_units_per_lot=cost, cost_evidence_ref="fixture://cost/" + name,
        binding=data(binding), rules=(data(rule),),
        events=(data(AccountEvent("genesis", START, 1, "observation")),),
        opening_obligations=tuple(obligations),
    )


def create_fixture(path: Path, *, shared=1000, caps=(800, 800), costs=(0, 0),
                   policy_name="cushion", obligations=()):
    private = Ed25519PrivateKey.generate()
    trust = TrustPolicyV1(
        schema_version=1, trust_domain="SYNTHETIC_ONLY", max_grant_seconds=3600,
        issuers=(TrustedIssuerV1(issuer_id="ATS6-test-issuer",
                                public_key_b64=public_key_b64(private), enabled=True),),
    )
    policy = DomainPolicy(
        domain_id="shadow:ats6-fixture", revision=1, currency="USD", units_per_currency=100,
        shared_limit_units=shared, family_limit_units=shared, max_source_age_seconds=3600,
        allocation_policy=policy_name, evidence_ref="fixture://frozen-policy-v1",
    )
    router = ShadowRouter.create(path, policy, trust, now=START)
    token = router.claim("fixture-owner", 0, now=START)["epoch"]
    for i, cap in enumerate(caps):
        result = router.update_account(
            account("shadow:" + chr(97 + i), cap, cost=costs[i] if i < len(costs) else 0,
                    obligations=obligations if i == 0 else ()), token, now=START,
        )
        assert result["status"] == "UPDATED", result
    ps = PortfolioSnapshot(revision=1, at=START, valid_until=END,
                           evidence_ref="fixture://ats4-identities", sleeves=(sleeve(),))
    assert router.update_portfolio(ps, token, now=START)["status"] == "UPDATED"
    return router, private, token


def signed(router, private, item):
    action = router.prepare(item)
    scope = build_scope(action, window_start=item.created_at, window_end=item.valid_until,
                        selection_sha256=action["portfolio"])
    grant = issue_synthetic_grant(
        scope, issuer_id="ATS6-test-issuer", private_key=private,
        issued_at=START, expires_at=END,
        grant_id=str(uuid5(NAMESPACE_URL, scope.action_sha256)), shadow=True,
    )
    return action, data(grant)


def admitted(router, private, token, item, *, now=START):
    action, grant = signed(router, private, item)
    result = router.admit(action, grant, token, now=now)
    assert result["status"] == "ADMITTED", result
    return action, grant


def publish(router, item_id, token, *, now=START):
    rev = router.snapshot()["routes"][item_id]["revision"]
    result = router.publish(item_id, rev, token, now=now)
    assert result["status"] == "SHADOW_DISPATCHED", result
    return result


def observe(router, item_id, token, seq, kind, *, executions=(), terminal=None,
            complete=False, now=None, at=None, event_id=None):
    now = now or START + timedelta(seconds=seq)
    at = at or now
    raw = {
        "event_id": event_id or item_id + "-event-" + str(seq),
        "source_sequence": seq, "at": at.isoformat(), "kind": kind,
        "evidence_ref": "fixture://source/" + item_id + "/" + str(seq),
        "executions": list(executions), "terminal": terminal, "coverage_complete": complete,
    }
    rev = router.snapshot()["routes"][item_id]["revision"]
    return router.observe(item_id, raw, rev, token, now=now)


def fill(eid, lots, *, leg="leg-0", role="open", price="100.00", fee=0):
    return {"execution_id": eid, "leg_id": leg, "role": role, "lots": lots,
            "price": price, "fee_units": fee}


def opening_unknown(risk=400):
    return Obligation(obligation_id="prior-unknown", kind="unknown", family="legacy",
                      risk_units=risk, margin_units=risk // 5,
                      evidence_ref="fixture://pre-existing-unresolved-order")


def amended_account(raw, *, at=None, risk_limit=None, unknown=False):
    at = at or START + timedelta(seconds=1)
    s = AccountSnapshot.model_validate(raw)
    r = rules()
    new = replace(r, version_id="synthetic-v2",
                  unknown_rules=frozenset({"trading_permissions"}) if unknown else frozenset())
    b = data(s.binding)
    b["assignments"].append(data(TermAssignment(at, new.version_id, "SYNTHETIC-AMENDMENT")))
    return s.model_copy(update={
        "revision": s.revision + 1, "at": at,
        "rules": s.rules + (data(new),), "binding": b,
        "risk_limit_units": s.risk_limit_units if risk_limit is None else risk_limit,
    })
