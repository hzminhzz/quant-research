"""G6 — independent feature/target implementation (Polars engine).

Written from the source contract only (`docs/audit/matthiola_source_contract.md`),
using a different dataframe engine from the upstream pandas implementation. If the
two agree to floating tolerance, the specification is unambiguous.

Independence caveat, stated plainly: this is a second *engine*, not a second
*author*. A subagent that had never seen this repository was dispatched for a fully
independent implementation and could not run (provider usage limit), so the
engine-level check is what this gate actually delivers. A third-party cross-check of
RSI and MACD via `ml4t.engineer` is included where the library exposes them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "upstream"))

FEATURES = [
    "mom_12_1", "reversal_1w", "size_adv_60",
    "ret_21d", "ret_63d", "ret_126d", "ret_252d",
    "vol_20d", "vol_60d",
    "rsi_14", "macd_hist", "volume_z_60",
]


def build(panel: pl.DataFrame) -> pl.DataFrame:
    df = panel.sort(["symbol", "timestamp"]).with_columns([
        (pl.col("close").shift(21).over("symbol") / pl.col("close").shift(273).over("symbol") - 1.0).alias("mom_12_1"),
        (-(pl.col("close") / pl.col("close").shift(5).over("symbol") - 1.0)).alias("reversal_1w"),
        (-((pl.col("close") * pl.col("volume")).rolling_mean(60).over("symbol"))).alias("size_adv_60"),
        (pl.col("close") / pl.col("close").shift(21).over("symbol") - 1.0).alias("ret_21d"),
        (pl.col("close") / pl.col("close").shift(63).over("symbol") - 1.0).alias("ret_63d"),
        (pl.col("close") / pl.col("close").shift(126).over("symbol") - 1.0).alias("ret_126d"),
        (pl.col("close") / pl.col("close").shift(252).over("symbol") - 1.0).alias("ret_252d"),
    ]).with_columns([
        (pl.col("close") / pl.col("close").shift(1).over("symbol")).log().alias("__logret"),
    ]).with_columns([
        pl.col("__logret").rolling_std(20).over("symbol").alias("vol_20d"),
        pl.col("__logret").rolling_std(60).over("symbol").alias("vol_60d"),
        (pl.col("close").diff().over("symbol").clip(lower_bound=0.0)
         .ewm_mean(alpha=1.0 / 14, adjust=False, min_periods=14).over("symbol")).alias("__avg_gain"),
        ((-pl.col("close").diff().over("symbol")).clip(lower_bound=0.0)
         .ewm_mean(alpha=1.0 / 14, adjust=False, min_periods=14).over("symbol")).alias("__avg_loss"),
        (pl.col("close").ewm_mean(span=12, adjust=False).over("symbol")
         - pl.col("close").ewm_mean(span=26, adjust=False).over("symbol")).alias("__macd_line"),
    ]).with_columns([
        (100.0 - 100.0 / (1.0 + (
            pl.col("__avg_gain") / pl.when(pl.col("__avg_loss") == 0).then(None).otherwise(pl.col("__avg_loss"))
        ))).alias("rsi_14"),
        (pl.col("__macd_line")
         - pl.col("__macd_line").ewm_mean(span=9, adjust=False).over("symbol")).alias("macd_hist"),
        (pl.col("volume").log1p()
         - pl.col("volume").log1p().rolling_mean(60).over("symbol")).alias("__vz_num"),
        pl.col("volume").log1p().rolling_std(60).over("symbol").alias("__vz_den"),
    ]).with_columns([
        (pl.col("__vz_num") / pl.when(pl.col("__vz_den") == 0).then(None).otherwise(pl.col("__vz_den"))
         ).alias("volume_z_60"),
        (pl.col("close").shift(-21).over("symbol") / pl.col("close") - 1.0).alias("fwd_ret_21d"),
    ]).with_columns([
        pl.col("fwd_ret_21d").rank(method="average").over("timestamp").alias("__r"),
        pl.len().over("timestamp").alias("__n"),
    ]).with_columns([
        (pl.col("__r") / pl.col("__n")).alias("fwd_rank_21d"),
    ])

    return df.select(["timestamp", "symbol", *FEATURES, "fwd_ret_21d", "fwd_rank_21d"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "oracle_output"))
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    raw = pl.read_parquet(HERE / "repro_output" / "btc_uni_prices.parquet")
    panel = raw.rename({"date": "timestamp"}).with_columns(
        pl.col("timestamp").cast(pl.Datetime("us"))
    )
    built = build(panel)
    built.write_parquet(out / "oracle_features.parquet")
    sha = hashlib.file_digest((out / "oracle_features.parquet").open("rb"), "sha256").hexdigest()
    manifest = {
        "engine": "polars",
        "rows": built.height,
        "symbols": built["symbol"].n_unique(),
        "date_min": str(built["timestamp"].min()),
        "date_max": str(built["timestamp"].max()),
        "feature_order": FEATURES,
        "panel_sha256": sha,
    }
    (out / "oracle_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))

    # ---- agreement against the upstream pandas implementation -------------
    import pandas as pd
    from mlcs.features import add_forward_target, build_feature_panel

    prices = raw.to_pandas()
    prices["date"] = pd.to_datetime(prices["date"])
    close = prices.pivot(index="date", columns="symbol", values="close").sort_index()
    volume = prices.pivot(index="date", columns="symbol", values="volume").sort_index()
    ref = add_forward_target(build_feature_panel(close, volume), close, horizon=21)
    ref["date"] = pd.to_datetime(ref["date"])
    ref = ref.rename(columns={"date": "timestamp"})

    mine = built.to_pandas()
    mine["timestamp"] = pd.to_datetime(mine["timestamp"])
    ref["timestamp"] = pd.to_datetime(ref["timestamp"])

    merged = ref.merge(mine, on=["timestamp", "symbol"], how="outer", suffixes=("_ref", "_oracle"), indicator=True)
    agree = {"rows_ref": len(ref), "rows_oracle": len(mine), "rows_merged": len(merged)}
    per_col = {}
    for c in FEATURES + ["fwd_ret_21d", "fwd_rank_21d"]:
        a = merged[f"{c}_ref"].to_numpy(dtype="float64")
        b = merged[f"{c}_oracle"].to_numpy(dtype="float64")
        both_nan = np.isnan(a) & np.isnan(b)
        one_nan = np.isnan(a) ^ np.isnan(b)
        diff = np.where(both_nan, 0.0, np.abs(a - b))
        per_col[c] = {
            "max_abs_diff": float(np.nanmax(diff)) if len(diff) else float("nan"),
            "n_gt_1e9": int((diff > 1e-9).sum()),
            "n_gt_1e6": int((diff > 1e-6).sum()),
            "nan_mismatch": int(one_nan.sum()),
        }
    agree["per_column"] = per_col
    agree["all_agree_1e9"] = all(v["n_gt_1e9"] == 0 and v["nan_mismatch"] == 0 for v in per_col.values())
    (out / "oracle_agreement.json").write_text(json.dumps(agree, indent=2), encoding="utf-8")
    print(json.dumps(agree, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
