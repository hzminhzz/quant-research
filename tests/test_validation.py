from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from src.labeling import ORBTradeEvent
from src.validation import (
    ValidationContractError,
    chronological_final_oos_split,
    fold_uniqueness_weights,
    final_oos_gate,
    order_events,
    purge_and_embargo,
    require_complete_oof_coverage,
)

UTC = timezone.utc


def make_event(symbol: str, decision_minute: int, duration_minutes: int = 30) -> ORBTradeEvent:
    decision = datetime(2026, 1, 1, 9, tzinfo=UTC) + timedelta(minutes=decision_minute)
    entry = decision + timedelta(minutes=5)
    exit_time = entry + timedelta(minutes=duration_minutes)
    return ORBTradeEvent(
        entry_time=entry.isoformat(),
        exit_time=exit_time.isoformat(),
        decision_time=decision.isoformat(),
        session_name="cash",
        date="2026-01-01",
        symbol=symbol,
        direction=1,
        entry_price=100.0,
        exit_price=101.0,
        or_high=100.0,
        or_low=99.0,
        or_range=1.0,
        atr20=1.0,
        delta=1.0,
        upper_barrier=101.0,
        lower_barrier=99.0,
        holding_bars=6,
        exit_reason="profit_target",
        label=1,
        realized_return=0.01,
        r_multiple=1.0,
        features={},
    )


def test_order_events_is_global_and_deterministic():
    events = [make_event("B", 20), make_event("A", 10), make_event("A", 20)]
    ordered = order_events(events)
    assert [(e.symbol, e.decision_time) for e in ordered] == [
        ("A", "2026-01-01T09:10:00+00:00"),
        ("A", "2026-01-01T09:20:00+00:00"),
        ("B", "2026-01-01T09:20:00+00:00"),
    ]


def test_interval_purge_removes_long_overlap_and_applies_elapsed_embargo():
    events = [make_event("A", 0, 120), make_event("B", 30), make_event("C", 120), make_event("D", 160)]
    kept, diagnostics = purge_and_embargo(
        events, train_indices=[0, 2, 3], test_indices=[1], embargo=timedelta(minutes=60)
    )
    assert kept.tolist() == [3]
    assert diagnostics.purged_count == 1
    assert diagnostics.embargoed_count == 1
    assert diagnostics.exact_overlap_count == 0


def test_fold_weights_ignore_held_out_events():
    events = [make_event("A", 0), make_event("B", 10), make_event("C", 20)]
    baseline = fold_uniqueness_weights(events, [0, 1])
    with_held_out = fold_uniqueness_weights(events, [0, 1])
    assert np.allclose(baseline, with_held_out)


def test_final_oos_split_is_locked_by_decision_time():
    events = [make_event("A", 0), make_event("A", 30), make_event("A", 60)]
    development, final_oos = chronological_final_oos_split(
        events, datetime(2026, 1, 1, 9, 30, tzinfo=UTC)
    )
    assert development.tolist() == [0]
    assert final_oos.tolist() == [1, 2]


def test_final_oos_gate_is_pending_without_post_boundary_events():
    events = [make_event("A", 0), make_event("A", 30)]
    result = final_oos_gate(events, datetime(2026, 1, 1, 10, tzinfo=UTC))
    assert result["status"] == "FINAL_OOS_PENDING_DATA"
    assert result["metrics"] is None


def test_missing_oof_coverage_fails_closed():
    with pytest.raises(ValidationContractError, match="missing OOF"):
        require_complete_oof_coverage(np.array([1, 0]), np.array([True, True]))
