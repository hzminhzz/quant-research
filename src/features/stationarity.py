"""Native fixed-width fractional differencing with training-only parameter fit."""

import math
from datetime import datetime
import polars as pl
from ml4t.engineer.features.fdiff import ffdiff, find_optimal_d
from ._contracts import require_single_ordered


def fit_fractional_difference_d(
    frame: pl.DataFrame,
    *,
    training_end: datetime | None = None,
    timestamp_col: str = "timestamp",
    availability_col: str = "available_at",
    instrument_col: str = "instrument",
    price_col: str = "close",
    d_range: tuple[float, float] = (0.0, 1.0),
    step: float = 0.01,
) -> dict[str, float]:
    """Fit d on available training rows only, never on validation outcomes.

    With no cutoff, frame must contain only training rows. Caller owns that
    partition. With a cutoff, both event time and availability must be earlier.
    """
    require_single_ordered(frame, instrument_col=instrument_col, timestamp_col=timestamp_col)
    if availability_col not in frame.columns or frame[availability_col].null_count():
        raise ValueError("non-null available_at column required")
    if frame.schema[availability_col].base_type() != pl.Datetime or frame.schema[availability_col].time_zone != "UTC":
        raise ValueError("availability must be UTC-aware")
    if not frame[availability_col].is_sorted() or (frame[availability_col] < frame[timestamp_col]).any():
        raise ValueError("availability must be chronological and not precede event time")
    if training_end is not None:
        if training_end.tzinfo is None or training_end.utcoffset() is None:
            raise ValueError("training_end must be timezone-aware")
        training = frame.filter((pl.col(timestamp_col) < training_end)
                                & (pl.col(availability_col) < training_end))
    else:
        training = frame
    if price_col not in training.columns or len(training) < 50:
        raise ValueError("training price column needs at least 50 rows")
    values = training[price_col]
    if values.null_count() or not values.is_finite().all():
        raise ValueError("training prices must be finite and non-null")
    if values.min() <= 0:
        raise ValueError("training prices must be positive")
    if not (0 <= d_range[0] <= d_range[1] <= 1) or not math.isfinite(step) or step <= 0:
        raise ValueError("invalid d search range or step")
    return find_optimal_d(values, d_range=d_range, step=step)


def add_fractional_difference(
    frame: pl.DataFrame,
    *,
    d: float,
    price_col: str = "close",
    alias: str = "close_ffdiff",
    threshold: float = 1e-5,
    instrument_col: str = "instrument",
    timestamp_col: str = "timestamp",
) -> pl.DataFrame:
    """Apply prefit d causally; include training history for validation warm-up.

    Input must be one ordered instrument. Do not fit d using this full frame.
    """
    require_single_ordered(frame, instrument_col=instrument_col, timestamp_col=timestamp_col)
    if price_col not in frame.columns:
        raise ValueError(f"missing price column: {price_col}")
    if frame[price_col].null_count() or not frame[price_col].is_finite().all():
        raise ValueError("prices must be finite and non-null")
    if not math.isfinite(d) or not 0 <= d <= 1:
        raise ValueError("d must be a finite prefit value in [0, 1]")
    if not math.isfinite(threshold) or not 0 < threshold < 1:
        raise ValueError("threshold must be finite and in (0, 1)")
    return frame.with_columns(ffdiff(price_col, d=d, threshold=threshold).alias(alias))
