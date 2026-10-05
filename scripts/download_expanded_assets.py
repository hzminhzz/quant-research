"""Download 5m high-frequency data for USD/JPY, BTC/USD, and extend DE30/JP225/SPX500 through latest available."""

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from lse import LSE
import polars as pl

# Coverage floor from acquisition handoff: bars required through at least
# 2026-09-22; chunks also run up to today so latest available bars
# (including post-2026-08-01 OOS) are retained. Dev/OOS boundary
# 2026-07-31/2026-08-01 is NOT a stop condition.
COVERAGE_FLOOR = date(2026, 9, 22)


def _coverage_end() -> str:
    """End date string: max(coverage floor, today, UTC)."""
    return max(COVERAGE_FLOOR, datetime.now(timezone.utc).date()).isoformat()


def _ensure_utc(df):
    """Normalize timestamp column to tz-aware UTC.

    Naive columns are legacy UTC wall-times (stripped by older downloads);
    re-attach UTC without conversion. tz-aware columns convert to UTC.
    """
    ts = df.schema["timestamp"]
    if ts.time_zone is None:
        return df.with_columns(pl.col("timestamp").dt.replace_time_zone("UTC"))
    if ts.time_zone != "UTC":
        return df.with_columns(pl.col("timestamp").dt.convert_time_zone("UTC"))
    return df


def get_client() -> LSE:
    """Create the provider client only after the caller has supplied a key."""
    api_key = os.environ.get("LSE_API_KEY")
    if not api_key:
        raise RuntimeError("LSE_API_KEY must be set in the environment; no credential is stored in source")
    return LSE(api_key=api_key)


def download_14d_chunks(sym: str, timeframe: str, start_date: str, end_date: str, out_path: str):
    client = get_client()
    print(f"\n=======================================================")
    print(f"Downloading {sym} ({timeframe}) from {start_date} to {end_date}")
    print(f"Target: {out_path}")
    print(f"=======================================================")
    
    cur = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    all_rows = []
    chunk_idx = 0

    while cur < end_dt:
        nxt = min(cur + timedelta(days=14), end_dt)
        s_str = cur.strftime("%Y-%m-%d")
        e_str = nxt.strftime("%Y-%m-%d")
        chunk_idx += 1
        
        try:
            rows = client.candles(sym, timeframe=timeframe, start=s_str, end=e_str, limit=5000, order="asc")
            all_rows.extend(rows)
            if chunk_idx % 10 == 0 or nxt >= end_dt:
                print(f"  [{sym}] chunk {chunk_idx}: {s_str} -> {e_str} ({len(rows)} bars, total {len(all_rows):,})")
        except Exception as e:
            print(f"  [{sym}] Error at {s_str} -> {e_str}: {e}")
            
        cur = nxt

    if not all_rows:
        print(f"ERROR: No rows for {sym}")
        return None

    # UTC rule (setup.yaml data_contracts.default_timezone: UTC): parse as
    # UTC and keep tz-aware; no silent tz strip.
    df = (
        pl.DataFrame(all_rows)
        .with_columns(pl.col("timestamp").str.to_datetime(time_zone="UTC"))
        .sort("timestamp")
        .unique(subset=["timestamp"])
    )

    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(p)
    print(f"SUCCESS: Saved {len(df):,} rows ({df['timestamp'].min()} to {df['timestamp'].max()}) to {out_path}")
    return df


def extend_existing(sym: str, timeframe: str, start_date: str, end_date: str, parquet_path: str):
    client = get_client()
    print(f"\nTopping up {sym} ({timeframe}) from {start_date} to {end_date}...")
    p = Path(parquet_path)
    existing_df = pl.read_parquet(p)
    
    cur = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    new_rows = []
    
    while cur < end_dt:
        nxt = min(cur + timedelta(days=14), end_dt)
        s_str = cur.strftime("%Y-%m-%d")
        e_str = nxt.strftime("%Y-%m-%d")
        try:
            rows = client.candles(sym, timeframe=timeframe, start=s_str, end=e_str, limit=5000, order="asc")
            new_rows.extend(rows)
        except Exception as e:
            print(f"  Error {s_str} -> {e_str}: {e}")
        cur = nxt

    if new_rows:
        # UTC rule (setup.yaml data_contracts.default_timezone: UTC): new
        # rows parsed as tz-aware UTC; existing naive files are legacy UTC
        # wall-times re-attached as UTC via _ensure_utc. No silent tz strip.
        df_new = (
            pl.DataFrame(new_rows)
            .with_columns(pl.col("timestamp").str.to_datetime(time_zone="UTC"))
        )
        existing_df = _ensure_utc(existing_df)
        combined = pl.concat([existing_df, df_new]).sort("timestamp").unique(subset=["timestamp"])
        if "DE30" in sym:
            combined = combined.filter(pl.col("close") > 0)
        combined.write_parquet(p)
        print(f"Updated {parquet_path}: {len(combined):,} rows ({combined['timestamp'].min()} to {combined['timestamp'].max()})")


if __name__ == "__main__":
    _end = _coverage_end()

    # 1. Download USD/JPY 5m
    download_14d_chunks("USD/JPY", "5m", "2022-01-01", _end, "data/processed/USDJPY_5m_2022_2026.parquet")
    
    # 2. Download BTC/USD 5m
    download_14d_chunks("BTC/USD", "5m", "2022-01-01", _end, "data/processed/BTCUSD_5m_2022_2026.parquet")
    
    # 3. Top up DE30, JP225, SPX500 through latest available (retains post-2026-08-01 OOS bars)
    extend_existing("DE30/EUR", "5m", "2026-03-01", _end, "data/processed/DE30_EUR_5m_2017_2026.parquet")
    extend_existing("JP225/USD", "5m", "2026-03-01", _end, "data/processed/JP225_USD_5m_2017_2026.parquet")
    extend_existing("SPX500/USD", "15m", "2026-03-01", _end, "data/processed/SPX500_USD_15m_2017_2026.parquet")
