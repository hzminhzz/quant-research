"""Default remote training script executed on Google Colab GPU.

Reads /content/train.arrow, computes baseline features, trains a fast LightGBM
return predictor, and writes a serialized feature callable to /content/model.pkl.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import cloudpickle
import polars as pl

try:
    import lightgbm as lgb
except ImportError:
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "lightgbm", "polars", "pyarrow"],
        check=True,
    )
    import lightgbm as lgb

INPUT_DATA = Path("/content/train.arrow")
OUTPUT_MODEL = Path("/content/model.pkl")


def build_and_train():
    if not INPUT_DATA.is_file():
        raise FileNotFoundError(f"Input training dataset missing: {INPUT_DATA}")

    df = pl.read_ipc(INPUT_DATA)
    df = (
        df.sort(["symbol", "timestamp"])
        .with_columns([
            ((pl.col("close") / pl.col("close").shift(24).over("symbol")) - 1.0).alias("mom_24"),
            ((pl.col("close") / pl.col("close").shift(48).over("symbol")) - 1.0).alias("mom_48"),
            ((pl.col("high") - pl.col("low")) / pl.col("close")).rolling_mean(24).over("symbol").alias("vol_24"),
            ((pl.col("close").shift(-48).over("symbol") / pl.col("close")) - 1.0).alias("target_fwd_48"),
        ])
        .drop_nulls()
    )

    feature_cols = ["mom_24", "mom_48", "vol_24"]
    X = df.select(feature_cols).to_numpy()
    y = df["target_fwd_48"].to_numpy()

    model = lgb.LGBMRegressor(
        n_estimators=100,
        learning_rate=0.05,
        max_depth=4,
        num_leaves=15,
        random_state=42,
        verbosity=-1,
    )
    model.fit(X, y)

    class PredictorCallable:
        def __init__(self, trained_model, features):
            self.model = trained_model
            self.features = features

        def __call__(self, panel: pl.DataFrame) -> pl.DataFrame:
            orig = panel.sort(["symbol", "timestamp"])
            computed = orig.with_columns([
                ((pl.col("close") / pl.col("close").shift(24).over("symbol")) - 1.0).fill_null(0.0).alias("mom_24"),
                ((pl.col("close") / pl.col("close").shift(48).over("symbol")) - 1.0).fill_null(0.0).alias("mom_48"),
                ((pl.col("high") - pl.col("low")) / pl.col("close")).rolling_mean(24).over("symbol").fill_null(0.0).alias("vol_24"),
            ])
            X_mat = computed.select(self.features).to_numpy()
            preds = self.model.predict(X_mat)
            return orig.with_columns(pl.Series("lgb_return_pred", preds))

    predictor = PredictorCallable(model, feature_cols)
    OUTPUT_MODEL.write_bytes(cloudpickle.dumps(predictor))
    print(f"Model saved to {OUTPUT_MODEL} ({OUTPUT_MODEL.stat().st_size} bytes)")


if __name__ == "__main__":
    build_and_train()
