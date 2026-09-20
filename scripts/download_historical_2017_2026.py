"""Download historical 5m data (2017-2026) for DAX and Nikkei, and 15m data for SPX500 from LSE Vault."""

import sys
from datetime import datetime
from pathlib import Path
from lse import LSE
import polars as pl

client = LSE(api_key="lse_live_d72c14901cca9af5e4eb163cd4f7ae56")


def generate_intervals(start_year: int = 2017, end_year: int = 2026):
    intervals = []
    for y in range(start_year, end_year + 1):
        for m in [1, 3, 5, 7, 9, 11]:
            s_str = f"{y}-{m:02d}-01"
            if m == 11:
                e_str = f"{y+1}-01-01"
            else:
                e_str = f"{y}-{m+2:02d}-01"
            # Stop if in future
            if s_str > "2026-04-01":
                continue
            intervals.append((s_str, e_str))
    return intervals


def download_series(sym: str, timeframe: str, out_path: str, start_year: int = 2017, end_year: int = 2026):
    print(f"\n=======================================================")
    print(f"Downloading {sym} ({timeframe}) from {start_year} to {end_year}")
    print(f"Target: {out_path}")
    print(f"=======================================================")
    intervals = generate_intervals(start_year, end_year)
    all_rows = []

    for idx, (s, e) in enumerate(intervals):
        try:
            rows = client.candles(sym, timeframe=timeframe, start=s, end=e, limit=5000, order="asc")
            all_rows.extend(rows)
            print(f"[{idx+1}/{len(intervals)}] {s} -> {e}: {len(rows)} bars (Cumulative: {len(all_rows)})")
        except Exception as ex:
            print(f"[{idx+1}/{len(intervals)}] Error fetching {s} -> {e}: {ex}")

    if not all_rows:
        print(f"ERROR: No rows downloaded for {sym}")
        return None

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
    print(f"SUCCESS: Saved {len(df):,} rows ({df['timestamp'].min()} to {df['timestamp'].max()}) to {out_path}")
    return df


if __name__ == "__main__":
    download_series("DE30/EUR", "5m", "data/processed/DE30_EUR_5m_2017_2026.parquet", 2017, 2026)
    download_series("JP225/USD", "5m", "data/processed/JP225_USD_5m_2017_2026.parquet", 2017, 2026)
    download_series("SPX500/USD", "15m", "data/processed/SPX500_USD_15m_2017_2026.parquet", 2017, 2026)
