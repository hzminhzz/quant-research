"""Bounded canonical FX m1 snapshot, 2015-2024 only; NO 2025+ access.

Input preparation only. Executes no features, trades, or PnL. Output immutable.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import polars as pl

ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path("/home/quant/dev/quant/ml4t-data/.data/store")
DEST=ROOT/"data/processed/mechanicalpremia_yen_squeeze_mt5atr_2015_2024"

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1<<20),b""):
            h.update(block)
    return h.hexdigest()

def main() -> None:
    if DEST.exists():
        raise FileExistsError(f"refuse overwrite: {DEST}")
    symbols=("USDJPY","GBPJPY","CADJPY")
    index={}
    # No extended backtest starts before the snapshot manifest is complete.
    DEST.mkdir(parents=True,exist_ok=False)
    for symbol in symbols:
        base=SOURCE/f"forex_minute_{symbol}"
        files=[]
        counts={}
        for year in range(2015,2025):
            match=sorted((base/f"year={year}").rglob("*.parquet"))
            if len(match)<10:
                raise RuntimeError(f"insufficient canonical partitions {symbol} {year}: {len(match)}")
            files+=match
            counts[str(year)]=len(match)
        dest=DEST/f"{symbol}_2015_2024_1m.parquet"
        frame=pl.scan_parquet([str(p) for p in files],hive_partitioning=False).select(
            "timestamp","symbol","open","high","low","close","volume"
        ).filter(
            (pl.col("timestamp")>=pl.datetime(2015,1,1,time_zone="UTC"))
            & (pl.col("timestamp")<pl.datetime(2025,1,1,time_zone="UTC"))
        ).sort("timestamp")
        frame.sink_parquet(dest,compression="zstd",maintain_order=True)
        # Read Parquet footer for rows, and selectively validate timestamp/schema.
        import pyarrow.parquet as pq
        pf=pq.ParquetFile(dest)
        index[symbol]={
            "snapshot":str(dest.relative_to(ROOT)),
            "sha256":sha256(dest),
            "rows":pf.metadata.num_rows,
            "partitions_per_year":counts,
            "source_root":str(base),
            "source_years":"2015-2024 ONLY",
            "timezone_source":"timestamp aware UTC in selected canonical partitions",
            "source_version":"ml4t-data canonical forex_minute store; upstream broker identity unverified",
        }
        print(json.dumps({symbol:index[symbol]}),flush=True)
    (DEST/"source_manifest.json").write_text(json.dumps({
        "window_start":"2015-01-01T00:00:00Z",
        "window_end_exclusive":"2025-01-01T00:00:00Z",
        "source":"local canonical ml4t-data FX minute store",
        "no_protected_market_data_access":True,"pairs":index},indent=2)+"\n")
    print("SNAPSHOT_COMPLETE",flush=True)

if __name__=="__main__":
    main()
