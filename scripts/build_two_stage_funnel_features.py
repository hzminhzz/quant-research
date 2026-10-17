"""Engineer Two-Stage Funnel features for dynamic universe: Liquidity + Trend Gate + Risk-Adj Rank."""

from pathlib import Path
import numpy as np
import polars as pl
from ml4t.engineer import compute_features

DATA_DIR = Path("data/processed")
SCHEDULE_PATH = Path("run_log/dynamic_universe/monthly_top10_universe.json")
FEATURES_DIR = Path("data/features")
FEATURES_DIR.mkdir(parents=True, exist_ok=True)


def build_funnel_features():
    import json
    with SCHEDULE_PATH.open() as f:
        pit_schedule = json.load(f)

    all_members = set()
    for m, syms in pit_schedule.items():
        all_members.update(syms)

    print(f"Loading data and engineering Two-Stage Funnel features for {len(all_members)} symbols...")
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
            if raw.height < 250:
                continue
            feat = compute_features(raw, feature_specs)
            feat = feat.with_columns(pl.lit(sym).alias("symbol"))

            # Hourly returns
            feat = feat.with_columns([
                ((pl.col("close") - pl.col("close").shift(1)) / pl.col("close").shift(1)).alias("hourly_ret")
            ])
            # Realized volatility (7 days)
            feat = feat.with_columns([
                (pl.col("hourly_ret").rolling_std(168) * ann_factor).alias("realized_vol_168")
            ])
            # Structural trend indicators: EMA 200 and EMA 24
            feat = feat.with_columns([
                pl.col("close").ewm_mean(span=200).alias("ema_200"),
                pl.col("close").ewm_mean(span=24).alias("ema_24"),
            ])
            # Risk-adjusted momentum
            feat = feat.with_columns([
                (pl.col("roc_168") / (pl.col("realized_vol_168") + 0.05)).alias("risk_adj_mom")
            ])
            # Volatility-scaled weight (target 20% annual vol across 5 top leaders)
            target_vol = 0.20
            feat = feat.with_columns([
                pl.when(pl.col("realized_vol_168") > 0.05)
                .then((target_vol / pl.col("realized_vol_168") / 5.0).clip(0.04, 0.20))
                .otherwise(0.15)
                .alias("vol_scaled_weight")
            ])
            frames.append(feat)
        except Exception as e:
            print(f"  Error processing {sym}: {e}")

    panel = pl.concat(frames).sort(["symbol", "timestamp"])

    # Map Point-in-Time Top 10 liquidity membership
    panel = panel.with_columns([
        pl.col("timestamp").dt.strftime("%Y-%m").alias("month_key")
    ])

    lookup_rows = []
    for m_key, top10_list in pit_schedule.items():
        for s in top10_list:
            lookup_rows.append({"month_key": m_key, "symbol": s, "is_in_top10_universe": 1.0})

    lookup_df = pl.DataFrame(lookup_rows)
    panel = panel.join(lookup_df, on=["month_key", "symbol"], how="left").with_columns([
        pl.col("is_in_top10_universe").fill_null(0.0)
    ])

    print("Applying Gate 2 (Structural Trend Health) and Gate 3 (Risk-Adjusted Momentum Ranking)...")
    # Gate 2: Must be in Top 10 liquid pool AND Close > EMA200 AND EMA24 > EMA200 AND ROC168 > 0
    panel = panel.with_columns([
        (
            (pl.col("is_in_top10_universe") == 1.0)
            & (pl.col("close") > pl.col("ema_200"))
            & (pl.col("ema_24") > pl.col("ema_200"))
            & (pl.col("roc_168") > 0.015)
        ).fill_null(False).alias("pass_trend_gate")
    ])

    # Gate 3: Cross-sectional rank by risk-adjusted momentum among coins passing trend gate
    panel = panel.with_columns([
        pl.when(pl.col("pass_trend_gate"))
        .then(pl.col("risk_adj_mom").rank(descending=True).over("timestamp"))
        .otherwise(999.0)
        .alias("trend_rank")
    ])

    # Select Top 5 cleanest trending leaders
    panel = panel.with_columns([
        pl.when(pl.col("trend_rank") <= 5.0)
        .then(1.0)
        .otherwise(0.0)
        .alias("is_selected_leader")
    ])

    # Forward returns for validation
    panel = panel.with_columns([
        ((pl.col("close").shift(-1).over("symbol") - pl.col("close")) / pl.col("close")).alias("fwd_ret_1h"),
        ((pl.col("close").shift(-24).over("symbol") - pl.col("close")) / pl.col("close")).alias("fwd_ret_24h"),
        ((pl.col("close").shift(-72).over("symbol") - pl.col("close")) / pl.col("close")).alias("fwd_ret_72h"),
    ])

    out_file = FEATURES_DIR / "crypto_tsmom_two_stage_funnel_features.parquet"
    panel.write_parquet(out_file)
    print(f"Saved Two-Stage Funnel feature matrix to {out_file} with shape {panel.shape}")


if __name__ == "__main__":
    build_funnel_features()
