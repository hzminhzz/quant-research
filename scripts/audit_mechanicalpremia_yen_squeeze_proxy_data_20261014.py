"""Pre-performance data/feature audit for the frozen Yen Squeeze proxy."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import polars as pl
from ml4t.data.core.schemas import MultiAssetSchema

from scripts.audit_mechanicalpremia_yen_squeeze_native_20261014 import build_complete_h1
from scripts.mechanicalpremia_yen_squeeze_native_strategy_20261014 import build_features

ROOT = Path(__file__).resolve().parents[1]
STAGE = Path("/home/quant/dev/quant/ml4t-data/.data/staging/dukascopy-cadjpy-20261013")
CAD_SNAPSHOT = ROOT / "data/processed/mechanicalpremia_yen_squeeze_proxy_20261014/CADJPY_2023_2024_1m.parquet"
MANIFEST = CAD_SNAPSHOT.parent / "source_manifest.json"
OUT = ROOT / "docs/audit/mechanicalpremia_yen_squeeze_proxy_data_20261014.json"
DEV_END = pl.datetime(2025, 1, 1, time_zone="UTC")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def data_checks(frame: pl.DataFrame, symbol: str) -> dict[str, Any]:
    MultiAssetSchema.validate(frame, strict=True)
    is_utc = isinstance(frame.schema["timestamp"], pl.Datetime) and frame.schema["timestamp"].time_zone == "UTC"
    if not is_utc:
        raise ValueError(f"{symbol}: canonical snapshot must have UTC-aware timestamps")
    issues = {
        "rows": frame.height,
        "duplicate_timestamp_rows": frame.height - frame["timestamp"].n_unique(),
        "symbol_mismatch_rows": frame.filter(pl.col("symbol") != symbol).height,
        "high_below_low_rows": frame.filter(pl.col("high") < pl.col("low")).height,
        "open_outside_range_rows": frame.filter((pl.col("open") < pl.col("low")) | (pl.col("open") > pl.col("high"))).height,
        "close_outside_range_rows": frame.filter((pl.col("close") < pl.col("low")) | (pl.col("close") > pl.col("high"))).height,
        "null_nonfinite_ohlcv_rows": frame.filter(pl.any_horizontal(
            pl.col("open", "high", "low", "close", "volume").is_null()
            | pl.col("open", "high", "low", "close", "volume").is_finite().not_()
        )).height,
        "unaligned_minute_rows": frame.filter(pl.col("timestamp").dt.truncate("1m") != pl.col("timestamp")).height,
        "rows_at_or_after_2025": frame.filter(pl.col("timestamp") >= DEV_END).height,
        "first_timestamp": str(frame["timestamp"].min()),
        "last_timestamp": str(frame["timestamp"].max()),
        "longest_observed_gap_seconds": float(frame.sort("timestamp")["timestamp"].diff().dt.total_seconds().max()),
        "utc_aware": is_utc,
        "ml4t_multi_asset_schema": "PASS",
    }
    if any(issues[k] for k in (
        "duplicate_timestamp_rows", "symbol_mismatch_rows", "high_below_low_rows",
        "open_outside_range_rows", "close_outside_range_rows", "null_nonfinite_ohlcv_rows",
        "unaligned_minute_rows", "rows_at_or_after_2025",
    )):
        raise ValueError(f"{symbol}: data quality failure: {issues}")
    return issues


def main() -> dict[str, Any]:
    source_manifest = json.loads(MANIFEST.read_text())
    stage_files = [STAGE / "cadjpy_2023.arrow", STAGE / "cadjpy_2024.arrow"]
    source_entries = {Path(item["path"]).name: item for item in source_manifest["inputs"]}
    staged = []
    for path in stage_files:
        entry = source_entries[path.name]
        actual = sha256(path)
        if actual != entry["sha256"]:
            raise AssertionError(f"CADJPY stage identity mismatch: {path.name}")
        staged.append({"path": str(path), "sha256": actual, "size_bytes": path.stat().st_size,
                       "rows_from_manifest": entry["rows"], "year": int(path.stem[-4:])})

    datasets = {
        "USDJPY": (ROOT / "data/processed/mechanicalpremia_yen_squeeze_mvp_20261014/USDJPY_2023_2024_1m.parquet", False),
        "GBPJPY": (ROOT / "data/processed/mechanicalpremia_yen_squeeze_mvp_20261014/GBPJPY_2023_2024_1m.parquet", True),
        "CADJPY": (CAD_SNAPSHOT, False),
    }
    pair_records: dict[str, Any] = {}
    all_minutes = []
    for symbol, (path, naive_is_utc) in datasets.items():
        frame = pl.read_parquet(path)
        quality = data_checks(frame, symbol)
        all_minutes.append(frame)
        h1, aggregation = build_complete_h1(frame, naive_is_utc=naive_is_utc)
        features = build_features(h1)
        violation = features.filter(pl.col("available_at") < pl.col("timestamp")).height
        if violation:
            raise AssertionError(f"{symbol}: H1 availability violation")
        usable = features.filter(pl.col("atr14").is_finite() & pl.col("atr100_upper_median").is_finite())
        pair_records[symbol] = {
            "path": str(path.relative_to(ROOT)),
            "sha256": sha256(path),
            "timezone_localization_assumption": naive_is_utc,
            "minute_quality": quality,
            "h1_aggregation": aggregation,
            "native_ml4t_engineer_features": ["atr14", "atr100_upper_median_upper_order_stat_50", "donchian20", "donchian500"],
            "feature_rows": features.height,
            "atr14_finite_rows": features.filter(pl.col("atr14").is_finite()).height,
            "median_finite_rows": features.filter(pl.col("atr100_upper_median").is_finite()).height,
            "signal_ready_rows": usable.height,
            "feature_availability_violations": violation,
        }

    panel = pl.concat(all_minutes, how="vertical_relaxed").sort("symbol", "timestamp")
    if panel.filter(pl.col("timestamp") >= DEV_END).height:
        raise AssertionError("protected rows in combined panel")
    report = {
        "session_intended": "mechanicalpremia-yen-squeeze-proxy-20261014-v3",
        "trial": "DATA-AND-FEATURE-PARITY",
        "status": "completed",
        "performance_observed": False,
        "protected_2025_plus_price_data_read": False,
        "skills": [
            {"name": "ml4t-fetch-data", "revision": "ml4t/skills@8800d3fb4c57ffba3e96da78c6b46ee77076b024", "invariant": "Assert provider row schema, range, and provenance.", "upstream": "https://github.com/ml4t/skills/tree/8800d3fb4c57ffba3e96da78c6b46ee77076b024/data/fetch-data"},
            {"name": "ml4t-validate-data", "revision": "ml4t/skills@8800d3fb4c57ffba3e96da78c6b46ee77076b024", "invariant": "Verify UTC, uniqueness, gaps, finite OHLCV and price bounds.", "upstream": "https://github.com/ml4t/skills/tree/8800d3fb4c57ffba3e96da78c6b46ee77076b024/data/validate-data"},
            {"name": "ml4t-canonical-schema", "revision": "ml4t/skills@8800d3fb4c57ffba3e96da78c6b46ee77076b024", "invariant": "Enforce symbol/timestamp/lowercase OHLCV columns.", "upstream": "https://github.com/ml4t/skills/tree/8800d3fb4c57ffba3e96da78c6b46ee77076b024/infrastructure/canonical-schema"},
            {"name": "ml4t-compute-features", "revision": "ml4t/skills@8800d3fb4c57ffba3e96da78c6b46ee77076b024", "invariant": "Compute rolling features per symbol, in timestamp order.", "upstream": "https://github.com/ml4t/skills/tree/8800d3fb4c57ffba3e96da78c6b46ee77076b024/features/compute-features"},
            {"name": "ml4t-lookahead-bias", "revision": "ml4t/skills@8800d3fb4c57ffba3e96da78c6b46ee77076b024", "invariant": "Only completed H1 values available at or after H1 close.", "upstream": "https://github.com/ml4t/skills/tree/8800d3fb4c57ffba3e96da78c6b46ee77076b024/concepts/lookahead-bias"},
        ],
        "ml4t_data_contract": {"library_version": __import__("ml4t.data").data.__version__, "validator": "ml4t.data.core.schemas.MultiAssetSchema.validate(strict=True)"},
        "cadjpy_staging_inputs": staged,
        "cadjpy_materialized_snapshot": {"manifest": str(MANIFEST.relative_to(ROOT)), "manifest_sha256": sha256(MANIFEST), "snapshot_sha256": sha256(CAD_SNAPSHOT), "source_manifest": source_manifest},
        "pairs": pair_records,
        "combined_panel": {"rows": panel.height, "symbols": sorted(panel["symbol"].unique().to_list()), "rows_at_or_after_2025": 0},
        "limitations": [
            "CADJPY UTC offset zero follows the staged download manifest and installed Dukascopy epoch-ms converter; staging itself has no per-job provenance id.",
            "GBPJPY naive timestamps remain localized to UTC under the previously disclosed lineage assumption.",
            "Observed timestamp gaps are retained; missing-session completeness and bid/ask are unavailable.",
        ],
    }
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    return report


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, sort_keys=True, default=str))
