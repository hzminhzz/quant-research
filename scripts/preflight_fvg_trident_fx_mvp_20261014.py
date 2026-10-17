"""Preflight only: verify declared FX inputs and ML4T feature APIs. No returns or holdout."""
from __future__ import annotations

import hashlib
import inspect
import json
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
from ml4t.engineer import compute_features, feature_catalog

ROOT = Path(__file__).resolve().parents[1]
SESSION = "fvg_trident_fx_mvp_20261014_v1"
DATA = ROOT / "data/processed/ftmo_fx_reversion_202610"
OUTPUT = ROOT / "run_log" / SESSION / "P0_data_and_clock_preflight.json"
PAIRS = ["EURUSD", "GBPUSD", "AUDUSD"]
ERAS = ("2010_2017", "2018_2024")
NY = ZoneInfo("America/New_York")


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def audit_file(path: Path) -> dict:
    scan = pl.scan_parquet(path)
    schema = scan.collect_schema()
    if schema["timestamp"].time_zone != "UTC":
        raise ValueError(f"{path}: timestamps must have UTC timezone; found {schema['timestamp']}")
    bad = (
        (pl.col("high") < pl.col("low"))
        | (pl.col("high") < pl.col("open"))
        | (pl.col("high") < pl.col("close"))
        | (pl.col("low") > pl.col("open"))
        | (pl.col("low") > pl.col("close"))
        | (pl.col("source_rows") != 5)
        | pl.any_horizontal(pl.col(c).is_null() for c in ("open", "high", "low", "close"))
    )
    result = scan.select(
        pl.len().alias("rows"),
        pl.col("timestamp").n_unique().alias("unique_timestamps"),
        pl.col("timestamp").min().alias("first"),
        pl.col("timestamp").max().alias("last"),
        bad.sum().alias("bad_ohlc_or_components"),
        pl.col("source_rows").min().alias("min_source_rows"),
    ).collect().row(0, named=True)
    result["path"] = str(path.relative_to(ROOT))
    result["sha256"] = digest(path)
    result["first"] = str(result["first"])
    result["last"] = str(result["last"])
    return result


def run():
    manifest = json.loads((DATA / "manifest.json").read_text())
    outputs = {Path(e["output"]).name: e for e in manifest["outputs"]}
    report = dict(
        status="PASS",
        session_id=SESSION,
        stage="P0_data_and_clock_preflight",
        inspected_holdout=False,
        registry_feature_ema_present="ema" in feature_catalog.list(),
        ml4t_compute_features_signature=str(inspect.signature(compute_features)),
        ml4t_engineer_version=version("ml4t-engineer"),
        ml4t_backtest_version=version("ml4t-backtest"),
        polars_version=pl.__version__,
        inputs=[],
    )
    checks = [
        ("2024-03-08T08:00:00+00:00", 3, "-05:00"),
        ("2024-03-11T07:00:00+00:00", 3, "-04:00"),
        ("2024-11-01T07:00:00+00:00", 3, "-04:00"),
        ("2024-11-04T08:00:00+00:00", 3, "-05:00"),
    ]
    report["ny_dst_tests"] = []
    for stamp, hour, offset in checks:
        ny_time = datetime.fromisoformat(stamp).astimezone(NY)
        ok = ny_time.hour == hour and ny_time.isoformat().endswith(offset)
        report["ny_dst_tests"].append(dict(utc=stamp, ny=ny_time.isoformat(), pass_check=ok))
        if not ok:
            raise AssertionError(f"DST check failed: {stamp} -> {ny_time}")
    for pair in PAIRS:
        for era in ERAS:
            name = f"{pair}_dev_{era}_5m.parquet"
            path = DATA / name
            result = audit_file(path)
            expected = outputs[name]
            result["source_hash_matches_manifest"] = result["sha256"] == expected["sha256"]
            report["inputs"].append(dict(pair=pair, era=era, **result))
            if result["bad_ohlc_or_components"] or result["unique_timestamps"] != result["rows"]:
                raise AssertionError(f"Data consistency failure: {name}: {result}")
            if not result["source_hash_matches_manifest"]:
                raise AssertionError(f"Data identity mismatch: {name}")
    if not report["registry_feature_ema_present"]:
        raise AssertionError("ML4T EMA registry missing")
    if OUTPUT.exists():
        raise FileExistsError(f"Immutable evidence already exists: {OUTPUT}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("x") as handle:
        json.dump(report, handle, indent=2, default=str, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"stage": report["stage"], "status": report["status"],
                      "input_rows": sum(x["rows"] for x in report["inputs"]),
                      "ema_signature": report["ml4t_compute_features_signature"],
                      "first_file": report["inputs"][0]["path"],
                      "output": str(OUTPUT.relative_to(ROOT))}, indent=2))


if __name__ == "__main__":
    run()
