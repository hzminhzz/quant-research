"""Phase 3 Factor Diagnostics: Evaluating Rank IC with Two-Stage Funnel instrument selection."""

import json
from pathlib import Path
import numpy as np
import polars as pl
from scipy import stats

FEATURES_PATH = Path("data/features/crypto_tsmom_dynamic_top10_features.parquet")
OUT_DIR = Path("run_log/diagnostics")
OUT_DIR.mkdir(parents=True, exist_ok=True)

DEV_START = pl.datetime(2021, 1, 1, 0, 0, 0, time_zone="UTC")
DEV_END = pl.datetime(2024, 12, 31, 23, 59, 59, time_zone="UTC")

OOS_START = pl.datetime(2025, 1, 1, 0, 0, 0, time_zone="UTC")
OOS_END = pl.datetime(2026, 7, 31, 23, 59, 59, time_zone="UTC")


def prepare_data():
    print("Loading dynamic feature panel...")
    df = pl.read_parquet(FEATURES_PATH).sort(["symbol", "timestamp"])

    # Compute 200-hour EMA and 24-hour EMA
    df = df.with_columns([
        pl.col("close").ewm_mean(span=200).over("symbol").alias("ema_200"),
        pl.col("close").ewm_mean(span=24).over("symbol").alias("ema_24"),
        (pl.col("roc_168") / (pl.col("realized_vol_168") + 0.05)).alias("risk_adj_mom"),
        # Forward returns
        ((pl.col("close").shift(-1).over("symbol") - pl.col("close")) / pl.col("close")).alias("fwd_ret_1h"),
        ((pl.col("close").shift(-4).over("symbol") - pl.col("close")) / pl.col("close")).alias("fwd_ret_4h"),
        ((pl.col("close").shift(-24).over("symbol") - pl.col("close")) / pl.col("close")).alias("fwd_ret_24h"),
    ])

    # Gate 2: Structural Trend Health Filter
    df = df.with_columns([
        ((pl.col("close") > pl.col("ema_200")) & (pl.col("ema_24") > pl.col("ema_200"))).alias("pass_trend_gate")
    ])

    return df


def evaluate_ic_for_slice(df_slice, label):
    horizons = [("fwd_ret_1h", "1h"), ("fwd_ret_4h", "4h"), ("fwd_ret_24h", "24h"), ("fwd_ret_72h", "72h")]
    factors = [("roc_168", "Raw ROC 168h"), ("risk_adj_mom", "Risk-Adjusted Momentum")]

    print("\n" + "=" * 70)
    print(f"=== {label} ===")
    print("=" * 70)

    results = {}

    for f_col, f_name in factors:
        print(f"\n--- Factor: {f_name} ({f_col}) ---")
        results[f_col] = {}

        for ret_col, h_label in horizons:
            # 1. Unfiltered universe (All active tokens in pool)
            unfiltered = df_slice.filter(
                (pl.col("is_in_top10_universe") == 1.0) &
                pl.col(f_col).is_not_null() &
                pl.col(ret_col).is_not_null()
            )
            r_unfilt, p_unfilt = stats.spearmanr(unfiltered[f_col].to_numpy(), unfiltered[ret_col].to_numpy())

            # 2. Two-Stage Funnel (Liquid pool + PASS TREND GATE Close > EMA200)
            filtered = df_slice.filter(
                (pl.col("is_in_top10_universe") == 1.0) &
                (pl.col("pass_trend_gate") == True) &
                pl.col(f_col).is_not_null() &
                pl.col(ret_col).is_not_null()
            )
            r_filt, p_filt = stats.spearmanr(filtered[f_col].to_numpy(), filtered[ret_col].to_numpy())

            # Quintile spread for filtered
            q_ranks = pl.Series(stats.rankdata(filtered[f_col].to_numpy()))
            q_buckets = (q_ranks / len(q_ranks) * 5).ceil().clip(1, 5).cast(pl.Int32)
            temp = filtered.with_columns(q_buckets.alias("quintile"))
            q_means = temp.group_by("quintile").agg(pl.col(ret_col).mean().alias("mean_ret")).sort("quintile")
            spread_bps = float(q_means.filter(pl.col("quintile") == 5)["mean_ret"][0] - q_means.filter(pl.col("quintile") == 1)["mean_ret"][0]) * 10000.0

            # Cross-sectional timestamp IC for filtered
            ts_groups = filtered.group_by("timestamp")
            cs_ics = []
            for _, grp in ts_groups:
                if len(grp) >= 3:
                    r_ts, _ = stats.spearmanr(grp[f_col].to_numpy(), grp[ret_col].to_numpy())
                    if not np.isnan(r_ts):
                        cs_ics.append(r_ts)
            cs_mean = float(np.mean(cs_ics)) if cs_ics else 0.0
            cs_ir = float(cs_mean / np.std(cs_ics)) if len(cs_ics) > 1 and np.std(cs_ics) > 0 else 0.0

            results[f_col][h_label] = {
                "unfiltered_rank_ic": float(r_unfilt),
                "filtered_rank_ic": float(r_filt),
                "filtered_p_value": float(p_filt),
                "filtered_cs_ic_mean": cs_mean,
                "filtered_cs_ic_ir": cs_ir,
                "filtered_spread_bps": spread_bps,
                "observations_count": filtered.height,
            }

            diff_str = f"({(r_filt - r_unfilt):+.4f} vs Unfiltered)"
            print(f"  [{h_label:>3}] Unfiltered IC: {r_unfilt:+.4f}  -->  TREND-FILTERED IC: {r_filt:+.4f} {diff_str:20s} | Spread: {spread_bps:+6.1f} bps | CS Mean: {cs_mean:+.4f} (IR: {cs_ir:+.2f})")

    return results


def main():
    df = prepare_data()

    # 1. Development window (2021-2024)
    dev_slice = df.filter((pl.col("timestamp") >= DEV_START) & (pl.col("timestamp") <= DEV_END))
    dev_results = evaluate_ic_for_slice(dev_slice, "DEVELOPMENT WINDOW (2021-2024, 4 Full Years)")

    # 2. Out-of-sample holdout (2025-2026)
    oos_slice = df.filter((pl.col("timestamp") >= OOS_START) & (pl.col("timestamp") <= OOS_END))
    oos_results = evaluate_ic_for_slice(oos_slice, "OUT-OF-SAMPLE HOLDOUT (2025-2026, 19 Months)")

    # 3. Specifically 2026 bear market
    oos_2026_slice = df.filter((pl.col("timestamp") >= pl.datetime(2026, 1, 1, time_zone="UTC")) & (pl.col("timestamp") <= OOS_END))
    oos_2026_results = evaluate_ic_for_slice(oos_2026_slice, "2026 BEAR MARKET OUT-OF-SAMPLE (Jan-Jul 2026)")

    out_file = OUT_DIR / "two_stage_funnel_ic_diagnostics.json"
    with out_file.open("w") as f:
        json.dump({
            "development_2021_2024": dev_results,
            "out_of_sample_2025_2026": oos_results,
            "out_of_sample_2026": oos_2026_results,
        }, f, indent=2)
    print(f"\nSaved full diagnostics report to {out_file}")


if __name__ == "__main__":
    main()
