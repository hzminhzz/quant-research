"""Download 2017-2022 historical 5m data for NAS100 and HK33, creating unified 2017-2026 datasets."""

from datetime import datetime
from pathlib import Path
from lse import LSE
import polars as pl

client = LSE(api_key="lse_live_d72c14901cca9af5e4eb163cd4f7ae56")


def generate_intervals(start_year: int = 2017, end_year: int = 2022):
    intervals = []
    for y in range(start_year, end_year):
        for m in [1, 3, 5, 7, 9, 11]:
            s_str = f"{y}-{m:02d}-01"
            if m == 11:
                e_str = f"{y+1}-01-01"
            else:
                e_str = f"{y}-{m+2:02d}-01"
            intervals.append((s_str, e_str))
    return intervals


def extend_to_2017(sym: str, existing_parquet: str, out_parquet: str):
    print(f"\n=======================================================")
    print(f"Downloading historical 2017-2022 for {sym}")
    print(f"Merging with: {existing_parquet}")
    print(f"Output target: {out_parquet}")
    print(f"=======================================================")
    
    intervals = generate_intervals(2017, 2022)
    all_rows = []

    for idx, (s, e) in enumerate(intervals):
        try:
            rows = client.candles(sym, timeframe="5m", start=s, end=e, limit=5000, order="asc")
            all_rows.extend(rows)
            print(f"[{idx+1}/{len(intervals)}] {s} -> {e}: {len(rows)} bars (Cumulative: {len(all_rows):,})")
        except Exception as ex:
            print(f"[{idx+1}/{len(intervals)}] Error fetching {s} -> {e}: {ex}")

    df_hist = (
        pl.DataFrame(all_rows)
        .with_columns(
            pl.col("timestamp").str.to_datetime(time_zone="UTC").dt.replace_time_zone(None)
        )
    )

    df_existing = pl.read_parquet(existing_parquet)
    # Ensure timestamp dtypes match
    if df_existing["timestamp"].dtype != df_hist["timestamp"].dtype:
        df_existing = df_existing.with_columns(pl.col("timestamp").cast(df_hist["timestamp"].dtype))

    combined = (
        pl.concat([df_hist.select(df_existing.columns), df_existing])
        .sort("timestamp")
        .unique(subset=["timestamp"])
    )

    p = Path(out_parquet)
    p.parent.mkdir(parents=True, exist_ok=True)
    combined.write_parquet(p)
    print(f"SUCCESS: Saved {len(combined):,} rows ({combined['timestamp'].min()} to {combined['timestamp'].max()}) to {out_parquet}")
    return combined


if __name__ == "__main__":
    extend_to_2017(
        sym="NAS100/USD",
        existing_parquet="data/processed/NAS100_5m_2022_2026.parquet",
        out_parquet="data/processed/NAS100_5m_2017_2026.parquet",
    )
    extend_to_2017(
        sym="HK33/HKD",
        existing_parquet="data/processed/HK33_5m_2022_2026.parquet",
        out_parquet="data/processed/HK33_5m_2017_2026.parquet",
    )
