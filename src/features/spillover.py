"""Point-in-time cross-session feature join for declared session identities."""

import polars as pl


def join_cross_session_asof(
    decisions: pl.DataFrame,
    source: pl.DataFrame,
    *,
    source_session: str,
    decision_session: str,
    feature_cols: tuple[str, ...],
    instrument_col: str = "instrument",
    decision_time_col: str = "decision_time",
    event_time_col: str = "event_time",
    availability_col: str = "available_at",
) -> pl.DataFrame:
    """Attach most recent available source-session features per instrument.

    Source rows must already be qualified as source_session. A different
    decision_session is mandatory. Available time includes source processing
    lag; no event-date equality join or future-value fallback is used.
    """
    if not source_session or not decision_session or source_session == decision_session:
        raise ValueError("distinct declared source and decision sessions required")
    if not feature_cols or len(set(feature_cols)) != len(feature_cols):
        raise ValueError("explicit unique feature_cols required")
    if not {instrument_col, decision_time_col} <= set(decisions.columns):
        raise ValueError("decision instrument and time required")
    if not {instrument_col, event_time_col, availability_col, *feature_cols} <= set(source.columns):
        raise ValueError("source instrument, event time, availability, and features required")
    if set(feature_cols) & {instrument_col, event_time_col, availability_col, decision_time_col}:
        raise ValueError("feature columns cannot override temporal keys")
    if {event_time_col, availability_col} & set(decisions.columns):
        raise ValueError("source temporal columns collide with decisions")
    for frame, column in ((decisions, decision_time_col), (source, event_time_col),
                          (source, availability_col)):
        if frame[column].null_count() or frame.schema[column].base_type() != pl.Datetime or frame.schema[column].time_zone != "UTC":
            raise ValueError("all clocks must be non-null UTC-aware datetimes")
        if frame[instrument_col].null_count():
            raise ValueError("instrument must be non-null")
    if (source[availability_col] < source[event_time_col]).any():
        raise ValueError("source availability cannot precede event time")
    if source.select(pl.struct(instrument_col, availability_col).is_duplicated().any()).item():
        raise ValueError("ambiguous duplicate source availability per instrument")
    if set(feature_cols) & set(decisions.columns):
        raise ValueError("feature columns collide with decision columns")
    right = source.select(instrument_col, event_time_col, availability_col, *feature_cols)
    result = decisions.sort(decision_time_col).join_asof(
        right.sort(availability_col), left_on=decision_time_col,
        right_on=availability_col, by=instrument_col, strategy="backward",
        allow_exact_matches=True,
    )
    if result.filter(pl.col(availability_col).is_not_null()).select(
        (pl.col(availability_col) > pl.col(decision_time_col)).any()
    ).item():
        raise AssertionError("as-of join used unavailable source")
    return result
