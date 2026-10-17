"""Run comprehensive factor diagnostics for Time-Series Momentum features."""

import json
from pathlib import Path
import polars as pl
from scipy import stats

FEATURES_PATH = Path("data/features/crypto_tsmom_features.parquet")
LABELS_PATH = Path("data/labels/crypto_tsmom_labels.parquet")
OUT_DIR = Path("run_log/diagnostics")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Development period only (Holdout remains strictly untouched)
DEV_START = pl.datetime(2021, 1, 1, 0, 0, 0, time_zone="UTC")
DEV_END = pl.datetime(2024, 12, 31, 23, 59, 59, time_zone="UTC")

FACTORS = [
    ("roc_24", "Rate of Change (24h / 1d)"),
    ("roc_72", "Rate of Change (72h / 3d)"),
    ("roc_168", "Rate of Change (168h / 7d)"),
    ("ema_spread_12_48", "Fast EMA 12 - Slow EMA 48 Spread"),
    ("ema_spread_24_168", "Fast EMA 24 - Slow EMA 168 Spread"),
    ("donchian_24_breakout", "Donchian 24h Breakout"),
    ("donchian_168_breakout", "Donchian 168h Breakout"),
]

HORIZONS = [
    ("fwd_ret_1h", "1h"),
    ("fwd_ret_4h", "4h"),
    ("fwd_ret_24h", "24h"),
    ("fwd_ret_72h", "72h"),
]


def run_diagnostics():
    print("Loading development features and labels...")
    feat_df = (
        pl.scan_parquet(FEATURES_PATH)
        .filter((pl.col("timestamp") >= DEV_START) & (pl.col("timestamp") <= DEV_END))
        .collect()
    )
    labels_df = (
        pl.scan_parquet(LABELS_PATH)
        .filter((pl.col("timestamp") >= DEV_START) & (pl.col("timestamp") <= DEV_END))
        .collect()
    )

    df = feat_df.join(
        labels_df.select(["timestamp", "symbol", "fwd_ret_1h", "fwd_ret_4h", "fwd_ret_24h", "fwd_ret_72h"]),
        on=["timestamp", "symbol"],
        how="inner",
    ).drop_nulls()

    results = {}

    for factor_col, factor_desc in FACTORS:
        print(f"\n=== Analyzing {factor_desc} ({factor_col}) ===")
        results[factor_col] = {
            "description": factor_desc,
            "horizons": {},
        }
        
        for ret_col, ret_label in HORIZONS:
            # Vectorized Spearman correlation per asset and pooled panel
            corr_by_symbol = {}
            for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
                sub = df.filter(pl.col("symbol") == sym)
                r, p = stats.spearmanr(sub[factor_col].to_numpy(), sub[ret_col].to_numpy())
                corr_by_symbol[sym] = {"rank_ic": float(r), "p_value": float(p)}

            # Pooled panel Spearman Rank IC
            pooled_r, pooled_p = stats.spearmanr(df[factor_col].to_numpy(), df[ret_col].to_numpy())
            
            # Quintile returns
            q_ranks = pl.Series(stats.rankdata(df[factor_col].to_numpy()))
            q_buckets = (q_ranks / len(q_ranks) * 3).ceil().clip(1, 3).cast(pl.Int32)
            temp = df.with_columns(q_buckets.alias("quantile"))
            q_means = (
                temp.group_by("quantile")
                .agg(pl.col(ret_col).mean().alias("mean_ret"))
                .sort("quantile")
            )
            spread = float(q_means.filter(pl.col("quantile") == 3)["mean_ret"][0] - q_means.filter(pl.col("quantile") == 1)["mean_ret"][0])

            results[factor_col]["horizons"][ret_label] = {
                "pooled_rank_ic": float(pooled_r),
                "pooled_p_value": float(pooled_p),
                "ic_by_symbol": corr_by_symbol,
                "top_bottom_spread": spread,
            }
            print(f"  [{ret_label:>3}] Pooled Rank IC: {pooled_r:+.4f} (p={pooled_p:.4e}) | Spread: {spread*10000:+.1f} bps")

    out_path = OUT_DIR / "crypto_tsmom_diagnostics.json"
    with out_path.open("w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved full diagnostics report to {out_path}")


if __name__ == "__main__":
    run_diagnostics()
