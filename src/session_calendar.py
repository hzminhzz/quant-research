"""Strict timezone and exchange-calendar helpers for the EOW rebuild.

The rebuild separates two concepts that legacy code conflated:
1. an instrument's market calendar/timezone; and
2. the strategy anchor clock used to form the opening/overlap range.

DE30 is the key example: its market calendar is Europe/Berlin/XETR, while the
user-confirmed strategy anchor is 09:00 America/New_York.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars as xcals


UTC = timezone.utc


class CalendarContractError(ValueError):
    """Raised when timezone/calendar semantics are ambiguous or invalid."""


@dataclass(frozen=True)
class StrategyAnchor:
    name: str
    timezone: str
    local_time: time
    opening_range: timedelta
    candidate_window: timedelta


@dataclass(frozen=True)
class AnchorWindow:
    strategy_date: date
    anchor_utc: datetime
    opening_range_end_utc: datetime
    candidate_end_utc: datetime


def parse_clock(value: str) -> time:
    parts = value.split(":")
    if len(parts) != 2:
        raise CalendarContractError(f"invalid HH:MM clock: {value}")
    hour, minute = (int(part) for part in parts)
    return time(hour=hour, minute=minute)


def localize_strict(
    local_date: date,
    local_time: time,
    tz_name: str,
    *,
    fold: int | None = None,
) -> datetime:
    """Localize a wall clock without silently resolving DST anomalies.

    Normal clock times have one effective UTC offset. Ambiguous fall-back times
    have two valid offsets and require an explicit fold. Nonexistent spring-forward
    times have no valid round-trip representation and are rejected.
    """
    zone = ZoneInfo(tz_name)
    naive = datetime.combine(local_date, local_time)

    candidates: list[datetime] = []
    for candidate_fold in (0, 1):
        candidate = naive.replace(tzinfo=zone, fold=candidate_fold)
        roundtrip = candidate.astimezone(UTC).astimezone(zone)
        if roundtrip.replace(tzinfo=None) == naive:
            candidates.append(candidate)

    if not candidates:
        raise CalendarContractError(
            f"nonexistent local time {naive.isoformat()} in {tz_name}"
        )

    unique_offsets = {candidate.utcoffset() for candidate in candidates}
    if len(unique_offsets) > 1:
        if fold is None:
            raise CalendarContractError(
                f"ambiguous local time {naive.isoformat()} in {tz_name}; fold required"
            )
        if fold not in (0, 1):
            raise CalendarContractError("fold must be 0 or 1")
        chosen = naive.replace(tzinfo=zone, fold=fold)
        if (
            chosen.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
            != naive
        ):
            raise CalendarContractError("requested fold does not round-trip")
        return chosen

    return candidates[0]


def anchor_window(strategy_date: date, spec: StrategyAnchor) -> AnchorWindow:
    localized = localize_strict(strategy_date, spec.local_time, spec.timezone)
    anchor = localized.astimezone(UTC)
    opening_end = anchor + spec.opening_range
    return AnchorWindow(
        strategy_date=strategy_date,
        anchor_utc=anchor,
        opening_range_end_utc=opening_end,
        candidate_end_utc=opening_end + spec.candidate_window,
    )


@lru_cache(maxsize=None)
def get_calendar(name: str):
    try:
        return xcals.get_calendar(name)
    except Exception as exc:  # pragma: no cover - defensive boundary
        raise CalendarContractError(f"unknown exchange calendar: {name}") from exc


def calendar_sessions(name: str, start: date, end: date) -> list[date]:
    if end < start:
        return []
    calendar = get_calendar(name)
    sessions = calendar.sessions_in_range(start.isoformat(), end.isoformat())
    return [stamp.date() for stamp in sessions]


def session_open_close_utc(name: str, session_date: date) -> tuple[datetime, datetime]:
    calendar = get_calendar(name)
    label = session_date.isoformat()
    try:
        opened = calendar.session_open(label)
        closed = calendar.session_close(label)
    except Exception as exc:
        raise CalendarContractError(
            f"{session_date.isoformat()} is not a session in {name}"
        ) from exc
    return opened.to_pydatetime().astimezone(UTC), closed.to_pydatetime().astimezone(UTC)


def last_exchange_session_of_week(name: str, session_date: date) -> date:
    """Return the last scheduled exchange session in the local Mon-Sun week."""
    monday = session_date - timedelta(days=session_date.weekday())
    sunday = monday + timedelta(days=6)
    sessions = calendar_sessions(name, monday, sunday)
    if not sessions:
        raise CalendarContractError(
            f"no exchange sessions in week containing {session_date} for {name}"
        )
    if session_date not in sessions:
        raise CalendarContractError(
            f"{session_date.isoformat()} is not a scheduled session for {name}"
        )
    return sessions[-1]


def utc_to_local_date(timestamp: datetime, tz_name: str) -> date:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise CalendarContractError("timestamp must be timezone-aware")
    return timestamp.astimezone(ZoneInfo(tz_name)).date()
