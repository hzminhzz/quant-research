#!/usr/bin/env python3
"""Pre-registered liquidity-conditioned short-term crypto reversal research."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats

from scripts.run_crypto_high_momentum import hac_mean_test, simulate, validate_panel
from src.experiment import compute_deflated_sharpe

LOOKBACKS = (12, 24, 48)
CANONICAL = 24
MIN_HISTORY_HOURS = 720
ILLIQUID_FRACTION = 0.60
MIN_CROSS_SECTION = 8
BASE_COST_BPS = 3.0
DEV_START = datetime(2021, 1, 1, tzinfo=timezone.utc)
DEV_END = datetime(2024, 1, 1, tzinfo=timezone.utc)
OOS_START = datetime(2024, 1, 1, tzinfo=timezone.utc)
OOS_END = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_factor_frame(df: pl.DataFrame, lookback_hours: int) -> pl.DataFrame:
    ordered = df.sort(["symbol", "timestamp"]).with_columns(
        (pl.col("close") * pl.col("volume")).alias("_dollar_volume")
    )
    feat = ordered.with_columns(
        pl.col("close").shift(1).over("symbol").alias("_prior_close"),
        pl.col("close").shift(lookback_hours + 1).over("symbol").alias("_past_close"),
        pl.col("_dollar_volume")
        .shift(1)
        .rolling_mean(window_size=MIN_HISTORY_HOURS)
        .over("symbol")
        .alias("_trailing_dollar_volume"),
        pl.col("timestamp")
        .shift(MIN_HISTORY_HOURS)
        .over("symbol")
        .alias("_history_anchor"),
        pl.col("timestamp").shift(-24).over("symbol").alias("_next_day_ts"),
        pl.col("open").shift(-24).over("symbol").alias("_next_day_open"),
    ).with_columns(
        (-(pl.col("_prior_close") / pl.col("_past_close") - 1.0)).alias("signal"),
        (pl.col("_next_day_open") / pl.col("open") - 1.0).alias("forward_return"),
    )

    daily = feat.filter(
        (pl.col("timestamp").dt.hour() == 0)
        & pl.col("signal").is_finite()
        & pl.col("_trailing_dollar_volume").is_finite()
        & (pl.col("_history_anchor") == pl.col("timestamp") - pl.duration(hours=MIN_HISTORY_HOURS))
        & (pl.col("_next_day_ts") == pl.col("timestamp") + pl.duration(hours=24))
    )

    daily = daily.with_columns(
        pl.col("_trailing_dollar_volume")
        .rank(method="ordinal")
        .over("timestamp")
        .alias("_liq_rank"),
        pl.len().over("timestamp").alias("_n_preliq"),
    ).filter(
        pl.col("_liq_rank")
        <= (pl.col("_n_preliq").cast(pl.Float64) * ILLIQUID_FRACTION).ceil()
    )

    return daily.filter(
        pl.len().over("timestamp") >= MIN_CROSS_SECTION
    ).sort(["timestamp", "symbol"])


def diagnostic(frame: pl.DataFrame) -> dict:
    dev = frame.filter(
        (pl.col("timestamp") >= DEV_START) & (pl.col("timestamp") < DEV_END)
    )
    ics: list[float] = []
    spreads: list[float] = []
    counts: list[int] = []
    for part in dev.partition_by("timestamp", maintain_order=True):
        if part.height < MIN_CROSS_SECTION:
            continue
        signal = part["signal"].to_numpy()
        fwd = part["forward_return"].to_numpy()
        ic = stats.spearmanr(signal, fwd).statistic
        if np.isfinite(ic):
            ics.append(float(ic))
            counts.append(part.height)
        rows = sorted(zip(signal.tolist(), fwd.tolist()), key=lambda z: z[0])
        k = max(1, math.ceil(len(rows) / 3))
        long_ret = float(np.mean([r for _, r in rows[-k:]]))
        short_ret = float(np.mean([r for _, r in rows[:k]]))
        spreads.append(long_ret - short_ret)

    arr = np.asarray(ics, dtype=float)
    hac_t, hac_p = hac_mean_test(arr, max_lag=7)
    return {
        "n_days": len(ics),
        "mean_ic": float(np.mean(arr)) if len(arr) else math.nan,
        "ic_ir": float(np.mean(arr) / np.std(arr, ddof=1))
        if len(arr) > 1 and np.std(arr, ddof=1) > 0
        else 0.0,
        "hac_t": hac_t,
        "hac_p": hac_p,
        "long_minus_short": float(np.mean(spreads)) if spreads else math.nan,
        "mean_assets": float(np.mean(counts)) if counts else 0.0,
    }


def build_targets(
    frame: pl.DataFrame,
    start: datetime,
    end: datetime,
    exclude: set[str] | None = None,
    delay_hours: int = 0,
) -> dict[datetime, dict[str, float]]:
    excluded = exclude or set()
    selected = frame.filter(
        (pl.col("timestamp") >= start)
        & (pl.col("timestamp") < end)
        & (~pl.col("symbol").is_in(sorted(excluded)))
    )
    targets: dict[datetime, dict[str, float]] = {}
    for part in selected.partition_by("timestamp", maintain_order=True):
        rows = sorted(
            [(r["symbol"], float(r["signal"])) for r in part.iter_rows(named=True)],
            key=lambda z: z[1],
        )
        if len(rows) < MIN_CROSS_SECTION:
            continue
        k = max(1, math.ceil(len(rows) / 3))
        weights: dict[str, float] = {}
        for sym, _ in rows[-k:]:
            weights[sym] = 0.5 / k
        for sym, _ in rows[:k]:
            weights[sym] = -0.5 / k
        targets[part["timestamp"][0] + timedelta(hours=delay_hours)] = weights
    return targets


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    args = parser.parse_args()

    prices = pl.read_parquet(args.data).sort(["symbol", "timestamp"])
    integrity = validate_panel(prices)

    dev_source = prices.filter(pl.col("timestamp") < DEV_END)
    dev_frames = {h: make_factor_frame(dev_source, h) for h in LOOKBACKS}
    diagnostics = {h: diagnostic(dev_frames[h]) for h in LOOKBACKS}
    canonical = diagnostics[CANONICAL]
    gate = (
        canonical["n_days"] >= 700
        and canonical["mean_ic"] >= 0.02
        and canonical["hac_p"] < 0.05
        and canonical["long_minus_short"] > 0
    )

    payload = {
        "schema_version": 1,
        "run_id": "20260928-liquidity-short-term-reversal",
        "data_integrity": integrity,
        "diagnostics": {str(h): diagnostics[h] for h in LOOKBACKS},
        "development_gate_passed": gate,
        "oos_consumed": False,
        "trial_accounting": {
            "previous_parameter_trials": 9,
            "new_parameter_trials": 3,
            "cumulative_parameter_trials": 12,
        },
    }

    if not gate:
        payload["classification"] = "REJECT"
        payload["conclusion"] = (
            "Development liquidity-conditioned reversal diagnostic failed; "
            "primary OOS was not consumed."
        )
        print(json.dumps(payload, indent=2, default=str))
        return 0

    frames = {h: make_factor_frame(prices, h) for h in LOOKBACKS}
    results: dict[str, dict[str, dict]] = {}
    base_sharpes: list[float] = []
    for h in LOOKBACKS:
        targets = build_targets(frames[h], OOS_START, OOS_END)
        results[str(h)] = {}
        for mult in (1.0, 2.0, 3.0):
            results[str(h)][str(mult)] = simulate(
                prices,
                targets,
                BASE_COST_BPS * mult,
                OOS_START,
                OOS_END,
            )
        base_sharpes.append(
            float(results[str(h)]["1.0"]["metrics"]["annualized_sharpe"])
        )

    canonical_result = results[str(CANONICAL)]["1.0"]
    contributions = canonical_result["asset_contribution"]
    strongest = max(contributions, key=contributions.get) if contributions else None

    ablations: dict[str, object] = {
        "exclude_btc_eth": simulate(
            prices,
            build_targets(
                frames[CANONICAL],
                OOS_START,
                OOS_END,
                exclude={"BTCUSDT", "ETHUSDT"},
            ),
            BASE_COST_BPS,
            OOS_START,
            OOS_END,
        ),
        "delay_one_hour": simulate(
            prices,
            build_targets(
                frames[CANONICAL],
                OOS_START,
                OOS_END,
                delay_hours=1,
            ),
            BASE_COST_BPS,
            OOS_START,
            OOS_END,
        ),
    }
    if strongest is not None:
        ablations["exclude_strongest"] = {
            "asset": strongest,
            "result": simulate(
                prices,
                build_targets(
                    frames[CANONICAL],
                    OOS_START,
                    OOS_END,
                    exclude={strongest},
                ),
                BASE_COST_BPS,
                OOS_START,
                OOS_END,
            ),
        }

    dsr = compute_deflated_sharpe(
        float(canonical_result["metrics"]["annualized_sharpe"]),
        base_sharpes,
        n_obs_days=int(canonical_result["metrics"]["n_days"]),
    )

    base = canonical_result["metrics"]
    two_x = results[str(CANONICAL)]["2.0"]["metrics"]
    neighbor_positive = sum(
        results[str(h)]["1.0"]["metrics"]["total_return"] > 0 for h in LOOKBACKS
    )
    breadth_ok = (
        ablations["exclude_btc_eth"]["metrics"]["total_return"] > 0
        and ablations["delay_one_hour"]["metrics"]["total_return"] > 0
        and (
            strongest is None
            or ablations["exclude_strongest"]["result"]["metrics"]["total_return"] > 0
        )
    )
    qualifies = (
        base["annualized_sharpe"] > 1.0
        and base["total_return"] > 0
        and two_x["total_return"] > 0
        and neighbor_positive >= 2
        and breadth_ok
    )

    payload.update(
        {
            "oos_consumed": True,
            "oos_results": results,
            "ablations": ablations,
            "multiple_testing": {
                "base_cost_sharpes": base_sharpes,
                "dsr": dsr,
                "pbo": "N/A: three preregistered lookbacks",
            },
            "success_gate_candidate": qualifies,
            "classification": "EXPLORATORY_PASS" if qualifies else "REJECT",
        }
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
