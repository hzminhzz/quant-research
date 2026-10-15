"""Strict event ordering contract for opt-in single-instrument features."""

import polars as pl


def require_single_ordered(
    frame: pl.DataFrame, *, instrument_col: str, timestamp_col: str
) -> None:
    """Reject mixed assets, missing clocks, naive times, and duplicate events."""
    if instrument_col not in frame.columns or timestamp_col not in frame.columns:
        raise ValueError("instrument and timestamp columns are required")
    if frame.is_empty() or frame[instrument_col].null_count() or frame[instrument_col].n_unique() != 1:
        raise ValueError("one non-null instrument is required")
    if frame[timestamp_col].null_count():
        raise ValueError("timestamps must be non-null")
    dtype = frame.schema[timestamp_col]
    if dtype.base_type() != pl.Datetime or dtype.time_zone != "UTC":
        raise ValueError("timestamps must be UTC-aware datetime values")
    if not frame[timestamp_col].is_sorted() or frame[timestamp_col].n_unique() != len(frame):
        raise ValueError("timestamps must be strictly chronological")
