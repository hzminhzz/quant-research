"""Leakage-resistant event ordering, interval purging, and fold-local weights.

Legacy exports remain available after module-to-package migration.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import combinations
from typing import Sequence

import numpy as np

from ml4t.diagnostic.splitters import CombinatorialCV

from src.labeling import ORBTradeEvent


class ValidationContractError(ValueError):
    """Raised when a validation invariant is violated."""


@dataclass(frozen=True)
class EventInterval:
    event_id: str
    symbol: str
    decision_time: datetime
    entry_time: datetime
    exit_time: datetime

    def __post_init__(self) -> None:
        for name in ("decision_time", "entry_time", "exit_time"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValidationContractError(f"{name} must be timezone-aware")
        if not self.decision_time <= self.entry_time <= self.exit_time:
            raise ValidationContractError("event times must satisfy decision <= entry <= exit")


def _parse_aware(value: str | datetime) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationContractError("event timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def event_interval(event: ORBTradeEvent) -> EventInterval:
    decision = _parse_aware(event.decision_time or event.entry_time)
    entry = _parse_aware(event.entry_time)
    exit_time = _parse_aware(event.exit_time)
    event_id = stable_event_id(event)
    return EventInterval(event_id, event.symbol, decision, entry, exit_time)


def stable_event_id(event: ORBTradeEvent) -> str:
    session = event.session_name or "default"
    decision = event.decision_time or event.entry_time
    return "|".join(
        (event.symbol, session, decision, event.entry_time, str(event.direction))
    )


def order_events(events: Sequence[ORBTradeEvent]) -> list[ORBTradeEvent]:
    """Sort all assets globally and reject malformed or duplicate event IDs."""
    intervals = [event_interval(event) for event in events]
    ids = [interval.event_id for interval in intervals]
    if len(set(ids)) != len(ids):
        raise ValidationContractError("duplicate event IDs")
    indexed = list(zip(events, intervals))
    indexed.sort(key=lambda pair: (pair[1].decision_time, pair[1].symbol, pair[1].event_id))
    return [event for event, _ in indexed]


def intervals_overlap(left: EventInterval, right: EventInterval) -> bool:
    return left.entry_time <= right.exit_time and right.entry_time <= left.exit_time


@dataclass(frozen=True)
class SplitDiagnostics:
    test_count: int
    purged_count: int
    embargoed_count: int
    remaining_train_count: int
    exact_overlap_count: int


def purge_and_embargo(
    events: Sequence[ORBTradeEvent],
    train_indices: Sequence[int],
    test_indices: Sequence[int],
    embargo: timedelta = timedelta(0),
) -> tuple[np.ndarray, SplitDiagnostics]:
    """Purge interval-overlapping train events and apply elapsed-time embargo.

    The original implementation scanned every test interval for every training
    candidate. The endpoint-count formulation below is exactly equivalent for
    inclusive intervals and reduces each membership query to O(log n).
    """
    intervals = [event_interval(event) for event in events]
    test_intervals = [intervals[i] for i in test_indices]
    if not test_intervals:
        kept = np.asarray(list(train_indices), dtype=int)
        diagnostics = SplitDiagnostics(0, 0, 0, len(kept), 0)
        return kept, diagnostics

    test_starts = sorted(test.entry_time for test in test_intervals)
    test_ends = sorted(test.exit_time for test in test_intervals)
    embargo_ends = sorted(test.exit_time + embargo for test in test_intervals)

    def overlap_count(candidate: EventInterval) -> int:
        return bisect_right(test_starts, candidate.exit_time) - bisect_left(
            test_ends, candidate.entry_time
        )

    def inside_embargo(decision_time: datetime) -> bool:
        active = bisect_right(test_starts, decision_time) - bisect_left(
            embargo_ends, decision_time
        )
        return active > 0

    kept: list[int] = []
    purged = 0
    embargoed = 0
    for idx in train_indices:
        candidate = intervals[idx]
        if overlap_count(candidate) > 0:
            purged += 1
            continue
        if inside_embargo(candidate.decision_time):
            embargoed += 1
            continue
        kept.append(idx)

    exact_overlap_count = sum(overlap_count(intervals[i]) for i in kept)
    diagnostics = SplitDiagnostics(
        test_count=len(test_indices),
        purged_count=purged,
        embargoed_count=embargoed,
        remaining_train_count=len(kept),
        exact_overlap_count=exact_overlap_count,
    )
    if exact_overlap_count:
        raise ValidationContractError("interval purge left train/test overlap")
    return np.asarray(kept, dtype=int), diagnostics


def purged_cpcv_splits(
    events: Sequence[ORBTradeEvent],
    *,
    n_groups: int,
    n_test_groups: int,
    embargo: timedelta,
) -> list[tuple[np.ndarray, np.ndarray, SplitDiagnostics]]:
    """Build CPCV group combinations, then apply exact event-interval controls."""
    if not events:
        return []
    ordered = order_events(events)
    cv = CombinatorialCV(
        n_groups=n_groups,
        n_test_groups=n_test_groups,
        label_horizon=0,
        embargo_size=0,
        isolate_groups=False,
    )
    dummy = np.zeros((len(ordered), 1), dtype=float)
    splits: list[tuple[np.ndarray, np.ndarray, SplitDiagnostics]] = []
    for raw_train, test in cv.split(dummy):
        train, diagnostics = purge_and_embargo(ordered, raw_train, test, embargo)
        splits.append((train, np.asarray(test, dtype=int), diagnostics))
    return splits


def fold_uniqueness_weights(
    events: Sequence[ORBTradeEvent],
    train_indices: Sequence[int],
) -> np.ndarray:
    """Compute normalized uniqueness from training intervals only.

    For an inclusive interval [entry, exit], the number of overlapping training
    intervals equals count(entry_j <= exit_i) - count(exit_j < entry_i). Sorting
    the endpoints once preserves the exact legacy overlap definition while
    avoiding an O(n^2) Python loop in every CPCV fold.
    """
    if len(train_indices) == 0:
        return np.array([], dtype=float)
    intervals = [event_interval(events[i]) for i in train_indices]
    starts = sorted(interval.entry_time for interval in intervals)
    ends = sorted(interval.exit_time for interval in intervals)
    weights = np.empty(len(intervals), dtype=float)
    for i, current in enumerate(intervals):
        overlaps = bisect_right(starts, current.exit_time) - bisect_left(
            ends, current.entry_time
        )
        if overlaps <= 0:
            raise ValidationContractError("event interval does not overlap itself")
        weights[i] = 1.0 / overlaps
    mean = float(weights.mean())
    return weights / mean if mean else np.ones_like(weights)


def chronological_final_oos_split(
    events: Sequence[ORBTradeEvent],
    final_oos_start: datetime,
) -> tuple[np.ndarray, np.ndarray]:
    """Split by decision time and reject development events after the boundary."""
    boundary = _parse_aware(final_oos_start)
    intervals = [event_interval(event) for event in events]
    development = np.asarray([i for i, e in enumerate(intervals) if e.decision_time < boundary], dtype=int)
    final_oos = np.asarray([i for i, e in enumerate(intervals) if e.decision_time >= boundary], dtype=int)
    if len(development) and len(final_oos) and intervals[development[-1]].decision_time >= intervals[final_oos[0]].decision_time:
        raise ValidationContractError("final OOS split is not chronological")
    return development, final_oos


def final_oos_gate(
    events: Sequence[ORBTradeEvent],
    final_oos_start: datetime,
) -> dict[str, object]:
    """Return an explicit pending state when no post-boundary events exist."""
    development, final_oos = chronological_final_oos_split(events, final_oos_start)
    if len(final_oos) == 0:
        return {
            "status": "FINAL_OOS_PENDING_DATA",
            "development_count": int(len(development)),
            "final_oos_count": 0,
            "metrics": None,
        }
    return {
        "status": "FINAL_OOS_READY",
        "development_count": int(len(development)),
        "final_oos_count": int(len(final_oos)),
        "metrics": None,
    }


def require_complete_oof_coverage(coverage: np.ndarray, active_mask: np.ndarray) -> None:
    missing = np.flatnonzero(active_mask & (coverage <= 0))
    if len(missing):
        raise ValidationContractError(f"missing OOF coverage for {len(missing)} active events")
