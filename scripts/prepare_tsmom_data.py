"""Prepare canonical 1H price bars and funding rates for BTC, ETH, SOL."""

from pathlib import Path
import polars as pl

STORE_BASE = Path("/home/quant/dev/quant/ml4t-data/.data/store")
OUT_DIR = Path("data/processed")
OUT_DIR.mkdir(parents=True, exist_ok=True)

START_TS = pl.datetime(2021, 1, 1, 0, 0, 0, time_zone="UTC")
END_TS = pl.datetime(2026, 8, 29, 0, 0, 0, time_zone="UTC")

SYMBOLS = [
    ("BTCUSDT", "btc"),
    ("ETHUSDT", "eth"),
    ("SOLUSDT", "sol"),
]


def prepare_prices():
    for sym, prefix in SYMBOLS:
        p = STORE_BASE / f"crypto_futures_minute_{sym}_PERP"
        files = sorted(p.glob("year=202[1-6]/**/*.parquet"))
        print(f"Processing {sym} 1H prices from {len(files)} minute files...")

        df_1h = (
            pl.scan_parquet(files)
            .filter(
                (pl.col("timestamp") >= START_TS)
                & (pl.col("timestamp") <= END_TS)
            )
            .sort("timestamp")
            .group_by_dynamic("timestamp", every="1h")
            .agg(
                [
                    pl.col("open").first(),
                    pl.col("high").max(),
                    pl.col("low").min(),
                    pl.col("close").last(),
                    pl.col("volume").sum(),
                ]
            )
            .collect()
            .unique(subset=["timestamp"])
            .sort("timestamp")
        )
        out_path = OUT_DIR / f"{prefix}_1h.parquet"
        df_1h.write_parquet(out_path)
        print(f"Saved {out_path}: {df_1h.shape}")


def prepare_funding():
    for sym, prefix in SYMBOLS:
        pf = STORE_BASE / f"crypto_futures_funding_{sym}_PERP"
        files = sorted(pf.glob("**/*.parquet"))
        print(f"Processing {sym} funding from {len(files)} files...")

        df_fund = (
            pl.scan_parquet(files)
            .filter(
                (pl.col("timestamp") >= START_TS)
                & (pl.col("timestamp") <= END_TS)
            )
            .select(["timestamp", "funding_rate"])
            .collect()
            .unique(subset=["timestamp"])
            .sort("timestamp")
        )
        out_path = OUT_DIR / f"{prefix}_funding.parquet"
        df_fund.write_parquet(out_path)
        print(f"Saved {out_path}: {df_fund.shape}")


if __name__ == "__main__":
    prepare_prices()
    prepare_funding()
    print("All canonical datasets generated successfully.")
