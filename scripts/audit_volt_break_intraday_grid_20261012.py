"""Read-only CT 00:00-14:30 bar-grid audit. Excludes all 2026 data."""
import json
from pathlib import Path
import polars as pl

ROOT = Path("/home/quant/dev/quant/ml4t-data/.data/store")
paths = [str(p) for y in range(2018, 2026)
         for p in sorted((ROOT / "index_minute_NQ" / f"year={y}").glob("month=*/data.parquet"))]
lf = pl.scan_parquet(paths, hive_partitioning=False).select(
    pl.col("timestamp").dt.replace_time_zone("UTC").dt.convert_time_zone("America/Chicago").alias("ct"),
    "volume",
)
df = (lf.with_columns(
    date=pl.col("ct").dt.date(),
    year=pl.col("ct").dt.year(),
    minute_index=pl.col("ct").dt.hour().cast(pl.Int32)*60+pl.col("ct").dt.minute().cast(pl.Int32),
).filter(pl.col("year").is_between(2018,2025))
.filter(pl.col("minute_index") <= 870).collect())
days=(df.group_by("date", "year").agg(
    bars=pl.col("minute_index").filter(pl.col("minute_index") < 870).n_unique(),
    has_midnight=(pl.col("minute_index")==0).any(),
    has_signal_start=(pl.col("minute_index")==600).any(),
    has_exit=(pl.col("minute_index")==870).any(),
    positive_vol_bars=((pl.col("minute_index") < 870)&(pl.col("volume")>0)).sum(),
    first_min=pl.col("minute_index").min(),
    last_min=pl.col("minute_index").max(),
).with_columns(
    coverage=pl.col("bars")/870,
    full_day=(pl.col("bars")==870)&pl.col("has_exit"),
    eligible_99=(pl.col("bars")>=861)&pl.col("has_midnight")&pl.col("has_signal_start")&pl.col("has_exit"),
    eligible_98=(pl.col("bars")>=853)&pl.col("has_midnight")&pl.col("has_signal_start")&pl.col("has_exit"),
))
yearly=(days.group_by("year").agg(
    days=pl.len(),
    midnight_days=pl.col("has_midnight").sum(),
    both_morning_exit=(pl.col("has_midnight")&pl.col("has_signal_start")&pl.col("has_exit")).sum(),
    full_days=pl.col("full_day").sum(),
    eligible_99=pl.col("eligible_99").sum(),
    eligible_98=pl.col("eligible_98").sum(),
    median_coverage=pl.col("coverage").median(),
    min_coverage=pl.col("coverage").min(),
    max_coverage=pl.col("coverage").max(),
    nonpositive_volume_bars=(pl.col("bars")-pl.col("positive_vol_bars")).sum(),
).sort("year"))
print(json.dumps({"yearly":yearly.to_dicts(),"sample_short_days":days.filter(
    (pl.col("year")==2025)&(pl.col("bars")>500)&(pl.col("bars")<861)
    ).sort("date").head(15).to_dicts()},default=str))
