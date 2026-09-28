#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import polars as pl

from scripts.run_crypto_top20_donchian import (
    COST,
    DEV0,
    DEV1,
    H,
    OOS0,
    OOS1,
    model_states,
    run,
)
from src.experiment import compute_deflated_sharpe


def panel_fast(root: Path) -> pl.DataFrame:
    pattern = str(root / "symbol=*" / "year=*" / "month=*" / "data.parquet")
    daily = (
        pl.scan_parquet(pattern, hive_partitioning=True)
        .filter(
            pl.col("symbol").str.ends_with("USDT")
            & (pl.col("symbol") != "BTCDOMUSDT")
            & (pl.col("timestamp") < pl.datetime(2026, 1, 2, time_zone="UTC"))
        )
        .select("timestamp", "symbol", "open", "close", "quote_volume")
        .with_columns(pl.col("timestamp").dt.date().alias("date"))
        .group_by(["symbol", "date"])
        .agg(
            pl.col("open").first().alias("open"),
            pl.col("close").last().alias("close"),
            pl.col("quote_volume").sum().alias("qv"),
            pl.len().alias("hours"),
        )
        .filter(pl.col("hours") == 24)
        .drop("hours")
        .sort(["symbol", "date"])
        .collect(engine="streaming")
    )

    frames: list[pl.DataFrame] = []
    for d in daily.partition_by("symbol", maintain_order=True):
        if d.height < 370:
            continue
        symbol = str(d["symbol"][0])
        dates = np.asarray(d["date"].to_list(), dtype=object)
        close = d["close"].to_numpy()
        open_ = d["open"].to_numpy()
        qv = d["qv"].to_numpy()

        combo = np.mean(
            np.column_stack([model_states(close, dates, h) for h in H]), axis=1
        )
        ret = np.full(len(close), np.nan)
        ret[1:] = close[1:] / close[:-1] - 1.0
        vol = np.full(len(close), np.nan)
        liq = np.full(len(close), np.nan)

        for i in range(len(close)):
            if i >= 91 and (dates[i - 1] - dates[i - 91]).days == 90:
                z = ret[i - 90 : i]
                if np.all(np.isfinite(z)):
                    vol[i] = np.std(z, ddof=1) * math.sqrt(365)
            if i >= 30 and (dates[i - 1] - dates[i - 30]).days == 29:
                liq[i] = float(np.median(qv[i - 30 : i]))

        lev = np.where(
            np.isfinite(vol) & (vol > 0), np.minimum(2.0, 0.25 / vol), 0.0
        )
        next_open = np.r_[open_[1:], np.nan]
        next_date = np.asarray(list(dates[1:]) + [None], dtype=object)
        valid_next = np.asarray(
            [
                nd is not None and (nd - cur).days == 1
                for cur, nd in zip(dates, next_date, strict=True)
            ],
            dtype=bool,
        )
        next_open = np.where(valid_next, next_open, np.nan)
        age = np.asarray([(x - dates[0]).days for x in dates])

        frames.append(
            pl.DataFrame(
                {
                    "date": dates,
                    "symbol": [symbol] * len(dates),
                    "open": open_,
                    "next_open": next_open,
                    "exposure": combo * lev,
                    "liq": liq,
                    "age": age,
                }
            )
        )

    return (
        pl.concat(frames, how="vertical")
        .filter(
            pl.col("next_open").is_finite()
            & pl.col("liq").is_finite()
            & (pl.col("age") >= 365)
        )
        .sort(["date", "symbol"])
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()

    p = panel_fast(args.root)
    dev = run(p, DEV0, DEV1, COST)
    gate = (
        dev["metrics"]["annualized_sharpe"] > 0.8
        and dev["metrics"]["total_return"] > 0
        and dev["metrics"]["max_drawdown"] > -0.30
    )
    out = {
        "schema_version": 1,
        "run_id": "20260928-top20-donchian-ensemble",
        "execution_status": "COMPLETE_PREVIOUS_TIMEOUT_RESOLVED_FAST_LOADER",
        "panel_rows": p.height,
        "symbols": p["symbol"].n_unique(),
        "development": dev,
        "development_gate_passed": gate,
        "oos_consumed": False,
        "trial_accounting": {
            "previous_parameter_trials": 61,
            "new_parameter_trials": 1,
            "cumulative_parameter_trials": 62,
            "new_trials_from_resume": 0,
        },
    }

    if not gate:
        out.update(
            classification="REJECT",
            success_gate_candidate=False,
            conclusion="REJECT. Development gate failed; OOS not consumed.",
        )
        print(json.dumps(out, indent=2, default=str))
        return

    res = {str(m): run(p, OOS0, OOS1, COST * m) for m in (1, 2, 3, 5)}
    delay = run(p, OOS0, OOS1, COST, delay=1)
    can = res["1"]
    b = can["metrics"]
    two = res["2"]["metrics"]
    years = all(
        can["by_year"].get(str(y), {}).get("total_return", -1) > 0
        for y in (2024, 2025)
    )
    dsr = compute_deflated_sharpe(
        b["annualized_sharpe"],
        [b["annualized_sharpe"]] + [0.0] * 61,
        n_obs_days=b["n_days"],
    )
    qual = (
        b["annualized_sharpe"] > 1
        and b["total_return"] > 0
        and two["total_return"] > 0
        and years
        and b["max_drawdown"] > -0.25
        and delay["metrics"]["annualized_sharpe"] > 0.8
        and dsr["dsr_probability"] >= 0.95
    )
    out.update(
        oos_consumed=True,
        oos_results=res,
        delay_one_day=delay,
        multiple_testing={"global_62_trial_proxy": dsr},
        success_gate_candidate=qual,
        classification=(
            "PROMOTE_TO_MANUAL_CONFIRMATION" if qual else "REJECT"
        ),
        conclusion=(
            "PROMOTE_TO_MANUAL_CONFIRMATION. Preregistered exploratory gate passed; sealed confirmation remains untouched."
            if qual
            else "REJECT. Exploratory OOS or robustness/multiple-testing gate failed."
        ),
    )
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
