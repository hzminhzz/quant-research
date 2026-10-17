"""Price-only, source-identified FX, index, and precious-metal canonical panels.

Materializes observed vendor OHLCV bars, NOT an execution-qualified CFD feed.
No synthetic swap or spread is charged. Runtime provenance blocks Stage 3 until
an explicit, independently audited broker cost/carry adapter is available.

Trusted bounded month/day ingestion writes separate development/protected files.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import polars as pl

from src.engine.common import QuantError, digest, file_hash, read_json, utc, write_json

from .panel_builder import (
    CANONICAL_COLUMNS,
    PanelBuilder,
    parquet_bounds,
    symbol_partition_name,
    validate_panel,
)

MarketGroup = Literal["forex", "index", "metals"]
Granularity = Literal["1s", "1m", "1h", "1d"]
BAR_SECONDS = {"1s": 1, "1m": 60, "1h": 3600, "1d": 86400}
RAW_FIELDS = ["timestamp", "symbol", "open", "high", "low", "close", "volume"]
BUILD_VERSION = "price-only-monthly-v1"

@dataclass(frozen=True)
class PriceSource:
    symbol: str
    category: MarketGroup
    granularity: Granularity
    root: str
    source_frequency: str
    source_seconds: int
    session_model: str = "UTC source-bar calendar, no broker schedule inferred"


def source_raw_symbol(source: PriceSource) -> str:
    # This observed USDJPY daily feed encodes the internal ticker as JPY.
    # Its Dec 1, 2025 open/close (155.907/155.561) agree with independent
    # minute USDJPY quotes (155.900/155.556), not inverted JPY/USD.
    if source.category == "forex" and source.granularity == "1d" and source.symbol == "USDJPY":
        return "JPY"
    return source.symbol


def discover_price_sources(
    store: str | Path, *, category: MarketGroup, granularity: Granularity,
) -> tuple[list[PriceSource], list[dict]]:
    """Conservative namespace discovery; duplicate or misleading aliases excluded."""
    root = Path(store).resolve()
    if category not in ("forex", "index", "metals") or granularity not in BAR_SECONDS:
        raise QuantError("INVALID_SPEC", "Choose forex/index/metals and 1s/1m/1h/1d")
    # Precious metals are separately labeled USD quotes; not currency pairs.
    if granularity == "1d" and category == "metals":
        return [], [{"source": "forex_daily_XAUUSD/XAGUSD", "status": "NOT_DISCOVERED",
                     "reason": "No metals_daily namespace in the inspected local store"}]
    if granularity == "1s" and category != "index":
        return [], [{"status": "NOT_DISCOVERED", "source": f"{category}_second_*"}]
    namespace = "index" if category == "index" else "forex"
    freq = "second" if granularity == "1s" else "minute" if granularity in ("1m", "1h") else "daily"
    pattern = f"{namespace}_{freq}_*"
    sources, excluded = [], []
    for path in sorted(root.glob(pattern)):
        if not path.is_dir():
            continue
        symbol = path.name.removeprefix(f"{namespace}_{freq}_")
        is_metal = symbol in ("XAUUSD", "XAGUSD")
        if (category == "metals") != is_metal:
            continue
        files = sorted(path.rglob("*.parquet"))
        if not files:
            excluded.append({"source": str(path), "symbol": symbol, "status": "EMPTY_SOURCE"})
            continue
        import pyarrow.parquet as pq
        arrow = pq.read_table(files[0], columns=["symbol"])
        observed = set(arrow.column("symbol").to_pylist())
        candidate = PriceSource(symbol=symbol, category=category, granularity=granularity,
                                root=str(path), source_frequency=freq,
                                source_seconds=1 if granularity == "1s" else 60 if granularity in ("1m", "1h") else 86400)
        if observed != {source_raw_symbol(candidate)}:
            excluded.append({"source": str(path), "symbol": symbol, "status": "ALIAS_MISMATCH",
                             "observed": sorted(observed),
                             "reason": "Do not double count path aliases as separate instruments"})
            continue
        sources.append(candidate)
    return sources, excluded


def _month_group(files: list[Path], source: PriceSource) -> dict[tuple[int, int, int | None], list[Path]]:
    grouped = defaultdict(list)
    for path in files:
        year = next((int(part.split("=", 1)[1]) for part in path.parts
                     if part.startswith("year=") and part[5:].isdigit()), None)
        month = next((int(part.split("=", 1)[1]) for part in path.parts
                      if part.startswith("month=") and part[6:].isdigit()), None)
        if year is None or month is None or not 1 <= month <= 12:
            raise QuantError("BLOCKED_DATA", f"Cannot identify source month for {source.symbol}: {path}")
        day = (next((int(part.split("=", 1)[1]) for part in path.parts
                     if part.startswith("day=") and part[4:].isdigit()), None)
               if source.granularity == "1s" else None)
        if source.granularity == "1s" and (day is None or not 1 <= day <= 31):
            raise QuantError("BLOCKED_DATA", f"Second-level ingestion needs daily slices: {path}")
        grouped[(year, month, day)].append(path)
    return dict(sorted(grouped.items()))


def _monthly_panel(
    source: PriceSource, files: list[Path], left: datetime, right: datetime,
) -> tuple[pl.DataFrame, dict]:
    # Check every input footer before decode; source has explicit UTC clocks.
    for path in files:
        start, end = parquet_bounds(path)
        if start >= right or end < left:
            raise QuantError("INVALID_EVIDENCE", f"Source month/path has out-of-window timestamps: {path}")
    raw = (pl.scan_parquet(files, hive_partitioning=False).select(RAW_FIELDS)
           .filter((pl.col("timestamp") >= left) & (pl.col("timestamp") < right))
           .collect(engine="streaming").sort("timestamp"))
    if raw.is_empty():
        raise QuantError("BLOCKED_DATA", f"No source rows in month for {source.symbol}")
    if raw["timestamp"].n_unique() != raw.height or raw["symbol"].unique().to_list() != [source_raw_symbol(source)]:
        raise QuantError("BLOCKED_DATA", f"Duplicate UTC timestamps or source identity change: {source.symbol}")
    raw = raw.with_columns(pl.col("timestamp").cast(pl.Datetime("us", "UTC")))
    if source.granularity == "1h":
        # Each 60-minute bar remains present even when a minute is absent, but
        # is_tradable=False unless 60 complete, unique adjacent minutes exist.
        bucket = pl.col("timestamp").dt.truncate("1h")
        monthly = (raw.group_by(bucket)
                   .agg(pl.col("open").sort_by("timestamp").first(),
                        pl.col("high").max(), pl.col("low").min(),
                        pl.col("close").sort_by("timestamp").last(),
                        pl.col("volume").sum(),
                        pl.len().alias("_n"),
                        pl.col("timestamp").min().alias("_first"),
                        pl.col("timestamp").max().alias("_last"))
                   .sort("timestamp"))
        complete = ((pl.col("_n") == 60) &
                    (pl.col("_first") == pl.col("timestamp")) &
                    (pl.col("_last") == pl.col("timestamp") + pl.duration(minutes=59)))
        monthly = monthly.with_columns(complete.alias("is_tradable"))
    else:
        monthly = raw
        # Copy native 1-second, 1-minute or daily OHLC without resampling.
        # Missing timestamps are not filled. Observed bar != broker fill proof.
        monthly = monthly.with_columns(
            (pl.col("timestamp") == pl.col("timestamp").dt.truncate(source.granularity))
            .alias("is_tradable"))
    monthly = (monthly.with_columns(
        pl.lit(source.symbol).alias("symbol"),
        pl.lit(0.0).alias("carry_rate"),
        pl.lit(0.0).alias("spread_bps"),
        pl.col("timestamp").dt.strftime("%Y-%m-%d").alias("session_id"),
        ((pl.col("timestamp").dt.hour().cast(pl.Int32) * (3600 // BAR_SECONDS[source.granularity])
          + pl.col("timestamp").dt.minute().cast(pl.Int32) * (60 // BAR_SECONDS[source.granularity])
          + pl.col("timestamp").dt.second().cast(pl.Int32) // BAR_SECONDS[source.granularity])
         if source.granularity != "1d" else pl.lit(0))
            .cast(pl.Int32).alias("bar_in_session"))
        .select(CANONICAL_COLUMNS))
    validated = validate_panel(monthly)
    audit = {
        "source_rows": raw.height, "canonical_rows": validated.height,
        "incomplete_or_unaligned_rows": validated.filter(~pl.col("is_tradable")).height,
        "observed_gaps_gt_source_cadence": int(raw.select(
            (pl.col("timestamp").diff().dt.total_seconds() > source.source_seconds)
            .sum().fill_null(0)).item()),
        "missing_intervals_policy": "missing clock ticks unfilled; no gap imputation",
        "minimum_timestamp": validated["timestamp"].min().isoformat(),
        "maximum_timestamp": validated["timestamp"].max().isoformat(),
    }
    return validated, audit


def materialize_price_markets(
    store: str | Path, output: str | Path, *,
    category: MarketGroup, granularity: Granularity,
    start: str | datetime = "2000-01-01T00:00:00Z",
    end: str | datetime = "2026-10-01T00:00:00Z",
    protected_test_start: str | datetime = "2026-01-01T00:00:00Z",
    trusted_partitioning: bool = False,
) -> dict:
    first, last, cutoff = utc(start), utc(end), utc(protected_test_start)
    if first >= last:
        raise QuantError("INVALID_SPEC", "Invalid source time window")
    if last > cutoff and not trusted_partitioning:
        raise QuantError("BLOCKED_DATA", "Protected compilation requires trusted_partitioning")
    if last > datetime.now(UTC) + timedelta(days=1):
        raise QuantError("INVALID_SPEC", "Requested range extends beyond the observed calendar")
    builder = PanelBuilder(store, output, protected_test_start=cutoff)
    sources, exclusions = discover_price_sources(builder.store, category=category, granularity=granularity)
    if not sources:
        raise QuantError("BLOCKED_DATA", f"No independent {category}/{granularity} source")
    out = builder.output
    checkpoints = out / ".checkpoints"
    checkpoints.mkdir(parents=True, exist_ok=True)
    entries, audits = [], []
    for source in sources:
        groups = _month_group(sorted(Path(source.root).rglob("*.parquet")), source)
        for (year, month, day), files in groups.items():
            chunk_start = datetime(year, month, day or 1, tzinfo=UTC)
            chunk_end = (chunk_start + timedelta(days=1) if day is not None else
                         (chunk_start.replace(day=28) + timedelta(days=4)).replace(day=1))
            left, right = max(first, chunk_start), min(last, chunk_end)
            slice_label = f"{year:04d}-{month:02d}" + (f"-{day:02d}" if day is not None else "")
            if left >= right:
                continue
            # Half-open monthly/daily buckets never straddle January 1 holdout,
            # even if the underlying vendor Parquet covers multiple days.
            partition = "development" if left < cutoff else "protected"
            input_files = {str(path): file_hash(path) for path in files}
            identity = {
                "builder": BUILD_VERSION, "source": asdict(source),
                "category": category, "granularity": granularity,
                "start": left.isoformat(), "end": right.isoformat(),
                "cutoff": cutoff.isoformat(), "input_files": input_files,
                "carry_status": "UNKNOWN_NOT_EXECUTION_QUALIFIED",
                "spread_status": "UNKNOWN_NOT_EXECUTION_QUALIFIED",
            }
            receipt_file = checkpoints / (digest(identity) + ".json")
            if receipt_file.exists():
                record = read_json(receipt_file)
                payload = dict(record)
                checksum = payload.pop("receipt_hash", None)
                if checksum != digest(payload) or record.get("identity") != identity:
                    raise QuantError("INVALID_EVIDENCE", "Price-only checkpoint metadata changed")
                for item in record["entries"]:
                    path = out / item["path"]
                    if not path.is_file() or file_hash(path) != item["sha256"] or                        parquet_bounds(path) != (utc(item["start"]), utc(item["last"])):
                        raise QuantError("INVALID_EVIDENCE", f"Price-only receipt output changed: {path}")
                    entries.append(item)
                audits.append(record["audit"])
                continue
            expected = (out / partition / symbol_partition_name(source.symbol) /
                        f"panel-{slice_label}.parquet")
            if expected.exists():
                raise QuantError("INVALID_EVIDENCE",
                                 f"Unreceipted output requires manual source/content reconciliation: {expected}")
            try:
                panel, audit = _monthly_panel(source, files, left, right)
                provenance = {
                    "source": asdict(source), "source_files": input_files,
                    "raw_vendor_symbol": source_raw_symbol(source),
                    "identity_override": "AUDITED_USDJPY_DAILY_VENDOR_JPY_ALIAS"
                    if source_raw_symbol(source) != source.symbol else None,
                    "product": ("index_tracking_etf_price_proxy" if source.symbol == "SPY" else
                                "index_vendor_quote_proxy") if category == "index" else (
                                "precious_metal_quote_proxy" if category == "metals" else "forex_quote_proxy"),
                    "source_timestamp_semantics": "UTC opening timestamp as stored; daily source release clock unverified",
                    "event_time": "source opening timestamp UTC",
                    "available_time": f"bar close after {BAR_SECONDS[granularity]} seconds (research assumption)",
                    "volume_semantics": "vendor_reported_quote_or_tick_proxy_not_exchange_turnover",
                    "session_calendar": "UTC source-observed calendar, not verified broker dealing hours",
                    "carry_assumption": "unknown CFD swap/rollover; 0 is SCHEMA PLACEHOLDER, not observed zero",
                    "spread_assumption": "unknown broker spread; 0 is SCHEMA PLACEHOLDER, not observed zero",
                    "carry_status": "UNKNOWN_NOT_EXECUTION_QUALIFIED",
                    "spread_status": "UNKNOWN_NOT_EXECUTION_QUALIFIED",
                    "execution_qualified": False,
                    "observed_timestamp_coverage_only": True,
                    "historical_recorded_time": "unavailable; immutable ingested source snapshot",
                    **audit,
                }
                published = builder.publish(panel, funding=None, provenance=provenance,
                                            write_manifest=False, bar_seconds=BAR_SECONDS[granularity],
                                            slice_name=slice_label)
                receipt = {"identity": identity, "entries": published, "audit": {
                    "symbol": source.symbol, "partition": partition,
                    "month": slice_label, **audit,
                }}
                receipt["receipt_hash"] = digest(receipt)
                write_json(receipt_file, receipt, exclusive=True)
                entries.extend(published)
                audits.append(receipt["audit"])
            except QuantError as error:
                if error.status == "INVALID_EVIDENCE":
                    raise
                exclusions.append({
                    "source": source.root, "symbol": source.symbol,
                    "month": slice_label, "status": error.status,
                    "reason": error.reason,
                })
    if not entries:
        raise QuantError("BLOCKED_DATA", f"No {category}/{granularity} panels were built")
    summary = {
        "source_group": category, "granularity": granularity,
        "sources_discovered": len(sources),
        "symbols_built": len({entry["symbol"] for entry in entries}),
        "rows_by_partition": {
            kind: sum(e["rows"] for e in entries if e["kind"] == kind and e["table"] == "prices")
            for kind in ("development", "protected")},
        "incomplete_bars": sum(a["incomplete_or_unaligned_rows"] for a in audits),
        "observed_gaps_gt_cadence": sum(a["observed_gaps_gt_source_cadence"] for a in audits),
        "source_provenance": "price-only, no financing/spread certification",
        "execution_qualified": False,
    }
    manifest = builder._manifest(entries, exclusions, BAR_SECONDS[granularity])
    manifest.update({"market_group": category, "source_granularity": granularity,
                     "quality_summary": summary})
    manifest.pop("manifest_hash")
    manifest["manifest_hash"] = digest(manifest)
    existing_path = out / "manifest.json"
    if existing_path.is_file():
        old = read_json(existing_path)
        old_digest = old.get("manifest_hash")
        old_payload = {k: v for k, v in old.items() if k != "manifest_hash"}
        if old_digest != digest(old_payload):
            raise QuantError("INVALID_EVIDENCE", "Previously published manifest was modified")
        def stable_fields(payload):
            return {k: v for k, v in payload.items() if k not in ("manifest_hash", "ingested_at")}
        if stable_fields(old) == stable_fields(manifest):
            return old
    write_json(existing_path, manifest)
    return manifest
