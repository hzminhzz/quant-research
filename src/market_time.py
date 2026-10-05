"""Canonical point-in-time timestamp and exchange-session contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import polars as pl


class TimestampContractError(ValueError):
    """Raised when timestamp semantics cannot be established safely."""


@dataclass(frozen=True)
class BarTimestampSpec:
    convention: Literal["open", "close"]
    duration: timedelta
    source_timezone: str = "UTC"

    def __post_init__(self) -> None:
        if self.convention not in {"open", "close"}:
            raise TimestampContractError("bar timestamp convention must be 'open' or 'close'")
        if self.duration <= timedelta(0):
            raise TimestampContractError("bar duration must be positive")
        try:
            ZoneInfo(self.source_timezone)
        except ZoneInfoNotFoundError as exc:
            raise TimestampContractError(
                f"unknown source timezone: {self.source_timezone}"
            ) from exc


@dataclass(frozen=True)
class SessionSpec:
    name: str
    timezone: str
    local_open: time
    opening_range: timedelta = timedelta(hours=1)
    candidate_window: timedelta = timedelta(minutes=90)
    calendar_timezone: str | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise TimestampContractError("session name is required")
        if self.opening_range <= timedelta(0) or self.candidate_window <= timedelta(0):
            raise TimestampContractError("session windows must be positive")
        try:
            ZoneInfo(self.timezone)
            if self.calendar_timezone is not None:
                ZoneInfo(self.calendar_timezone)
        except ZoneInfoNotFoundError as exc:
            raise TimestampContractError(f"unknown session timezone: {exc}") from exc


def _ensure_aware(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise TimestampContractError("timestamp must be timezone-aware")
    return timestamp


def parse_utc_timestamp(timestamp: datetime | str) -> datetime:
    """Parse an already timezone-aware timestamp and normalize it to UTC."""
    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return _ensure_aware(timestamp).astimezone(timezone.utc)


def available_at(timestamp: datetime | str, spec: BarTimestampSpec) -> datetime:
    """Return the first instant at which a complete bar is knowable."""
    start = parse_utc_timestamp(timestamp)
    return start if spec.convention == "close" else start + spec.duration


def localize_strict(local_value: datetime, timezone_name: str, *, fold: int | None = None) -> datetime:
    """Attach an IANA timezone without silently accepting ambiguous/nonexistent wall times."""
    if local_value.tzinfo is not None:
        raise TimestampContractError("localize_strict expects a naive local datetime")
    zone = ZoneInfo(timezone_name)
    candidates = []
    for candidate_fold in (0, 1):
        aware = local_value.replace(tzinfo=zone, fold=candidate_fold)
        roundtrip = aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
        if roundtrip == local_value:
            candidates.append(aware)
    unique_offsets = {candidate.utcoffset() for candidate in candidates}
    if not candidates:
        raise TimestampContractError(
            f"nonexistent local time {local_value.isoformat()} in {timezone_name}"
        )
    if len(unique_offsets) > 1:
        if fold is None:
            raise TimestampContractError(
                f"ambiguous local time {local_value.isoformat()} in {timezone_name}; fold is required"
            )
        return local_value.replace(tzinfo=zone, fold=fold)
    return candidates[0]


def session_window(trading_date: date | str, spec: SessionSpec) -> tuple[datetime, datetime, datetime]:
    """Return UTC-aware strategy-anchor open, opening-range end, and candidate end."""
    if isinstance(trading_date, str):
        trading_date = date.fromisoformat(trading_date)
    local_start = localize_strict(datetime.combine(trading_date, spec.local_open), spec.timezone)
    start = local_start.astimezone(timezone.utc)
    return start, start + spec.opening_range, start + spec.opening_range + spec.candidate_window


def canonicalize_utc_timestamp(
    df: pl.DataFrame,
    timestamp_col: str = "timestamp",
    *,
    source_timezone: str | None = None,
) -> pl.DataFrame:
    """Return sorted UTC-aware timestamps, rejecting naive/duplicate/unsorted input.

    A naive input is accepted only when ``source_timezone`` is explicitly supplied.
    The original row order must already be chronological; silently sorting a malformed
    feed would hide a data-contract violation.
    """
    if timestamp_col not in df.columns:
        raise TimestampContractError(f"missing timestamp column: {timestamp_col}")
    if df.is_empty():
        return df

    dtype = df.schema[timestamp_col]
    result = df
    if dtype == pl.String:
        if source_timezone is None:
            raise TimestampContractError("string timestamps require an explicit source_timezone")
        result = result.with_columns(
            pl.col(timestamp_col).str.to_datetime(strict=True, time_zone=source_timezone)
        )
    elif dtype == pl.Datetime:
        if df.schema[timestamp_col].time_zone is None:
            if source_timezone is None:
                raise TimestampContractError("naive timestamps require an explicit source_timezone")
            result = result.with_columns(
                pl.col(timestamp_col).dt.replace_time_zone(source_timezone)
            )
    else:
        raise TimestampContractError(f"unsupported timestamp dtype: {dtype}")

    result = result.with_columns(
        pl.col(timestamp_col).dt.convert_time_zone("UTC")
    )
    values = result.get_column(timestamp_col).to_list()
    if any(values[i] > values[i + 1] for i in range(len(values) - 1)):
        raise TimestampContractError("timestamps must be sorted before canonicalization")
    if len(set(values)) != len(values):
        raise TimestampContractError("duplicate timestamps are not allowed")
    return result
