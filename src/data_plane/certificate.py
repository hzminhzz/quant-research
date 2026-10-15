"""Fail-closed, hash-bound checks for bounded catalog-sourced bar frames.

This module does not load files or isolate data access. Callers must enforce
holdout permissions and source file identity separately.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.resources
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from numbers import Real
from pathlib import Path
from typing import Any, Literal
from zoneinfo import TZPATH, ZoneInfo, ZoneInfoNotFoundError


class CertificateError(ValueError):
    """Input cannot be certified for the declared use."""


@dataclass(frozen=True)
class DataPolicy:
    dataset_key: str
    catalog_identity: str
    source_vendor: str
    source_symbol: str
    product_class: Literal["cfd", "perpetual", "spot", "dated_future"]
    role: Literal["price_proxy", "tradable_product"]
    proxy_target: str | None
    volume_semantics: Literal[
        "genuine_exchange_traded", "broker_tick_or_quote_proxy", "absent"
    ]
    timezone: str
    calendar: Literal["continuous", "exchange"]
    exchange_calendar: str | None
    revision_policy: Literal["append_only", "revised"]
    bar_duration: timedelta
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    max_rows: int = 100_000


@dataclass(frozen=True)
class DataCertificate:
    version: int
    dataset_key: str
    catalog_identity: str
    catalog_sha256: str
    policy_sha256: str
    frame_sha256: str
    row_count: int
    first_event_at: str
    last_event_at: str
    first_usable_at: str
    last_usable_at: str
    schema: tuple[tuple[str, str], ...]
    calendar_sha256: str
    calendar_version: str
    timezone_sha256: str
    tzdata_version: str


_FIELDS = ("dataset_key", "source_vendor", "source_symbol", "product_class",
           "role", "proxy_target", "volume_semantics", "timezone", "calendar",
           "exchange_calendar", "revision_policy")
_BASE = {"symbol", "event_at", "available_at", "open", "high", "low", "close"}
_BAR = {"open", "high", "low", "close"}


def _fail(message: str) -> None:
    raise CertificateError(message)


def _canonical(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            _fail("timestamps must be timezone-aware")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_canonical(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        _fail("non-finite numeric value")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    _fail(f"unsupported value type: {type(value).__name__}")


def _hash(value: Any) -> str:
    payload = json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _rows(frame: Any, max_rows: int) -> tuple[list[dict[str, Any]], tuple[tuple[str, str], ...]]:
    import pandas as pd
    import polars as pl

    if isinstance(frame, pd.DataFrame):
        if not frame.columns.is_unique or not all(isinstance(c, str) for c in frame.columns):
            _fail("columns must have unique string names")
        if len(frame) > max_rows:
            _fail("row limit exceeded")
        schema = tuple((c, str(frame[c].dtype)) for c in frame.columns)
        records = frame.to_dict("records")
    elif isinstance(frame, pl.DataFrame):
        if frame.height > max_rows:
            _fail("row limit exceeded")
        schema = tuple((c, str(t)) for c, t in frame.schema.items())
        records = frame.to_dicts()
    else:
        _fail("expected pandas or polars DataFrame")
    if not records:
        _fail("empty frame")
    return records, schema


def _utc(value: Any, field: str) -> datetime:
    # Pandas Timestamp subclasses datetime; reject date-only and strings.
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        _fail(f"{field} must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _policy_check(policy: DataPolicy, entry: dict[str, Any]) -> ZoneInfo:
    # Dataclass Literal annotations do not enforce values at runtime.
    allowed = {
        "product_class": {"cfd", "perpetual", "spot", "dated_future"},
        "role": {"price_proxy", "tradable_product"},
        "volume_semantics": {
            "genuine_exchange_traded", "broker_tick_or_quote_proxy", "absent"
        },
        "revision_policy": {"append_only", "revised"},
    }
    for field, values in allowed.items():
        if getattr(policy, field) not in values:
            _fail(f"unsupported {field}")
    if not isinstance(entry, dict) or any(entry.get(f) != getattr(policy, f) for f in _FIELDS):
        _fail("catalog entry differs from declared policy")
    if entry.get("authority") != "canonical" or entry.get("qualification") not in (
        "accepted", "accepted_with_exclusions"
    ):
        _fail("catalog authority or qualification is not accepted")
    if not all((policy.catalog_identity, policy.dataset_key, policy.source_symbol,
                policy.source_vendor)):
        _fail("missing catalog or source identity")
    try:
        tz = ZoneInfo(policy.timezone)
    except ZoneInfoNotFoundError as exc:
        raise CertificateError("invalid IANA timezone") from exc
    if policy.max_rows < 1 or policy.max_rows > 100_000 or policy.bar_duration < timedelta(minutes=1):
        _fail("invalid row limit or bar duration")
    if (policy.coverage_start is None) != (policy.coverage_end is None):
        _fail("coverage requires both start and end")
    if policy.coverage_start is not None and _utc(policy.coverage_start, "coverage_start") >= _utc(
        policy.coverage_end, "coverage_end"
    ):
        _fail("invalid coverage window")
    if policy.calendar == "continuous":
        if policy.exchange_calendar is not None:
            _fail("continuous calendar cannot name exchange schedule")
    elif policy.calendar == "exchange":
        if not policy.exchange_calendar:
            _fail("exchange calendar requires exact calendar code")
    else:
        _fail("unsupported calendar")
    if policy.role == "price_proxy" and not policy.proxy_target:
        _fail("price proxy requires explicit target product")
    if policy.role == "tradable_product" and policy.proxy_target is not None:
        _fail("tradable product cannot claim proxy target")
    if policy.product_class == "cfd" and policy.volume_semantics == "genuine_exchange_traded":
        _fail("CFD cannot claim exchange-traded volume")
    return tz


def _timezone_identity(zone: str) -> tuple[str, str]:
    if not zone or zone.startswith("/") or ".." in zone.split("/"):
        _fail("invalid timezone path")
    for root in TZPATH:
        path = Path(root, zone)
        if path.is_file():
            return hashlib.sha256(path.read_bytes()).hexdigest(), f"system:{root};version-unknown"
    # A zone resolved from bundled tzdata must bind those exact bundled bytes.
    try:
        resource = importlib.resources.files("tzdata.zoneinfo").joinpath(*zone.split("/"))
        return hashlib.sha256(resource.read_bytes()).hexdigest(), importlib.metadata.version("tzdata")
    except (ImportError, FileNotFoundError) as exc:
        raise CertificateError("timezone source unavailable") from exc


def _grid(policy: DataPolicy, start: datetime, end: datetime) -> tuple[list[datetime], str, str]:
    """Enumerate complete eligible bar starts; never extrapolate beyond schedule coverage."""
    if policy.calendar == "continuous":
        segments = [(start, end)]
        calendar_version = "continuous-utc-v1"
        schedule = {"segments": segments}
    else:
        try:
            import exchange_calendars as xcals
            import pandas as pd

            if policy.exchange_calendar not in xcals.get_calendar_names():
                _fail("unsupported exchange calendar")
            cal = xcals.get_calendar(policy.exchange_calendar)
            calendar_version = importlib.metadata.version("exchange_calendars")
            # Session labels can differ from their UTC open date for overnight markets.
            if start.date() < (cal.first_session - timedelta(days=2)).date() or end.date() > (
                cal.last_session + timedelta(days=2)
            ).date():
                _fail("exchange calendar coverage unavailable")
            sessions = cal.sessions_in_range(start.date() - timedelta(days=2),
                                             end.date() + timedelta(days=2))
            if len(sessions) == 0:
                _fail("exchange calendar coverage unavailable")
            segments = []
            for label in sessions:
                opened = cal.session_open(label).to_pydatetime()
                closed = cal.session_close(label).to_pydatetime()
                break_start = cal.session_break_start(label)
                if pd.isna(break_start):
                    segments.append((opened, closed))
                else:
                    segments.extend(((opened, break_start.to_pydatetime()),
                                     (cal.session_break_end(label).to_pydatetime(), closed)))
            schedule = {"calendar": policy.exchange_calendar, "segments": segments,
                        "first_session": str(cal.first_session),
                        "last_session": str(cal.last_session)}
        except CertificateError:
            raise
        except (ImportError, ValueError, OverflowError) as exc:
            raise CertificateError("exchange calendar unavailable or out of coverage") from exc
    expected = []
    for left, right in segments:
        point = left
        while point + policy.bar_duration <= right:
            if start <= point and point + policy.bar_duration <= end:
                expected.append(point)
                if len(expected) > policy.max_rows:
                    _fail("calendar grid exceeds row limit")
            point += policy.bar_duration
    if not expected:
        _fail("no complete bars within calendar session coverage")
    return expected, _hash(schedule), calendar_version


def certify_frame(frame: Any, *, catalog: dict[str, Any], policy: DataPolicy) -> DataCertificate:
    """Certify bounded input against exact catalog entry and declared bar policy."""
    if not isinstance(catalog, dict) or catalog.get("catalog_identity") != policy.catalog_identity:
        _fail("catalog identity mismatch")
    entries = catalog.get("entries")
    if not isinstance(entries, list) or sum(
        isinstance(e, dict) and e.get("dataset_key") == policy.dataset_key for e in entries
    ) != 1:
        _fail("missing or ambiguous catalog entry")
    entry = next(e for e in entries if e.get("dataset_key") == policy.dataset_key)
    _policy_check(policy, entry)
    rows, schema = _rows(frame, policy.max_rows)
    columns = {c for c, _ in schema}
    needed = _BASE | ({"volume"} if policy.volume_semantics != "absent" else set())
    needed |= {"recorded_at", "vintage_at"} if policy.revision_policy == "revised" else set()
    if not needed <= columns:
        _fail(f"missing required columns: {sorted(needed - columns)}")
    if policy.revision_policy == "append_only" and "vintage_at" in columns:
        _fail("append-only frame cannot carry vintages")
    if policy.volume_semantics == "absent" and "volume" in columns:
        _fail("absent volume cannot carry volume column")
    if "timestamp" in columns or "date" in columns:
        _fail("ambiguous timestamp column; use event_at and available_at")
    # Require explicit numeric schema. Do not coerce strings or nullable OHLC.
    numeric = re.compile(r"^(?:int|uint|float|Int|UInt|Float|decimal|Decimal)")
    for col, dtype in schema:
        if col in _BAR | {"volume"} and not numeric.match(dtype):
            _fail(f"{col} must have a numeric dtype")
    events = [_utc(row["event_at"], "event_at") for row in rows]
    if events != sorted(events):
        _fail("events must be sorted")
    start = _utc(policy.coverage_start, "coverage_start") if policy.coverage_start else _utc(
        events[0], "event_at"
    )
    end = _utc(policy.coverage_end, "coverage_end") if policy.coverage_end else _utc(
        events[-1], "event_at"
    ) + policy.bar_duration
    expected, calendar_sha, calendar_version = _grid(policy, start, end)
    timezone_sha, tzdata_version = _timezone_identity(policy.timezone)
    expected_set = set(expected)
    last_event: datetime | None = None
    last_version: dict[datetime, tuple[datetime, datetime, datetime]] = {}
    observed: set[datetime] = set()
    first_usable: datetime | None = None
    last_usable: datetime | None = None
    for row in rows:
        if row["symbol"] != policy.source_symbol:
            _fail("source symbol mismatch")
        event = _utc(row["event_at"], "event_at")
        available = _utc(row["available_at"], "available_at")
        if last_event is not None and event < last_event:
            _fail("events must be sorted")
        if event + policy.bar_duration > available:
            _fail("bar available before completion")
        if event not in expected_set:
            _fail("bar outside declared calendar session or grid")
        observed.add(event)
        if policy.revision_policy == "append_only":
            if event == last_event:
                _fail("duplicate event in append-only feed")
            usable = available
            if "recorded_at" in columns:
                recorded = _utc(row["recorded_at"], "recorded_at")
                if recorded < available:
                    _fail("recorded_at precedes availability")
                usable = recorded
        else:
            recorded = _utc(row["recorded_at"], "recorded_at")
            vintage = _utc(row["vintage_at"], "vintage_at")
            if not event <= vintage <= available <= recorded:
                _fail("revision vintage/availability/recorded clock invalid")
            if event in last_version and (
                vintage <= last_version[event][0]
                or available <= last_version[event][1]
                or recorded <= last_version[event][2]
            ):
                _fail("revisions must advance vintage, availability, and recorded_at")
            last_version[event] = (vintage, available, recorded)
            usable = recorded
        prices = []
        for field in ("open", "high", "low", "close"):
            value = row[field]
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) or value <= 0:
                _fail(f"{field} must be finite and positive")
            prices.append(value)
        op, hi, lo, cl = prices
        if lo > min(op, cl) or hi < max(op, cl) or hi < lo:
            _fail("invalid OHLC relationships")
        if "volume" in columns:
            vol = row["volume"]
            if isinstance(vol, bool) or not isinstance(vol, Real) or not math.isfinite(vol) or vol < 0:
                _fail("volume must be finite and nonnegative")
        last_event = event
        first_usable = usable if first_usable is None else min(first_usable, usable)
        last_usable = usable if last_usable is None else max(last_usable, usable)
    if observed != expected_set:
        _fail("missing bars in calendar grid")
    return DataCertificate(
        version=1, dataset_key=policy.dataset_key, catalog_identity=policy.catalog_identity,
        catalog_sha256=_hash(catalog), policy_sha256=_hash(asdict(policy)),
        frame_sha256=_hash({"schema": schema, "rows": rows}), row_count=len(rows),
        first_event_at=_utc(rows[0]["event_at"], "event_at").isoformat(),
        last_event_at=last_event.isoformat(), first_usable_at=first_usable.isoformat(),
        last_usable_at=last_usable.isoformat(), schema=schema,
        calendar_sha256=calendar_sha, calendar_version=calendar_version,
        timezone_sha256=timezone_sha, tzdata_version=tzdata_version,
    )


def verify_certificate(
    certificate: DataCertificate, frame: Any, *, catalog: dict[str, Any], policy: DataPolicy,
) -> None:
    """Revalidate cached data and metadata; reject stale or forged certificates."""
    if not isinstance(certificate, DataCertificate) or certificate.version != 1:
        _fail("unknown certificate")
    if certify_frame(frame, catalog=catalog, policy=policy) != certificate:
        _fail("certificate identity drift")


def asof_frame(
    certificate: DataCertificate, frame: Any, *, catalog: dict[str, Any],
    policy: DataPolicy, decision_at: datetime,
) -> Any:
    """Return latest eligible recorded vintage per event, never future revisions.

    The result has the same frame backend. Its certificate binds the original
    full frame, not this derived subset. It does not isolate source files,
    authorize a holdout, or prove any decision used this view.
    """
    verify_certificate(certificate, frame, catalog=catalog, policy=policy)
    decision = _utc(decision_at, "decision_at")
    rows, _ = _rows(frame, policy.max_rows)
    selected: dict[datetime, int] = {}
    for index, row in enumerate(rows):
        event = _utc(row["event_at"], "event_at")
        available = _utc(row["available_at"], "available_at")
        recorded = _utc(row["recorded_at"], "recorded_at") if "recorded_at" in row else available
        if max(available, recorded) <= decision:
            selected[event] = index
    indices = list(selected.values())
    import pandas as pd

    if isinstance(frame, pd.DataFrame):
        return frame.iloc[indices].copy()
    return frame[indices].clone()
