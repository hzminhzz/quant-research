"""Read-only canonical data qualification; optional one-way pre-2025 daily snapshot.

This is a DATA stage for gold_fx_trend_diversification_mvp_20261015.
No market signals, PnL, final evaluation or post-2024 input are touched.
Run:
  uv run --no-sync python -m scripts.qualify_gold_fx_daily_20261015 --inspect
  uv run --no-sync python -m scripts.qualify_gold_fx_daily_20261015 --materialize
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

ROOT = Path("/home/quant/dev/quant/ml4t-data/.data/store")
OUT = Path("data/processed/gold_fx_trend_diversification_20261015")
SYMBOLS = ("XAUUSD", "EURUSD", "AUDUSD")
YEARS = tuple(range(2013, 2025))
END = datetime(2025, 1, 1, tzinfo=UTC)


def qualify(symbol: str, *, materialize: bool) -> dict:
    root = ROOT / f"forex_minute_{symbol}"
    files = sorted(p for year in YEARS for p in (root / f"year={year}").rglob("data.parquet"))
    if not files:
        raise FileNotFoundError(f"Missing canonical source: {root}")
    source = pl.scan_parquet([str(p) for p in files], hive_partitioning=False,
        cast_options=pl.ScanCastOptions(datetime_cast="millisecond-upcast", integer_cast="allow-float"),
    ).select("timestamp", "open", "high", "low", "close", "volume")
    source = source.filter(
        (pl.col("timestamp") >= datetime(2013, 1, 1, tzinfo=UTC))
        & (pl.col("timestamp") < END)
    )
    # Validate raw schema/time before converting bar-open clock.
    df = source.collect()
    if df.is_empty() or df["timestamp"].dtype.time_zone != "UTC":
        raise ValueError(f"{symbol}: empty or non-UTC source")
    if df["timestamp"].n_unique() != df.height:
        raise ValueError(f"{symbol}: duplicate minute timestamps")
    malformed = df.filter((pl.col("high") < pl.max_horizontal("open", "close", "low"))
        | (pl.col("low") > pl.min_horizontal("open", "close", "high"))
        | (pl.col("low") <= 0) | pl.col("close").is_null()).height
    if malformed:
        raise ValueError(f"{symbol}: {malformed} OHLC defects")
    local = pl.col("timestamp").dt.convert_time_zone("America/New_York")
    # Close-of-day session 17:00 New York time. Quote minute timestamp = bar open.
    # All early/late session bars share the next local session date.
    day = pl.when(local.dt.hour() >= 17).then(local.dt.date() + pl.duration(days=1)).otherwise(local.dt.date())
    enriched = df.sort("timestamp").with_columns(day.alias("session_date"))
    session = enriched.group_by("session_date").agg(
        pl.col("timestamp").min().alias("first_raw_minute"),
        pl.col("timestamp").max().alias("last_raw_minute"),
        pl.col("open").sort_by("timestamp").first().alias("open"),
        pl.col("high").max().alias("high"),
        pl.col("low").min().alias("low"),
        pl.col("close").sort_by("timestamp").last().alias("close"),
        pl.col("volume").sum().alias("volume"),
        pl.len().alias("n_minutes"),
        pl.col("timestamp").diff().dt.total_minutes().max().alias("max_inside_gap_minutes"),
    ).sort("session_date").with_columns(
        (pl.col("last_raw_minute") + pl.duration(minutes=1)).alias("timestamp"),
    )
    valid_day = (
        (pl.col("session_date").dt.weekday() <= 5)
        & (pl.col("n_minutes") >= 600)
        & (pl.col("max_inside_gap_minutes") <= 90)
    )
    # The last quote must be close to the 17:00 NY session clock.
    close_hm = (pl.col("timestamp").dt.convert_time_zone("America/New_York")
                .dt.hour().cast(pl.Int16) * 60
                + pl.col("timestamp").dt.convert_time_zone("America/New_York")
                .dt.minute().cast(pl.Int16))
    session = session.with_columns(
        (valid_day & close_hm.is_between(16 * 60 + 30, 17 * 60 + 30)).alias("data_eligible")
    )
    valid = session.filter(pl.col("data_eligible") & (pl.col("timestamp") < END))
    if valid.is_empty():
        raise ValueError(f"{symbol}: no qualified sessions")
    # Keep actual vendor-quote quantity semantics; this is not exchange traded size.
    daily = valid.select("timestamp", "session_date", "open", "high", "low", "close",
                         "volume", "n_minutes", "max_inside_gap_minutes")
    years = session.with_columns(pl.col("session_date").dt.year().alias("year")).group_by("year").agg(
        pl.len().alias("raw_sessions"),
        pl.col("data_eligible").sum().alias("eligible_sessions"),
        (pl.col("n_minutes") < 600).sum().alias("under_600_minutes"),
        (pl.col("max_inside_gap_minutes") > 90).sum().alias("inside_gap_gt90"),
    ).sort("year")
    info = {"symbol": symbol, "source": str(root), "source_partition_count":len(files),
            "raw_rows":df.height, "raw_first":str(df["timestamp"].min()),"raw_last":str(df["timestamp"].max()),
            "qualified_daily_rows":daily.height, "qualified_start":str(daily["timestamp"].min()),
            "qualified_end":str(daily["timestamp"].max()),
            "years":years.to_dicts(), "post_2024_source_read": False,
            "data_eligible_criterion":"NY 17:00 close +/- 30m, >=600 bars, no within-session gap >90min",
            "volume_semantics":"Dukascopy broker quote activity, not genuine exchange volume"}
    if materialize:
        OUT.mkdir(parents=True, exist_ok=True)
        dest = OUT / f"{symbol}_NY17_daily_2013_2024.parquet"
        if dest.exists():
            raise FileExistsError(f"Preserve data identity: {dest}")
        daily.write_parquet(dest)
        info["snapshot"] = str(dest)
        info["sha256"] = hashlib.sha256(dest.read_bytes()).hexdigest()
    return info


def main():
    ap=argparse.ArgumentParser()
    group=ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--inspect", action="store_true")
    group.add_argument("--materialize", action="store_true")
    args=ap.parse_args()
    report = {"purpose":"data qualification only","UTC_time":datetime.now(UTC).isoformat(),
              "symbols":{}, "protected_2025_2026":"NOT_TOUCHED"}
    for symbol in SYMBOLS:
        report["symbols"][symbol]=qualify(symbol, materialize=args.materialize)
        info=report["symbols"][symbol]
        print(symbol, "raw",info["raw_rows"], "qualified",info["qualified_daily_rows"],
              "first",info["qualified_start"], "last",info["qualified_end"],flush=True)
    if args.materialize:
        dest = OUT / "data_qualification.json"
        if dest.exists():
            raise FileExistsError(dest)
        dest.write_text(json.dumps(report,indent=2,default=str)+"\n")
    else:
        print(json.dumps({symbol: report["symbols"][symbol]["years"]
                          for symbol in SYMBOLS},default=str)[:6500])


if __name__ == "__main__":
    main()
