"""Build feature panel with Point-in-Time Top 10 universe membership flag."""

import json
from pathlib import Path
import numpy as np
import polars as pl
from ml4t.engineer import compute_features

DATA_DIR = Path("data/processed")
SCHEDULE_PATH = Path("run_log/dynamic_universe/monthly_top10_universe.json")
FEATURES_DIR = Path("data/features")
FEATURES_DIR.mkdir(parents=True, exist_ok=True)


def build_dynamic_features():
    with SCHEDULE_PATH.open() as f:
        pit_schedule = json.load(f)

    all_members = set()
    for m, syms in pit_schedule.items():
        all_members.update(syms)

    print(f"Loading data and computing features for {len(all_members)} dynamic universe symbols...")
    feature_specs = [
        {"name": "roc", "output": "roc_168", "params": {"period": 168}},
    ]

    frames = []
    ann_factor = float(np.sqrt(8760))

    for sym in sorted(all_members):
        p_file = DATA_DIR / f"{sym.lower()}_1h.parquet"
        if not p_file.exists():
            continue
        try:
            raw = pl.read_parquet(p_file).sort("timestamp")
            if raw.height < 200:
                continue
            feat = compute_features(raw, feature_specs)
            feat = feat.with_columns(pl.lit(sym).alias("symbol"))

            # Hourly returns & realized vol
            feat = feat.with_columns([
                ((pl.col("close") - pl.col("close").shift(1)) / pl.col("close").shift(1)).alias("hourly_ret")
            ])
            feat = feat.with_columns([
                (pl.col("hourly_ret").rolling_std(168) * ann_factor).alias("realized_vol_168")
            ])
            # Volatility-scaled risk-parity weight (target 20% annual vol across 10 assets)
            target_vol = 0.20
            feat = feat.with_columns([
                pl.when(pl.col("realized_vol_168") > 0.05)
                .then((target_vol / pl.col("realized_vol_168") / 10.0).clip(0.02, 0.20))
                .otherwise(0.10)
                .alias("vol_scaled_weight")
            ])
            frames.append(feat)
        except Exception as e:
            print(f"  Error processing {sym}: {e}")

    panel = pl.concat(frames).sort(["symbol", "timestamp"])
    print(f"Combined panel shape: {panel.shape} across {panel['symbol'].n_unique()} symbols.")

    print("Mapping point-in-time monthly Top 10 membership flag...")
    # Add month string "YYYY-MM"
    panel = panel.with_columns([
        pl.col("timestamp").dt.strftime("%Y-%m").alias("month_key")
    ])

    # Build lookup dataframe for (symbol, month_key) -> is_in_top10
    lookup_rows = []
    for m_key, top10_list in pit_schedule.items():
        for s in top10_list:
            lookup_rows.append({"month_key": m_key, "symbol": s, "is_in_top10_universe": 1.0})

    lookup_df = pl.DataFrame(lookup_rows)
    panel = panel.join(lookup_df, on=["month_key", "symbol"], how="left").with_columns([
        pl.col("is_in_top10_universe").fill_null(0.0)
    ])

    # Forward returns
    panel = panel.with_columns([
        ((pl.col("close").shift(-72).over("symbol") - pl.col("close")) / pl.col("close")).alias("fwd_ret_72h")
    ])

    out_path = FEATURES_DIR / "crypto_tsmom_dynamic_top10_features.parquet"
    panel.write_parquet(out_path)
    print(f"Saved dynamic feature panel to {out_path} with shape {panel.shape}")


if __name__ == "__main__":
    build_dynamic_features()
