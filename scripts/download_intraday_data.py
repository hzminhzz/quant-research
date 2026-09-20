"""Download 5m and 1m high-frequency data for DAX, Nikkei, and SPX from London Strategic Edge Vault."""

from datetime import datetime, timedelta
from pathlib import Path
from lse import LSE
import polars as pl

client = LSE(api_key="lse_live_d72c14901cca9af5e4eb163cd4f7ae56")


def download_5m(sym: str, out_path: str, start_year: int = 2023, end_year: int = 2026):
    print(f"=== Downloading 5m for {sym} ({start_year}-{end_year}) ===")
    all_rows = []
    
    # 2-month intervals
    intervals = []
    for y in range(start_year, end_year):
        for m in [1, 3, 5, 7, 9, 11]:
            s_str = f"{y}-{m:02d}-01"
            if m == 11:
                e_str = f"{y+1}-01-01"
            else:
                e_str = f"{y}-{m+2:02d}-01"
            intervals.append((s_str, e_str))
            
    for s, e in intervals:
        rows = client.candles(sym, timeframe="5m", start=s, end=e, limit=5000, order="asc")
        all_rows.extend(rows)
        print(f"  [{sym} 5m] {s} -> {e}: {len(rows)} bars (total {len(all_rows)})")
        
    df = (
        pl.DataFrame(all_rows)
        .with_columns(
            pl.col("timestamp").str.to_datetime(time_zone="UTC").dt.replace_time_zone(None)
        )
        .sort("timestamp")
        .unique(subset=["timestamp"])
    )
    if "DE30" in sym:
        df = df.filter(pl.col("close") > 2000.0)
        
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(p)
    print(f"-> Saved {len(df)} 5m rows to {out_path}")
    return df


def download_1m(sym: str, out_path: str, start_date: str = "2024-01-01", end_date: str = "2026-01-01"):
    print(f"=== Downloading 1m for {sym} ({start_date} to {end_date}) ===")
    all_rows = []
    
    # Step weekly (7 days ~ 3500 bars < 5000)
    cur = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    
    while cur < end_dt:
        nxt = min(cur + timedelta(days=7), end_dt)
        s_str = cur.strftime("%Y-%m-%d")
        e_str = nxt.strftime("%Y-%m-%d")
        rows = client.candles(sym, timeframe="1m", start=s_str, end=e_str, limit=5000, order="asc")
        all_rows.extend(rows)
        cur = nxt
        if len(all_rows) % 25000 < 5000:
            print(f"  [{sym} 1m] at {e_str}: total {len(all_rows)} bars")
            
    df = (
        pl.DataFrame(all_rows)
        .with_columns(
            pl.col("timestamp").str.to_datetime(time_zone="UTC").dt.replace_time_zone(None)
        )
        .sort("timestamp")
        .unique(subset=["timestamp"])
    )
    if "DE30" in sym:
        df = df.filter(pl.col("close") > 2000.0)
        
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(p)
    print(f"-> Saved {len(df)} 1m rows to {out_path}")
    return df


if __name__ == "__main__":
    download_5m("DE30/EUR", "data/processed/DE30_EUR_5m_2023_2026.parquet")
    download_5m("JP225/USD", "data/processed/JP225_USD_5m_2023_2026.parquet")
    download_1m("DE30/EUR", "data/processed/DE30_EUR_1m_2024_2026.parquet", start_date="2024-01-01", end_date="2026-01-01")
    download_1m("JP225/USD", "data/processed/JP225_USD_1m_2024_2026.parquet", start_date="2024-01-01", end_date="2026-01-01")
