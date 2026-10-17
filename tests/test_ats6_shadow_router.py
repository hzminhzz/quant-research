"""Behavioral tests through the durable public ATS-6 API."""
from __future__ import annotations

import multiprocessing as mp
import sqlite3
from datetime import timedelta

import pytest

from scripts.ats6_fixtures import (
    START,
    admitted,
    amended_account,
    create_fixture,
    fill,
    intent,
    observe,
    opening_unknown,
    publish,
    signed,
)
from src.research_control.action_authorization import TrustPolicyV1, canonical_json
from src.research_control.ats3_audit import reconcile
from src.shadow_contracts import AccountSnapshot, DomainPolicy, data
from src.shadow_router import ShadowRouter


def child_admit(path, action, grant, epoch, barrier, queue, fault=None):
    barrier.wait(15)
    result = ShadowRouter(path).admit(action, grant, epoch, now=START, fault=fault)
    queue.put(result)


def child_fault(path, op, args, fault):
    router = ShadowRouter(path)
    if op == "admit":
        router.admit(*args, now=START, fault=fault)
    else:
        router.publish(*args, now=START, fault=fault)


def used(router):
    return router.snapshot()["usage"]["shared"]


def test_exact_partial_fill_cancel_late_fill_and_closed_position(tmp_path):
    r, key, epoch = create_fixture(tmp_path / "router.db", shared=1200, caps=(1200,))
    admitted(r, key, epoch, intent("trade", lots=10))
    assert used(r)["reserved"] == 1000
    publish(r, "trade", epoch)
    observe(r, "trade", epoch, 1, "ack")
    one, two, close = fill("fill-1", 4), fill("fill-2", 2), fill("close-1", 3, role="close")
    observe(r, "trade", epoch, 2, "fill", executions=(one,))
    assert (used(r)["reserved"], used(r)["recognized"]) == (600, 400)
    observe(r, "trade", epoch, 3, "cancel")
    assert used(r)["used"] == 1000
    observe(r, "trade", epoch, 4, "fill", executions=(two,))
    assert (used(r)["reserved"], used(r)["recognized"]) == (400, 600)
    observe(r, "trade", epoch, 5, "reconcile", executions=(one, two),
            terminal="canceled", complete=True)
    assert (used(r)["reserved"], used(r)["recognized"]) == (0, 600)
    observe(r, "trade", epoch, 6, "fill", executions=(close,))
    assert used(r)["recognized"] == 600  # Reduction awaits position reconciliation.
    observe(r, "trade", epoch, 7, "reconcile", executions=(one, two, close),
            terminal="canceled", complete=True)
    assert (used(r)["reserved"], used(r)["recognized"], used(r)["remaining"]) == (0, 300, 900)
    assert r.recover()["usage"] == r.snapshot()["usage"]


@pytest.mark.parametrize("lots,shared,expected", [(7, 1000, 1), (5, 1000, 2)])
def test_real_processes_reserve_account_and_domain_once(tmp_path, lots, shared, expected):
    r, key, epoch = create_fixture(tmp_path / "router.db", caps=(700, 700), shared=shared)
    inputs = [signed(r, key, intent(name, lots)) for name in ("one", "two")]
    ctx = mp.get_context("spawn")
    barrier, queue = ctx.Barrier(2), ctx.Queue()
    workers = [ctx.Process(target=child_admit, args=(str(r.path), a, g, epoch, barrier, queue))
               for a, g in inputs]
    for p in workers:
        p.start()
    for p in workers:
        p.join(25)
        assert p.exitcode == 0
    results = [queue.get(timeout=5) for _ in workers]
    assert sum(v["status"] == "ADMITTED" for v in results) == expected
    assert used(r)["used"] == expected * lots * 100
    assert all(a["used"] <= 700 for a in r.snapshot()["usage"]["accounts"].values())
    r.recover()


@pytest.mark.parametrize("fault,committed", [
    ("admit:before_commit", False), ("admit:after_commit", True),
    ("publish:before_commit", False), ("publish:after_commit", True),
])
def test_process_death_at_sqlite_commit_boundaries(tmp_path, fault, committed):
    r, key, epoch = create_fixture(tmp_path / "router.db")
    a, g = signed(r, key, intent("one"))
    op = fault.split(":")[0]
    if op == "admit":
        args = (a, g, epoch)
    else:
        assert r.admit(a, g, epoch, now=START)["status"] == "ADMITTED"
        args = ("one", 1, epoch)
    ctx = mp.get_context("spawn")
    p = ctx.Process(target=child_fault, args=(str(r.path), op, args, fault))
    p.start()
    p.join(25)
    assert p.exitcode == (92 if committed else 91)
    recovered = ShadowRouter(r.path)
    recovered.recover()
    if op == "admit":
        assert ("one" in recovered.snapshot()["routes"]) is committed
        recovered.admit(a, g, epoch, now=START)
    else:
        assert bool(recovered.snapshot()["sink"]) is committed
    recovered.publish("one", recovered.snapshot()["routes"]["one"]["revision"], epoch, now=START)
    assert used(recovered)["used"] == 600
    assert len(recovered.snapshot()["sink"]) == 1
    recovered.publish("one", 1, epoch, now=START)
    assert len(recovered.snapshot()["sink"]) == 1


def test_duplicate_intent_delivery_ack_and_lost_ack_do_not_reroute(tmp_path):
    r, key, epoch = create_fixture(tmp_path / "router.db")
    a, g = admitted(r, key, epoch, intent("one"))
    publish(r, "one", epoch)
    observe(r, "one", epoch, 1, "unknown")
    before = r.snapshot()
    restarted = ShadowRouter(r.path)
    restarted.recover()
    assert restarted.admit(a, g, epoch, now=START + timedelta(seconds=2))["reason"] == "EXISTING_DECISION"
    assert restarted.snapshot()["routes"]["one"]["account_id"] == before["routes"]["one"]["account_id"]
    assert used(restarted)["reserved"] == 600
    result = observe(restarted, "one", epoch, 3, "ack")
    assert result["status"] == "ACKNOWLEDGED"
    result = observe(restarted, "one", epoch, 3, "ack", now=START + timedelta(seconds=4),
                     at=START + timedelta(seconds=3))
    assert result["reason"] == "DUPLICATE_OBSERVATION"
    assert used(restarted)["used"] == 600


@pytest.mark.parametrize("change", ["revoke", "rule", "mark", "margin", "portfolio", "limit"])
def test_dispatch_rechecks_sources_and_authority_and_keeps_risk(tmp_path, change):
    r, key, epoch = create_fixture(tmp_path / "router.db")
    _, grant = admitted(r, key, epoch, intent("one"))
    now = START + timedelta(seconds=2)
    if change == "revoke":
        p = TrustPolicyV1.model_validate_json(canonical_json(r.snapshot()["authority"]))
        r.update_authority(p.model_copy(update={"revoked_grant_ids": (grant["grant_id"],)}),
                           1, epoch, now=now)
    elif change in ("rule", "mark", "margin"):
        raw = r.snapshot()["accounts"]["shadow:a"]
        s = amended_account(raw, at=now, unknown=change == "rule")
        if change == "mark":
            s = s.model_copy(update={"marks_complete": False})
        if change == "margin":
            s = s.model_copy(update={"margin_capacity_units": None})
        assert r.update_account(s, epoch, now=now)["status"] == "UPDATED"
    elif change == "portfolio":
        from src.shadow_contracts import PortfolioSnapshot
        p = PortfolioSnapshot.model_validate(r.snapshot()["portfolio"])
        r.update_portfolio(p.model_copy(update={"revision": 2, "at": now}), epoch, now=now)
    else:
        p = DomainPolicy.model_validate(r.snapshot()["policy"])
        r.update_policy(p.model_copy(update={"revision": 2, "shared_limit_units": 300}), epoch, now=now)
    result = r.publish("one", 1, epoch, now=now)
    assert result["status"] == "DISPATCH_BLOCKED", result
    assert not r.snapshot()["sink"]
    assert used(r)["used"] == 600
    if change == "limit":
        assert used(r)["remaining"] == -300
    r.recover()


@pytest.mark.parametrize("kind", ["marks", "margin", "coverage", "rules", "expired", "public_terms"])
def test_missing_eligibility_fails_before_ranking(tmp_path, kind):
    r, key, epoch = create_fixture(tmp_path / "router.db", caps=(800,))
    raw = r.snapshot()["accounts"]["shadow:a"]
    s = AccountSnapshot.model_validate(raw)
    updates = {"revision": 2}
    if kind == "marks":
        updates["marks_complete"] = False
    elif kind == "margin":
        updates["margin_capacity_units"] = None
    elif kind == "coverage":
        b = data(s.binding)
        b["coverage"] = []
        updates["binding"] = b
    elif kind == "rules":
        s = amended_account(raw, unknown=True)
    elif kind == "public_terms":
        b = data(s.binding)
        b["agreement_verified"] = False
        updates["binding"] = b
    elif kind == "expired":
        updates["valid_until"] = START + timedelta(seconds=1)
    s = s.model_copy(update=updates)
    now = START + timedelta(seconds=2)
    assert r.update_account(s, epoch, now=now)["status"] == "UPDATED"
    a, g = signed(r, key, intent("one"))
    result = r.admit(a, g, epoch, now=now)
    assert result["status"] == "SKIPPED"
    assert used(r)["used"] == 0
    assert r.snapshot()["routes"]["one"]["candidates"][0]["reasons"]


def test_owner_fence_rejects_all_late_mutations_without_freeing_unknown(tmp_path):
    r, key, old = create_fixture(tmp_path / "router.db")
    a, g = admitted(r, key, old, intent("one"))
    publish(r, "one", old)
    observe(r, "one", old, 1, "unknown")
    new = r.claim("replacement", old, now=START + timedelta(seconds=2))["epoch"]
    assert new > old
    result = r.admit(a, g, old, now=START + timedelta(seconds=3))
    assert result["reason"] == "STALE_OWNER_FENCE"
    assert r.confirm_publication("one", old, now=START + timedelta(seconds=3))["reason"] == "STALE_OWNER_FENCE"
    assert used(r)["unknown"] == 600
    r.recover()


def test_single_account_multileg_is_not_split_and_cross_venue_denied(tmp_path):
    r, key, epoch = create_fixture(tmp_path / "router.db", shared=2000, caps=(500, 500))
    from scripts.ats6_fixtures import SECOND, SYMBOL
    for item in (intent("multi", 3, symbols=(SYMBOL, SECOND)),
                 intent("cross", 1, symbols=(SYMBOL, "other:perpetual:BETAUSD"))):
        a, g = signed(r, key, item)
        assert r.admit(a, g, epoch, now=START)["status"] == "SKIPPED"
    assert used(r)["used"] == 0
    assert "CROSS_VENUE_ATOMICITY_UNQUALIFIED" in r.snapshot()["routes"]["cross"]["reasons"]


def test_prior_unknown_exposure_survives_restart_and_snapshot_update(tmp_path):
    r, key, epoch = create_fixture(tmp_path / "router.db", obligations=(opening_unknown(700),))
    assert used(r)["unknown"] == 700
    r = ShadowRouter(r.path)
    r.recover()
    a, g = signed(r, key, intent("one", 4))
    assert r.admit(a, g, epoch, now=START)["status"] == "SKIPPED"
    s = AccountSnapshot.model_validate(r.snapshot()["accounts"]["shadow:a"])
    s = s.model_copy(update={"revision": 2, "opening_obligations": ()})
    assert r.update_account(s, epoch, now=START)["status"] == "DENIED"
    assert used(r)["used"] == 700


def test_reordered_fills_and_duplicate_execution_conserve_quantity(tmp_path):
    r, key, epoch = create_fixture(tmp_path / "router.db")
    admitted(r, key, epoch, intent("one"))
    publish(r, "one", epoch)
    f1, f2 = fill("one-fill", 2), fill("two-fill", 1)
    observe(r, "one", epoch, 3, "fill", executions=(f2,))
    observe(r, "one", epoch, 2, "fill", executions=(f1,),
            now=START + timedelta(seconds=4), at=START + timedelta(seconds=2))
    observe(r, "one", epoch, 4, "fill", executions=(f1,), now=START + timedelta(seconds=5))
    assert (used(r)["reserved"], used(r)["recognized"]) == (300, 300)
    observe(r, "one", epoch, 5, "reconcile", executions=(f1, f2),
            terminal="canceled", complete=True, now=START + timedelta(seconds=6))
    assert used(r)["used"] == 300
    r.recover()


def test_conflicting_evidence_is_retained_and_blocks_new_exposure(tmp_path):
    r, key, epoch = create_fixture(tmp_path / "router.db", shared=2000, caps=(2000,))
    admitted(r, key, epoch, intent("one"))
    publish(r, "one", epoch)
    observe(r, "one", epoch, 1, "fill", executions=(fill("fill-1", 2),))
    observe(r, "one", epoch, 2, "fill", executions=(fill("fill-1", 3),))
    assert r.snapshot()["halted"]
    assert (used(r)["recognized"], used(r)["reserved"]) == (200, 700)
    a, g = signed(r, key, intent("two", 1))
    assert r.admit(a, g, epoch, now=START + timedelta(seconds=3))["status"] == "SKIPPED"
    r.recover()


def test_incomplete_cancel_certificate_never_releases_pending(tmp_path):
    r, key, epoch = create_fixture(tmp_path / "router.db")
    admitted(r, key, epoch, intent("one"))
    publish(r, "one", epoch)
    f = fill("fill-1", 2)
    observe(r, "one", epoch, 1, "fill", executions=(f,))
    result = observe(r, "one", epoch, 2, "reconcile", terminal="canceled", complete=True)
    assert result["status"] == "UNKNOWN"
    assert used(r)["used"] == 600


def test_projection_rebuild_and_corrupted_journal_refusal(tmp_path):
    r, key, epoch = create_fixture(tmp_path / "router.db")
    admitted(r, key, epoch, intent("one"))
    expected = used(r)
    with sqlite3.connect(r.path) as con:
        con.execute("UPDATE projection SET body='{}',sha256='bad' WHERE id=1")
    with pytest.raises(ValueError, match="PROJECTION"):
        r.recover()
    assert r.recover(repair_projection=True)["usage"]["shared"] == expected
    with sqlite3.connect(r.path) as con:
        con.execute("UPDATE journal SET previous_sha256='bad' WHERE seq=2")
    with pytest.raises(ValueError, match="JOURNAL_CHAIN_INVALID"):
        r.recover(repair_projection=True)


def test_ats3_bridge_preserves_shadow_namespace_and_open_fill_economics(tmp_path):
    r, key, epoch = create_fixture(tmp_path / "router.db")
    admitted(r, key, epoch, intent("one"))
    publish(r, "one", epoch, now=START + timedelta(seconds=5))
    observe(r, "one", epoch, 1, "ack", now=START + timedelta(seconds=7),
            at=START + timedelta(seconds=6))
    observe(r, "one", epoch, 2, "fill", executions=(fill("fill-1", 2, fee=3),),
            now=START + timedelta(seconds=9), at=START + timedelta(seconds=8))
    r.recover()
    events = ShadowRouter(r.path).audit_events("one")
    assert {e.environment for e in events} == {"shadow"}
    by_kind = {e.kind: e for e in events}
    assert by_kind["order"].event_at == START + timedelta(seconds=5)
    assert by_kind["ack"].event_at == START + timedelta(seconds=6)
    assert by_kind["ack"].available_at == START + timedelta(seconds=7)
    assert by_kind["fill"].event_at == START + timedelta(seconds=8)
    assert by_kind["fill"].available_at == START + timedelta(seconds=9)
    result = reconcile(events, initial_cash="1000")
    assert result["positions"] == {"fixture:perpetual:ALPHAUSD": "0.02"}
    assert result["commissions"] == "0.03"
    assert result["status"] == "INSUFFICIENT_EVIDENCE"  # No fabricated marks or financing.


def test_stale_ack_cannot_rewind_unknown_but_late_fill_is_retained(tmp_path):
    r, key, epoch = create_fixture(tmp_path / "router.db")
    admitted(r, key, epoch, intent("late-control"))
    publish(r, "late-control", epoch)
    observe(r, "late-control", epoch, 3, "unknown")
    result = observe(r, "late-control", epoch, 1, "ack",
                     now=START + timedelta(seconds=4), at=START + timedelta(seconds=1))
    assert result["reason"] == "STALE_EXECUTION_CONTROL_EVENT"
    assert used(r)["unknown"] == 600
    observe(r, "late-control", epoch, 2, "fill", executions=(fill("late-fill", 2),),
            now=START + timedelta(seconds=5), at=START + timedelta(seconds=2))
    assert used(r)["reserved"] == used(r)["unknown"] == 400
    assert used(r)["recognized"] == 200
    assert r.recover()["usage"]["shared"] == used(r)


def test_unauthorized_or_wrong_effect_input_cannot_consume_risk(tmp_path):
    r, key, epoch = create_fixture(tmp_path / "router.db")
    a, g = signed(r, key, intent("one"))
    for patch in ({"trading": True}, {"allowed_effect": "development_only"},
                  {"signature_b64": "A" * 88}):
        result = r.admit(a, {**g, **patch}, epoch, now=START)
        assert result["status"] == "DENIED"
        assert used(r)["used"] == 0
    assert r.admit(a, g, epoch, now=START)["status"] == "ADMITTED"
