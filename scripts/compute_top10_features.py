"""Compute Time-Series Momentum and cross-sectional features for 10-asset universe."""

from pathlib import Path
import numpy as np
import polars as pl
from ml4t.engineer import compute_features

DATA_DIR = Path("data/processed")
FEATURES_DIR = Path("data/features")
LABELS_DIR = Path("data/labels")

TOP10 = [
    ("BTCUSDT", DATA_DIR / "btc_1h.parquet"),
    ("ETHUSDT", DATA_DIR / "eth_1h.parquet"),
    ("SOLUSDT", DATA_DIR / "sol_1h.parquet"),
    ("XRPUSDT", DATA_DIR / "xrp_1h.parquet"),
    ("DOGEUSDT", DATA_DIR / "doge_1h.parquet"),
    ("ADAUSDT", DATA_DIR / "ada_1h.parquet"),
    ("AVAXUSDT", DATA_DIR / "avax_1h.parquet"),
    ("NEARUSDT", DATA_DIR / "near_1h.parquet"),
    ("BANDUSDT", DATA_DIR / "band_1h.parquet"),
    ("BALUSDT", DATA_DIR / "bal_1h.parquet"),
]

FEATURE_SPECS = [
    {"name": "roc", "output": "roc_72", "params": {"period": 72}},
    {"name": "roc", "output": "roc_168", "params": {"period": 168}},
    {"name": "ema", "output": "ema_24", "params": {"period": 24}},
    {"name": "ema", "output": "ema_168", "params": {"period": 168}},
    {"name": "atr", "output": "atr_14", "params": {"period": 14}},
    {"name": "adx", "output": "adx", "params": {"period": 14}},
    {"name": "choppiness_index", "output": "choppiness_index", "params": {"period": 14}},
]


def build_top10_features():
    frames = []
    for sym, path in TOP10:
        print(f"Computing features for {sym}...")
        df_raw = pl.read_parquet(path).sort("timestamp")
        df_feat = compute_features(df_raw, FEATURE_SPECS)
        df_feat = df_feat.with_columns(pl.lit(sym).alias("symbol"))
        frames.append(df_feat)

    panel = pl.concat(frames).sort(["symbol", "timestamp"])

    print("Computing panel volatility, cross-sectional ranks, and forward returns...")
    ann_factor = float(np.sqrt(8760))
    panel = panel.with_columns([
        ((pl.col("close") - pl.col("close").shift(1).over("symbol")) / pl.col("close").shift(1).over("symbol")).alias("hourly_ret")
    ])

    # 7-day realized volatility
    panel = panel.with_columns([
        (pl.col("hourly_ret").rolling_std(168).over("symbol") * ann_factor).alias("realized_vol_168")
    ])

    # Volatility-targeted risk-parity weight (target 20% annual portfolio vol across 10 assets)
    # Raw weight = (target_vol / realized_vol) / 10
    target_vol = 0.20
    panel = panel.with_columns([
        pl.when(pl.col("realized_vol_168") > 0.05)
        .then((target_vol / pl.col("realized_vol_168") / 10.0).clip(0.02, 0.20))
        .otherwise(0.10)
        .alias("vol_scaled_weight")
    ])

    # Cross-sectional momentum ranks across all 10 assets at each timestamp
    panel = panel.with_columns([
        pl.col("roc_168").rank().over("timestamp").alias("cs_rank_roc_168"),
        ((pl.col("ema_24") - pl.col("ema_168")) / pl.col("close")).alias("ema_spread_24_168"),
    ])

    # Top 3 momentum assets (top 30% of 10 assets)
    panel = panel.with_columns([
        pl.when(pl.col("cs_rank_roc_168") >= 8.0)
        .then(1.0)
        .otherwise(0.0)
        .alias("is_top_3_momentum")
    ])

    # Forward returns
    panel = panel.with_columns([
        ((pl.col("close").shift(-1).over("symbol") - pl.col("close")) / pl.col("close")).alias("fwd_ret_1h"),
        ((pl.col("close").shift(-4).over("symbol") - pl.col("close")) / pl.col("close")).alias("fwd_ret_4h"),
        ((pl.col("close").shift(-24).over("symbol") - pl.col("close")) / pl.col("close")).alias("fwd_ret_24h"),
        ((pl.col("close").shift(-72).over("symbol") - pl.col("close")) / pl.col("close")).alias("fwd_ret_72h"),
    ])

    features_path = FEATURES_DIR / "crypto_tsmom_top10_features.parquet"
    panel.write_parquet(features_path)
    print(f"Saved 10-asset feature panel to {features_path} with shape {panel.shape}")


if __name__ == "__main__":
    build_top10_features()
