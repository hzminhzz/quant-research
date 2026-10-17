"""Compute Time-Series Momentum features, volatility targeting, and regime metrics."""

import numpy as np
from pathlib import Path
import polars as pl
from ml4t.engineer import compute_features

DATA_DIR = Path("data/processed")
FEATURES_DIR = Path("data/features")
LABELS_DIR = Path("data/labels")
FEATURES_DIR.mkdir(parents=True, exist_ok=True)
LABELS_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS = [
    ("BTCUSDT", DATA_DIR / "btc_1h.parquet"),
    ("ETHUSDT", DATA_DIR / "eth_1h.parquet"),
    ("SOLUSDT", DATA_DIR / "sol_1h.parquet"),
]

FEATURE_SPECS = [
    {"name": "roc", "output": "roc_24", "params": {"period": 24}},
    {"name": "roc", "output": "roc_72", "params": {"period": 72}},
    {"name": "roc", "output": "roc_168", "params": {"period": 168}},
    {"name": "ema", "output": "ema_12", "params": {"period": 12}},
    {"name": "ema", "output": "ema_24", "params": {"period": 24}},
    {"name": "ema", "output": "ema_48", "params": {"period": 48}},
    {"name": "ema", "output": "ema_168", "params": {"period": 168}},
    {"name": "donchian_channels", "output": "donchian_24", "params": {"period": 24}},
    {"name": "donchian_channels", "output": "donchian_48", "params": {"period": 48}},
    {"name": "donchian_channels", "output": "donchian_168", "params": {"period": 168}},
    {"name": "atr", "output": "atr_14", "params": {"period": 14}},
    {"name": "adx", "output": "adx", "params": {"period": 14}},
    {"name": "choppiness_index", "output": "choppiness_index", "params": {"period": 14}},
]


def build_features_and_labels():
    per_symbol_frames = []

    for sym, path in SYMBOLS:
        print(f"Computing ml4t.engineer features for {sym}...")
        df_raw = pl.read_parquet(path).sort("timestamp")
        df_feat = compute_features(df_raw, FEATURE_SPECS)
        
        df_feat = df_feat.rename({
            "donchian_24_0": "donchian_24_upper",
            "donchian_24_1": "donchian_24_lower",
            "donchian_24_2": "donchian_24_mid",
            "donchian_48_0": "donchian_48_upper",
            "donchian_48_1": "donchian_48_lower",
            "donchian_48_2": "donchian_48_mid",
            "donchian_168_0": "donchian_168_upper",
            "donchian_168_1": "donchian_168_lower",
            "donchian_168_2": "donchian_168_mid",
        })
        
        df_feat = df_feat.with_columns(pl.lit(sym).alias("symbol"))
        per_symbol_frames.append(df_feat)

    panel = pl.concat(per_symbol_frames).sort(["symbol", "timestamp"])

    print("Computing volatility targeting and regime metrics...")
    annualization_factor = float(np.sqrt(8760))
    panel = panel.with_columns([
        ((pl.col("close") - pl.col("close").shift(1).over("symbol")) / pl.col("close").shift(1).over("symbol")).alias("hourly_ret")
    ])

    # Realized volatility
    panel = panel.with_columns([
        (pl.col("hourly_ret").rolling_std(168).over("symbol") * annualization_factor).alias("realized_vol_168"),
        (pl.col("hourly_ret").rolling_std(24).over("symbol") * annualization_factor).alias("realized_vol_24"),
    ])

    # 90-day (2,160 hour) rolling volatility min/max rank
    panel = panel.with_columns([
        pl.col("realized_vol_168").rolling_min(2160).shift(1).over("symbol").alias("vol_min_90d"),
        pl.col("realized_vol_168").rolling_max(2160).shift(1).over("symbol").alias("vol_max_90d"),
    ])

    panel = panel.with_columns([
        pl.when((pl.col("vol_max_90d") - pl.col("vol_min_90d")) > 0.01)
        .then((pl.col("realized_vol_168") - pl.col("vol_min_90d")) / (pl.col("vol_max_90d") - pl.col("vol_min_90d")))
        .otherwise(0.50)
        .clip(0.0, 1.0)
        .alias("vol_rank_90d")
    ])

    # Base volatility-targeted weight
    target_vol = 0.20
    panel = panel.with_columns([
        pl.when(pl.col("realized_vol_168") > 0.05)
        .then((target_vol / pl.col("realized_vol_168") / 3.0).clip(0.05, 0.35))
        .otherwise(0.20)
        .alias("vol_scaled_weight")
    ])

    # Regime multipliers
    # Trend strength: ADX / 25 capped at [0.5, 1.5]
    # Volatility discount: (1.3 - vol_rank_90d) capped at [0.5, 1.3]
    panel = panel.with_columns([
        (pl.col("adx") / 25.0).clip(0.5, 1.5).alias("trend_multiplier"),
        (1.3 - pl.col("vol_rank_90d")).clip(0.5, 1.3).alias("vol_discount"),
    ])

    panel = panel.with_columns([
        (pl.col("vol_scaled_weight") * pl.col("trend_multiplier") * pl.col("vol_discount")).clip(0.05, 0.40).alias("regime_scaled_weight")
    ])

    # Signals
    panel = panel.with_columns([
        ((pl.col("ema_24") - pl.col("ema_168")) / pl.col("close")).alias("ema_spread_24_168"),
        # Forward returns
        ((pl.col("close").shift(-1).over("symbol") - pl.col("close")) / pl.col("close")).alias("fwd_ret_1h"),
        ((pl.col("close").shift(-72).over("symbol") - pl.col("close")) / pl.col("close")).alias("fwd_ret_72h"),
    ])

    features_path = FEATURES_DIR / "crypto_tsmom_features.parquet"
    panel.write_parquet(features_path)
    print(f"Saved feature matrix to {features_path} with shape {panel.shape}")


if __name__ == "__main__":
    build_features_and_labels()
