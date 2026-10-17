"""Materialize bounded 2023-2024 Yen-cross development prices, without signals.

Read only year=2023 and year=2024 from canonical ml4t-data. Never access
2025+ partitions. This is input preparation, NOT a trial or optimization.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
STORE = Path("/home/quant/dev/quant/ml4t-data/.data/store")
DEST = ROOT / "data/processed/mechanicalpremia_yen_squeeze_mvp_20261014"
START = datetime(2023, 1, 1, tzinfo=timezone.utc)
END = datetime(2025, 1, 1, tzinfo=timezone.utc)
PAIR_PROVENANCE = {
    "USDJPY": "LSE/legacy canonical US dollar vs yen mix; verify historical source identity",
    "GBPJPY": "Dukascopy bid-only legacy, UTC-localization assumption must be audited",
}


def source_files(pair: str) -> list[Path]:
    files = []
    for year in (2023, 2024):
        for month in range(1, 13):
            folder = STORE / f"forex_minute_{pair}" / f"year={year}" / f"month={month}"
            files.extend(sorted(folder.rglob("data.parquet")))
    return files


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if DEST.exists():
        raise RuntimeError(f"Refuse existing immutable snapshot: {DEST}")
    staged = {}
    for pair in ("USDJPY", "GBPJPY"):
        files = source_files(pair)
        if len(files) < 20:
            raise RuntimeError(f"Inadequate source coverage for {pair}: {len(files)} files")
        frame = pl.scan_parquet(files, hive_partitioning=False)
        src_schema = frame.collect_schema()
        naive = src_schema["timestamp"].time_zone is None
        if naive:
            frame = frame.with_columns(pl.col("timestamp").dt.replace_time_zone("UTC"))
        frame = (frame.filter((pl.col("timestamp") >= START) & (pl.col("timestamp") < END))
                 .select("timestamp", "symbol", "open", "high", "low", "close", "volume")
                 .sort("timestamp"))
        df = frame.collect()
        if df.is_empty() or df["timestamp"].n_unique() != df.height:
            raise RuntimeError(f"Empty or duplicate timestamps: {pair}")
        if df["symbol"].unique().to_list() != [pair]:
            raise RuntimeError(f"Unexpected symbol: {pair}")
        if df.filter((pl.col("open") <= 0) | (pl.col("high") < pl.col("low"))
                     | (pl.col("low") > pl.col("open")) | (pl.col("open") > pl.col("high"))
                     | (pl.col("low") > pl.col("close")) | (pl.col("close") > pl.col("high"))).height:
            raise RuntimeError(f"Invalid OHLC: {pair}")
        staged[pair] = (df, files, naive, str(src_schema))
    DEST.mkdir(parents=True, exist_ok=False)
    manifest = {"development_start": START.isoformat(), "development_end_exclusive": END.isoformat(),
                "protected_final_test_start": END.isoformat(), "pairs": {}, "CADJPY": "MISSING; source universe incomplete"}
    for pair, (df, files, naive, schema) in staged.items():
        target = DEST / f"{pair}_2023_2024_1m.parquet"
        df.write_parquet(target, compression="zstd")
        manifest["pairs"][pair] = {
            "path": str(target.relative_to(ROOT)), "sha256": digest(target),
            "rows": df.height, "first": str(df["timestamp"].min()), "last": str(df["timestamp"].max()),
            "source_file_count": len(files), "raw_partition_roots": [f"forex_minute_{pair}/year=2023",
                f"forex_minute_{pair}/year=2024"], "source_schema": schema,
            "timezone_naive_localized_as_utc": naive, "provenance": PAIR_PROVENANCE[pair],
            "observed_spread_or_financing": False,
        }
    (DEST / "source_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
