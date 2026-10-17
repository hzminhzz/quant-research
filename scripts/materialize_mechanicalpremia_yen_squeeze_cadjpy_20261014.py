"""Materialize CADJPY 2023/2024 Dukascopy staging. Data-only, no signals/PnL."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
STAGE = Path("/home/quant/dev/quant/ml4t-data/.data/staging/dukascopy-cadjpy-20261013")
DEST = ROOT / "data/processed/mechanicalpremia_yen_squeeze_proxy_20261014"
FILES = [STAGE / f"cadjpy_{year}.arrow" for year in (2023, 2024)]

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            h.update(block)
    return h.hexdigest()

def main() -> None:
    if DEST.exists():
        raise FileExistsError(f"Immutable destination exists: {DEST}")
    frames, inputs = [], []
    for p in FILES:
        if not p.is_file():
            raise FileNotFoundError(p)
        frame = pl.read_ipc(p)
        schema = {name: str(dtype) for name, dtype in frame.schema.items()}
        if set(("timestamp", "symbol", "open", "high", "low", "close", "volume")) - set(frame.columns):
            raise ValueError(f"Unexpected columns: {p}")
        if frame.schema["timestamp"].time_zone is not None:
            if frame.schema["timestamp"].time_zone != "UTC":
                raise ValueError(f"Unexpected timezone: {p}")
        else:
            # Source Dukascopy-node UTC offset zero; Arrow timestamp is naive.
            # Interpretation must be labeled provisional, never certified.
            frame = frame.with_columns(pl.col("timestamp").dt.replace_time_zone("UTC"))
        if frame.filter(pl.col("timestamp").dt.year() != int(p.stem.split("_")[-1])).height:
            raise ValueError(f"Out-of-year rows: {p}")
        if frame.filter(pl.col("symbol") != "CADJPY").height:
            raise ValueError(f"Unexpected symbol: {p}")
        inputs.append({"path": str(p), "sha256": sha(p), "rows": frame.height,
                       "schema": schema, "first": str(frame["timestamp"].min()),
                       "last": str(frame["timestamp"].max())})
        frames.append(frame.select("timestamp", "symbol", "open", "high", "low", "close", "volume"))
    joined = pl.concat(frames).sort("timestamp")
    if joined["timestamp"].n_unique() != joined.height:
        raise ValueError("Duplicated CADJPY timestamps")
    invalid = joined.filter(
        (pl.col("open") <= 0) | (pl.col("high") < pl.col("low"))
        | (pl.col("low") > pl.col("open")) | (pl.col("open") > pl.col("high"))
        | (pl.col("low") > pl.col("close")) | (pl.col("close") > pl.col("high"))
        | pl.any_horizontal(pl.col("open", "high", "low", "close").is_finite().not_())
    ).height
    if invalid:
        raise ValueError(f"Invalid CADJPY OHLC: {invalid}")
    if joined.filter(pl.col("timestamp").dt.truncate("1m") != pl.col("timestamp")).height:
        raise ValueError("Misaligned CADJPY minute timestamps")
    if joined.height < 650000:
        raise ValueError(f"Insufficient expected row count: {joined.height}")
    DEST.mkdir(parents=True, exist_ok=False)
    path = DEST / "CADJPY_2023_2024_1m.parquet"
    joined.write_parquet(path, compression="zstd")
    report = {
        "symbol": "CADJPY", "development_end_exclusive": "2025-01-01T00:00:00Z",
        "source": "Dukascopy-node bid m1 Arrow staging, UTC offset zero presumed",
        "source_eligibility": "STAGING_NOT_CANONICAL",
        "inputs": inputs, "rows": joined.height,
        "first": str(joined["timestamp"].min()), "last": str(joined["timestamp"].max()),
        "snapshot": str(path.relative_to(ROOT)), "snapshot_sha256": sha(path),
        "caveats": ["No observed historical bid/ask", "No upstream per-day categorical coverage acceptance",
                     "UTC interpretation from source process, not native Arrow timezone"],
    }
    (DEST / "source_manifest.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))
if __name__ == "__main__":
    main()
