"""Prepare canonical 1H price bars and funding rates for Top 10 Liquid Binance USD-M Futures assets."""

from pathlib import Path
import polars as pl

STORE_BASE = Path("/home/quant/dev/quant/ml4t-data/.data/store")
P_1H_BASE = STORE_BASE / "crypto_futures_ohlcv_1h_BINANCE_UM_PERP"
OUT_DIR = Path("data/processed")
OUT_DIR.mkdir(parents=True, exist_ok=True)

START_TS = pl.datetime(2021, 1, 1, 0, 0, 0, time_zone="UTC")
END_TS = pl.datetime(2026, 7, 31, 23, 0, 0, time_zone="UTC")

TOP10 = [
    ("BTCUSDT", "btc"),
    ("ETHUSDT", "eth"),
    ("SOLUSDT", "sol"),
    ("XRPUSDT", "xrp"),
    ("DOGEUSDT", "doge"),
    ("ADAUSDT", "ada"),
    ("AVAXUSDT", "avax"),
    ("NEARUSDT", "near"),
    ("BANDUSDT", "band"),
    ("BALUSDT", "bal"),
]


def prepare_prices():
    for sym, prefix in TOP10:
        sp = P_1H_BASE / f"symbol={sym}"
        files = sorted(sp.glob("**/*.parquet"))
        print(f"Processing {sym} 1H prices from {len(files)} files...")
        
        df = (
            pl.scan_parquet(files)
            .filter((pl.col("timestamp") >= START_TS) & (pl.col("timestamp") <= END_TS))
            .select(["timestamp", "open", "high", "low", "close", "volume"])
            .collect()
            .unique(subset=["timestamp"])
            .sort("timestamp")
        )
        out_path = OUT_DIR / f"{prefix}_1h.parquet"
        df.write_parquet(out_path)
        print(f"  Saved {out_path}: {df.shape}, {df['timestamp'].min()} -> {df['timestamp'].max()}")


def prepare_funding():
    for sym, prefix in TOP10:
        pf = STORE_BASE / f"crypto_futures_funding_{sym}_PERP"
        files = sorted(pf.glob("**/*.parquet"))
        print(f"Processing {sym} funding from {len(files)} files...")
        
        df_fund = (
            pl.scan_parquet(files)
            .filter((pl.col("timestamp") >= START_TS) & (pl.col("timestamp") <= END_TS))
            .select(["timestamp", "funding_rate"])
            .collect()
            .unique(subset=["timestamp"])
            .sort("timestamp")
        )
        out_path = OUT_DIR / f"{prefix}_funding.parquet"
        df_fund.write_parquet(out_path)
        print(f"  Saved {out_path}: {df_fund.shape}, {df_fund['timestamp'].min()} -> {df_fund['timestamp'].max()}")


if __name__ == "__main__":
    prepare_prices()
    prepare_funding()
    print("All Top 10 datasets generated successfully.")
