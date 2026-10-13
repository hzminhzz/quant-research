"""Predeclared XNAS regular-session eligibility for the M8 cash-session study."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import cache

import exchange_calendars as xcals

BAR = timedelta(minutes=30)
HOLDOUT_START = datetime(2025, 1, 1, tzinfo=UTC)


@cache
def _xnas_schedule(day):
    """Return the installed XNAS calendar's scheduled UTC open and close."""
    calendar = xcals.get_calendar("XNAS", start="2020-01-01", end="2025-01-01")
    try:
        session = calendar.date_to_session(day, direction="none")
    except (ValueError, KeyError):
        return None
    return calendar.session_open(session).to_pydatetime(), calendar.session_close(session).to_pydatetime()


def cash_session_signal_eligible(signal_at: datetime, *, evaluation_end: datetime = HOLDOUT_START) -> bool:
    """Use only the known session schedule and bar clock, never future row presence.

    The signal bar is [t, t+30m). Both planned fills are at t+30m and
    t+60m. Fill opens must be within the half-open cash session and before
    the frozen evaluation end.
    """
    stamp = signal_at.replace(tzinfo=UTC) if signal_at.tzinfo is None else signal_at.astimezone(UTC)
    boundary = evaluation_end.replace(tzinfo=UTC) if evaluation_end.tzinfo is None else evaluation_end.astimezone(UTC)
    schedule = _xnas_schedule(stamp.date())
    if schedule is None:
        return False
    session_open, session_close = schedule
    signal_close = stamp + BAR
    entry_open, exit_open = stamp + BAR, stamp + 2 * BAR
    return (
        session_open <= stamp
        and signal_close <= session_close
        and session_open <= entry_open < session_close
        and session_open <= exit_open < session_close
        and signal_close < boundary
        and entry_open < boundary
        and exit_open < boundary
    )


def cash_session_dates(start: datetime, end: datetime) -> list:
    """Return scheduled XNAS sessions intersecting the half-open date range."""
    start_utc = start.replace(tzinfo=UTC) if start.tzinfo is None else start.astimezone(UTC)
    end_utc = end.replace(tzinfo=UTC) if end.tzinfo is None else end.astimezone(UTC)
    calendar = xcals.get_calendar("XNAS", start="2020-01-02", end="2024-12-31")
    first = max(start_utc.date(), calendar.first_session.date())
    last = min((end_utc - timedelta(microseconds=1)).date(), calendar.last_session.date())
    if first > last:
        return []
    return [stamp.date() for stamp in calendar.sessions_in_range(first, last)]


def assert_planned_fill_bars_present(observed_opens: set[datetime], signals: list[datetime]) -> None:
    """Fail the complete frozen signal set when any scheduled fill bar is absent."""
    missing = [
        signal.isoformat()
        for signal in signals
        if any(signal + offset not in observed_opens for offset in (BAR, 2 * BAR))
    ]
    if missing:
        raise RuntimeError(f"EXECUTION_EXCEPTION: missing scheduled fill bars for {missing[:10]}")
