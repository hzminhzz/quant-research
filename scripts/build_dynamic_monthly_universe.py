"""Build Point-in-Time Monthly Rolling Universe from Binance USD-M Futures 1H data."""

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import polars as pl

STORE_PATH = Path("/home/quant/dev/quant/ml4t-data/.data/store/crypto_futures_ohlcv_1h_BINANCE_UM_PERP")
OUT_DIR = Path("run_log/dynamic_universe")
OUT_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR = Path("data/processed")
DATA_DIR.mkdir(parents=True, exist_ok=True)


def compute_monthly_dollar_volumes() -> dict:
    print("Scanning all USDT perpetuals for monthly dollar volume...")
    candidates = []
    for sd in STORE_PATH.glob("symbol=*USDT"):
        files = list(sd.glob("year=*/month=*/data.parquet"))
        if len(files) >= 12:  # At least 1 year history
            candidates.append((sd.name.replace("symbol=", ""), files))

    print(f"Aggregating monthly dollar volume across {len(candidates)} symbols...")
    monthly_vol = defaultdict(dict)  # (year, month) -> {symbol: dollar_vol}

    for sym, files in candidates:
        for f in files:
            parts = f.parts
            y = int(parts[-3].replace("year=", ""))
            m = int(parts[-2].replace("month=", ""))
            if y < 2020 or y > 2026:
                continue
            try:
                df = pl.read_parquet(f, columns=["close", "volume"])
                dvol = float((df["close"] * df["volume"]).sum())
                monthly_vol[(y, m)][sym] = dvol
            except Exception:
                pass

    return monthly_vol


def build_pit_schedule(monthly_vol: dict) -> tuple[dict, set]:
    print("Constructing Point-in-Time monthly Top 10 selection (zero lookahead)...")
    # For month (Y, M), rank symbols using prior month (Y_prev, M_prev)
    pit_universe = {}  # "YYYY-MM" -> [symbols]
    all_member_symbols = set()

    for y in range(2021, 2027):
        for m in range(1, 13):
            if y == 2026 and m > 7:
                break

            # Previous month
            if m == 1:
                prev_ym = (y - 1, 12)
            else:
                prev_ym = (y, m - 1)

            prev_vols = monthly_vol.get(prev_ym, {})
            if not prev_vols:
                continue

            # Top 10 by trailing volume
            top10 = sorted(prev_vols.items(), key=lambda x: -x[1])[:10]
            top_syms = [s[0] for s in top10]

            month_key = f"{y}-{m:02d}"
            pit_universe[month_key] = top_syms
            all_member_symbols.update(top_syms)

    return pit_universe, all_member_symbols


def prepare_universe_data(member_symbols: set):
    print(f"\nPreparing canonical 1H OHLCV files for {len(member_symbols)} unique dynamic members...")
    start_ts = pl.datetime(2021, 1, 1, 0, 0, 0, time_zone="UTC")
    end_ts = pl.datetime(2026, 7, 31, 23, 0, 0, time_zone="UTC")

    for sym in sorted(member_symbols):
        sp = STORE_PATH / f"symbol={sym}"
        files = sorted(sp.glob("**/*.parquet"))
        if not files:
            continue
        out_file = DATA_DIR / f"{sym.lower()}_1h.parquet"
        if out_file.exists():
            continue

        try:
            df = (
                pl.scan_parquet(files)
                .filter((pl.col("timestamp") >= start_ts) & (pl.col("timestamp") <= end_ts))
                .select(["timestamp", "open", "high", "low", "close", "volume"])
                .collect()
                .unique(subset=["timestamp"])
                .sort("timestamp")
            )
            df.write_parquet(out_file)
            print(f"  Extracted {sym}: {df.shape[0]} bars ({df['timestamp'].min()} -> {df['timestamp'].max()})")
        except Exception as e:
            print(f"  Error extracting {sym}: {e}")


def main():
    vol_data = compute_monthly_dollar_volumes()
    pit_schedule, members = build_pit_schedule(vol_data)

    print(f"\nConstructed PIT schedule for {len(pit_schedule)} months.")
    print(f"Total unique symbols that entered Top 10 across history: {len(members)}")
    print(f"Unique members: {sorted(members)}")

    schedule_path = OUT_DIR / "monthly_top10_universe.json"
    with schedule_path.open("w") as f:
        json.dump(pit_schedule, f, indent=2)
    print(f"Saved PIT schedule to {schedule_path}")

    prepare_universe_data(members)
    print("Point-in-Time monthly universe build complete.")


if __name__ == "__main__":
    main()
