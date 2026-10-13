"""Prepare frozen, price-only 30-minute bars from the qualified minute store."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

import polars as pl

EXPECTED_KEY = "index_minute_NQ"
EXPECTED_SOURCE = "usatechidxusd"
WARMUP_START = datetime(2019, 12, 1, tzinfo=UTC)
EVALUATION_END = datetime(2025, 1, 1, tzinfo=UTC)
BAR_MINUTES = 30


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_files(store: Path) -> list[Path]:
    root = store / EXPECTED_KEY
    paths = [*root.glob("year=2019/month=12/day=*/data.parquet")]
    for year in range(2020, 2025):
        paths.extend(root.glob(f"year={year}/month=*/day=*/data.parquet"))
    start = WARMUP_START.date()
    end = EVALUATION_END.date()
    return sorted(
        path
        for path in paths
        if start
        <= date(
            int(path.parents[2].name[5:]),
            int(path.parents[1].name[6:]),
            int(path.parent.name[4:]),
        )
        < end
    )


def _load_source(paths: list[Path]) -> pl.DataFrame:
    if not paths:
        raise ValueError("DATA_UNAVAILABLE: no source files in the frozen date window")
    data = (
        pl.read_parquet(paths)
        .select("timestamp", "symbol", "open", "high", "low", "close", "volume")
        .sort("timestamp")
    )
    if data["timestamp"].dtype.time_zone != "UTC":
        raise ValueError("DATA_UNQUALIFIED: source timestamps must be UTC-aware")
    if data["symbol"].unique().to_list() != ["NQ"]:
        raise ValueError(
            "SOURCE_IDENTITY_CONFLICT: expected the NQ catalog store symbol"
        )
    if data["timestamp"].n_unique() != data.height:
        raise ValueError("DATA_UNQUALIFIED: minute timestamps are not unique")
    invalid = data.filter(
        (pl.col("timestamp") < WARMUP_START)
        | (pl.col("timestamp") >= EVALUATION_END)
        | (pl.col("high") < pl.col("low"))
        | (pl.col("open") < pl.col("low"))
        | (pl.col("open") > pl.col("high"))
        | (pl.col("close") < pl.col("low"))
        | (pl.col("close") > pl.col("high"))
        | pl.any_horizontal(pl.col("open", "high", "low", "close", "volume").is_null())
        | pl.any_horizontal(
            pl.col("open", "high", "low", "close", "volume").is_finite().not_()
        )
        | (pl.col("volume") < 0)
    ).height
    if invalid:
        raise ValueError(f"DATA_UNQUALIFIED: {invalid} invalid minute rows")
    return data


def aggregate_30m(data: pl.DataFrame) -> pl.DataFrame:
    """Aggregate only complete 30-minute windows with exact minute continuity."""
    grouped = (
        data.sort("timestamp")
        .group_by_dynamic(
            "timestamp",
            every="30m",
            period="30m",
            closed="left",
            label="left",
            start_by="window",
            group_by="symbol",
        )
        .agg(
            pl.len().alias("minute_count"),
            pl.col("timestamp").first().alias("first_minute"),
            pl.col("timestamp").last().alias("last_minute"),
            pl.col("timestamp").diff().drop_nulls().n_unique().alias("minute_steps"),
            pl.col("open").first(),
            pl.col("high").max(),
            pl.col("low").min(),
            pl.col("close").last(),
            pl.col("volume").sum(),
        )
    )
    expected_last = pl.col("timestamp") + pl.duration(minutes=BAR_MINUTES - 1)
    bars = (
        grouped.filter(
            (pl.col("minute_count") == BAR_MINUTES)
            & (pl.col("first_minute") == pl.col("timestamp"))
            & (pl.col("last_minute") == expected_last)
            & (pl.col("minute_steps") == 1)
        )
        .select("timestamp", "symbol", "open", "high", "low", "close", "volume")
        .sort("timestamp")
    )
    _assert_python_oracle(data, bars)
    return bars


def _assert_python_oracle(minutes: pl.DataFrame, bars: pl.DataFrame) -> None:
    bins: dict[datetime, list[dict[str, Any]]] = {}
    for row in minutes.iter_rows(named=True):
        stamp = row["timestamp"]
        minute_of_day = stamp.hour * 60 + stamp.minute
        start = stamp.replace(
            minute=(minute_of_day // BAR_MINUTES) * BAR_MINUTES % 60,
            second=0,
            microsecond=0,
        )
        if minute_of_day // BAR_MINUTES % 2:
            start = start.replace(
                hour=stamp.hour - 1 if stamp.minute < 30 else stamp.hour, minute=30
            )
        else:
            start = start.replace(minute=0)
        bins.setdefault(start, []).append(row)
    expected: dict[datetime, tuple[float, ...]] = {}
    for start, rows in bins.items():
        stamps = [row["timestamp"] for row in rows]
        if (
            len(rows) != BAR_MINUTES
            or stamps[0] != start
            or stamps[-1] != start + timedelta(minutes=29)
        ):
            continue
        if any(
            right - left != timedelta(minutes=1) for left, right in pairwise(stamps)
        ):
            continue
        expected[start] = (
            rows[0]["open"],
            max(row["high"] for row in rows),
            min(row["low"] for row in rows),
            rows[-1]["close"],
            sum(row["volume"] for row in rows),
        )
    actual = {
        row["timestamp"]: (
            row["open"],
            row["high"],
            row["low"],
            row["close"],
            row["volume"],
        )
        for row in bars.iter_rows(named=True)
    }
    if actual != expected:
        raise ValueError(
            f"BAR_AGGREGATION_MISMATCH: independent oracle found {len(expected)} bars; "
            f"Polars produced {len(actual)}"
        )


def _verify_catalog(store: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    catalog_path = store / ".catalog" / "research-dataset-catalog.json"
    acceptance_path = store / ".acceptance" / EXPECTED_KEY / "dataset.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    record = next(
        (entry for entry in catalog["entries"] if entry["dataset_key"] == EXPECTED_KEY),
        None,
    )
    if (
        record is None
        or record.get("provider") != "dukascopy"
        or record.get("source_symbol") != EXPECTED_SOURCE
        or record.get("authority") != "canonical"
        or record.get("qualification") != "accepted"
        or record.get("capabilities", {}).get("contract_level_futures") is not False
    ):
        raise ValueError(
            "SOURCE_IDENTITY_CONFLICT: live catalog differs from the frozen CFD source"
        )
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    return (
        {
            "path": ".catalog/research-dataset-catalog.json",
            "sha256": _sha256(catalog_path),
            "catalog_identity": catalog["catalog_identity"],
            "entry_identity": record["entry_identity"],
            "consumer_identity": record["consumer_identity"],
        },
        {
            "path": ".acceptance/index_minute_NQ/dataset.json",
            "sha256": _sha256(acceptance_path),
            "record": acceptance,
        },
    )


def prepare(store: Path, root: Path) -> dict[str, Any]:
    catalog, acceptance = _verify_catalog(store)
    paths = _source_files(store)
    minute_data = _load_source(paths)
    bars = aggregate_30m(minute_data)
    if bars.is_empty():
        raise ValueError("DATA_UNAVAILABLE: no complete 30-minute source bars")
    bars = bars.with_columns(pl.lit(EXPECTED_SOURCE).alias("symbol"))

    output = (
        root
        / "data/research_sessions/m8_n8_dukascopy_nas100_cfd_30m_v1/prices_30m.parquet"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    bars.write_parquet(output, compression="zstd")
    fingerprint_path = root / "run_log/m8/n8/source_fingerprints_recovery.json"
    fingerprint_path.parent.mkdir(parents=True, exist_ok=True)
    fingerprint = {
        "schema_version": 1,
        "source": "Dukascopy NAS100 CFD price proxy; canonical key index_minute_NQ",
        "source_symbol": EXPECTED_SOURCE,
        "catalog": catalog,
        "acceptance": {
            key: value for key, value in acceptance.items() if key != "record"
        },
        "acceptance_identity": acceptance["record"],
        "source_window_utc": {
            "warmup_start_inclusive": WARMUP_START.isoformat(),
            "evaluation_start_inclusive": "2020-01-01T00:00:00+00:00",
            "evaluation_end_exclusive": EVALUATION_END.isoformat(),
            "holdout_start": "2025-01-01T00:00:00+00:00",
            "holdout_accessed": False,
        },
        "minute_files": [
            {
                "path": str(path.relative_to(store)),
                "sha256": _sha256(path),
                "size_bytes": path.stat().st_size,
            }
            for path in paths
        ],
        "minute_rows": minute_data.height,
        "complete_30m_bars": bars.height,
        "bar_recipe": {
            "interval": "30m UTC, epoch-aligned, half-open [start,start+30m)",
            "open": "first source 1m open",
            "high": "maximum source 1m high",
            "low": "minimum source 1m low",
            "close": "last source 1m close",
            "volume": "sum of Dukascopy provider units; not used by the price-only signal",
            "eligibility": "exactly 30 unique, contiguous UTC minute bars per 30m interval",
            "oracle": "independent Python aggregation checked every retained interval",
            "timestamp_semantics": "source catalog identifies UTC minute timestamps; candle-open alignment checked against interval starts",
        },
        "derived_data": {
            "path": str(output.relative_to(root)),
            "sha256": _sha256(output),
            "size_bytes": output.stat().st_size,
            "schema": {name: str(dtype) for name, dtype in bars.schema.items()},
        },
        "limitations": [
            "The series is a Dukascopy CFD price proxy, not NQ futures or a named broker contract.",
            "Broker trading calendar, point value, costs, lot limits, and margin remain unverified.",
            "Signal eligibility uses the frozen weekly GMT schedule and conservative US-market holiday exclusions; actual missing scheduled fills block the trial.",
            "The transferred source is page-separated PDF text. The original 12-page PDF bytes are not in this checkout.",
        ],
    }
    fingerprint_path.write_text(
        json.dumps(fingerprint, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return {
        "fingerprint_path": str(fingerprint_path.relative_to(root)),
        "fingerprint_sha256": _sha256(fingerprint_path),
        "derived_path": str(output.relative_to(root)),
        "derived_sha256": _sha256(output),
        "minute_files": len(paths),
        "minute_rows": minute_data.height,
        "complete_30m_bars": bars.height,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    print(json.dumps(prepare(args.store.resolve(), args.root.resolve()), indent=2))


if __name__ == "__main__":
    main()
