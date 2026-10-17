"""Read-only, source-preserving ATS-3 operational evidence projection.

No order or broker APIs are imported. Unknown economic inputs never become zero.
Reconciliation is deterministic, and every missing or conflicting observation
fails closed: gaps report INSUFFICIENT_EVIDENCE, contradictions report
CONFLICTING_EVIDENCE, and neither is ever relabeled or silently repaired.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

KINDS = frozenset({"intent", "route", "order", "ack", "cancel", "reject", "fill", "position", "mark", "commission", "financing", "cash", "incident", "notification"})


@dataclass(frozen=True)
class AuditEvent:
    source: str
    environment: str
    account: str
    strategy: str
    instrument: str
    event_id: str
    kind: str
    event_at: datetime
    available_at: datetime
    observed_at: datetime
    payload: Mapping[str, Any]
    execution_id: str = ""
    supersedes: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS or not all((self.source, self.environment, self.account, self.event_id)):
            raise ValueError("INVALID_EVENT_IDENTITY")
        for timestamp in (self.event_at, self.available_at, self.observed_at):
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("NAIVE_EVENT_CLOCK")
        if self.available_at > self.observed_at:
            raise ValueError("OBSERVED_BEFORE_AVAILABLE")


def _number(payload: Mapping[str, Any], name: str) -> Decimal:
    if name not in payload or payload[name] is None:
        raise ValueError("MISSING_" + name.upper())
    try:
        value = Decimal(str(payload[name]))
    except (InvalidOperation, ValueError):
        raise ValueError("INVALID_" + name.upper()) from None
    if not value.is_finite():
        raise ValueError("NONFINITE_" + name.upper())
    return value


def reconcile(events: Sequence[AuditEvent], *, initial_cash: str | None = None,
              as_of: datetime | None = None, max_mark_age: timedelta | None = None) -> dict[str, Any]:
    """Deterministic projection. Only authoritative events count; conflicts fail closed."""
    if as_of is not None and (as_of.tzinfo is None or as_of.utcoffset() is None):
        raise ValueError('NAIVE_AS_OF_CLOCK')
    if max_mark_age is not None and max_mark_age <= timedelta(0):
        raise ValueError('INVALID_MARK_MAX_AGE')
    seen: dict[tuple[str, str, str, str], AuditEvent] = {}
    conflicts: list[str] = []
    for event in events:
        key = (event.source, event.environment, event.account, event.event_id)
        if key in seen and seen[key] != event:
            conflicts.append(event.event_id)
        else:
            seen[key] = event
    ordered = sorted((e for e in seen.values() if as_of is None or e.observed_at <= as_of),
                     key=lambda e: (e.available_at, e.event_at, e.source, e.event_id))
    if len({(e.environment, e.account) for e in ordered}) > 1:
        conflicts.append("MIXED_ACCOUNT_SCOPE")
    cash = Decimal(str(initial_cash)) if initial_cash is not None else None
    positions: dict[str, Decimal] = defaultdict(Decimal)
    declared_positions: dict[str, Decimal] = {}
    marks: dict[str, Decimal] = {}
    mark_times: dict[str, datetime] = {}
    order_requested: dict[str, Decimal] = {}
    order_filled: dict[str, Decimal] = defaultdict(Decimal)
    fill_event_ids: set[str] = set()
    commission_for: set[str] = set()
    corrected: set[str] = set()
    fees = Decimal(0)
    financing = Decimal(0)
    transfers = Decimal(0)
    fill_ids: set[str] = set()
    order_ids: set[str] = set()
    ack_ids: set[str] = set()
    gaps: set[str] = set()
    for event in ordered:
        p = event.payload
        if event.supersedes:
            # Corrections cannot silently rewrite previously recognized economics.
            corrected.add(event.supersedes)
            conflicts.append('CORRECTION_REQUIRES_REPLAY:' + event.supersedes)
        try:
            if event.kind == "order":
                if not event.execution_id:
                    gaps.add('ORDER_ID_MISSING')
                else:
                    order_ids.add(event.execution_id)
                if 'quantity' not in p or p['quantity'] is None:
                    gaps.add('ORDER_QUANTITY_MISSING')
                else:
                    value = _number(p, 'quantity')
                    if value <= 0:
                        raise ValueError('INVALID_ORDER_QUANTITY')
                    if event.execution_id in order_requested and order_requested[event.execution_id] != value:
                        conflicts.append('ORDER_QUANTITY_CONFLICT:' + event.execution_id)
                    order_requested[event.execution_id] = value
            elif event.kind == "ack":
                if not event.execution_id:
                    gaps.add('ACK_ID_MISSING')
                else:
                    ack_ids.add(event.execution_id)
            elif event.kind == "fill":
                if not event.execution_id:
                    gaps.add("FILL_ORDER_ID_MISSING")
                fill_ids.add(event.execution_id)
                fill_event_ids.add(event.event_id)
                qty = _number(p, "quantity")
                price = _number(p, "price")
                if qty <= 0 or price <= 0 or p.get("side") not in ("buy", "sell"):
                    raise ValueError("INVALID_FILL")
                order_filled[event.execution_id] += qty
                signed = qty if p["side"] == "buy" else -qty
                positions[event.instrument] += signed
                if cash is not None:
                    cash -= signed * price
            elif event.kind == "commission":
                if 'fill_event_id' in p:
                    commission_for.add(str(p['fill_event_id']))
                amount = _number(p, "amount")
                if amount < 0:
                    raise ValueError("NEGATIVE_COMMISSION")
                fees += amount
                if cash is not None:
                    cash -= amount
            elif event.kind == "financing":
                amount = _number(p, "amount")
                financing += amount
                if cash is not None:
                    cash += amount
            elif event.kind == "cash":
                amount = _number(p, "amount")
                transfers += amount
                if cash is not None:
                    cash += amount
            elif event.kind == "mark":
                price = _number(p, "price")
                if price <= 0:
                    raise ValueError("INVALID_MARK")
                if event.instrument in marks:
                    # One observed mark per instrument. A second distinct mark
                    # would silently reprice without a superseding correction.
                    conflicts.append('MARK_OVERWRITE:' + event.instrument)
                marks[event.instrument] = price
                mark_times[event.instrument] = event.event_at
            elif event.kind == "position":
                quantity = _number(p, "quantity")
                previous = declared_positions.get(event.instrument)
                if previous is not None and previous != quantity:
                    # Two differing declarations for one instrument can never be
                    # reconciled; the last one would silently decide alone.
                    conflicts.append(
                        'POSITION_QUANTITY_CONFLICT:' + event.instrument)
                declared_positions[event.instrument] = quantity
        except ValueError as exc:
            gaps.add(str(exc))
    for order_id, filled in order_filled.items():
        if order_id in order_requested:
            requested = order_requested[order_id]
            if filled > requested:
                conflicts.append('OVERFILLED_ORDER:' + order_id)
            elif filled < requested:
                gaps.add('PARTIAL_FILL:' + order_id)
    if commission_for:
        for identity in fill_event_ids - commission_for:
            gaps.add('FILL_COMMISSION_UNKNOWN:' + identity)
    for identity in commission_for - fill_event_ids:
        # A fee naming a fill that never occurred contradicts the replay.
        conflicts.append('COMMISSION_FOR_UNKNOWN_FILL:' + identity)
    for order_id in fill_ids:
        if order_id not in order_ids:
            gaps.add("MISSING_ORDER:" + order_id)
    for order_id in order_ids - ack_ids:
        gaps.add("ACK_UNKNOWN:" + order_id)
    for symbol, quantity in positions.items():
        if quantity and symbol not in marks:
            gaps.add("MISSING_MARK:" + symbol)
    for symbol, quantity in declared_positions.items():
        if quantity != positions.get(symbol, Decimal(0)):
            conflicts.append("POSITION_MISMATCH:" + symbol)
    if not any(e.kind == "commission" for e in ordered) and fill_ids:
        gaps.add("COMMISSION_NOT_OBSERVED")
    if not any(e.kind == "financing" for e in ordered) and fill_ids:
        gaps.add("FINANCING_NOT_OBSERVED")
    if cash is None:
        gaps.add("INITIAL_CASH_UNKNOWN")
    if as_of is not None and max_mark_age is not None:
        for symbol, quantity in positions.items():
            if quantity and symbol in mark_times and (mark_times[symbol] > as_of or as_of - mark_times[symbol] > max_mark_age):
                gaps.add('STALE_MARK:' + symbol)
    open_positions = {k: v for k, v in sorted(positions.items()) if v}
    equity = (cash + sum((qty * marks[sym] for sym, qty in open_positions.items()), Decimal(0))
              if cash is not None and all(sym in marks for sym in open_positions) else None)
    status = ("CONFLICTING_EVIDENCE" if conflicts else "INSUFFICIENT_EVIDENCE" if gaps
              else "VERIFIED")
    return {"status": status, "event_count": len(ordered), "duplicates": len(events) - len(seen),
            "conflicts": sorted(set(conflicts)), "unknowns": sorted(gaps),
            "cash": str(cash) if cash is not None else None,
            "equity": str(equity) if equity is not None else None,
            "positions": {k: str(v) for k, v in open_positions.items()},
            "commissions": str(fees), "financing": str(financing), "external_cashflow": str(transfers),
            "source_ids": sorted((e.source, e.event_id) for e in ordered)}
