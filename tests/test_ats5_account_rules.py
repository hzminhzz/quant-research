"""Independent ATS-5 boundary and immutable golden-account checks."""
import json
from dataclasses import replace
from datetime import datetime
from decimal import Decimal as D
from pathlib import Path

import pytest

from src.account_rules import (
    AccountBinding,
    AccountEvent,
    ObservationCoverage,
    PhaseRule,
    RuleError,
    RuleSource,
    RuleVersion,
    TermAssignment,
    digest,
    replay,
    replay_chunk,
    rule_from_dict,
    semantic_diff,
)


def dt(s):
    return datetime.fromisoformat(s)


START = dt("2026-03-27T12:00:00Z")
END = dt("2026-11-01T00:00:00Z")


def source(kind="synthetic"):
    return RuleSource("fixture-source", "fixture://ats5", START, kind)


def rules(**kw):
    return replace(RuleVersion(
        version_id="v1", program_id="fixture", source=source(),
        phases=(PhaseRule("challenge", "evaluation", D(".10"), 1, "verification"),
                PhaseRule("verification", "evaluation", D(".05"), 1, "funded"),
                PhaseRule("funded", "funded", None, None, payout_fraction=D(".80"),
                          payout_wait_calendar_days=0)),
        timezone_name="Europe/Prague", reset_hour=0,
        daily_loss_fraction=D(".05"), max_loss_fraction=D(".10"),
        mark_max_age_seconds=300,
    ), **kw)


def binding(rule=None, **kw):
    r = rule or rules()
    return replace(AccountBinding(
        "synthetic-account", r.program_id, START, D(100000), "challenge",
        (TermAssignment(START, r.version_id, "synthetic-binding"),),
        (ObservationCoverage(START, END, True, True),),
    ), **kw)


def ev(n, t, kind, amount="0", ref=None):
    return AccountEvent(str(n), dt(t), n, kind, D(amount), ref)


def run(events, rule=None, account=None):
    r = rule or rules()
    return replay(account or binding(r), {r.version_id: r}, events)


def test_golden_breach_then_recovery_cannot_unbreach():
    events = [
        ev(1, "2026-03-27T12:00:01Z", "realized_pnl", "-5001"),
        ev(2, "2026-03-27T12:00:02Z", "realized_pnl", "8000"),
    ]
    path = run(events)
    assert path.decisions[1].state == "BREACHED"
    assert path.decisions[1].breach_codes == ("DAILY_LOSS",)
    assert path.last.state == "BREACHED"
    assert path.last.equity == D(102999)
    assert path.last.minimum_headroom > 0


def test_exact_loss_boundary_is_not_breach_unless_on_touch():
    events = [ev(1, "2026-03-27T12:00:01Z", "realized_pnl", "-5000")]
    assert run(events).last.state == "OBSERVED_CLEAR"
    assert run(events, rules(breach_on_touch=True)).last.breach_codes == ("DAILY_LOSS",)


def test_daily_reset_before_boundary_event_including_dst_transition():
    path = run([
        ev(1, "2026-03-28T22:59:59Z", "realized_pnl", "-2000"),
        ev(2, "2026-03-28T23:00:00Z", "observation"),
        ev(3, "2026-03-29T22:00:00Z", "observation"),
    ])
    resets = [d for d in path.decisions if d.kind == "daily_reset"]
    assert [d.at for d in resets] == [
        dt("2026-03-27T23:00:00Z"), dt("2026-03-28T23:00:00Z"),
        dt("2026-03-29T22:00:00Z"),
    ]
    assert resets[1].daily_floor == D(93000)
    assert resets[2].daily_floor == D(93000)


def test_floating_breach_mark_then_recovery_latched():
    events = [
        ev(1, "2026-03-27T12:00:01Z", "position_opened"),
        ev(2, "2026-03-27T12:00:02Z", "mark", "-5100"),
        ev(3, "2026-03-27T12:00:03Z", "mark", "200"),
    ]
    path = run(events)
    assert path.decisions[1].state == "INCONCLUSIVE"
    assert "FRESH_EQUITY_MARK_MISSING" in path.decisions[1].uncertainty
    assert path.decisions[2].breach_codes == ("DAILY_LOSS",)
    assert path.last.breach_codes == ("DAILY_LOSS",)
    assert "UNOBSERVED_MARK_INTERVAL" in path.last.evidence_gaps


def test_trailing_floor_only_ratchets_up():
    r = rules(max_loss_mode="trailing", trailing_basis="equity")
    path = run([
        ev(1, "2026-03-27T12:00:01Z", "realized_pnl", "4000"),
        ev(2, "2026-03-27T12:00:02Z", "realized_pnl", "-2000"),
    ], r)
    assert path.decisions[1].maximum_floor == D(94000)
    assert path.last.maximum_floor == D(94000)


def test_unknown_critical_blocks_no_permissive_default():
    r = rules(daily_loss_fraction=None, max_loss_fraction=None)
    path = run([ev(1, "2026-03-27T12:00:01Z", "observation")], r)
    assert path.last.state == "INCONCLUSIVE"
    assert {"DAILY_RULE_UNKNOWN", "MAXIMUM_RULE_UNKNOWN"} <= set(path.last.uncertainty)
    assert not path.last.eligible_for_shadow


def test_incomplete_window_and_stale_mark():
    r = rules(mark_max_age_seconds=1)
    a = binding(r, coverage=())
    path = run([ev(1, "2026-03-27T12:00:01Z", "position_opened"),
                ev(2, "2026-03-27T12:10:00Z", "observation")], r, a)
    assert "INCOMPLETE_COVERAGE" in path.last.evidence_gaps
    assert path.last.equity is None
    assert path.last.state == "INCONCLUSIVE"


def test_phase_transition_is_explicit_and_restarts_evaluation_history():
    events = [
        ev(1, "2026-03-27T12:00:01Z", "position_opened"),
        ev(2, "2026-03-27T12:00:01Z", "position_closed", "10000"),
        ev(3, "2026-03-27T12:00:03Z", "phase_advanced", ref="confirmation"),
        ev(4, "2026-03-27T12:00:04Z", "position_opened"),
        ev(5, "2026-03-27T12:00:04Z", "position_closed", "5000"),
        ev(6, "2026-03-27T12:00:06Z", "phase_advanced", ref="confirmation2"),
        ev(7, "2026-03-27T12:00:07Z", "owner_fee_paid", "500"),
        ev(8, "2026-03-27T12:00:08Z", "position_opened"),
        ev(12, "2026-03-27T12:00:08Z", "position_closed", "2000"),
        ev(13, "2026-03-27T12:00:08Z", "reward_requested", "1000", "claim"),
        ev(9, "2026-03-27T12:00:09Z", "reward_approved", ref="claim"),
        ev(10, "2026-03-27T12:00:10Z", "reward_debited", "1000", "claim"),
        ev(11, "2026-03-27T12:00:11Z", "reward_received", "800", "claim"),
    ]
    path = run(events)
    assert path.decisions[3].phase == "verification"
    assert path.decisions[6].phase == "funded"
    assert path.last.cash_paid == D(500)
    assert path.last.cash_received == D(800)
    assert path.last.owner_net_cash == D(300)
    assert path.last.hypothetical_payout_due == 0
    assert path.last.balance == D(101000)


def test_checkpoint_replay_matches_whole_and_duplicate_idempotency():
    events = [ev(n, f"2026-03-27T12:00:{n:02d}Z", "realized_pnl", "10")
              for n in range(1, 20)]
    r, a = rules(), binding()
    whole = run(events)
    first = replay_chunk(a, {"v1": r}, events[:7])
    second = replay_chunk(a, {"v1": r}, events[7:], cursor=first.cursor)
    assert first.decisions + second.decisions == whole.decisions
    assert second.cursor == whole.cursor
    duplicated = replay_chunk(a, {"v1": r}, events[:7], cursor=first.cursor)
    assert not duplicated.decisions
    with pytest.raises(RuleError, match="Conflicting"):
        replay_chunk(a, {"v1": r}, [replace(events[0], amount=D(11))], cursor=first.cursor)
    with pytest.raises(RuleError, match="Out-of-order"):
        replay_chunk(a, {"v1": r}, [ev(99, "2026-03-27T12:00:02Z", "observation")],
                     cursor=first.cursor)


def test_amendment_only_future_assignment_grandfather_survives():
    old = rules()
    new = replace(old, version_id="v2", daily_loss_fraction=D(".04"))
    change = dt("2026-03-28T12:00:00Z")
    changed = binding(old, assignments=(
        TermAssignment(START, "v1", "agreement-old", True),
        TermAssignment(change, "v2", "new-agreement"),
    ))
    grand = binding(old, account_id="grandfathered")
    impact = semantic_diff(old, new, (changed, grand))
    assert impact.affected_accounts_from == (("synthetic-account", change),)
    assert impact.impacted_decisions == ("intraday_replay", "shadow_eligibility")
    path = replay(changed, {"v1": old, "v2": new}, [
        ev(1, "2026-03-27T12:00:01Z", "observation"),
        ev(2, "2026-03-28T12:00:01Z", "observation"),
    ])
    assert path.decisions[1].version_id == "v1"
    assert path.last.version_id == "v2"
    assert path.decisions[1].daily_floor == D(95000)
    assert path.last.daily_floor == D(96000)
    assert digest(old) != digest(new)


def test_semantic_diff_provenance_only_is_not_behavior_change():
    r = rules()
    newer = replace(r, version_id="v2", source=RuleSource(
        "another-source", "fixture://new", START, "published"
    ))
    assert semantic_diff(r, newer).changed_fields == ()
    assert semantic_diff(r, newer).impacted_decisions == ()


def test_missing_account_specific_agreement_denies_routing_even_with_clear_marks():
    r = rules()
    assert run([ev(1, "2026-03-27T12:00:01Z", "observation")], r).last.state == "OBSERVED_CLEAR"
    assert not run([ev(1, "2026-03-27T12:00:01Z", "observation")], r).last.eligible_for_shadow


def test_unrequested_payout_and_illegal_phase_advancement_rejected():
    with pytest.raises(RuleError, match="Phase advance"):
        run([ev(1, "2026-03-27T12:00:01Z", "phase_advanced", ref="fake")])
    with pytest.raises(RuleError, match="Payout eligibility"):
        run([ev(1, "2026-03-27T12:00:01Z", "reward_requested", "1000", "r")])


def test_duplicate_sequence_conflict_and_naive_time_refused():
    with pytest.raises(RuleError, match="Out-of-order"):
        run([ev(1, "2026-03-27T12:00:01Z", "observation"),
             ev(0, "2026-03-27T12:00:01Z", "observation")])
    with pytest.raises(RuleError, match="timestamp"):
        AccountEvent("bad", datetime.fromisoformat("2026-03-27T00:00:00"), 1, "mark", D(0))

def test_public_ftmo_capture_fail_closed_and_correct_objectives():
    path = Path("docs/architecture/trading_system/ats5_ftmo_public_20261016.json")
    r = rule_from_dict(json.loads(path.read_text()))
    assert r.program_id == "FTMO_CFD_2STEP_PUBLIC"
    assert r.phase("challenge").target_fraction == D(".10")
    assert r.phase("verification").target_fraction == D(".05")
    assert r.phase("challenge").min_open_days == 4
    assert r.daily_loss_fraction == D(".05")
    assert r.max_loss_fraction == D(".10")
    assert r.phase("funded").payout_fraction is None
    account = binding(r, coverage=(), agreement_verified=False)
    result = replay(account, {r.version_id: r}, ())
    assert result.last.state == "INCONCLUSIVE"
    assert "EVENT_STREAM_INCOMPLETE" in result.last.uncertainty
    assert not result.last.eligible_for_shadow


def test_account_cash_ledger_independent_of_trading_drawdown():
    events = [
        ev(1, "2026-03-27T12:00:01Z", "owner_fee_paid", "450"),
        ev(2, "2026-03-27T12:00:02Z", "deposit", "3000"),
        ev(3, "2026-03-27T12:00:03Z", "owner_fee_refund_received", "450"),
        ev(4, "2026-03-27T12:00:04Z", "withdrawal", "1000"),
    ]
    path = run(events)
    assert path.last.balance == D(102000)
    assert path.last.owner_net_cash == D(0)
    assert path.last.cash_paid == D(450)
    assert path.last.cash_received == D(450)
    assert path.last.daily_floor == D(95000)
    assert path.last.maximum_floor == D(90000)


def test_reproducible_prefixes_and_permutations_of_same_time_sequence():
    r, a = rules(), binding()
    events = [ev(i, "2026-03-27T12:00:01Z", "realized_pnl",
                 str(i % 3 - 1)) for i in range(1, 50)]
    single = replay(a, {"v1": r}, events)
    for split in range(len(events) + 1):
        p = replay_chunk(a, {"v1": r}, events[:split])
        q = replay_chunk(a, {"v1": r}, events[split:], cursor=p.cursor)
        assert p.decisions + q.decisions == single.decisions
        assert q.cursor == single.cursor
    with pytest.raises(RuleError, match="Out-of-order"):
        replay(a, {"v1": r}, list(reversed(events)))


def test_missing_mark_during_overnight_position_blocks_qualification():
    r = rules()
    account = binding(r)
    path = run([
        ev(1, "2026-03-27T12:00:01Z", "position_opened"),
        ev(2, "2026-03-27T12:00:01Z", "mark", "500"),
        ev(3, "2026-03-27T23:00:01Z", "observation"),
    ], r, account)
    assert path.last.state == "INCONCLUSIVE"
    assert "FRESH_EQUITY_MARK_MISSING" in path.last.uncertainty
    assert not path.last.eligible_for_shadow
