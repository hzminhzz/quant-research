"""Native ML4T feature and clock audit for the frozen Yen Squeeze session.

This module does not simulate strategy fills or calculate performance metrics.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl
from ml4t.engineer import compute_features


ROOT = Path(__file__).resolve().parents[1]
SESSION_ID = "mechanicalpremia-yen-squeeze-mvp-20261014"
DEV_DIR = ROOT / "data/processed/mechanicalpremia_yen_squeeze_mvp_20261014"
OUTPUT = ROOT / "docs/audit/mechanicalpremia_yen_squeeze_feature_parity_recheck_20261014.json"
DEV_END = datetime(2025, 1, 1, tzinfo=timezone.utc)
PAIRS = {
    "USDJPY": DEV_DIR / "USDJPY_2023_2024_1m.parquet",
    "GBPJPY": DEV_DIR / "GBPJPY_2023_2024_1m.parquet",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_complete_h1(minutes: pl.DataFrame, *, naive_is_utc: bool = False) -> tuple[pl.DataFrame, dict[str, Any]]:
    """Aggregate only complete UTC hours from minute bar-open observations.

    Missing minutes and market closures remain gaps. No values are forward filled.
    GBPJPY's existing naive source timestamps are localized to UTC only under an
    explicit assumption, which remains a data eligibility blocker.
    """
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = required.difference(minutes.columns)
    if missing:
        raise ValueError(f"missing input columns: {sorted(missing)}")
    dtype = minutes.schema["timestamp"]
    if not isinstance(dtype, pl.Datetime):
        raise TypeError(f"timestamp must be Datetime, got {dtype}")
    if dtype.time_zone is None:
        if not naive_is_utc:
            raise ValueError("naive timestamps require explicit UTC localization")
        minutes = minutes.with_columns(pl.col("timestamp").dt.replace_time_zone("UTC"))
    elif dtype.time_zone != "UTC":
        raise ValueError(f"expected UTC timestamps, got {dtype.time_zone}")

    minutes = minutes.select("timestamp", "open", "high", "low", "close", "volume").sort("timestamp")
    if minutes.height == 0:
        raise ValueError("minute input is empty")
    if minutes.filter(pl.col("timestamp") >= pl.lit(DEV_END)).height:
        raise ValueError("input crosses the protected 2025-01-01 boundary")

    quality = minutes.select(
        pl.len().alias("rows"),
        pl.col("timestamp").n_unique().alias("unique_timestamps"),
        pl.col("timestamp").min().alias("first_timestamp"),
        pl.col("timestamp").max().alias("last_timestamp"),
        (pl.col("timestamp").dt.truncate("1m") != pl.col("timestamp")).sum().alias("unaligned_minute_timestamps"),
        (pl.col("high") < pl.col("low")).sum().alias("high_below_low"),
        ((pl.col("close") < pl.col("low")) | (pl.col("close") > pl.col("high"))).sum().alias("close_outside_range"),
        pl.any_horizontal(pl.col("open", "high", "low", "close").is_finite().not_()).sum().alias("non_finite_ohlc_rows"),
    ).row(0, named=True)
    if quality["rows"] != quality["unique_timestamps"]:
        raise ValueError("duplicate minute timestamps prevent exact H1 aggregation")
    if quality["unaligned_minute_timestamps"]:
        raise ValueError("minute bar-open timestamps must align to exact minutes")
    if quality["high_below_low"] or quality["close_outside_range"] or quality["non_finite_ohlc_rows"]:
        raise ValueError(f"invalid OHLC input: {quality}")

    hourly = (
        minutes.group_by_dynamic("timestamp", every="1h", period="1h", closed="left", label="left")
        .agg(
            pl.len().alias("minute_count"),
            pl.col("timestamp").n_unique().alias("unique_minute_count"),
            pl.col("open").first(),
            pl.col("high").max(),
            pl.col("low").min(),
            pl.col("close").last(),
            pl.col("volume").sum(),
        )
        .sort("timestamp")
    )
    complete = hourly.filter(
        (pl.col("minute_count") == 60)
        & (pl.col("unique_minute_count") == 60)
        & (pl.col("timestamp").dt.minute() == 0)
        & (pl.col("timestamp").dt.second() == 0)
    ).drop("minute_count", "unique_minute_count")
    counts = {
        "candidate_hours": hourly.height,
        "complete_hours": complete.height,
        "excluded_incomplete_hours": hourly.height - complete.height,
    }
    return complete, {**quality, **counts}


def add_native_features(hourly: pl.DataFrame) -> pl.DataFrame:
    """Compute registered ML4T features and the documented upper median."""
    features = compute_features(
        hourly,
        [
            {"name": "atr", "params": {"period": 14}, "output": "atr14"},
            {"name": "donchian_channels", "params": {"period": 20}, "output": "donchian20"},
            {"name": "donchian_channels", "params": {"period": 500}, "output": "donchian500"},
        ],
        timestamp_col="timestamp",
    )
    # MQL ArraySort(...)[50] for 100 values is the upper middle observation.
    # Polars rolling_quantile(interpolation="higher") selects order statistic 50.
    return add_upper_median(features).with_columns(
        (pl.col("timestamp") + pl.duration(hours=1)).alias("available_at")
    )


def add_upper_median(frame: pl.DataFrame) -> pl.DataFrame:
    """Use the vectorized order statistic matching sorted[50] for 100 values."""
    return frame.with_columns(
        pl.when(pl.col("atr14").is_finite())
        .then(pl.col("atr14"))
        .otherwise(None)
        .rolling_quantile(quantile=0.5, interpolation="higher", window_size=100, min_samples=100)
        .alias("atr100_upper_median")
    )


def causal_minute_join(minutes: pl.DataFrame, hourly_features: pl.DataFrame, *, naive_is_utc: bool = False) -> pl.DataFrame:
    """Attach only the latest feature set available at each minute bar-open."""
    dtype = minutes.schema["timestamp"]
    if dtype.time_zone is None:
        if not naive_is_utc:
            raise ValueError("naive timestamps require explicit UTC localization")
        minutes = minutes.with_columns(pl.col("timestamp").dt.replace_time_zone("UTC"))
    minutes = minutes.sort("timestamp")
    right = hourly_features.sort("available_at")
    return minutes.join_asof(
        right,
        left_on="timestamp",
        right_on="available_at",
        strategy="backward",
    )


def run_audit() -> dict[str, Any]:
    pair_results: dict[str, Any] = {}
    for symbol, path in PAIRS.items():
        minutes = pl.read_parquet(path)
        naive = minutes.schema["timestamp"].time_zone is None
        hourly, data_quality = build_complete_h1(minutes, naive_is_utc=naive)
        features = add_native_features(hourly)
        if features.height != hourly.height:
            raise AssertionError("native feature computation changed row count")

        # A prior H1 feature becomes usable at its end timestamp. Record only
        # bounded counts and the final development timestamp; never read 2025+.
        joined = causal_minute_join(minutes, features, naive_is_utc=naive)
        available = joined.filter(pl.col("atr14").is_finite())
        violations = available.filter(pl.col("available_at") > pl.col("timestamp")).height
        if violations:
            raise AssertionError(f"{symbol}: {violations} feature availability violations")
        channel_rows = features.filter(
            pl.col("donchian20_0").is_finite()
            & pl.col("donchian500_0").is_finite()
        )
        differing = channel_rows.filter(
            (pl.col("donchian20_0") != pl.col("donchian500_0"))
            | (pl.col("donchian20_1") != pl.col("donchian500_1"))
        ).height
        pair_results[symbol] = {
            "input_path": str(path.relative_to(ROOT)),
            "input_sha256": _sha256(path),
            "processed_timestamps_are_utc_aware": not naive,
            "source_timezone_localization_assumption_unverified": symbol == "GBPJPY",
            "data_quality": data_quality,
            "native_features": ["atr(period=14)", "donchian_channels(period=20)", "donchian_channels(period=500)"],
            "feature_rows": features.height,
            "atr14_finite": features.filter(pl.col("atr14").is_finite()).height,
            "atr100_upper_median_finite": features.filter(pl.col("atr100_upper_median").is_finite()).height,
            "channel_20_vs_500_differing_rows": differing,
            "minute_rows_with_features": available.height,
            "causal_availability_violations": violations,
            "first_feature_available_at": str(available["available_at"].min()),
            "last_feature_available_at": str(available["available_at"].max()),
        }

    result = {
        "session_id": SESSION_ID,
        "trial_id": "FEATURE-PARITY",
        "status": "completed",
        "classification": "EXPLORATORY",
        "frozen_spec_sha256": "6a600d273b1e257d8dbad967a3f2ac4aeb5e3591166ded6bbb413ec77294a718",
        "holdout_accessed": False,
        "method": {
            "ml4t_engineer": "0.1.4",
            "compute_features_signature": "(data, features, *, group_col=None, timestamp_col=None, assume_sorted=False)",
            "atr_registration": "atr, period=14, ta_lib_compatible=true",
            "donchian_registration": "donchian_channels, period parameter; output upper/lower/mid",
            "upper_median": "Polars rolling_quantile(0.5, interpolation='higher', window_size=100); order statistic 50 of 100",
            "selected_skills": [
                {"name": "ml4t-compute-features", "path": ".agents/skills/ml4t-compute-features/SKILL.md", "invariant": "Use registered group-aware features; preserve causal ordering."},
                {"name": "ml4t-lookahead-bias", "path": ".agents/skills/ml4t-lookahead-bias/SKILL.md", "invariant": "Only use completed H1 features at or after H1 end."},
                {"name": "ml4t-polars-patterns", "path": ".agents/skills/ml4t-polars-patterns/SKILL.md", "invariant": "Sort timestamps; do not fill missing market intervals."},
                {"name": "ml4t-validate-data", "path": ".agents/skills/ml4t-validate-data/SKILL.md", "invariant": "Require unique UTC timestamps and valid finite OHLC."},
                {"name": "ml4t-feature-validation", "path": ".agents/skills/ml4t-feature-validation/SKILL.md", "invariant": "Check warmup, window separation, and future-append stability."},
            ],
        },
        "pairs": pair_results,
        "limitations": [
            "GBPJPY timestamps are naive in source and were localized to UTC as an unverified assumption.",
            "Feature parity demonstrates the registered implementation and causal availability, not venue bar parity.",
            "ATR median uses the specified upper order statistic, not an interpolated median.",
            "The data remains two-pair only; CADJPY is missing.",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, default=str)
        stream.write("\n")
    return result


if __name__ == "__main__":
    print(json.dumps(run_audit(), indent=2, default=str))
