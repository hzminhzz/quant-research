"""Create a bounded USDJPY one-minute development snapshot for Tokyo fix research.

Only reads canonical LSE USDJPY 1m partitions from ml4t-data. Does not score
any outcome or open the September 2026 onward candidate holdout.
"""
from __future__ import annotations

import glob
import hashlib
import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path("/home/quant/dev/quant/ml4t-data/.data/store/forex_minute_USDJPY/year=2026")
OUT = ROOT / "data/processed/tokyo_fix_gotobi_20261010/USDJPY_dev_20260101_20260831_1m.parquet"
MANIFEST = OUT.with_suffix(".source.json")


def main() -> None:
    if OUT.exists() or MANIFEST.exists():
        raise RuntimeError("Frozen source snapshot exists; refusing to overwrite")
    files = sorted(
        p for month in range(1, 9)
        for p in glob.glob(str(SOURCE / f"month={month}" / "day=*" / "data.parquet"))
    )
    if not files:
        raise RuntimeError("No canonical USDJPY LSE 1m files available")
    df = (
        pl.scan_parquet(files, hive_partitioning=False)
        .select("timestamp", "symbol", "open", "high", "low", "close", "volume")
        .filter(
            (pl.col("timestamp") >= pl.datetime(2026, 1, 1, time_zone="UTC"))
            & (pl.col("timestamp") < pl.datetime(2026, 9, 1, time_zone="UTC"))
        )
        .sort("timestamp")
        .collect()
    )
    if df.is_empty() or df["symbol"].unique().to_list() != ["USDJPY"]:
        raise RuntimeError("Invalid symbol or empty source")
    if df.select(pl.col("timestamp").is_duplicated().sum()).item():
        raise RuntimeError("Duplicate minute timestamps in source")
    if df.select(pl.any_horizontal(pl.col("open").is_null(),pl.col("high").is_null(),pl.col("low").is_null(),pl.col("close").is_null()).sum()).item():
        raise RuntimeError("Missing OHLC values")
    if df.filter((pl.col("low")>pl.col("high"))|(pl.col("open")<pl.col("low"))|(pl.col("open")>pl.col("high"))|(pl.col("close")<pl.col("low"))|(pl.col("close")>pl.col("high"))).height:
        raise RuntimeError("Invalid OHLC geometry")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(OUT, compression="zstd")
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    manifest = {
        "provider":"LSE canonical ml4t-data USDJPY 1-minute store",
        "source_root":str(SOURCE),
        "source_partitions":len(files),
        "source_partition_listing_sha256":hashlib.sha256("\n".join(files).encode()).hexdigest(),
        "snapshot_path":str(OUT.relative_to(ROOT)),
        "snapshot_sha256":digest,
        "rows":df.height,
        "first":str(df["timestamp"].min()),
        "last":str(df["timestamp"].max()),
        "timestamps":"UTC minute bar opens, based on canonical LSE manifest",
        "market":"USDJPY FX proxy; no executable bid/ask or broker commission",
        "research_window":"2026-01-01 through 2026-08-31 UTC",
        "holdout_exclusion":"2026-09-01 onward untouched by this job",
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2)+"\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
