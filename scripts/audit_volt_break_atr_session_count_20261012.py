"""Read-only audit of daily Globex-like session completeness."""
import json
from pathlib import Path
import polars as pl

root=Path("/home/quant/dev/quant/ml4t-data/.data/store/index_minute_NQ")
paths=[str(p) for y in range(2018,2026) for p in (root/f"year={y}").glob("month=*/data.parquet")]
x=(pl.scan_parquet(paths,hive_partitioning=False)
.select(pl.col("timestamp").dt.replace_time_zone("UTC").dt.convert_time_zone("America/Chicago").alias("ct"))
.with_columns(d=pl.col("ct").dt.date(), m=pl.col("ct").dt.hour().cast(pl.Int32)*60+pl.col("ct").dt.minute().cast(pl.Int32))
.with_columns(sess=pl.when(pl.col("m")>=1020).then(pl.col("d")+pl.duration(days=1)).otherwise(pl.col("d")))
.group_by("sess").agg(n=pl.len(),first=pl.col("ct").min(),last=pl.col("ct").max())
.filter(pl.col("sess").dt.year().is_between(2019,2025))
.with_columns(year=pl.col("sess").dt.year(),weekday=pl.col("sess").dt.weekday())
.collect().sort("sess"))
summary=(x.group_by("year").agg(
session_dates=pl.len(), n_median=pl.col("n").median(),
n_min=pl.col("n").min(), n_p10=pl.col("n").quantile(.1),
n_ge_1300=(pl.col("n")>=1300).sum(),n_ge_1000=(pl.col("n")>=1000).sum(),
n_ge_700=(pl.col("n")>=700).sum(),
).sort("year"))
print(json.dumps({"summary":summary.to_dicts(),
"n_common":x.group_by("n").agg(k=pl.len()).sort("k",descending=True).head(25).to_dicts(),
"bad_example":x.filter(pl.col("year")==2025).filter(pl.col("n")<1300).head(15).to_dicts()},default=str))
