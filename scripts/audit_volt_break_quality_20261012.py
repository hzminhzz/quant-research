"""Read-only 2011-2025 VOLT BREAK market-data audit. No trading outcomes."""
import json
from pathlib import Path
import polars as pl

BASE = Path("/home/quant/dev/quant/ml4t-data/.data/store")
for name, start in [("index_minute_NQ", 2013), ("index_minute_NAS100", 2011)]:
    paths = sorted(p for year in range(start, 2026)
                   for p in (BASE / name / f"year={year}").glob("month=*/data.parquet"))
    if not paths:
        print(json.dumps({"store": name, "error": "no files"}))
        continue
    lf = pl.scan_parquet([str(p) for p in paths], hive_partitioning=False)
    ts_dtype = lf.collect_schema()["timestamp"]
    ts = pl.col("timestamp")
    if ts_dtype.time_zone is None:
        ts = ts.dt.replace_time_zone("UTC")
    else:
        ts = ts.dt.convert_time_zone("UTC")
    df = (
        lf.select("timestamp", "open", "high", "low", "close", "volume")
        .with_columns(ts.alias("timestamp"))
        .sort("timestamp")
        .with_columns(
            ct=pl.col("timestamp").dt.convert_time_zone("America/Chicago"),
            bad_ohlc=(
                (pl.col("high") < pl.max_horizontal("open", "close", "low"))
                | (pl.col("low") > pl.min_horizontal("open", "close", "high"))
                | (pl.col("open") <= 0) | (pl.col("close") <= 0)
            ),
        )
        .with_columns(
            year=pl.col("ct").dt.year(),
            ct_date=pl.col("ct").dt.date(),
            hour=pl.col("ct").dt.hour(),
            minute=pl.col("ct").dt.minute(),
        )
        .collect()
    )
    per_year = (
        df.group_by("year").agg(
            rows=pl.len(),
            start=pl.col("timestamp").min(),
            end=pl.col("timestamp").max(),
            zero_volume=(pl.col("volume") == 0).sum(),
            volume_min=pl.col("volume").min(),
            volume_median=pl.col("volume").median(),
            volume_max=pl.col("volume").max(),
            ohlc_invalid=pl.col("bad_ohlc").sum(),
            midnight_bars=((pl.col("hour") == 0) & (pl.col("minute") == 0)).sum(),
            ten_bars=((pl.col("hour") == 10) & (pl.col("minute") == 0)).sum(),
        ).sort("year")
    )
    days = (
        df.group_by("ct_date").agg(
            midnight=((pl.col("hour") == 0) & (pl.col("minute") == 0)).sum(),
            ten=((pl.col("hour") == 10) & (pl.col("minute") == 0)).sum(),
            fourteen_thirty=((pl.col("hour") == 14) & (pl.col("minute") == 30)).sum(),
            total=pl.len(),
            valid_vwap_minutes=((pl.col("volume") > 0) & (pl.col("hour") < 15)).sum(),
            entry_minutes=((pl.col("hour") >= 10) & (pl.col("hour") < 15)).sum(),
        ).sort("ct_date")
    )
    result = {
        "store": name,
        "partition_files": len(paths),
        "rows": df.height,
        "first_utc": str(df["timestamp"][0]),
        "last_utc": str(df["timestamp"][-1]),
        "timestamp_tz_in_source": str(ts_dtype),
        "duplicate_timestamp_rows": df.height - df["timestamp"].n_unique(),
        "null_counts": df.select([pl.col(c).null_count().alias(c) for c in ("timestamp","open","high","low","close","volume")]).to_dicts()[0],
        "nonfinite_price_rows": df.select(pl.any_horizontal([~pl.col(c).is_finite() for c in ("open","high","low","close")]).sum()).item(),
        "ohlc_invalid_rows": int(df["bad_ohlc"].sum()),
        "total_days": days.height,
        "days_with_midnight": int((days["midnight"] > 0).sum()),
        "days_with_10_ct": int((days["ten"] > 0).sum()),
        "days_with_1430_ct": int((days["fourteen_thirty"] > 0).sum()),
        "days_with_midnight_and_10": int(((days["midnight"] > 0) & (days["ten"] > 0)).sum()),
        "yearly": [{k: str(v) if k in ("start","end") else v for k,v in row.items()} for row in per_year.to_dicts()],
        "sample_days": days.filter(pl.col("ct_date").dt.year().is_in([2013, 2016, 2020, 2025]))
            .group_by(pl.col("ct_date").dt.year().alias("year"))
            .agg(days=pl.len(), midnight_days=(pl.col("midnight") > 0).sum(),
                 no_entry_window=(pl.col("ten") == 0).sum(),
                 no_vwap_volume=(pl.col("valid_vwap_minutes") == 0).sum())
            .sort("year").to_dicts(),
    }
    print(json.dumps(result, default=str))
