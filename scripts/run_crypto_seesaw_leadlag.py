#!/usr/bin/env python3
# Pre-registered seesaw lead-lag research runner.
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

HORIZONS = (2, 4, 8)
CANONICAL = 4
MIN_HISTORY_HOURS = 720
N_LEADERS = 5
MIN_FOLLOWERS = 6
BASE_COST_BPS = 3.0
DEV_START = datetime(2021, 1, 1, tzinfo=timezone.utc)
DEV_END = datetime(2024, 1, 1, tzinfo=timezone.utc)
OOS_START = datetime(2024, 1, 1, tzinfo=timezone.utc)
OOS_END = datetime(2026, 1, 1, tzinfo=timezone.utc)

def prepared_panel(df: pl.DataFrame, horizon: int) -> pl.DataFrame:
    ordered = df.sort(["symbol", "timestamp"]).with_columns(
        (pl.col("close") * pl.col("volume")).alias("_dollar_volume")
    )
    return ordered.with_columns(
        pl.col("close").shift(1).over("symbol").alias("_last_close"),
        pl.col("close").shift(horizon + 1).over("symbol").alias("_past_close"),
        pl.col("_dollar_volume").shift(1).rolling_mean(MIN_HISTORY_HOURS).over("symbol").alias("_liq"),
        pl.col("timestamp").shift(MIN_HISTORY_HOURS).over("symbol").alias("_anchor"),
        pl.col("timestamp").shift(-horizon).over("symbol").alias("_future_ts"),
        pl.col("open").shift(-horizon).over("symbol").alias("_future_open"),
    ).with_columns(
        (pl.col("_last_close") / pl.col("_past_close") - 1.0).alias("_lag_return"),
        (pl.col("_future_open") / pl.col("open") - 1.0).alias("_future_return"),
    ).filter(
        pl.col("_lag_return").is_finite()
        & pl.col("_liq").is_finite()
        & (pl.col("_anchor") == pl.col("timestamp") - pl.duration(hours=MIN_HISTORY_HOURS))
        & (pl.col("_future_ts") == pl.col("timestamp") + pl.duration(hours=horizon))
    )


def block_records(prepared: pl.DataFrame, horizon: int, start: datetime, end: datetime, exclude: set[str] | None = None) -> list[dict]:
    excluded = exclude or set()
    frame = prepared.filter(
        (pl.col("timestamp") >= start)
        & (pl.col("timestamp") < end)
        & (~pl.col("symbol").is_in(sorted(excluded)))
    )
    records = []
    for part in frame.partition_by("timestamp", maintain_order=True):
        ts = part["timestamp"][0]
        if int(ts.timestamp() // 3600) % horizon != 0:
            continue
        rows = sorted(part.iter_rows(named=True), key=lambda r: float(r["_liq"]), reverse=True)
        if len(rows) < N_LEADERS + MIN_FOLLOWERS:
            continue
        leaders = rows[:N_LEADERS]
        followers = rows[N_LEADERS:]
        leader_return = float(np.mean([float(r["_lag_return"]) for r in leaders]))
        follower_future = float(np.mean([float(r["_future_return"]) for r in followers]))
        records.append({
            "timestamp": ts,
            "signal": -leader_return,
            "future": follower_future,
            "leaders": [r["symbol"] for r in leaders],
            "followers": [r["symbol"] for r in followers],
        })
    return records


def diagnostic(records: list[dict]) -> dict:
    signal = np.asarray([r["signal"] for r in records], dtype=float)
    future = np.asarray([r["future"] for r in records], dtype=float)
    if len(signal) < 20:
        return {"n_blocks": len(signal), "spearman": math.nan, "hac_t": 0.0, "hac_p": 1.0, "mean_signed_return": math.nan}
    rho = float(stats.spearmanr(signal, future).statistic)
    signed = np.sign(signal) * future
    hac_t, hac_p = hac_mean_test(signed, max_lag=4)
    return {
        "n_blocks": len(signal),
        "spearman": rho,
        "hac_t": hac_t,
        "hac_p": hac_p,
        "mean_signed_return": float(np.mean(signed)),
        "mean_followers": float(np.mean([len(r["followers"]) for r in records])),
    }


def build_targets(records: list[dict], delay_hours: int = 0, exclude_follower: set[str] | None = None) -> dict[datetime, dict[str, float]]:
    excluded = exclude_follower or set()
    targets = {}
    for record in records:
        followers = [s for s in record["followers"] if s not in excluded]
        if len(followers) < MIN_FOLLOWERS:
            continue
        signal = float(record["signal"])
        direction = 1.0 if signal > 0 else -1.0 if signal < 0 else 0.0
        weights = {s: direction / len(followers) for s in followers} if direction else {}
        targets[record["timestamp"] + timedelta(hours=delay_hours)] = weights
    return targets


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    args = parser.parse_args()
    prices = pl.read_parquet(args.data).sort(["symbol", "timestamp"])
    integrity = validate_panel(prices)

    dev_prepared = {
        h: prepared_panel(prices.filter(pl.col("timestamp") < DEV_END + timedelta(hours=h)), h)
        for h in HORIZONS
    }
    dev_records = {
        h: block_records(dev_prepared[h], h, DEV_START, DEV_END)
        for h in HORIZONS
    }
    diagnostics = {h: diagnostic(dev_records[h]) for h in HORIZONS}
    canonical = diagnostics[CANONICAL]
    gate = (
        canonical["n_blocks"] >= 1000
        and canonical["spearman"] >= 0.02
        and canonical["hac_p"] < 0.05
        and canonical["mean_signed_return"] > 0
    )

    payload = {
        "schema_version": 1,
        "run_id": "20260928-seesaw-large-to-small-leadlag",
        "data_integrity": integrity,
        "diagnostics": {str(h): diagnostics[h] for h in HORIZONS},
        "development_gate_passed": gate,
        "oos_consumed": False,
        "trial_accounting": {
            "previous_parameter_trials": 15,
            "new_parameter_trials": 3,
            "cumulative_parameter_trials": 18,
        },
    }
    if not gate:
        payload["classification"] = "REJECT"
        payload["conclusion"] = "Development large-to-small lead-lag diagnostic failed; OOS was not consumed."
        print(json.dumps(payload, indent=2, default=str))
        return 0

    prepared = {h: prepared_panel(prices, h) for h in HORIZONS}
    oos_records = {h: block_records(prepared[h], h, OOS_START, OOS_END) for h in HORIZONS}
    results = {}
    base_sharpes = []
    for horizon in HORIZONS:
        results[str(horizon)] = {}
        desired = build_targets(oos_records[horizon])
        for mult in (1.0, 2.0, 3.0):
            results[str(horizon)][str(mult)] = simulate(
                prices, desired, BASE_COST_BPS * mult, OOS_START, OOS_END
            )
        base_sharpes.append(float(results[str(horizon)]["1.0"]["metrics"]["annualized_sharpe"]))

    canonical_result = results[str(CANONICAL)]["1.0"]
    contributions = canonical_result["asset_contribution"]
    strongest = max(contributions, key=contributions.get) if contributions else None

    without_btc_records = block_records(
        prepared[CANONICAL],
        CANONICAL,
        OOS_START,
        OOS_END,
        exclude={"BTCUSDT"},
    )
    ablations = {
        "without_btc": simulate(
            prices,
            build_targets(without_btc_records),
            BASE_COST_BPS,
            OOS_START,
            OOS_END,
        ),
        "delay_one_hour": simulate(
            prices,
            build_targets(oos_records[CANONICAL], delay_hours=1),
            BASE_COST_BPS,
            OOS_START,
            OOS_END,
        ),
    }
    if strongest is not None:
        ablations["without_strongest"] = {
            "asset": strongest,
            "result": simulate(
                prices,
                build_targets(oos_records[CANONICAL], exclude_follower={strongest}),
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
        results[str(h)]["1.0"]["metrics"]["total_return"] > 0 for h in HORIZONS
    )
    breadth_ok = (
        ablations["without_btc"]["metrics"]["total_return"] > 0
        and ablations["delay_one_hour"]["metrics"]["total_return"] > 0
        and (
            strongest is None
            or ablations["without_strongest"]["result"]["metrics"]["total_return"] > 0
        )
    )
    qualifies = (
        base["annualized_sharpe"] > 1.0
        and base["total_return"] > 0
        and two_x["total_return"] > 0
        and neighbor_positive >= 2
        and breadth_ok
    )
    payload.update({
        "oos_consumed": True,
        "oos_results": results,
        "ablations": ablations,
        "multiple_testing": {
            "base_cost_sharpes": base_sharpes,
            "dsr": dsr,
            "pbo": "N/A: three preregistered horizons",
        },
        "success_gate_candidate": qualifies,
        "classification": "EXPLORATORY_PASS" if qualifies else "REJECT",
    })
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
