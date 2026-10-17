"""Materialize only staged CADJPY 2023/2024 Arrow files under ML4T schema."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl
from ml4t.data.core.schemas import MultiAssetSchema

ROOT = Path(__file__).resolve().parents[1]
STAGE = Path("/home/quant/dev/quant/ml4t-data/.data/staging/dukascopy-cadjpy-20261013")
DEST_DIR = ROOT / "data/processed/mechanicalpremia_yen_squeeze_proxy_20261014"
TARGET = DEST_DIR / "CADJPY_2023_2024_1m.parquet"
START = datetime(2023, 1, 1, tzinfo=timezone.utc)
END = datetime(2025, 1, 1, tzinfo=timezone.utc)
YEARS = (2023, 2024)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _issues(frame: pl.DataFrame) -> dict[str, int]:
    return {
        "duplicate_timestamp_rows": frame.height - frame["timestamp"].n_unique(),
        "wrong_symbol_rows": frame.filter(pl.col("symbol") != "CADJPY").height,
        "high_below_low_rows": frame.filter(pl.col("high") < pl.col("low")).height,
        "open_outside_range_rows": frame.filter((pl.col("open") < pl.col("low")) | (pl.col("open") > pl.col("high"))).height,
        "close_outside_range_rows": frame.filter((pl.col("close") < pl.col("low")) | (pl.col("close") > pl.col("high"))).height,
        "null_or_nonfinite_ohlc_rows": frame.filter(
            pl.any_horizontal(
                pl.col("open", "high", "low", "close", "volume").is_null()
                | pl.col("open", "high", "low", "close", "volume").is_finite().not_()
            )
        ).height,
        "unaligned_minute_rows": frame.filter(pl.col("timestamp").dt.truncate("1m") != pl.col("timestamp")).height,
        "rows_outside_bounded_interval": frame.filter(
            (pl.col("timestamp") < pl.lit(START)) | (pl.col("timestamp") >= pl.lit(END))
        ).height,
    }


def materialize() -> dict[str, Any]:
    if TARGET.exists():
        raise FileExistsError(f"Refuse to replace bounded snapshot: {TARGET}")
    annual: list[dict[str, Any]] = []
    frames: list[pl.DataFrame] = []
    for year in YEARS:
        source = STAGE / f"cadjpy_{year}.arrow"
        if not source.is_file():
            raise FileNotFoundError(f"required staged year absent: {source}")
        frame = pl.read_ipc(source)
        schema = frame.schema
        required = {"timestamp", "symbol", "open", "high", "low", "close", "volume"}
        if required.difference(frame.columns):
            raise ValueError(f"{source.name}: missing canonical fields {sorted(required.difference(frame.columns))}")
        # ML4T's Dukascopy reader converts epoch milliseconds into naive datetimes;
        # localize those UTC instants explicitly before applying its data contract.
        ts_dtype = frame.schema["timestamp"]
        if not isinstance(ts_dtype, pl.Datetime):
            raise TypeError(f"{source.name}: timestamp is not Datetime: {ts_dtype}")
        if ts_dtype.time_zone is None:
            frame = frame.with_columns(pl.col("timestamp").dt.replace_time_zone("UTC"))
            timezone_action = "naive epoch-millisecond timestamps localized to UTC per ml4t-data Dukascopy provider behavior"
        elif ts_dtype.time_zone == "UTC":
            timezone_action = "already timezone-aware UTC"
        else:
            raise ValueError(f"{source.name}: unexpected timezone {ts_dtype.time_zone}")
        frame = frame.select("timestamp", "symbol", "open", "high", "low", "close", "volume").sort("timestamp")
        frame = frame.with_columns(
            pl.col("timestamp").cast(pl.Datetime("us", "UTC")),
            pl.col("symbol").cast(pl.String),
            pl.col("open", "high", "low", "close", "volume").cast(pl.Float64),
        )
        MultiAssetSchema.validate(frame, strict=True)
        issues = _issues(frame)
        if any(issues.values()):
            raise ValueError(f"{source.name}: data contract issues: {issues}")
        if frame.is_empty() or frame["timestamp"].dt.year().unique().to_list() != [year]:
            raise ValueError(f"{source.name}: year coverage does not match its bounded file identity")
        annual.append({
            "year": year,
            "path": str(source),
            "size_bytes": source.stat().st_size,
            "sha256": _sha256(source),
            "arrow_schema_before_normalization": str(schema),
            "timezone_action": timezone_action,
            "rows": frame.height,
            "first_timestamp": str(frame["timestamp"].min()),
            "last_timestamp": str(frame["timestamp"].max()),
            "unique_months_present": sorted(frame["timestamp"].dt.month().unique().to_list()),
            "quality_issues": issues,
        })
        frames.append(frame)

    combined = pl.concat(frames).sort("timestamp")
    issues = _issues(combined)
    if any(issues.values()):
        raise ValueError(f"combined CADJPY snapshot failed: {issues}")
    if combined["timestamp"].n_unique() != combined.height:
        raise ValueError("overlapping annual Arrow files contain duplicate timestamps")
    MultiAssetSchema.validate(combined, strict=True)
    if combined.filter(pl.col("timestamp") >= pl.lit(END)).height:
        raise ValueError("CADJPY stage contains protected 2025+ rows")

    DEST_DIR.mkdir(parents=True, exist_ok=False)
    combined.write_parquet(TARGET, compression="zstd", statistics=True)
    check = pl.read_parquet(TARGET)
    MultiAssetSchema.validate(check, strict=True)
    if check.height != combined.height or check.schema != combined.schema:
        raise AssertionError("Parquet round-trip changed row count or canonical schema")
    result = {
        "schema_version": "ml4t-multi-asset-ohclv-development-snapshot-v1",
        "session_id_candidate": "mechanicalpremia-yen-squeeze-proxy-20261014-v2",
        "source_provider": "Dukascopy staged Arrow, download was already running before this task",
        "canonical_ml4t_data_modified": False,
        "protected_2025_plus_data_read": False,
        "input_years_read": list(YEARS),
        "input_files": annual,
        "output": {
            "path": str(TARGET.relative_to(ROOT)),
            "sha256": _sha256(TARGET),
            "rows": check.height,
            "first_timestamp": str(check["timestamp"].min()),
            "last_timestamp": str(check["timestamp"].max()),
            "schema": {name: str(dtype) for name, dtype in check.schema.items()},
            "year_rows": check.group_by(pl.col("timestamp").dt.year().alias("year")).len().sort("year").to_dicts(),
            "monthly_rows": check.group_by(
                pl.col("timestamp").dt.year().alias("year"),
                pl.col("timestamp").dt.month().alias("month"),
            ).len().sort("year", "month").to_dicts(),
            "longest_observed_gap_seconds": float(check["timestamp"].diff().dt.total_seconds().max()),
            "quality_issues": issues,
            "ml4t_data_contract": "ml4t.data.core.schemas.MultiAssetSchema.validate(strict=True)",
        },
        "provenance_limitations": [
            "Staging Arrow source does not include a per-file provider manifest; file hashes and staged path are retained.",
            "Timestamp localization is supported by installed Dukascopy provider's epoch-millisecond conversion, but this specific staging job is not independently tied to that provider run identifier.",
            "Observed gaps are retained and not forward-filled; exact expected FX session completeness is not asserted.",
        ],
    }
    manifest = DEST_DIR / "cadjpy_materialization_manifest.json"
    manifest.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n")
    return result


if __name__ == "__main__":
    print(json.dumps(materialize(), indent=2, sort_keys=True, default=str))
