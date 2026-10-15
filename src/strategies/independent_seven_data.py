"""Canonical local ML4T-data loaders for independent seven exploratory 2020-2022 runs.

No downloads, changes to canonical stores, or invented ETF backfills.
Source time at daily level is an exchange/CFD session label, not a claim
that daily OHLC was known at the session start.
"""
from __future__ import annotations

from pathlib import Path
from datetime import datetime
import polars as pl

STORE = Path("/home/quant/dev/quant/ml4t-data/.data/store")
SOURCE = {
    "BTC": "crypto_futures_minute_BTCUSDT_PERP",
    "ES": "index_minute_ES",
    "XAU": "forex_minute_XAUUSD",
    "EUR": "forex_minute_EURUSD",
    "DXY": "equity_daily_DX_Y.NYB",
}

def load_daily(asset: str, first_year: int = 2019, last_year: int = 2022, *, end_exclusive: datetime | None = None) -> tuple[pl.DataFrame, dict]:
    if asset not in SOURCE:
        raise KeyError(asset)
    root = STORE / SOURCE[asset]
    files = sorted(p for year in range(first_year, last_year + 1)
                   for p in (root / f"year={year}").rglob("data.parquet"))
    if not files:
        raise FileNotFoundError(str(root))
    raw = pl.scan_parquet([str(p) for p in files], hive_partitioning=False,
                          cast_options=pl.ScanCastOptions(datetime_cast="millisecond-upcast", integer_cast="allow-float"))
    expected = {"timestamp", "open", "high", "low", "close", "volume"}
    if not expected.issubset(raw.collect_schema()):
        raise ValueError(f"{asset}: raw data missing {expected - set(raw.collect_schema())}")
    raw = raw.select("timestamp", "open", "high", "low", "close", "volume")
    if end_exclusive is not None:
        raw = raw.filter(pl.col("timestamp") < pl.lit(end_exclusive))
    if asset == "DXY":
        out = raw.with_columns(
            pl.col("timestamp").dt.convert_time_zone("UTC").dt.date().alias("session")
        ).collect()
        out = out.unique(subset=["session"], keep="first").sort("session")
        out = out.with_columns(pl.lit(1).alias("bars"))
    else:
        if asset == "BTC":
            session = pl.col("timestamp").dt.date()
        else:
            local = pl.col("timestamp").dt.convert_time_zone("America/New_York")
            session = pl.when(local.dt.hour() >= 17).then(
                local.dt.date() + pl.duration(days=1)
            ).otherwise(local.dt.date())
        # Source minute OHLC are in market time; session key is assigned
        # from actual timezone-aware timestamps before daily aggregation.
        raw = raw.with_columns(session.alias("session"))
        out = raw.group_by("session").agg(
            pl.col("open").sort_by("timestamp").first().alias("open"),
            pl.col("high").max().alias("high"),
            pl.col("low").min().alias("low"),
            pl.col("close").sort_by("timestamp").last().alias("close"),
            pl.col("volume").sum().alias("volume"),
            pl.len().alias("bars"),
        ).collect().sort("session")
        minimum = 1300 if asset == "BTC" else 500
        out = out.filter(pl.col("bars") >= minimum)
    if asset != "BTC":
        out = out.filter(pl.col("session").dt.weekday() <= 5)
    out = out.with_columns(
        pl.col("session").cast(pl.Datetime("us")).dt.replace_time_zone("UTC").alias("timestamp")
    ).filter(
        pl.col("timestamp").dt.year().is_between(first_year, last_year)
    ).select("timestamp", "open", "high", "low", "close", "volume", "bars")
    bad = out.filter(
        (pl.col("high") < pl.col("low"))
        | (pl.col("close") > pl.col("high")) | (pl.col("close") < pl.col("low"))
        | (pl.col("open") > pl.col("high")) | (pl.col("open") < pl.col("low"))
        | (pl.col("close") <= 0) | (pl.col("open") <= 0)
    )
    if bad.height:
        raise ValueError(f"{asset}: {bad.height} malformed daily bars")
    if out["timestamp"].n_unique() != out.height:
        raise ValueError(f"{asset}: duplicate session timestamps")
    manifest = {
        "source": SOURCE[asset], "asset": asset, "files": len(files),
        "first": str(out["timestamp"].min()), "last": str(out["timestamp"].max()),
        "bars": out.height, "min_minutes_per_session": 1 if asset == "DXY" else minimum,
        "timestamp_semantics": "daily session label, not decision/fill clock",
        "session_calendar": "UTC crypto" if asset == "BTC" else ("DXY exchange date" if asset == "DXY" else "New York 17:00 session end"),
        "raw_store": str(root),
        "end_exclusive_utc": str(end_exclusive) if end_exclusive else None,
    }
    return out.drop("bars"), manifest
