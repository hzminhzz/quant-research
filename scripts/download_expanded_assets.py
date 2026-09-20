"""Download 5m high-frequency data for USD/JPY, BTC/USD, and extend DE30/JP225 through 2026-08."""

from datetime import datetime, timedelta
from pathlib import Path
from lse import LSE
import polars as pl

client = LSE(api_key="lse_live_d72c14901cca9af5e4eb163cd4f7ae56")


def download_14d_chunks(sym: str, timeframe: str, start_date: str, end_date: str, out_path: str):
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

    df = (
        pl.DataFrame(all_rows)
        .with_columns(
            pl.col("timestamp").str.to_datetime(time_zone="UTC").dt.replace_time_zone(None)
        )
        .sort("timestamp")
        .unique(subset=["timestamp"])
    )

    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(p)
    print(f"SUCCESS: Saved {len(df):,} rows ({df['timestamp'].min()} to {df['timestamp'].max()}) to {out_path}")
    return df


def extend_existing(sym: str, timeframe: str, start_date: str, end_date: str, parquet_path: str):
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
        df_new = (
            pl.DataFrame(new_rows)
            .with_columns(
                pl.col("timestamp").str.to_datetime(time_zone="UTC").dt.replace_time_zone(None)
            )
        )
        combined = pl.concat([existing_df, df_new]).sort("timestamp").unique(subset=["timestamp"])
        if "DE30" in sym:
            combined = combined.filter(pl.col("close") > 2000.0)
        combined.write_parquet(p)
        print(f"Updated {parquet_path}: {len(combined):,} rows ({combined['timestamp'].min()} to {combined['timestamp'].max()})")


if __name__ == "__main__":
    # 1. Download USD/JPY 5m
    download_14d_chunks("USD/JPY", "5m", "2022-01-01", "2026-08-01", "data/processed/USDJPY_5m_2022_2026.parquet")
    
    # 2. Download BTC/USD 5m
    download_14d_chunks("BTC/USD", "5m", "2022-01-01", "2026-08-01", "data/processed/BTCUSD_5m_2022_2026.parquet")
    
    # 3. Top up DE30, JP225, SPX500 through 2026-08
    extend_existing("DE30/EUR", "5m", "2026-03-01", "2026-08-01", "data/processed/DE30_EUR_5m_2017_2026.parquet")
    extend_existing("JP225/USD", "5m", "2026-03-01", "2026-08-01", "data/processed/JP225_USD_5m_2017_2026.parquet")
    extend_existing("SPX500/USD", "15m", "2026-03-01", "2026-08-01", "data/processed/SPX500_USD_15m_2017_2026.parquet")
