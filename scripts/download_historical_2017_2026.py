"""Download historical 5m data (2017-2026) for DAX and Nikkei, and 15m data for SPX500 from LSE Vault."""

import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from lse import LSE
import polars as pl

# Coverage floor from acquisition handoff: bars required through at least
# 2026-09-22; intervals also allowed up to "today" so the latest available
# bars (including post-2026-08-01 OOS) are fetched. Never stops at the
# 2026-07-31 dev boundary.
COVERAGE_FLOOR = date(2026, 9, 22)


def _latest_interval_start() -> date:
    """Latest allowed interval start: max(coverage floor, today, UTC)."""
    return max(COVERAGE_FLOOR, datetime.now(timezone.utc).date())


def get_client() -> LSE:
    """Create the provider client only after the caller has supplied a key."""
    api_key = os.environ.get("LSE_API_KEY")
    if not api_key:
        raise RuntimeError("LSE_API_KEY must be set in the environment; no credential is stored in source")
    return LSE(api_key=api_key)


def generate_intervals(start_year: int = 2017, end_year: int = 2026):
    """Bimonthly [start, end) windows from start_year through end_year.

    Intervals starting after `latest available` (today or the 2026-09-22
    coverage floor, whichever is later) are skipped; everything else runs
    through end_year so post-boundary bars are retained to latest.
    """
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


def download_series(sym: str, timeframe: str, out_path: str, start_year: int = 2017, end_year: int = 2026):
    client = get_client()
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

    # UTC rule (setup.yaml data_contracts.default_timezone: UTC): vendor
    # timestamps parsed as UTC and kept tz-aware; no silent tz strip.
    df = (
        pl.DataFrame(all_rows)
        .with_columns(pl.col("timestamp").str.to_datetime(time_zone="UTC"))
        .sort("timestamp")
        .unique(subset=["timestamp"])
    )

    if "DE30" in sym:
        df = df.filter(pl.col("close") > 0)

    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(p)
    print(f"SUCCESS: Saved {len(df):,} rows ({df['timestamp'].min()} to {df['timestamp'].max()}) to {out_path}")
    return df


if __name__ == "__main__":
    download_series("DE30/EUR", "5m", "data/processed/DE30_EUR_5m_2017_2026.parquet", 2017, 2026)
    download_series("JP225/USD", "5m", "data/processed/JP225_USD_5m_2017_2026.parquet", 2017, 2026)
    download_series("SPX500/USD", "15m", "data/processed/SPX500_USD_15m_2017_2026.parquet", 2017, 2026)
