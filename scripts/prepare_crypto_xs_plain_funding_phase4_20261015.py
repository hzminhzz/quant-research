"""Prepare Phase 4 funding-mark requirements and bounded mark evidence.

This module never computes portfolio PnL. It derives required official mark-price
months from the frozen Phase-3 basket schedule, then materializes only the
funding-event minute marks needed by the frozen Phase-4 contract.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_crypto_xs_plain_funding_mvp_20261015 import (
    build_baskets,
    load_bounded,
    required_funding_events,
)

PHASE3 = "crypto_xs_plain_funding_mvp_20261015_v1"
PHASE4 = "crypto_xs_plain_funding_phase4_20261015_v1"
OUT = ROOT / "data" / "processed" / PHASE4
MARK_STORE = Path(
    "/home/quant/dev/quant/ml4t-data/.data/store/"
    "crypto_futures_mark_price_1m_BINANCE_UM_PERP"
)
PANEL = (
    ROOT / "run_log" / "research_sessions" / PHASE3 / "mvp" / "factor_panel.parquet"
)


def sha256(path: Path) -> str:
    with path.open("rb") as fp:
        return hashlib.file_digest(fp, "sha256").hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def derive() -> dict[str, Any]:
    if not PANEL.exists():
        raise FileNotFoundError(PANEL)
    panel = pl.read_parquet(PANEL)
    baskets = build_baskets(panel)
    _, funding = load_bounded()
    required = required_funding_events(funding, baskets)
    if required.is_empty():
        raise RuntimeError("No held-position funding events")

    months: set[tuple[str, int, int]] = set()
    for symbol, timestamp in required.select("symbol", "timestamp").iter_rows():
        minute = timestamp.replace(second=0, microsecond=0)
        prior = minute - timedelta(minutes=1)
        months.add((symbol, minute.year, minute.month))
        months.add((symbol, prior.year, prior.month))

    requirements = [
        {"symbol": symbol, "year": year, "month": month}
        for symbol, year, month in sorted(months)
    ]
    payload = {
        "phase3_session": PHASE3,
        "phase4_session": PHASE4,
        "basket_cycles": len(baskets),
        "selected_symbols": required["symbol"].n_unique(),
        "required_funding_events": required.height,
        "requirements_count": len(requirements),
        "requirements": requirements,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    _write_json(OUT / "mark_requirements.json", payload)
    required.write_parquet(OUT / "required_funding_events.parquet")
    return payload


def _partition(symbol: str, timestamp) -> Path:
    return (
        MARK_STORE
        / f"symbol={symbol}"
        / f"year={timestamp.year:04d}"
        / f"month={timestamp.month}"
        / "data.parquet"
    )


def materialize() -> dict[str, Any]:
    required_path = OUT / "required_funding_events.parquet"
    manifest_path = OUT / "mark_requirements.json"
    if not required_path.exists() or not manifest_path.exists():
        raise FileNotFoundError("Run --derive before --materialize")
    required = pl.read_parquet(required_path).sort("symbol", "timestamp")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    event_keys = required.select("symbol", "timestamp").with_columns(
        pl.col("timestamp").dt.truncate("1m").alias("mark_minute"),
        (pl.col("timestamp").dt.truncate("1m") - pl.duration(minutes=1)).alias("prior_minute"),
    )

    # Read only exact event/prior minutes from each required monthly archive.
    # Loading all 1m rows across >1,000 months would be wasteful.
    needed: dict[tuple[str, int, int], set] = {}
    for row in event_keys.select("symbol", "mark_minute", "prior_minute").iter_rows(named=True):
        for key in ("mark_minute", "prior_minute"):
            timestamp = row[key]
            bucket = (row["symbol"], timestamp.year, timestamp.month)
            needed.setdefault(bucket, set()).add(timestamp)

    pieces: list[pl.DataFrame] = []
    partitions: list[str] = []
    for (symbol, year, month), timestamps in sorted(needed.items()):
        path = (
            MARK_STORE / f"symbol={symbol}" / f"year={year:04d}"
            / f"month={month}" / "data.parquet"
        )
        if not path.exists():
            raise FileNotFoundError(f"Missing canonical mark partition: {path}")
        partitions.append(str(path))
        needed_times = pl.Series(
            "needed_times",
            sorted(timestamps),
            dtype=pl.Datetime("ms", "UTC"),
        )
        piece = (
            pl.scan_parquet(path)
            .filter(pl.col("timestamp").is_in(needed_times))
            .select("timestamp", "symbol", "open", "high", "low", "close")
            .collect()
        )
        pieces.append(piece)
    marks = pl.concat(pieces).sort("symbol", "timestamp")
    if marks.group_by("symbol", "timestamp").len().filter(pl.col("len") > 1).height:
        raise RuntimeError("Duplicate canonical mark-price timestamps")
    if marks.filter(
        (~pl.col("open").is_finite())
        | (~pl.col("high").is_finite())
        | (~pl.col("low").is_finite())
        | (~pl.col("close").is_finite())
        | (pl.col("low") <= 0)
        | (pl.col("high") < pl.col("low"))
        | (pl.col("open") < pl.col("low"))
        | (pl.col("open") > pl.col("high"))
        | (pl.col("close") < pl.col("low"))
        | (pl.col("close") > pl.col("high"))
    ).height:
        raise RuntimeError("Invalid canonical mark-price OHLC")

    current = marks.rename({"timestamp": "mark_minute"})
    prior = marks.select(
        "symbol",
        pl.col("timestamp").alias("prior_minute"),
        pl.col("close").alias("prior_mark_close"),
    )
    joined = (
        required.join(event_keys, on=["symbol", "timestamp"], how="left")
        .join(current, on=["symbol", "mark_minute"], how="left")
        .join(prior, on=["symbol", "prior_minute"], how="left")
        .sort("timestamp", "symbol")
    )
    missing_prior = joined.filter(pl.col("prior_mark_close").is_null())
    if missing_prior.height:
        example = missing_prior.select(
            "timestamp", "symbol", "mark_minute", "prior_minute"
        ).head(10)
        raise RuntimeError(
            f"Missing prior-minute official mark rows: {missing_prior.height}; {example}"
        )

    fallback = joined.filter(pl.col("open").is_null())
    expected_fallback_ts = datetime(2023, 2, 24, 0, 0, 0, 15_000, tzinfo=UTC)
    if fallback.height:
        fallback_identity = fallback.select("symbol", "timestamp").to_dicts()
        if fallback_identity != [{
            "symbol": "LITUSDT",
            "timestamp": expected_fallback_ts,
        }]:
            raise RuntimeError(
                "Unexpected event-minute mark fallback requirements: "
                f"{fallback_identity}"
            )

    joined = joined.with_columns(
        pl.coalesce(["open", "prior_mark_close"]).alias("mark_proxy"),
        pl.when(pl.col("open").is_not_null())
        .then(pl.lit("EVENT_MINUTE_OPEN"))
        .otherwise(pl.lit("PRIOR_MINUTE_CLOSE_FALLBACK"))
        .alias("mark_quality"),
    )

    # Research-session audit receives only real official mark bars, never a
    # synthetic event-minute row. Keep both event and prior minutes because
    # both are part of the frozen accounting/sensitivity evidence.
    mark_panel = marks.unique(
        subset=["symbol", "timestamp"], maintain_order=True
    ).sort("symbol", "timestamp")
    if mark_panel.group_by("symbol", "timestamp").len().filter(pl.col("len") > 1).height:
        raise RuntimeError("Duplicate required event-minute mark rows")
    mark_panel.write_parquet(OUT / "required_funding_mark_1m.parquet")
    joined.write_parquet(OUT / "required_funding_events_with_marks.parquet")

    deltas = joined.with_columns(
        ((pl.col("mark_proxy") / pl.col("prior_mark_close")) - 1)
        .alias("proxy_vs_prior_close")
    )
    source_manifest: dict[str, Any] = {
        "mark_store": str(MARK_STORE),
        "archive_importer": {},
        "rest_gap_filler": {},
        "partitions": [],
    }
    for label, script_path in (
        (
            "archive_importer",
            Path("/home/quant/dev/quant/ml4t-data/scripts/fetch_binance_mark_price_1m.py"),
        ),
        (
            "rest_gap_filler",
            Path("/home/quant/dev/quant/ml4t-data/scripts/fill_binance_mark_price_1m_gaps.py"),
        ),
    ):
        source_manifest[label] = {
            "path": str(script_path),
            "sha256": sha256(script_path),
        }
    for partition_text in sorted(set(partitions)):
        partition = Path(partition_text)
        source_json = partition.parent / "source.json"
        rest_json = partition.parent / "rest_gap_sources.json"
        if not source_json.exists():
            raise FileNotFoundError(f"Missing archive lineage sidecar: {source_json}")
        entry: dict[str, Any] = {
            "partition": str(partition),
            "archive_source": json.loads(source_json.read_text(encoding="utf-8")),
            "archive_source_sidecar_sha256": sha256(source_json),
        }
        if rest_json.exists():
            entry["rest_gap_sources"] = json.loads(
                rest_json.read_text(encoding="utf-8")
            )
            entry["rest_gap_sidecar_sha256"] = sha256(rest_json)
        source_manifest["partitions"].append(entry)
    _write_json(OUT / "mark_source_manifest.json", source_manifest)

    result = {
        "required_funding_events": joined.height,
        "symbols": joined["symbol"].n_unique(),
        "mark_partitions": len(set(partitions)),
        "event_minute_open_count": joined.filter(
            pl.col("mark_quality") == "EVENT_MINUTE_OPEN"
        ).height,
        "prior_minute_fallback_count": joined.filter(
            pl.col("mark_quality") == "PRIOR_MINUTE_CLOSE_FALLBACK"
        ).height,
        "prior_minute_fallback_events": fallback.select(
            "timestamp", "symbol", "prior_minute", "prior_mark_close"
        ).to_dicts(),
        "all_required_mark_proxies_resolved": True,
        "all_prior_minute_closes_present": True,
        "max_abs_proxy_vs_prior_close": float(
            deltas["proxy_vs_prior_close"].abs().max()
        ),
        "p99_abs_proxy_vs_prior_close": float(
            deltas["proxy_vs_prior_close"].abs().quantile(0.99)
        ),
        "mark_panel_path": str(
            (OUT / "required_funding_mark_1m.parquet").relative_to(ROOT)
        ),
        "mark_panel_sha256": sha256(OUT / "required_funding_mark_1m.parquet"),
        "event_marks_path": str(
            (OUT / "required_funding_events_with_marks.parquet").relative_to(ROOT)
        ),
        "event_marks_sha256": sha256(
            OUT / "required_funding_events_with_marks.parquet"
        ),
        "mark_store": str(MARK_STORE),
        "mark_source_manifest_path": str(
            (OUT / "mark_source_manifest.json").relative_to(ROOT)
        ),
        "mark_source_manifest_sha256": sha256(OUT / "mark_source_manifest.json"),
    }
    _write_json(OUT / "mark_materialization_audit.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--derive", action="store_true")
    parser.add_argument("--materialize", action="store_true")
    args = parser.parse_args()
    if args.derive == args.materialize:
        parser.error("Choose exactly one of --derive or --materialize")
    result = derive() if args.derive else materialize()
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
