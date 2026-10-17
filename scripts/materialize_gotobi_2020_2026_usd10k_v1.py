"""Materialize ONLY 2020-Aug2026 Tokyo fix windows from canonical local LSE USDJPY.
This script creates data and coverage evidence, not return statistics.
"""
from __future__ import annotations
import glob
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
import exchange_calendars as xc
import polars as pl

ROOT=Path(__file__).resolve().parents[1]
STORES=Path("/home/quant/dev/quant/ml4t-data/.data/store/forex_minute_USDJPY")
DEST=ROOT/"data/processed/gotobi_2020_2026_usd10k_v1"
DATA=DEST/"USDJPY_tokyo_windows_1m.parquet"
MANIFEST=DEST/"source_manifest.json"
GATE=DEST/"calendar_coverage.json"
START=date(2020,1,1)
END=date(2026,8,31)

def eligible_days():
    cal=xc.get_calendar("XTKS")
    days={x.date() for x in cal.sessions_in_range("2019-12-15","2026-08-31")}
    return sorted(d for d in days if START<=d<=END),days

def gotobi_days(business):
    result=set()
    for year in range(2020,2027):
        for month in range(1,13):
            if (year,month)>(2026,8):break
            following=date(year+(month==12),month%12+1,1)
            last=following-timedelta(days=1)
            for day in [5,10,15,20,25,30,last.day]:
                try:
                    d=date(year,month,day)
                except ValueError:
                    continue
                for _ in range(15):
                    if d in business:break
                    d-=timedelta(days=1)
                if START<=d<=END and d in business:
                    result.add(d)
    return result

def main():
    if any(path.exists() for path in [DATA,MANIFEST,GATE]):
        raise RuntimeError("Immutable materialization already exists")
    filenames=sorted(p for y in range(2020,2027) for p in
        glob.glob(str(STORES/f"year={y}/month=*/day=*/data.parquet")))
    if len(filenames)<1000:
        raise RuntimeError(f"Insufficient source partitions: {len(filenames)}")
    q=(pl.scan_parquet(filenames,hive_partitioning=False)
       .filter((pl.col("timestamp")>=pl.datetime(2020,1,1,time_zone="UTC"))&
               (pl.col("timestamp")<pl.datetime(2026,9,1,time_zone="UTC")))
       .with_columns(pl.col("timestamp").dt.convert_time_zone("Asia/Tokyo").alias("jst"))
       .with_columns(pl.col("jst").dt.date().alias("session"),
         (pl.col("jst").dt.hour().cast(pl.Int32)*60+pl.col("jst").dt.minute().cast(pl.Int32)).alias("minute_jst"))
       .filter(pl.col("minute_jst").is_between(480,630))
       .filter((pl.col("session")>=pl.lit(START))&(pl.col("session")<=pl.lit(END)))
       .select("timestamp","symbol","open","high","low","close","volume","session","minute_jst")
       .sort("timestamp"))
    rows=q.collect()
    sessions,calendar=eligible_days()
    gotobi=gotobi_days(calendar)
    if rows.is_empty() or rows["symbol"].unique().to_list()!=["USDJPY"]:
        raise RuntimeError("Invalid source or symbol")
    duplicates=rows["timestamp"].is_duplicated().sum()
    malformed=rows.filter(
        (pl.col("high")<pl.col("low")) |
        (pl.col("open")<pl.col("low")) | (pl.col("open")>pl.col("high")) |
        (pl.col("close")<pl.col("low")) | (pl.col("close")>pl.col("high"))).height
    missing=rows.select(pl.any_horizontal(
         pl.col("open").is_null(),pl.col("high").is_null(),
         pl.col("low").is_null(),pl.col("close").is_null()).sum()).item()
    if duplicates or malformed or missing:
        raise RuntimeError(f"bad source: duplicates={duplicates}, malformed={malformed}, missing={missing}")
    days=(rows.group_by("session").agg(
         pl.len().alias("count"),pl.col("minute_jst").n_unique().alias("unique"))
         .filter(pl.col("session").is_in(sessions)).sort("session"))
    good=days.filter((pl.col("count")==151)&(pl.col("unique")==151))
    valid=set(good["session"].to_list())
    absent=sorted(set(sessions)-set(days["session"].to_list()))
    incomplete=days.filter((pl.col("count")!=151)|(pl.col("unique")!=151))
    selected=rows.filter(pl.col("session").is_in(sorted(valid)))
    DEST.mkdir(parents=True,exist_ok=True)
    selected.drop("session","minute_jst").write_parquet(DATA,compression="zstd")
    hash_=hashlib.sha256(DATA.read_bytes()).hexdigest()
    gate={
         "expected_tokyo_business_days":len(sessions),
         "full_window_days":len(valid),
         "absent_days":len(absent),"absent_dates":[str(x) for x in absent],
         "incomplete_days":incomplete.height,
         "incomplete_dates":[str(x) for x in incomplete["session"].to_list()],
         "gotobi_days_expected":len(gotobi),
         "gotobi_complete":len(valid&gotobi),
         "gotobi_missing":[str(x) for x in sorted(gotobi-valid)],
         "year_counts":{str(y):{"complete":sum(d.year==y for d in valid),
            "gotobi":sum(d.year==y for d in valid&gotobi)} for y in range(2020,2027)},
         "calendar_basis":"exchange_calendars XTKS proxy for Tokyo banking sessions; cross-check Bank of Japan closing days",
         "calendar_source":"https://www.boj.or.jp/en/about/outline/holi.htm",
         "time_window":"151 distinct 1m bar OPEN timestamps, 08:00 through 10:30 JST",
         "files_checked":len(filenames),"total_window_rows":rows.height,
         "retained_rows":selected.height,"snapshot_sha256":hash_,
         "holdout_scanned":False,
    }
    manifest={
       "provider":"LSE USDJPY canonical ml4t-data store",
       "source_glob":"forex_minute_USDJPY/year=2020..2026/month=*/day=*/data.parquet",
       "source_partition_count":len(filenames),
       "source_file_list_sha256":hashlib.sha256("\n".join(filenames).encode()).hexdigest(),
       "price_timestamp_semantics":"UTC, minute BAR OPEN",
       "output":str(DATA.relative_to(ROOT)),"snapshot_sha256":hash_,
       "rows":selected.height,"first":str(selected["timestamp"].min()),"last":str(selected["timestamp"].max()),
       "scope":"2020-01-01 to 2026-08-31 JST, full 08:00..10:30 minute windows only",
       "holdout_policy":"do not read JST >= 2026-09-01",
       "spread_bid_ask":"Not present; variable spread cannot be validated",
    }
    GATE.write_text(json.dumps(gate,indent=2)+"\n")
    MANIFEST.write_text(json.dumps(manifest,indent=2)+"\n")
    print(json.dumps({"gate":gate,"manifest":manifest},indent=2))

if __name__=="__main__":main()
