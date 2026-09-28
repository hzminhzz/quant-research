#!/usr/bin/env python3
"""Pre-registered weekly long-horizon crypto reversal factor research."""

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

WINDOWS = (720, 1440, 2160)
CANONICAL = 1440
LIQ_WINDOW = 720
LIQUID_FRACTION = 0.80
MIN_CROSS_SECTION = 8
BASE_COST_BPS = 3.0
DEV_START = datetime(2021, 1, 1, tzinfo=timezone.utc)
DEV_END = datetime(2024, 1, 1, tzinfo=timezone.utc)
OOS_START = datetime(2024, 1, 1, tzinfo=timezone.utc)
OOS_END = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_factor_frame(df: pl.DataFrame, window: int) -> pl.DataFrame:
    history = max(window + 1, LIQ_WINDOW)
    ordered = df.sort(["symbol", "timestamp"]).with_columns(
        (pl.col("close") * pl.col("volume")).alias("_dv")
    )
    frame = ordered.with_columns(
        pl.col("close").shift(1).over("symbol").alias("_c1"),
        pl.col("close").shift(window + 1).over("symbol").alias("_c0"),
        pl.col("_dv").shift(1).rolling_mean(LIQ_WINDOW).over("symbol").alias("_liq"),
        pl.col("timestamp").shift(history).over("symbol").alias("_anchor"),
        pl.col("timestamp").shift(-168).over("symbol").alias("_next_ts"),
        pl.col("open").shift(-168).over("symbol").alias("_next_open"),
    ).with_columns(
        (-(pl.col("_c1") / pl.col("_c0") - 1.0)).alias("signal"),
        (pl.col("_next_open") / pl.col("open") - 1.0).alias("forward_return"),
    )
    weekly = frame.filter(
        (pl.col("timestamp").dt.weekday() == 1)
        & (pl.col("timestamp").dt.hour() == 0)
        & pl.col("signal").is_finite()
        & pl.col("_liq").is_finite()
        & (pl.col("_anchor") == pl.col("timestamp") - pl.duration(hours=history))
        & (pl.col("_next_ts") == pl.col("timestamp") + pl.duration(hours=168))
    ).with_columns(
        pl.col("_liq").rank(method="ordinal", descending=True).over("timestamp").alias("_liq_rank"),
        pl.len().over("timestamp").alias("_n"),
    ).filter(
        pl.col("_liq_rank") <= (pl.col("_n").cast(pl.Float64) * LIQUID_FRACTION).ceil()
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
    buckets: dict[int, list[float]] = {q: [] for q in range(1, 5)}
    for part in dev.partition_by("timestamp", maintain_order=True):
        n = part.height
        if n < MIN_CROSS_SECTION:
            continue
        signal = part["signal"].to_numpy()
        fwd = part["forward_return"].to_numpy()
        ic = stats.spearmanr(signal, fwd).statistic
        if np.isfinite(ic):
            ics.append(float(ic))
            counts.append(n)
        rows = sorted(zip(signal.tolist(), fwd.tolist()), key=lambda z: z[0])
        k = max(1, math.ceil(n * 0.25))
        spreads.append(
            float(np.mean([r for _, r in rows[-k:]]) - np.mean([r for _, r in rows[:k]]))
        )
        for i, (_, ret) in enumerate(rows):
            q = min(4, int(i * 4 / n) + 1)
            buckets[q].append(float(ret))
    arr = np.asarray(ics, dtype=float)
    hac_t, hac_p = hac_mean_test(arr, max_lag=4)
    return {
        "n_weeks": len(ics),
        "mean_ic": float(np.mean(arr)) if len(arr) else math.nan,
        "ic_ir": float(np.mean(arr) / np.std(arr, ddof=1))
        if len(arr) > 1 and np.std(arr, ddof=1) > 0
        else 0.0,
        "hac_t": hac_t,
        "hac_p": hac_p,
        "loser_minus_winner": float(np.mean(spreads)) if spreads else math.nan,
        "quartile_returns": [
            float(np.mean(buckets[q])) if buckets[q] else math.nan for q in range(1, 5)
        ],
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
    out: dict[datetime, dict[str, float]] = {}
    for part in selected.partition_by("timestamp", maintain_order=True):
        rows = sorted(
            [(r["symbol"], float(r["signal"])) for r in part.iter_rows(named=True)],
            key=lambda z: z[1],
        )
        if len(rows) < MIN_CROSS_SECTION:
            continue
        k = max(1, math.ceil(len(rows) * 0.25))
        w: dict[str, float] = {}
        for sym, _ in rows[-k:]:
            w[sym] = 0.5 / k
        for sym, _ in rows[:k]:
            w[sym] = -0.5 / k
        out[part["timestamp"][0] + timedelta(hours=delay_hours)] = w
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    args = parser.parse_args()

    prices = pl.read_parquet(args.data).sort(["symbol", "timestamp"])
    integrity = validate_panel(prices)

    dev_source = prices.filter(pl.col("timestamp") < DEV_END)
    dev_frames = {w: make_factor_frame(dev_source, w) for w in WINDOWS}
    diagnostics = {w: diagnostic(dev_frames[w]) for w in WINDOWS}
    canonical = diagnostics[CANONICAL]
    gate = (
        canonical["n_weeks"] >= 100
        and canonical["mean_ic"] >= 0.02
        and canonical["hac_p"] < 0.05
        and canonical["loser_minus_winner"] > 0
    )

    payload = {
        "schema_version": 1,
        "run_id": "20260928-long-horizon-reversal-60d",
        "data_integrity": integrity,
        "diagnostics": {str(w): diagnostics[w] for w in WINDOWS},
        "development_gate_passed": gate,
        "oos_consumed": False,
        "trial_accounting": {
            "previous_parameter_trials": 30,
            "new_parameter_trials": 3,
            "cumulative_parameter_trials": 33,
        },
    }
    if not gate:
        payload["classification"] = "REJECT"
        payload["conclusion"] = "Development long-horizon reversal gate failed; OOS was not consumed."
        print(json.dumps(payload, indent=2, default=str))
        return 0

    frames = {w: make_factor_frame(prices, w) for w in WINDOWS}
    results: dict[str, dict[str, dict]] = {}
    base_sharpes: list[float] = []
    for w in WINDOWS:
        results[str(w)] = {}
        target = build_targets(frames[w], OOS_START, OOS_END)
        for mult in (1.0, 2.0, 3.0):
            results[str(w)][str(mult)] = simulate(
                prices, target, BASE_COST_BPS * mult, OOS_START, OOS_END
            )
        base_sharpes.append(
            float(results[str(w)]["1.0"]["metrics"]["annualized_sharpe"])
        )

    primary = results[str(CANONICAL)]["1.0"]
    contributions = primary["asset_contribution"]
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
    if strongest:
        ablations["exclude_strongest"] = {
            "asset": strongest,
            "result": simulate(
                prices,
                build_targets(frames[CANONICAL], OOS_START, OOS_END, exclude={strongest}),
                BASE_COST_BPS,
                OOS_START,
                OOS_END,
            ),
        }

    dsr = compute_deflated_sharpe(
        float(primary["metrics"]["annualized_sharpe"]),
        base_sharpes,
        n_obs_days=int(primary["metrics"]["n_days"]),
    )
    base = primary["metrics"]
    two = results[str(CANONICAL)]["2.0"]["metrics"]
    stable = sum(
        results[str(w)]["1.0"]["metrics"]["total_return"] > 0 for w in WINDOWS
    ) >= 2
    years = all(primary["by_year"][str(y)]["total_return"] >= 0 for y in (2024, 2025))
    breadth = (
        ablations["exclude_btc_eth"]["metrics"]["total_return"] > 0
        and ablations["delay_one_hour"]["metrics"]["total_return"] > 0
        and (
            not strongest
            or ablations["exclude_strongest"]["result"]["metrics"]["total_return"] > 0
        )
    )
    qualifies = (
        base["annualized_sharpe"] > 1.0
        and base["total_return"] > 0
        and two["total_return"] > 0
        and stable
        and years
        and breadth
        and dsr["dsr_probability"] >= 0.95
    )
    payload.update(
        {
            "oos_consumed": True,
            "oos_results": results,
            "ablations": ablations,
            "multiple_testing": {
                "base_cost_sharpes": base_sharpes,
                "dsr": dsr,
                "pbo": "N/A: three preregistered formation windows",
                "global_cumulative_parameter_trials": 33,
            },
            "funding_treatment": "not modeled in the OHLCV panel",
            "success_gate_candidate": qualifies,
            "classification": "EXPLORATORY_PASS" if qualifies else "REJECT",
        }
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
