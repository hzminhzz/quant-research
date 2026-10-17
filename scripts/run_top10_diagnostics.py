"""Factor diagnostics for 10-asset Time-Series Momentum features on development data."""

import json
from pathlib import Path
import numpy as np
import polars as pl
from scipy import stats

FEATURES_PATH = Path("data/features/crypto_tsmom_top10_features.parquet")
OUT_DIR = Path("run_log/diagnostics")
OUT_DIR.mkdir(parents=True, exist_ok=True)

DEV_START = pl.datetime(2021, 1, 1, 0, 0, 0, time_zone="UTC")
DEV_END = pl.datetime(2024, 12, 31, 23, 59, 59, time_zone="UTC")


def run_diagnostics():
    print("Loading 10-asset development panel...")
    df = (
        pl.scan_parquet(FEATURES_PATH)
        .filter((pl.col("timestamp") >= DEV_START) & (pl.col("timestamp") <= DEV_END))
        .collect()
        .drop_nulls(subset=["roc_168", "fwd_ret_72h", "fwd_ret_24h", "fwd_ret_4h", "fwd_ret_1h"])
    )

    print(f"Loaded {df.shape[0]} observations across {df['symbol'].n_unique()} symbols.")

    horizons = [("fwd_ret_1h", "1h"), ("fwd_ret_4h", "4h"), ("fwd_ret_24h", "24h"), ("fwd_ret_72h", "72h")]
    factors = [("roc_168", "168h Momentum"), ("cs_rank_roc_168", "Cross-Sectional Momentum Rank"), ("ema_spread_24_168", "EMA 24/168 Spread")]

    report = {}

    for factor_col, factor_name in factors:
        report[factor_col] = {"name": factor_name, "horizons": {}}
        print(f"\n=== Diagnostics for {factor_name} ({factor_col}) ===")

        for ret_col, label in horizons:
            # 1. Pooled Rank IC
            pooled_r, pooled_p = stats.spearmanr(df[factor_col].to_numpy(), df[ret_col].to_numpy())

            # 2. Per-timestamp Cross-Sectional Rank IC series
            ts_groups = df.group_by("timestamp")
            ic_list = []
            for ts, group in ts_groups:
                if len(group) >= 8:
                    r, _ = stats.spearmanr(group[factor_col].to_numpy(), group[ret_col].to_numpy())
                    if not np.isnan(r):
                        ic_list.append(r)

            cs_ic_mean = float(np.mean(ic_list)) if ic_list else 0.0
            cs_ic_std = float(np.std(ic_list)) if ic_list else 0.0
            cs_ic_ir = float(cs_ic_mean / cs_ic_std) if cs_ic_std > 0 else 0.0

            # 3. Top decile vs Bottom decile spread
            ranks = pl.Series(stats.rankdata(df[factor_col].to_numpy()))
            deciles = (ranks / len(ranks) * 5).ceil().clip(1, 5).cast(pl.Int32)
            temp = df.with_columns(deciles.alias("quintile"))
            q_ret = (
                temp.group_by("quintile")
                .agg(pl.col(ret_col).mean().alias("mean_ret"))
                .sort("quintile")
            )
            top_bottom_spread = float(q_ret.filter(pl.col("quintile") == 5)["mean_ret"][0] - q_ret.filter(pl.col("quintile") == 1)["mean_ret"][0])

            report[factor_col]["horizons"][label] = {
                "pooled_rank_ic": float(pooled_r),
                "pooled_p_value": float(pooled_p),
                "cross_sectional_ic_mean": cs_ic_mean,
                "cross_sectional_ic_ir": cs_ic_ir,
                "top_bottom_spread_bps": top_bottom_spread * 10000.0,
            }
            print(f"  [{label:>3}] Pooled IC: {pooled_r:+.4f} (p={pooled_p:.3e}) | Cross-Sectional Mean IC: {cs_ic_mean:+.4f} (IR: {cs_ic_ir:+.2f}) | Spread: {top_bottom_spread*10000:+.1f} bps")

    out_file = OUT_DIR / "crypto_tsmom_top10_diagnostics.json"
    with out_file.open("w") as f:
        json.dump(report, f, indent=2)
    print(f"\nSaved diagnostics to {out_file}")


if __name__ == "__main__":
    run_diagnostics()
