#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import polars as pl

from scripts.run_crypto_highvol_reversal import load_daily_range
from src.experiment import compute_deflated_sharpe

WEEKDAYS = (7, 1, 2)  # Sunday, Monday, Tuesday in Polars weekday numbering.
CAN = 1
TOPN = 30
LIQ_DAYS = 30
MIN_XS = 10
COST = 10.0
DEV0 = date(2022, 1, 1)
DEV1 = date(2024, 1, 1)
OOS0 = date(2024, 1, 1)
OOS1 = date(2026, 1, 1)
NAMES = {7: "Sunday", 1: "Monday", 2: "Tuesday"}


def feature_frame(d: pl.DataFrame, weekday: int) -> pl.DataFrame:
    x = (
        d.sort(["symbol", "date"])
        .with_columns(
            pl.col("qv")
            .shift(1)
            .rolling_sum(LIQ_DAYS)
            .over("symbol")
            .alias("_liq"),
            pl.col("date").shift(LIQ_DAYS).over("symbol").alias("_liq_anchor"),
            pl.col("open").shift(-1).over("symbol").alias("_exit_open"),
            pl.col("date").shift(-1).over("symbol").alias("_exit_date"),
        )
        .with_columns(
            (pl.col("_exit_open") / pl.col("open") - 1.0).alias("fwd_ret")
        )
        .filter(
            (pl.col("date").dt.weekday() == weekday)
            & pl.col("_liq").is_finite()
            & pl.col("fwd_ret").is_finite()
            & (
                pl.col("_liq_anchor")
                == pl.col("date") - pl.duration(days=LIQ_DAYS)
            )
            & (pl.col("_exit_date") == pl.col("date") + pl.duration(days=1))
        )
    )
    out: list[pl.DataFrame] = []
    for p in x.partition_by("date", maintain_order=True):
        liquid = p.sort("_liq", descending=True).head(TOPN)
        if liquid.height >= MIN_XS:
            out.append(liquid.select("date", "symbol", "fwd_ret"))
    if not out:
        return pl.DataFrame()
    return pl.concat(out, how="vertical").sort(["date", "symbol"])


def portfolio(
    f: pl.DataFrame,
    start: date,
    end: date,
    exclude: set[str] | None = None,
):
    ex = exclude or set()
    out = []
    ff = f.filter((pl.col("date") >= start) & (pl.col("date") < end))
    for p in ff.partition_by("date", maintain_order=True):
        rows = [r for r in p.iter_rows(named=True) if str(r["symbol"]) not in ex]
        if len(rows) < MIN_XS:
            continue
        weight = 1.0 / len(rows)
        gross = 0.0
        contrib: dict[str, float] = {}
        for row in rows:
            symbol = str(row["symbol"])
            ret = float(row["fwd_ret"])
            gross += weight * ret
            contrib[symbol] = weight * ret
        out.append((p["date"][0], gross, contrib))
    return out


def sim(rows, cost_bps_one_way: float) -> dict:
    rr = []
    contribution: dict[str, float] = {}
    for d, gross, contrib in rows:
        net = gross - 2.0 * cost_bps_one_way / 10_000.0
        rr.append((d, net))
        for symbol, value in contrib.items():
            contribution[symbol] = contribution.get(symbol, 0.0) + value

    if not rr:
        return {
            "metrics": {
                "annualized_sharpe": 0.0,
                "total_return": 0.0,
                "max_drawdown": 0.0,
                "n_weeks": 0,
                "mean_net_return": 0.0,
            },
            "by_year": {},
            "asset_contribution": {},
        }

    a = np.asarray([r for _, r in rr], dtype=float)
    eq = np.cumprod(1.0 + a)
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    sd = float(np.std(a, ddof=1)) if len(a) > 1 else 0.0
    by_year = {}
    for year in sorted({d.year for d, _ in rr}):
        q = np.asarray([r for d, r in rr if d.year == year], dtype=float)
        qs = float(np.std(q, ddof=1)) if len(q) > 1 else 0.0
        by_year[str(year)] = {
            "total_return": float(np.prod(1.0 + q) - 1.0),
            "sharpe": float(q.mean() / qs * math.sqrt(52.0)) if qs > 0 else 0.0,
        }

    return {
        "metrics": {
            "annualized_sharpe": (
                float(a.mean() / sd * math.sqrt(52.0)) if sd > 0 else 0.0
            ),
            "total_return": float(eq[-1] - 1.0),
            "max_drawdown": float(dd.min()),
            "n_weeks": int(len(a)),
            "mean_net_return": float(a.mean()),
        },
        "by_year": by_year,
        "asset_contribution": contribution,
    }


def compact(result: dict) -> dict:
    return {
        "metrics": result["metrics"],
        "by_year": result["by_year"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()

    # Development-first loading preserves the exploratory OOS until the
    # preregistered development gate passes.
    d_dev = load_daily_range(args.root, 2021, 11, 20, 2024, 1, 3)
    dev_frames = {w: feature_frame(d_dev, w) for w in WEEKDAYS}
    dev = {
        w: sim(portfolio(dev_frames[w], DEV0, DEV1), COST)
        for w in WEEKDAYS
    }
    cm = dev[CAN]["metrics"]
    monday_beats_placebos = (
        cm["mean_net_return"] > dev[7]["metrics"]["mean_net_return"]
        and cm["mean_net_return"] > dev[2]["metrics"]["mean_net_return"]
    )
    development_gate = (
        cm["annualized_sharpe"] > 0.70
        and cm["total_return"] > 0.0
        and cm["max_drawdown"] > -0.35
        and all(
            dev[CAN]["by_year"].get(str(y), {}).get("total_return", -1.0) >= 0.0
            for y in (2022, 2023)
        )
        and monday_beats_placebos
    )

    out = {
        "schema_version": 1,
        "run_id": "20260928-broad-monday-calendar",
        "strategy_family": "broad_monday_calendar_premium",
        "research_archetype": "calendar_time_series_basket",
        "development_universe_symbols": int(d_dev["symbol"].n_unique()),
        "development": {NAMES[w]: compact(dev[w]) for w in WEEKDAYS},
        "development_gate_passed": development_gate,
        "oos_consumed": False,
        "trial_accounting": {
            "previous_parameter_trials": 165,
            "new_parameter_trials": 3,
            "cumulative_parameter_trials": 168,
        },
    }

    if not development_gate:
        out.update(
            classification="REJECT",
            success_gate_candidate=False,
            multiple_testing={
                "dsr_probability": None,
                "pbo": "N/A: development gate failed before OOS.",
            },
            conclusion="REJECT. Development gate failed; exploratory OOS was not consumed.",
        )
        print(json.dumps(out, indent=2, default=str))
        return

    d_oos = load_daily_range(args.root, 2023, 11, 20, 2026, 1, 3)
    oos_frames = {w: feature_frame(d_oos, w) for w in WEEKDAYS}
    results = {}
    sharpes = []
    for w in WEEKDAYS:
        rows = portfolio(oos_frames[w], OOS0, OOS1)
        results[NAMES[w]] = {
            str(mult): sim(rows, COST * mult) for mult in (1, 2, 3)
        }
        sharpes.append(
            results[NAMES[w]]["1"]["metrics"]["annualized_sharpe"]
        )

    base = results["Monday"]["1"]
    bm = base["metrics"]
    ex_major = sim(
        portfolio(oos_frames[CAN], OOS0, OOS1, exclude={"BTCUSDT", "ETHUSDT"}),
        COST,
    )
    strongest = (
        max(
            base["asset_contribution"],
            key=lambda s: abs(base["asset_contribution"][s]),
        )
        if base["asset_contribution"]
        else None
    )
    ex_strongest = (
        sim(
            portfolio(
                oos_frames[CAN],
                OOS0,
                OOS1,
                exclude={strongest},
            ),
            COST,
        )
        if strongest
        else None
    )

    monday_beats_oos_placebos = (
        bm["mean_net_return"]
        > results["Sunday"]["1"]["metrics"]["mean_net_return"]
        and bm["mean_net_return"]
        > results["Tuesday"]["1"]["metrics"]["mean_net_return"]
    )
    years_ok = all(
        base["by_year"].get(str(y), {}).get("total_return", -1.0) >= 0.0
        for y in (2024, 2025)
    )
    family_dsr = compute_deflated_sharpe(
        bm["annualized_sharpe"],
        sharpes,
        n_obs_days=max(bm["n_weeks"] * 7, 1),
    )
    global_dsr = compute_deflated_sharpe(
        bm["annualized_sharpe"],
        sharpes + [0.0] * 165,
        n_obs_days=max(bm["n_weeks"] * 7, 1),
    )
    qual = (
        bm["annualized_sharpe"] > 1.0
        and results["Monday"]["2"]["metrics"]["total_return"] > 0.0
        and years_ok
        and bm["max_drawdown"] > -0.35
        and monday_beats_oos_placebos
        and ex_major["metrics"]["total_return"] > 0.0
        and (
            ex_strongest is None
            or ex_strongest["metrics"]["total_return"] > 0.0
        )
        and family_dsr["dsr_probability"] >= 0.95
        and global_dsr["dsr_probability"] >= 0.95
    )

    out.update(
        oos_consumed=True,
        oos_universe_symbols=int(d_oos["symbol"].n_unique()),
        oos_results={
            day: {k: compact(v) for k, v in stress.items()}
            for day, stress in results.items()
        },
        exclude_btc_eth=compact(ex_major),
        strongest_asset=strongest,
        exclude_strongest=compact(ex_strongest) if ex_strongest else None,
        multiple_testing={
            "family_dsr": family_dsr,
            "global_168_trial_proxy": global_dsr,
            "pbo": "N/A: three fixed preregistered weekday variants.",
        },
        success_gate_candidate=qual,
        classification=(
            "PROMOTE_TO_MANUAL_CONFIRMATION" if qual else "REJECT"
        ),
        conclusion=(
            "PROMOTE_TO_MANUAL_CONFIRMATION. Exploratory success gate passed; sealed confirmation remains untouched."
            if qual
            else "REJECT. Exploratory OOS or robustness/multiple-testing gate failed."
        ),
    )
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
