"""Phase 2 read-only data inventory for original B0 cross-index replication."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
STORE = Path("/home/quant/dev/quant/ml4t-data/.data/store")
OUT = ROOT / "run_log/one_bar_b0_cross_indices_20261012"
BEGIN = datetime(2013, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 7, 15, tzinfo=timezone.utc)
NAMES = ("NQ", "ES", "DAX", "NIKKEI225")
COLUMNS = ("timestamp", "symbol", "open", "high", "low", "close", "volume")


def write(name: str, obj: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(obj, indent=2, default=str) + "\n")


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def files_for(symbol: str) -> list[Path]:
    folder = STORE / ("index_minute_" + symbol)
    result = []
    for p in folder.glob("year=*/month=*/data.parquet"):
        y = int(p.parent.parent.name.split("=")[1])
        m = int(p.parent.name.split("=")[1])
        if y < 2026 or (y == 2026 and m <= 7):
            result.append(p)
    return sorted(result, key=lambda p: (
        int(p.parent.parent.name.split("=")[1]), int(p.parent.name.split("=")[1])
    ))


def scan_index(paths: list[Path]) -> pl.DataFrame:
    lazy = pl.scan_parquet([str(x) for x in paths],
        hive_partitioning=False, extra_columns="ignore",
        missing_columns="insert").select(COLUMNS)
    tz = lazy.collect_schema()["timestamp"].time_zone
    if tz is None:
        lazy = lazy.with_columns(pl.col("timestamp").dt.replace_time_zone("UTC"))
    elif tz != "UTC":
        lazy = lazy.with_columns(pl.col("timestamp").dt.convert_time_zone("UTC"))
    return lazy.filter(
        (pl.col("timestamp") >= BEGIN) & (pl.col("timestamp") < END)
    ).collect(engine="streaming").sort("timestamp")


def quality(df: pl.DataFrame) -> dict:
    if df.is_empty():
        return {"status": "BLOCKED_NO_ROWS"}
    ts = pl.col("timestamp")
    obs = df.with_columns(
        ((ts - ts.shift(1)).dt.total_minutes()).alias("minute_gap"),
        ts.dt.truncate("30m").alias("bin"),
        ts.dt.year().alias("year"),
    )
    bars = obs.group_by("bin").agg(
        pl.len().alias("rows"),
        ts.n_unique().alias("unique"),
        ts.min().alias("first"),
        ts.max().alias("last"),
    ).with_columns((
        (pl.col("rows") == 30) & (pl.col("unique") == 30)
        & (pl.col("first").dt.minute() % 30 == 0)
        & (pl.col("last").dt.minute() % 30 == 29)
    ).alias("complete"))
    pcols = ("open", "high", "low", "close")
    invalid = (
        (pl.col("high") < pl.col("low"))
        | (pl.col("open") > pl.col("high"))
        | (pl.col("open") < pl.col("low"))
        | (pl.col("close") > pl.col("high"))
        | (pl.col("close") < pl.col("low"))
    )
    a = {
        "status": "OBSERVED_ROWS_QUALITY_CHECKED",
        "rows": df.height,
        "first_utc": df["timestamp"].min().isoformat(),
        "last_utc": df["timestamp"].max().isoformat(),
        "observed_symbols": df["symbol"].unique().to_list(),
        "timezone": str(df.schema["timestamp"]),
        "duplicated_timestamps": df.height - df["timestamp"].n_unique(),
        "null_ohlc": sum(df[x].null_count() for x in pcols),
        "nonfinite_ohlc": int(df.select(pl.any_horizontal(
            [~pl.col(x).is_finite() for x in pcols]).sum()).item()),
        "invalid_ohlc": int(df.select(invalid.sum()).item()),
        "zero_volume": int(df["volume"].eq(0).sum()),
        "gaps_gt_1_minute": int(obs["minute_gap"].gt(1).sum()),
        "gaps_gt_30_minute": int(obs["minute_gap"].gt(30).sum()),
        "max_gap_minute": float(obs["minute_gap"].max()),
        "observed_30m_bins": bars.height,
        "fully_complete_observed_30m_bins": int(bars["complete"].sum()),
        "incomplete_observed_30m_bins": bars.height - int(bars["complete"].sum()),
        "observed_bins_without_boundary_opening_minute":
            int(bars.filter(pl.col("first").dt.minute() % 30 != 0).height),
        "annual_rows": [
            {"year": x["year"], "rows": x["rows"]} for x in
            obs.group_by("year").agg(pl.len().alias("rows")).sort("year").to_dicts()
        ],
    }
    if a["duplicated_timestamps"] or a["null_ohlc"] or a["invalid_ohlc"] or a["nonfinite_ohlc"]:
        a["status"] = "BLOCKED_OHLC_QUALITY"
    a["caveat"] = ("Timestamp gaps include holidays and overnight closures. "
                  "Absent complete 30m bins are not counted among observed bins. "
                  "Execution minutes must be retained even when signal bars are incomplete.")
    return a


def main() -> None:
    manifest = {}
    results = {}
    for sym in NAMES:
        paths = files_for(sym)
        schemas = {}
        records = []
        for f in paths:
            schema = pl.read_parquet_schema(f)
            variant = "extra_year_month" if "year" in schema or "month" in schema else "core_ohlcv"
            schemas[variant] = schemas.get(variant, 0) + 1
            records.append({
                "path": f.relative_to(STORE).as_posix(),
                "size_bytes": f.stat().st_size,
                "footer_rows_may_include_postcutoff_july": pq.ParquetFile(f).metadata.num_rows,
                "schema_variant": variant,
                "timestamp_type": str(schema["timestamp"]),
            })
        manifest[sym] = {
            "store": "index_minute_" + sym,
            "folder": str(STORE / ("index_minute_" + sym)),
            "parquet_parts_through_july2026": len(paths),
            "schema_variants": schemas,
            "files": records,
            "hash_contract": "metadata/paths; complete Parquet content hashes reserved for backtest gate",
        }
        print("SCANNING", sym, len(paths), flush=True)
        results[sym] = quality(scan_index(paths))
        print("DONE", sym, results[sym]["rows"], flush=True)

    hk = ROOT / "data/processed/HK33_5m_2017_2026.parquet"
    if hk.is_file():
        df = pl.scan_parquet(hk).filter(
            (pl.col("timestamp") >= BEGIN) & (pl.col("timestamp") < END)
        ).select(
            pl.len().alias("rows"),
            pl.col("timestamp").min().alias("first_utc"),
            pl.col("timestamp").max().alias("last_utc"),
            pl.col("symbol").first().alias("source_symbol"),
        ).collect().to_dicts()[0]
        results["HSI"] = {
            "status": "BLOCKED_1M_NOT_FOUND_5M_AVAILABLE",
            "alternate_frequency": "5m",
            "alternate_file": str(hk),
            **df,
        }
        manifest["HSI"] = {
            "one_minute_source": None,
            "five_minute_source": str(hk),
            "five_minute_file_sha256": hash_file(hk),
        }
    else:
        results["HSI"] = {"status": "BLOCKED_NO_SOURCE"}
        manifest["HSI"] = {"one_minute_source": None}

    frozen_b0 = ROOT / "run_log/one_bar_dukascopy_2013_2026_20261011/source_manifest.json"
    if frozen_b0.is_file():
        old = json.loads(frozen_b0.read_text())
        manifest["NQ"]["old_source_manifest_sha256"] = hash_file(frozen_b0)
        if isinstance(old, list):
            old_names = {x["path"] for x in old}
            new_names = {x["path"].split("/", 1)[1] for x in manifest["NQ"]["files"]}
            manifest["NQ"]["same_partition_paths_as_frozen_control"] = old_names == new_names
    write("source_manifest.json", manifest)
    write("phase2_quality.json", results)
    ledger = {
        "session_id": "one_bar_b0_cross_indices_20261012",
        "status": "REGISTERED_NO_CROSS_INDEX_BACKTESTS",
        "trials": [
            {"instrument": sym, "trial": "literal_B0_port", "phase1": "REGISTERED",
             "phase2": results[sym]["status"], "phase3": "NOT_STARTED",
             "phase4_native_ml4t": "NOT_STARTED", "attempts": 0}
            for sym in ("NQ", "ES", "DAX", "NIKKEI225", "HSI")
        ],
        "new_backtest_trials_executed": 0,
        "unresolved_native_contract_and_session_gates": True,
    }
    write("trial_ledger.json", ledger)
    write("status.json", {
        "phase1": "REGISTERED", "phase2": "COMPLETED_WITH_OPEN_DATA_GATES",
        "phase3": "NOT_STARTED", "phase4": "NOT_STARTED",
        "hang_seng": results["HSI"]["status"],
        "all_requested_markets": 5,
        "one_minute_sources_found": 4,
        "no_strategy_backtests": True,
        "source_cutoff": "2026-07-14 UTC",
    })
    print("PHASE1_PHASE2_DONE", flush=True)


if __name__ == "__main__":
    main()
