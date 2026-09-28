#!/usr/bin/env python3
"""Pre-registered 6h volatility-scaled time-series momentum research."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path

import numpy as np
import polars as pl

from scripts.run_crypto_high_momentum import simulate, validate_panel
from src.experiment import compute_deflated_sharpe

LOOKBACKS = (336, 720, 1440)
CANONICAL = 720
VOL_WINDOW = 720
LIQUID_FRACTION = 0.80
MIN_CROSS_SECTION = 8
BASE_COST_BPS = 3.0
DEV_START = datetime(2021, 1, 1, tzinfo=timezone.utc)
DEV_END = datetime(2024, 1, 1, tzinfo=timezone.utc)
OOS_START = datetime(2024, 1, 1, tzinfo=timezone.utc)
OOS_END = datetime(2026, 1, 1, tzinfo=timezone.utc)


def feature_frame(df: pl.DataFrame, lookback: int) -> pl.DataFrame:
    history = max(VOL_WINDOW, lookback + 1)
    ordered = df.sort(["symbol", "timestamp"]).with_columns(
        (pl.col("close") * pl.col("volume")).alias("_dv"),
        (pl.col("close") / pl.col("close").shift(1).over("symbol")).log().alias("_lr"),
    )
    frame = ordered.with_columns(
        pl.col("close").shift(1).over("symbol").alias("_c1"),
        pl.col("close").shift(lookback + 1).over("symbol").alias("_c0"),
        pl.col("_lr").shift(1).rolling_std(VOL_WINDOW).over("symbol").alias("_vol"),
        pl.col("_dv").shift(1).rolling_mean(VOL_WINDOW).over("symbol").alias("_liq"),
        pl.col("timestamp").shift(history).over("symbol").alias("_anchor"),
    ).with_columns(
        (pl.col("_c1") / pl.col("_c0") - 1.0).alias("_mom"),
    ).filter(
        pl.col("_mom").is_finite()
        & pl.col("_vol").is_finite()
        & (pl.col("_vol") > 0)
        & pl.col("_liq").is_finite()
        & (pl.col("_anchor") == pl.col("timestamp") - pl.duration(hours=history))
    )
    return frame.with_columns(
        pl.col("_liq").rank(method="ordinal", descending=True).over("timestamp").alias("_liq_rank"),
        pl.len().over("timestamp").alias("_n"),
    ).filter(
        pl.col("_liq_rank") <= (pl.col("_n").cast(pl.Float64) * LIQUID_FRACTION).ceil()
    )


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
    targets = {}
    for part in selected.partition_by("timestamp", maintain_order=True):
        ts = part["timestamp"][0]
        if int(ts.timestamp() // 3600) % 6 != 0 or part.height < MIN_CROSS_SECTION:
            continue
        rows = list(part.iter_rows(named=True))
        raw = {}
        for row in rows:
            mom = float(row["_mom"])
            vol = float(row["_vol"])
            if not math.isfinite(mom) or not math.isfinite(vol) or vol <= 0:
                continue
            direction = 1.0 if mom > 0 else -1.0 if mom < 0 else 0.0
            if direction:
                raw[str(row["symbol"])] = direction / vol
        gross = sum(abs(v) for v in raw.values())
        if gross <= 0 or len(raw) < MIN_CROSS_SECTION:
            continue
        targets[ts + timedelta(hours=delay_hours)] = {
            sym: value / gross for sym, value in raw.items()
        }
    return targets


def run_period(
    prices: pl.DataFrame,
    frames: dict[int, pl.DataFrame],
    start: datetime,
    end: datetime,
    cost_bps: float,
) -> dict[str, dict]:
    return {
        str(lb): simulate(
            prices,
            build_targets(frames[lb], start, end),
            cost_bps,
            start,
            end,
        )
        for lb in LOOKBACKS
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    args = parser.parse_args()

    prices = pl.read_parquet(args.data).sort(["symbol", "timestamp"])
    integrity = validate_panel(prices)
    frames = {lb: feature_frame(prices, lb) for lb in LOOKBACKS}

    development = run_period(prices, frames, DEV_START, DEV_END, BASE_COST_BPS)
    dev_sharpes = {
        lb: float(development[str(lb)]["metrics"]["annualized_sharpe"])
        for lb in LOOKBACKS
    }
    dev_returns = {
        lb: float(development[str(lb)]["metrics"]["total_return"])
        for lb in LOOKBACKS
    }
    gate = (
        dev_sharpes[CANONICAL] > 0.5
        and dev_returns[CANONICAL] > 0
        and sum(v > 0 for v in dev_returns.values()) >= 2
    )

    payload = {
        "schema_version": 1,
        "run_id": "20260928-volscaled-tsmom-6h",
        "data_integrity": integrity,
        "development": {
            str(lb): {
                "net_sharpe": dev_sharpes[lb],
                "total_return": dev_returns[lb],
                "max_drawdown": development[str(lb)]["metrics"]["max_drawdown"],
            }
            for lb in LOOKBACKS
        },
        "development_gate_passed": gate,
        "oos_consumed": False,
        "trial_accounting": {
            "previous_parameter_trials": 18,
            "new_parameter_trials": 3,
            "cumulative_parameter_trials": 21,
        },
    }
    if not gate:
        payload["classification"] = "REJECT"
        payload["conclusion"] = "Development volatility-scaled TSMOM gate failed; OOS was not consumed."
        print(json.dumps(payload, indent=2, default=str))
        return 0

    results = {}
    base_sharpes = []
    for lb in LOOKBACKS:
        results[str(lb)] = {}
        for mult in (1.0, 2.0, 3.0):
            results[str(lb)][str(mult)] = simulate(
                prices,
                build_targets(frames[lb], OOS_START, OOS_END),
                BASE_COST_BPS * mult,
                OOS_START,
                OOS_END,
            )
        base_sharpes.append(float(results[str(lb)]["1.0"]["metrics"]["annualized_sharpe"]))

    canonical = results[str(CANONICAL)]["1.0"]
    contributions = canonical["asset_contribution"]
    strongest = max(contributions, key=contributions.get) if contributions else None
    ablations = {
        "exclude_btc_eth": simulate(
            prices,
            build_targets(frames[CANONICAL], OOS_START, OOS_END, exclude={"BTCUSDT", "ETHUSDT"}),
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
                build_targets(frames[CANONICAL], OOS_START, OOS_END, exclude={strongest}),
                BASE_COST_BPS,
                OOS_START,
                OOS_END,
            ),
        }

    dsr = compute_deflated_sharpe(
        float(canonical["metrics"]["annualized_sharpe"]),
        base_sharpes,
        n_obs_days=int(canonical["metrics"]["n_days"]),
    )
    base = canonical["metrics"]
    two = results[str(CANONICAL)]["2.0"]["metrics"]
    positive_neighbors = sum(
        results[str(lb)]["1.0"]["metrics"]["total_return"] > 0 for lb in LOOKBACKS
    )
    breadth = (
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
        and two["total_return"] > 0
        and positive_neighbors >= 2
        and breadth
    )
    payload.update({
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
    })
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
