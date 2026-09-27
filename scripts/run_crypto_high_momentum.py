#!/usr/bin/env python3
"""Pre-registered cross-sectional crypto factor research runner."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats

WINDOWS = (168, 336, 672)
MIN_HISTORY_HOURS = 1344
LIQUID_FRACTION = 0.70
MIN_CROSS_SECTION = 8
BASE_COST_BPS = 3.0
DEV_START = datetime(2021, 1, 1, tzinfo=timezone.utc)
DEV_END = datetime(2024, 1, 1, tzinfo=timezone.utc)
OOS_START = datetime(2024, 1, 1, tzinfo=timezone.utc)
OOS_END = datetime(2026, 1, 1, tzinfo=timezone.utc)


def validate_panel(df: pl.DataFrame) -> dict:
    required = {"timestamp", "symbol", "open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    if df.null_count().sum_horizontal().item() != 0:
        raise ValueError("null values present")
    bad = df.filter(
        (pl.col("high") < pl.max_horizontal("open", "close", "low"))
        | (pl.col("low") > pl.min_horizontal("open", "close", "high"))
        | (pl.col("volume") < 0)
    ).height
    dup = df.group_by("symbol", "timestamp").len().filter(pl.col("len") > 1).height
    if bad or dup:
        raise ValueError(f"integrity failure: bad_ohlc={bad}, duplicate_pairs={dup}")
    ordered = df.sort(["symbol", "timestamp"])
    gaps = ordered.with_columns(
        pl.col("timestamp").diff().over("symbol").alias("_gap")
    ).filter(pl.col("_gap").is_not_null() & (pl.col("_gap") != pl.duration(hours=1))).height
    return {
        "rows": df.height,
        "symbols": df["symbol"].n_unique(),
        "start": df["timestamp"].min().isoformat(),
        "end": df["timestamp"].max().isoformat(),
        "duplicate_pairs": dup,
        "ohlc_failures": bad,
        "non_hourly_symbol_gaps": gaps,
    }


def make_weekly_factor_frame(df: pl.DataFrame, window: int) -> pl.DataFrame:
    ordered = df.sort(["symbol", "timestamp"]).with_columns(
        (pl.col("close") * pl.col("volume")).alias("_dollar_volume")
    )
    feat = ordered.with_columns(
        pl.col("close").shift(1).over("symbol").alias("prior_close"),
        pl.col("close").shift(1).rolling_max(window_size=window).over("symbol").alias("trailing_high"),
        pl.col("_dollar_volume").shift(1).rolling_mean(window_size=168).over("symbol").alias("trailing_dollar_volume"),
        pl.col("timestamp").shift(MIN_HISTORY_HOURS).over("symbol").alias("history_anchor"),
        pl.col("timestamp").shift(-168).over("symbol").alias("next_week_ts"),
        pl.col("open").shift(-168).over("symbol").alias("next_week_open"),
    ).with_columns(
        (pl.col("prior_close") / pl.col("trailing_high") - 1.0).alias("signal"),
        (pl.col("next_week_open") / pl.col("open") - 1.0).alias("forward_week_return"),
    )
    weekly = feat.filter(
        (pl.col("timestamp").dt.weekday() == 1)
        & (pl.col("timestamp").dt.hour() == 0)
        & pl.col("signal").is_finite()
        & pl.col("trailing_dollar_volume").is_finite()
        & (pl.col("history_anchor") == pl.col("timestamp") - pl.duration(hours=MIN_HISTORY_HOURS))
        & (pl.col("next_week_ts") == pl.col("timestamp") + pl.duration(hours=168))
    )
    weekly = weekly.with_columns(
        pl.col("trailing_dollar_volume").rank(method="ordinal", descending=True).over("timestamp").alias("_liq_rank"),
        pl.len().over("timestamp").alias("_n_preliq"),
    ).filter(
        pl.col("_liq_rank") <= (pl.col("_n_preliq").cast(pl.Float64) * LIQUID_FRACTION).ceil()
    )
    return weekly.filter(pl.len().over("timestamp") >= MIN_CROSS_SECTION).sort(["timestamp", "symbol"])


def hac_mean_test(x: np.ndarray, max_lag: int = 4) -> tuple[float, float]:
    if len(x) < 8:
        return 0.0, 1.0
    centered = x - np.mean(x)
    n = len(x)
    lrv = float(np.dot(centered, centered) / n)
    for lag in range(1, min(max_lag, n - 1) + 1):
        gamma = float(np.dot(centered[lag:], centered[:-lag]) / n)
        lrv += 2.0 * (1.0 - lag / (max_lag + 1.0)) * gamma
    if lrv <= 0:
        return 0.0, 1.0
    t_stat = float(np.mean(x) / math.sqrt(lrv / n))
    return t_stat, float(2.0 * stats.norm.sf(abs(t_stat)))


def diagnostic(frame: pl.DataFrame, window: int) -> dict:
    dev = frame.filter((pl.col("timestamp") >= DEV_START) & (pl.col("timestamp") < DEV_END))
    ics: list[float] = []
    spreads: list[float] = []
    counts: list[int] = []
    buckets: dict[int, list[float]] = {q: [] for q in range(1, 6)}
    for part in dev.partition_by("timestamp", maintain_order=True):
        n = part.height
        if n < MIN_CROSS_SECTION:
            continue
        signal = part["signal"].to_numpy()
        fwd = part["forward_week_return"].to_numpy()
        ic = stats.spearmanr(signal, fwd).statistic
        if np.isfinite(ic):
            ics.append(float(ic))
            counts.append(n)
        rows = sorted(zip(signal.tolist(), fwd.tolist()), key=lambda z: z[0])
        k = max(1, math.ceil(n * 0.20))
        spreads.append(float(np.mean([r for _, r in rows[-k:]]) - np.mean([r for _, r in rows[:k]])))
        for i, (_, ret) in enumerate(rows):
            q = min(5, int(i * 5 / n) + 1)
            buckets[q].append(float(ret))
    arr = np.asarray(ics, dtype=float)
    hac_t, hac_p = hac_mean_test(arr)
    quantiles = [float(np.mean(buckets[q])) if buckets[q] else math.nan for q in range(1, 6)]
    return {
        "window_hours": window,
        "n_weeks": len(ics),
        "mean_ic": float(np.mean(arr)) if len(arr) else math.nan,
        "ic_ir": float(np.mean(arr) / np.std(arr, ddof=1)) if len(arr) > 1 and np.std(arr, ddof=1) > 0 else 0.0,
        "hac_t": hac_t,
        "hac_p": hac_p,
        "top_minus_bottom": float(np.mean(spreads)) if spreads else math.nan,
        "quantile_returns": quantiles,
        "mean_assets": float(np.mean(counts)) if counts else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    args = parser.parse_args()
    df = pl.read_parquet(args.data).sort(["symbol", "timestamp"])
    integrity = validate_panel(df)
    frames = {w: make_weekly_factor_frame(df, w) for w in WINDOWS}
    diagnostics = {w: diagnostic(frames[w], w) for w in WINDOWS}
    canonical = diagnostics[168]
    gate = (
        canonical["n_weeks"] >= 100
        and canonical["mean_ic"] >= 0.02
        and canonical["hac_p"] < 0.05
        and canonical["top_minus_bottom"] > 0
    )
    payload = {
        "schema_version": 1,
        "run_id": "20260928-liquid-high-momentum-1w",
        "data_integrity": integrity,
        "diagnostics": {str(w): diagnostics[w] for w in WINDOWS},
        "development_gate_passed": gate,
        "oos_consumed": False,
        "trial_accounting": {
            "previous_crypto_parameter_trials": 3,
            "new_parameter_trials": 3,
            "cumulative_parameter_trials": 6,
        },
    }
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
