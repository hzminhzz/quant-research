#!/usr/bin/env python3
"""Pre-registered weekly low-idiosyncratic-risk crypto factor research."""

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

WINDOWS = (336, 720, 1440)
CANONICAL = 720
MIN_HISTORY_HOURS = 720
LIQUID_FRACTION = 0.80
MIN_CROSS_SECTION = 8
BASE_COST_BPS = 3.0
DEV_START = datetime(2021, 1, 1, tzinfo=timezone.utc)
DEV_END = datetime(2024, 1, 1, tzinfo=timezone.utc)
OOS_START = datetime(2024, 1, 1, tzinfo=timezone.utc)
OOS_END = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _market_frame(df: pl.DataFrame) -> pl.DataFrame:
    ordered = df.sort(["symbol", "timestamp"]).with_columns(
        (pl.col("close") / pl.col("close").shift(1).over("symbol"))
        .log()
        .alias("_asset_ret"),
        (pl.col("close") * pl.col("volume")).alias("_dollar_volume"),
    )
    market = (
        ordered.filter(pl.col("_asset_ret").is_finite())
        .group_by("timestamp")
        .agg(pl.col("_asset_ret").mean().alias("_market_ret"))
        .sort("timestamp")
    )
    return ordered.join(market, on="timestamp", how="left")


def make_factor_frame(df: pl.DataFrame, window_hours: int) -> pl.DataFrame:
    history = max(MIN_HISTORY_HOURS, window_hours)
    base = _market_frame(df).with_columns(
        pl.col("_asset_ret").shift(1).over("symbol").alias("_x"),
        pl.col("_market_ret").shift(1).over("symbol").alias("_y"),
    ).with_columns(
        (pl.col("_x") * pl.col("_x")).alias("_x2"),
        (pl.col("_y") * pl.col("_y")).alias("_y2"),
        (pl.col("_x") * pl.col("_y")).alias("_xy"),
    )

    rolled = base.with_columns(
        pl.col("_x").rolling_mean(window_hours).over("symbol").alias("_mx"),
        pl.col("_y").rolling_mean(window_hours).over("symbol").alias("_my"),
        pl.col("_x2").rolling_mean(window_hours).over("symbol").alias("_mx2"),
        pl.col("_y2").rolling_mean(window_hours).over("symbol").alias("_my2"),
        pl.col("_xy").rolling_mean(window_hours).over("symbol").alias("_mxy"),
        pl.col("_dollar_volume")
        .shift(1)
        .rolling_mean(MIN_HISTORY_HOURS)
        .over("symbol")
        .alias("_trailing_dollar_volume"),
        pl.col("timestamp").shift(history).over("symbol").alias("_history_anchor"),
        pl.col("timestamp").shift(-168).over("symbol").alias("_next_week_ts"),
        pl.col("open").shift(-168).over("symbol").alias("_next_week_open"),
    ).with_columns(
        (pl.col("_mx2") - pl.col("_mx") * pl.col("_mx")).alias("_var_x"),
        (pl.col("_my2") - pl.col("_my") * pl.col("_my")).alias("_var_y"),
        (pl.col("_mxy") - pl.col("_mx") * pl.col("_my")).alias("_cov_xy"),
    ).with_columns(
        pl.when(pl.col("_var_y") > 0)
        .then(
            pl.max_horizontal(
                pl.col("_var_x") - (pl.col("_cov_xy") * pl.col("_cov_xy") / pl.col("_var_y")),
                pl.lit(0.0),
            )
        )
        .otherwise(None)
        .alias("_idio_var"),
        (pl.col("_next_week_open") / pl.col("open") - 1.0).alias("forward_return"),
    ).with_columns(
        (-pl.col("_idio_var")).alias("signal"),
    )

    weekly = rolled.filter(
        (pl.col("timestamp").dt.weekday() == 1)
        & (pl.col("timestamp").dt.hour() == 0)
        & pl.col("signal").is_finite()
        & pl.col("_trailing_dollar_volume").is_finite()
        & (pl.col("_history_anchor") == pl.col("timestamp") - pl.duration(hours=history))
        & (pl.col("_next_week_ts") == pl.col("timestamp") + pl.duration(hours=168))
    ).with_columns(
        pl.col("_trailing_dollar_volume")
        .rank(method="ordinal", descending=True)
        .over("timestamp")
        .alias("_liq_rank"),
        pl.len().over("timestamp").alias("_n_preliq"),
    ).filter(
        pl.col("_liq_rank")
        <= (pl.col("_n_preliq").cast(pl.Float64) * LIQUID_FRACTION).ceil()
    )

    return weekly.filter(
        pl.len().over("timestamp") >= MIN_CROSS_SECTION
    ).sort(["timestamp", "symbol"])


def diagnostic(frame: pl.DataFrame) -> dict:
    dev = frame.filter(
        (pl.col("timestamp") >= DEV_START) & (pl.col("timestamp") < DEV_END)
    )
    ics: list[float] = []
    spreads: list[float] = []
    counts: list[int] = []
    quantile_buckets: dict[int, list[float]] = {q: [] for q in range(1, 6)}

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
        spreads.append(
            float(np.mean([r for _, r in rows[-k:]]) - np.mean([r for _, r in rows[:k]]))
        )
        n = len(rows)
        for i, (_, ret) in enumerate(rows):
            q = min(5, int(i * 5 / n) + 1)
            quantile_buckets[q].append(float(ret))

    arr = np.asarray(ics, dtype=float)
    hac_t, hac_p = hac_mean_test(arr, max_lag=4)
    quantiles = [
        float(np.mean(quantile_buckets[q])) if quantile_buckets[q] else math.nan
        for q in range(1, 6)
    ]
    return {
        "n_weeks": len(ics),
        "mean_ic": float(np.mean(arr)) if len(arr) else math.nan,
        "ic_ir": float(np.mean(arr) / np.std(arr, ddof=1))
        if len(arr) > 1 and np.std(arr, ddof=1) > 0
        else 0.0,
        "hac_t": hac_t,
        "hac_p": hac_p,
        "low_minus_high": float(np.mean(spreads)) if spreads else math.nan,
        "quantile_returns": quantiles,
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
    dev_frames = {h: make_factor_frame(dev_source, h) for h in WINDOWS}
    diagnostics = {h: diagnostic(dev_frames[h]) for h in WINDOWS}
    canonical = diagnostics[CANONICAL]
    gate = (
        canonical["n_weeks"] >= 100
        and canonical["mean_ic"] >= 0.02
        and canonical["hac_p"] < 0.05
        and canonical["low_minus_high"] > 0
    )

    payload = {
        "schema_version": 1,
        "run_id": "20260928-low-idiosyncratic-risk-weekly",
        "data_integrity": integrity,
        "diagnostics": {str(h): diagnostics[h] for h in WINDOWS},
        "development_gate_passed": gate,
        "oos_consumed": False,
        "trial_accounting": {
            "previous_parameter_trials": 21,
            "new_parameter_trials": 3,
            "cumulative_parameter_trials": 24,
        },
    }

    if not gate:
        payload["classification"] = "REJECT"
        payload["conclusion"] = (
            "Development low-idiosyncratic-risk diagnostic failed; OOS was not consumed."
        )
        print(json.dumps(payload, indent=2, default=str))
        return 0

    frames = {h: make_factor_frame(prices, h) for h in WINDOWS}
    results: dict[str, dict[str, dict]] = {}
    base_sharpes: list[float] = []
    for h in WINDOWS:
        targets = build_targets(frames[h], OOS_START, OOS_END)
        results[str(h)] = {}
        for mult in (1.0, 2.0, 3.0):
            results[str(h)][str(mult)] = simulate(
                prices, targets, BASE_COST_BPS * mult, OOS_START, OOS_END
            )
        base_sharpes.append(float(results[str(h)]["1.0"]["metrics"]["annualized_sharpe"]))

    canonical_result = results[str(CANONICAL)]["1.0"]
    contributions = canonical_result["asset_contribution"]
    strongest = max(contributions, key=contributions.get) if contributions else None

    ablations: dict[str, object] = {
        "exclude_btc_eth": simulate(
            prices,
            build_targets(
                frames[CANONICAL], OOS_START, OOS_END, exclude={"BTCUSDT", "ETHUSDT"}
            ),
            BASE_COST_BPS,
            OOS_START,
            OOS_END,
        ),
        "delay_one_hour": simulate(
            prices,
            build_targets(frames[CANONICAL], OOS_START, OOS_END, delay_hours=1),
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
                    frames[CANONICAL], OOS_START, OOS_END, exclude={strongest}
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
    positive_neighbors = sum(
        results[str(h)]["1.0"]["metrics"]["total_return"] > 0 for h in WINDOWS
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
        and positive_neighbors >= 2
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
                "pbo": "N/A: three preregistered estimation windows",
            },
            "success_gate_candidate": qualifies,
            "classification": "EXPLORATORY_PASS" if qualifies else "REJECT",
            "conclusion": (
                "Candidate clears preregistered exploratory gates; sealed confirmation remains required."
                if qualifies
                else "Candidate failed one or more preregistered OOS or robustness requirements."
            ),
        }
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
