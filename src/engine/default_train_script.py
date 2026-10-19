"""Default remote training script executed on Google Colab GPU.

Reads /content/train.arrow and /content/train_meta.json, trains a deterministic
LightGBM forward-return predictor on the train-only rows, and writes a
serialized feature callable to /content/model.pkl.

The callable returns row identity plus exactly the declared signal name. The
trusted feature compiler, not this model, owns canonical columns, the PIT mask,
the baseline and the ATR feature.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    import cloudpickle
    import lightgbm as lgb
    import polars as pl
except ImportError:
    # Fresh Colab kernels may lack Polars and LightGBM, not only LightGBM.
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "cloudpickle", "lightgbm", "polars"],
        check=True,
    )
    import cloudpickle
    import lightgbm as lgb
    import polars as pl

INPUT_DATA = Path("/content/train.arrow")
OUTPUT_MODEL = Path("/content/model.pkl")
META_DATA = Path("/content/train_meta.json")

REQUIRED_COLUMNS = {"timestamp", "symbol", "open", "high", "low", "close", "volume"}
FEATURE_COLUMNS = ["mom_24", "mom_48", "vol_24"]


def _training_contract(meta_data: str | Path | None) -> dict:
    payload = {}
    if meta_data is not None and Path(meta_data).is_file():
        payload = json.loads(Path(meta_data).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("train_meta.json must contain a JSON object")
    signal = payload.get("signal", "lgb_signal")
    if not isinstance(signal, str) or not signal or not signal.replace("_", "").replace(".", "").replace("-", "").isalnum():
        raise ValueError(f"Invalid signal name in train meta: {signal!r}")
    horizon = payload.get("label_horizon_bars", 48)
    bar_seconds = payload.get("bar_seconds", 3600)
    seed = payload.get("seed", 42)
    if not isinstance(horizon, int) or horizon < 1:
        raise ValueError("label_horizon_bars must be a positive integer")
    if not isinstance(bar_seconds, int) or bar_seconds < 60:
        raise ValueError("bar_seconds must be a positive integer")
    if not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    train_end = payload.get("train_end")
    if train_end is not None:
        train_end = datetime.fromisoformat(str(train_end))
        if train_end.tzinfo is None:
            raise ValueError("train_end must include a UTC offset")
    return {"signal": signal, "horizon": horizon, "bar_seconds": bar_seconds,
            "seed": seed, "train_end": train_end}


def build_and_train(input_data: str | Path | None = None,
                    output_model: str | Path | None = None,
                    meta_data: str | Path | None = None) -> Path:
    source = Path(input_data) if input_data is not None else INPUT_DATA
    destination = Path(output_model) if output_model is not None else OUTPUT_MODEL
    contract = _training_contract(meta_data if meta_data is not None else META_DATA)
    if not source.is_file():
        raise FileNotFoundError(f"Input training dataset missing: {source}")

    df = pl.read_ipc(source)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Training panel is missing required columns: {sorted(missing)}")
    if df.is_empty():
        raise ValueError("Training panel is empty")

    horizon = contract["horizon"]
    train_end = contract["train_end"]
    if train_end is not None and df.filter(pl.col("timestamp") >= train_end).height:
        raise ValueError("Training panel contains rows at or beyond train_end")

    df = (
        df.sort(["symbol", "timestamp"])
        .with_columns([
            ((pl.col("close") / pl.col("close").shift(24).over("symbol")) - 1.0).alias("mom_24"),
            ((pl.col("close") / pl.col("close").shift(48).over("symbol")) - 1.0).alias("mom_48"),
            ((pl.col("high") - pl.col("low")) / pl.col("close"))
            .rolling_mean(24).over("symbol").alias("vol_24"),
            # Match native Stage 2: signal on bar t, entry at open[t+1],
            # exit at open[t+horizon+1]. Never fit on censored train-end labels.
            (pl.col("open").shift(-(horizon + 1)).over("symbol")
             / pl.col("open").shift(-1).over("symbol") - 1.0).alias("target_fwd"),
            pl.col("timestamp").shift(-(horizon + 1)).over("symbol").alias("__label_end"),
        ])
        .drop_nulls(subset=[*FEATURE_COLUMNS, "target_fwd"])
    )
    # Native Stage 2 rejects gaps across label horizons; train on the same
    # contiguous-bar definition rather than learning from a sparse time jump.
    df = df.filter((pl.col("__label_end") - pl.col("timestamp")) ==
                   timedelta(seconds=(horizon + 1) * contract["bar_seconds"]))
    if train_end is not None:
        df = df.filter(pl.col("__label_end") < pl.lit(train_end, dtype=pl.Datetime("us", "UTC")))
    if df.height < 50:
        raise ValueError(f"Insufficient fully labelled training rows: {df.height}")

    X = df.select(FEATURE_COLUMNS).to_numpy()
    y = df["target_fwd"].to_numpy()
    model = lgb.LGBMRegressor(
        n_estimators=100,
        learning_rate=0.05,
        max_depth=4,
        num_leaves=15,
        random_state=contract["seed"],
        deterministic=True,
        force_col_wise=True,
        n_jobs=1,
        verbosity=-1,
    )
    model.fit(X, y)

    # A closure avoids the per-training random UUID cloudpickle assigns to a
    # nested callable *class*. Identical model trees can now yield identical
    # serialized artifact bytes (and therefore stable content addresses).
    features = tuple(FEATURE_COLUMNS)
    output_name = contract["signal"]

    def predictor(panel: pl.DataFrame) -> pl.DataFrame:
        required = {"timestamp", "symbol", "close", "high", "low"}
        missing_columns = required - set(panel.columns)
        if missing_columns:
            raise ValueError(f"Panel is missing predictor inputs: {sorted(missing_columns)}")
        ordered = panel.sort(["symbol", "timestamp"])
        computed = ordered.with_columns([
            ((pl.col("close") / pl.col("close").shift(24).over("symbol")) - 1.0)
            .fill_null(0.0).alias("mom_24"),
            ((pl.col("close") / pl.col("close").shift(48).over("symbol")) - 1.0)
            .fill_null(0.0).alias("mom_48"),
            ((pl.col("high") - pl.col("low")) / pl.col("close"))
            .rolling_mean(24).over("symbol").fill_null(0.0).alias("vol_24"),
        ])
        predictions = model.predict(computed.select(features).to_numpy())
        return ordered.select("timestamp", "symbol").with_columns(
            pl.Series(output_name, predictions))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(cloudpickle.dumps(predictor))
    print(f"Model saved to {destination} ({destination.stat().st_size} bytes)")
    return destination


if __name__ == "__main__":
    build_and_train()
