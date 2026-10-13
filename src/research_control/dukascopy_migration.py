"""Managed Dukascopy USATECH CFD features, source QA, and native execution inputs.

2026 retrospective replication only. Original source and trial outcomes stay immutable.
No CME or dated-futures identity, no claim of genuine exchange-traded volume.
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import polars as pl

from .contracts import ResearchContractV1
from .feature_gateway import FeatureComputation, FeatureGateway

SOURCE_SHA256 = "4ce2efcf496fb77d936d12d866ef5ed5d1e1869879a6b30434a1d0232bb75425"
SOURCE_SYMBOL = "USATECH.IDX/USD"
DATA_SYMBOL = "DUK_USATECH"
CT = ZoneInfo("America/Chicago")
BAR_MINUTES = 405
CUT_OFF = "15:14"
SEEN_RETROSPECTIVE_END = date(2026, 8, 17)


def dukascopy_feature_contract(session_id: str) -> ResearchContractV1:
    extensions = [
        {"id": "vwap", "provider": {
            "kind": "extension.approved", "extension_id": "cash_open_vwap",
            "version": "1.0.0", "session_open": "08:30",
            "timezone": "America/Chicago"},
         "inputs": {"high": "high", "low": "low", "close": "close",
                    "volume": "volume"}},
    ]
    for name, field, period in (
        ("prior4_high", "high", 4), ("prior5_high", "high", 5),
        ("prior19_low", "low", 19), ("prior20_low", "low", 20)
    ):
        extensions.append({"id": name, "provider": {
            "kind": "extension.approved", "extension_id": "prior_n_high_low",
            "version": "1.0.0", "field": field, "period": period},
            "inputs": {field: field}})
    return ResearchContractV1.model_validate({
        "schema_version": 1, "session_id": session_id,
        "dataset": {
            "requested_product": "Dukascopy USATECH.IDX/USD CFD price and quote-volume proxy",
            "source_vendor": "Dukascopy",
            "source_symbol": SOURCE_SYMBOL,
            "catalog_dataset_key": None,
            "external_exception_id": "dukascopy-usatech-rebuild-20261012-v1",
            "authority": "staged_noncanonical", "product_class": "cfd",
            "role": "price_proxy", "volume_semantics": "broker_tick_or_quote_proxy",
            "timeframe": "1m", "timestamp_convention": "bar_start",
            "timezone": "America/Chicago", "group_columns": ["symbol"]},
        "feature_set": [{
            "id": "adx", "provider": {"kind": "engineer.native",
                                   "name": "adx", "params": {"period": 14}},
            "inputs": {"high": "high", "low": "low", "close": "close"}
        }, *extensions],
        "strategy": {"rule_id": "frozen-B1-B2-B3-dukascopy-1514-ct",
                     "engine": "ml4t.backtest"},
        "evaluation": {"development": ["2026-01-01", "2026-07-01"]},
    })


def checked_source(source: str | Path, *, expected_sha256: str = SOURCE_SHA256) -> pl.DataFrame:
    path = Path(source)
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError("SOURCE_IDENTITY_CONFLICT: Dukascopy pinned SHA differs")
    data = pl.read_parquet(path).sort("timestamp")
    required = {"timestamp", "symbol", "open", "high", "low", "close", "volume"}
    if not required.issubset(data.columns):
        raise ValueError("DATA_UNQUALIFIED: missing source columns")
    if data["symbol"].unique().to_list() != [DATA_SYMBOL]:
        raise ValueError("SOURCE_IDENTITY_CONFLICT: must be Dukascopy CFD alias")
    if data["timestamp"].n_unique() != data.height or data["volume"].null_count() or data["volume"].min() < 0:
        raise ValueError("DATA_UNQUALIFIED: duplicate timestamps or invalid quote volume")
    if data["timestamp"].dtype.time_zone is None:
        raise ValueError("DATA_UNQUALIFIED: timestamps must be timezone-aware")
    return data


def features_for_legacy_rules(
    source: pl.DataFrame, request: ResearchContractV1
) -> tuple[pl.DataFrame, FeatureComputation]:
    """Use M2 gateway for native ADX and independently verified extensions.

    At decision bar t, old target/stop use window INCLUDING bar t.
    Compose current high/low with registered prior 4/19 bars respectively;
    do not incorrectly shift the decision or evaluate a future bar.
    """
    if (request.dataset.source_vendor != "Dukascopy"
        or request.dataset.source_symbol != SOURCE_SYMBOL
        or request.dataset.product_class != "cfd"
        or request.dataset.volume_semantics != "broker_tick_or_quote_proxy"):
        raise ValueError("SOURCE_IDENTITY_CONFLICT: no LSE/CME substitution")
    computation = FeatureGateway().compute(source, request)
    data = computation.data.sort("timestamp")
    data = data.with_columns(
        pl.col("timestamp").dt.convert_time_zone("America/Chicago").alias("ct")
    ).with_columns(
        pl.col("ct").dt.date().alias("day"),
        pl.col("ct").dt.strftime("%H:%M").alias("clock"),
        pl.max_horizontal("high", "prior4_high").alias("next_tp"),
        pl.min_horizontal("low", "prior19_low").alias("next_sl"),
        pl.col("close").shift(1).over("symbol").alias("prior_close"),
        pl.col("adx").shift(1).over("symbol").alias("prior_adx"),
    )
    or_high = (data.filter(pl.col("clock").is_between(pl.lit("08:30"), pl.lit("08:59")))
        .group_by("day")
        .agg(pl.col("high").max().alias("or_high"), pl.len().alias("or_count"))
    )
    return data.join(or_high, on="day", how="left"), computation


def strict_sessions(
    frame: pl.DataFrame, start: date, end: date
) -> tuple[pl.DataFrame, dict]:
    """Require each XNYS full session's real continuous 08:30–15:14 CFD bars."""
    if start > end or end > SEEN_RETROSPECTIVE_END:
        raise ValueError("HOLDOUT_EXPOSED: future or undeclared retrospective window")
    calendar = xcals.get_calendar("XNYS")
    schedule = {ts.date() for ts in calendar.sessions_in_range(str(start), str(end))}
    early = {ts.date() for ts in calendar.early_closes if start <= ts.date() <= end}
    eligible = sorted(schedule - early)
    grouped = frame.filter(pl.col("day").is_between(start, end)).partition_by(
        "day", as_dict=True
    )
    accepted: list[date] = []
    excluded: dict[str, str] = {}
    for day in eligible:
        candidate = grouped.get((day,))
        if candidate is None:
            excluded[str(day)] = "MISSING_SOURCE_DAY"
            continue
        cash = candidate.filter(pl.col("clock").is_between(pl.lit("08:30"), pl.lit(CUT_OFF)))
        clocks = cash["clock"].to_list()
        if (cash.height != BAR_MINUTES or len(set(clocks)) != BAR_MINUTES
            or clocks[0] != "08:30" or clocks[-1] != CUT_OFF):
            excluded[str(day)] = "INCOMPLETE_CFD_GRID"
            continue
        if cash["timestamp"].diff().drop_nulls().to_list() != [
            timedelta(minutes=1)
        ] * (BAR_MINUTES - 1):
            excluded[str(day)] = "CFD_GRID_GAP"
            continue
        if cash["volume"].min() <= 0 or cash.select(
            "adx", "prior_adx", "prior_close", "vwap",
            "next_tp", "next_sl", "or_high"
        ).null_count().sum_horizontal().sum() != 0:
            excluded[str(day)] = "UNAVAILABLE_FEATURE_OR_PROXY_VOLUME"
            continue
        accepted.append(day)
    selection = frame.filter(
        pl.col("day").is_in(accepted) & pl.col("clock").is_between(pl.lit("08:30"), pl.lit(CUT_OFF))
    ).with_columns(pl.lit(DATA_SYMBOL).alias("asset"))
    if selection.height != len(accepted) * BAR_MINUTES:
        raise ValueError("DATA_SESSION_MISMATCH: partial source sessions")
    return selection, {
        "source_vendor": "Dukascopy",
        "source_symbol": SOURCE_SYMBOL,
        "source_sha256": SOURCE_SHA256,
        "volume_semantics": "broker_tick_or_quote_proxy",
        "hard_flat_at": "15:14 America/Chicago bar open",
        "accepted_days": [str(d) for d in accepted],
        "excluded_days": excluded,
        "retrospective_seen": True,
        "holdout_unsealed": False,
        "cme_volume_verified": False,
        "native_execution_qualified_live": False,
    }
