"""Download 2017-latest historical 5m data for NAS100 and HK33, creating unified 2017-2026 datasets."""

import os
from datetime import date, datetime, timezone
from pathlib import Path
from lse import LSE
import polars as pl

# Coverage floor from acquisition handoff: bars required through at least
# 2026-09-22; intervals also allowed up to today so latest available bars
# (including post-2026-08-01 OOS) are retained. Dev/OOS boundary
# 2026-07-31/2026-08-01 is NOT a stop condition.
COVERAGE_FLOOR = date(2026, 9, 22)


def _latest_interval_start() -> date:
    """Latest allowed interval start: max(coverage floor, today, UTC)."""
    return max(COVERAGE_FLOOR, datetime.now(timezone.utc).date())


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


def generate_intervals(start_year: int = 2017, end_year: int = 2026):
    """Bimonthly [start, end) windows through end_year, stopping only past latest available."""
    latest_start = _latest_interval_start()
    intervals = []
    for y in range(start_year, end_year + 1):
        for m in [1, 3, 5, 7, 9, 11]:
            s_str = f"{y}-{m:02d}-01"
            if m == 11:
                e_str = f"{y+1}-01-01"
            else:
                e_str = f"{y}-{m+2:02d}-01"
            if date.fromisoformat(s_str) > latest_start:
                continue
            intervals.append((s_str, e_str))
    return intervals


def extend_to_2017(sym: str, existing_parquet: str, out_parquet: str):
    client = get_client()
    print(f"\n=======================================================")
    print(f"Downloading historical 2017-latest for {sym}")
    print(f"Merging with: {existing_parquet}")
    print(f"Output target: {out_parquet}")
    print(f"=======================================================")
    
    intervals = generate_intervals(2017, 2026)
    all_rows = []

    for idx, (s, e) in enumerate(intervals):
        try:
            rows = client.candles(sym, timeframe="5m", start=s, end=e, limit=5000, order="asc")
            all_rows.extend(rows)
            print(f"[{idx+1}/{len(intervals)}] {s} -> {e}: {len(rows)} bars (Cumulative: {len(all_rows):,})")
        except Exception as ex:
            print(f"[{idx+1}/{len(intervals)}] Error fetching {s} -> {e}: {ex}")

    # UTC rule (setup.yaml data_contracts.default_timezone: UTC): parse as
    # UTC and keep tz-aware; existing naive files are legacy UTC wall-times
    # re-attached as UTC via _ensure_utc. No silent tz strip.
    df_hist = (
        pl.DataFrame(all_rows)
        .with_columns(pl.col("timestamp").str.to_datetime(time_zone="UTC"))
    )

    df_existing = _ensure_utc(pl.read_parquet(existing_parquet))
    if df_hist.schema["timestamp"] != df_existing.schema["timestamp"]:
        df_hist = df_hist.with_columns(
            pl.col("timestamp").cast(df_existing.schema["timestamp"])
        )

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
