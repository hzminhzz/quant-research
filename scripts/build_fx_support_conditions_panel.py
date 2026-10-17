"""Prepare causal development-only features for four support-retest followups.

Outcome labels come from the immutable prior D0 event ledger. No holdout prices
or returns are opened. Technical indicators use ml4t.engineer public APIs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import polars as pl

from ml4t.engineer import compute_features
from scripts.run_fx_support_newhigh_d0 import _build_complete_30m, _read_development

ROOT = Path(__file__).resolve().parents[1]
SESSION = "fx_support_conditions_20261008"
SOURCE = ROOT / "run_log/fx_support_reclaim_newhigh_20261008/D0_support_hold_new_high/event_labels.parquet"
OUTPUT = ROOT / f"data/features/{SESSION}.parquet"
MANIFEST = ROOT / f"data/features/{SESSION}_manifest.json"
SYMBOLS = ("EURUSD", "GBPUSD", "AUDUSD")
FEATURE_NAMES = [
    "candle_strength", "roc3_atr", "roc12_atr", "roc24_atr",
    "ema50_slope16_atr", "ema_gap_atr", "atr_ratio",
    "support_gap_atr", "distance_high_atr", "reference_height_atr",
    "bars_elapsed_calendar", "utc_hour_sin", "utc_hour_cos",
]

def identity(path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": digest.hexdigest(),
        "size": path.stat().st_size,
    }

def build_symbol(symbol: str, events: pl.DataFrame) -> pl.DataFrame:
    bars = _build_complete_30m(_read_development(symbol))
    if bars["timestamp"].max().year > 2024:
        raise RuntimeError("Post-development timestamp")
    # Explicitly verified against installed ml4t.engineer.compute_features.
    indicator_input = bars.select(
        pl.col("timestamp"), pl.lit(symbol).alias("symbol"),
        "open", "high", "low", "close",
        pl.lit(1.0).alias("volume")
    )
    enriched = compute_features(
        indicator_input,
        [
            {"name": "ema", "params": {"period": 50}, "output": "ema50"},
            {"name": "atr", "params": {"period": 20}, "output": "atr20"},
            {"name": "atr", "params": {"period": 100}, "output": "atr100"},
        ],
        group_col="symbol",
        timestamp_col="timestamp"
    )
    features = (
        enriched
        .with_row_index("index_30m")
        .with_columns(
            pl.when(pl.col("high") > pl.col("low"))
            .then((pl.col("close") - pl.col("low")) / (pl.col("high") - pl.col("low")))
            .otherwise(None).alias("candle_strength"),
            ((pl.col("close") - pl.col("close").shift(3)) / pl.col("atr20"))
            .alias("roc3_atr"),
            ((pl.col("close") - pl.col("close").shift(12)) / pl.col("atr20"))
            .alias("roc12_atr"),
            ((pl.col("close") - pl.col("close").shift(24)) / pl.col("atr20"))
            .alias("roc24_atr"),
            ((pl.col("ema50") - pl.col("ema50").shift(16)) / pl.col("atr20"))
            .alias("ema50_slope16_atr"),
            ((pl.col("close") - pl.col("ema50")) / pl.col("atr20"))
            .alias("ema_gap_atr"),
            (pl.col("atr20") / pl.col("atr100")).alias("atr_ratio"),
            (pl.col("timestamp").dt.hour() + pl.col("timestamp").dt.minute() / 60.0)
            .alias("utc_hour"),
        )
        .with_columns(
            (pl.col("utc_hour") * (2 * np.pi / 24)).sin().alias("utc_hour_sin"),
            (pl.col("utc_hour") * (2 * np.pi / 24)).cos().alias("utc_hour_cos")
        )
        .rename({"timestamp": "event_timestamp"})
    )
    subset = events.filter((pl.col("symbol") == symbol) & pl.col("support_held"))
    joined = subset.join(features, on=["symbol", "event_timestamp"], how="inner", validate="1:1")
    if joined.height != subset.height:
        raise RuntimeError(f"Missing event feature matches for {symbol}: {joined.height} / {subset.height}")
    end_indices = joined["index_30m"].to_numpy() + 240
    if (end_indices >= bars.height).any():
        raise RuntimeError("Incomplete label horizon")
    final_times = bars["timestamp"].to_numpy()[end_indices]
    joined = joined.with_columns(
        pl.Series(name="label_horizon_end", values=final_times)
        .cast(pl.Datetime("us", "UTC")),
        ((pl.col("close_on_touch") - pl.col("origin_support")) / pl.col("atr20"))
        .alias("support_gap_atr"),
        ((pl.col("reference_high") - pl.col("close_on_touch")) / pl.col("atr20"))
        .alias("distance_high_atr"),
        ((pl.col("reference_high") - pl.col("origin_support")) / pl.col("atr20"))
        .alias("reference_height_atr"),
        ((pl.col("event_timestamp") - pl.col("reference_high_timestamp")).dt.total_minutes() / 30.0)
        .alias("bars_elapsed_calendar"),
    )
    return joined.select(
        "symbol", "event_timestamp", "reference_high_timestamp",
        "reference_high", "origin_support", "close_on_touch",
        "label_horizon_end", "month", "year",
        "within_240_bars", "target_before_support_invalidation_240",
        "candle_strength", "roc3_atr", "roc12_atr", "roc24_atr",
        "ema50_slope16_atr", "ema_gap_atr", "atr_ratio",
        "support_gap_atr", "distance_high_atr", "reference_height_atr",
        "bars_elapsed_calendar", "utc_hour_sin", "utc_hour_cos",
    )

def main() -> None:
    if OUTPUT.exists() or MANIFEST.exists():
        raise RuntimeError("Target artifacts exist; source and trial identities are immutable")
    if "holdout" in SOURCE.name.lower():
        raise RuntimeError("Refusing holdout source")
    all_events = pl.read_parquet(SOURCE)
    if all_events["event_timestamp"].max().year >= 2025:
        raise RuntimeError("Holdout exposed by parent ledger")
    joined = pl.concat([build_symbol(symbol, all_events) for symbol in SYMBOLS])
    joined = joined.sort(["event_timestamp", "symbol"])
    if joined.height != 1395:
        raise RuntimeError(f"Parent eligible support holds changed: {joined.height}")
    if joined.select(pl.all().is_null().sum()).row(0) != tuple(0 for _ in joined.columns):
        raise RuntimeError("Null in fixed feature panel")
    if joined.filter(pl.col("label_horizon_end") < pl.col("event_timestamp")).height:
        raise RuntimeError("Label end before event")
    if joined["event_timestamp"].max().year > 2024 or joined["label_horizon_end"].max().year > 2024:
        raise RuntimeError("Holdout contamination")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    joined.write_parquet(OUTPUT, compression="zstd")
    meta={
        "session": SESSION,
        "parent_session": "fx_support_reclaim_newhigh_20261008",
        "label": "target_before_support_invalidation_240",
        "features": FEATURE_NAMES,
        "source": identity(SOURCE),
        "data": identity(OUTPUT),
        "n_events": joined.height,
        "symbols": joined.group_by("symbol").len().sort("symbol").to_dicts(),
        "last_event_timestamp": str(joined["event_timestamp"].max()),
        "last_label_horizon_end": str(joined["label_horizon_end"].max()),
        "holdout_opened": False,
        "timestamp_semantics": "event_timestamp = open of retest 30m bar, signal decision only at event_timestamp+30m",
        "feature_availability": "only completed retest bar and earlier",
    }
    MANIFEST.write_text(json.dumps(meta, indent=2, sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(meta, indent=2, sort_keys=True))

if __name__=="__main__":
    main()
