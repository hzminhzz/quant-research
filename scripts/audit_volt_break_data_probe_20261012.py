"""Read-only provenance and schema probe for VOLT BREAK Phase 2."""
from pathlib import Path
import polars as pl

DATA = Path("/home/quant/dev/quant/ml4t-data/.data/store")
CASES = [
    DATA / "index_minute_NQ/year=2013/month=1/data.parquet",
    DATA / "index_minute_NQ/year=2025/month=6/data.parquet",
    DATA / "index_minute_NAS100/year=2011/month=1/data.parquet",
    DATA / "index_minute_NAS100/year=2025/month=6/data.parquet",
    Path("data/processed/nq_1m.parquet"),
]
for path in CASES:
    print("SOURCE", str(path), "exists", path.exists())
    if not path.exists():
        continue
    df = pl.read_parquet(path)
    print("SCHEMA", df.schema)
    print("ROW_COUNT", df.height)
    print("FIRST", df.head(2).to_dicts())
    print("LAST", df.tail(2).to_dicts())
    if "volume" in df.columns:
        print("VOLUME", df.select(pl.col("volume").null_count().alias("null"), (pl.col("volume") == 0).sum().alias("zeros"), pl.col("volume").min().alias("min"), pl.col("volume").max().alias("max")).to_dicts())
