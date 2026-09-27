#!/usr/bin/env python3
"""Pre-registered BTC 12h same-session reversal replication."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import polars as pl

from src.experiment import compute_deflated_sharpe


SECONDS_PER_YEAR = 365.0 * 24.0 * 60.0 * 60.0


def load_prices(path: Path, start: str, end_exclusive: str) -> pl.DataFrame:
    df = (
        pl.scan_parquet(path)
        .filter(
            (pl.col("timestamp") >= pl.lit(start).str.to_datetime(time_zone="UTC"))
            & (pl.col("timestamp") < pl.lit(end_exclusive).str.to_datetime(time_zone="UTC"))
        )
        .select("timestamp", "open", "high", "low", "close", "volume")
        .collect()
        .sort("timestamp")
    )
    if not df.height:
        raise ValueError("no data in requested exploration window")
    if df["timestamp"].is_duplicated().any():
        raise ValueError("duplicate timestamps")
    if not df["timestamp"].is_sorted():
        raise ValueError("timestamps are not sorted")
    if df.null_count().sum_horizontal().item() != 0:
        raise ValueError("null values present")
    if df.filter(
        (pl.col("high") < pl.max_horizontal("open", "close", "low"))
        | (pl.col("low") > pl.min_horizontal("open", "close", "high"))
        | (pl.col("volume") < 0)
    ).height:
        raise ValueError("OHLC/volume integrity failure")
    gaps = (
        df.select(pl.col("timestamp").diff().alias("gap"))
        .drop_nulls()
        .filter(pl.col("gap") != pl.duration(minutes=5))
    )
    if gaps.height:
        raise ValueError(f"non-5m gaps inside selected window: {gaps.height}")
    return df


def make_sessions(df: pl.DataFrame, day_start_hour: int) -> pl.DataFrame:
    other = (day_start_hour + 12) % 24
    endpoints = (
        df.with_columns((pl.col("timestamp") + pl.duration(minutes=5)).alias("endpoint"))
        .filter(
            (pl.col("endpoint").dt.minute() == 0)
            & pl.col("endpoint").dt.hour().is_in([day_start_hour, other])
        )
        .select("endpoint", pl.col("close").alias("price"))
        .sort("endpoint")
    )
    sessions = (
        endpoints.with_columns(
            pl.col("price").shift(1).alias("start_price"),
            pl.col("endpoint").shift(1).alias("start_endpoint"),
        )
        .drop_nulls()
        .with_columns(
            (pl.col("price") / pl.col("start_price") - 1.0).alias("session_return"),
            pl.when(pl.col("endpoint").dt.hour() == other)
            .then(pl.lit("day"))
            .otherwise(pl.lit("night"))
            .alias("session_type"),
            pl.col("endpoint").dt.date().alias("date"),
        )
    )
    expected = pl.duration(hours=12)
    bad = sessions.filter((pl.col("endpoint") - pl.col("start_endpoint")) != expected)
    if bad.height:
        raise ValueError(f"non-12h sessions detected: {bad.height}")
    return (
        sessions.with_columns(
            pl.col("session_return").shift(1).over("session_type").alias("lag_same_session")
        )
        .with_columns(
            pl.when(pl.col("lag_same_session").is_null() | (pl.col("lag_same_session") == 0))
            .then(pl.lit(0.0))
            .otherwise(-pl.col("lag_same_session").sign())
            .alias("position")
        )
        .sort("endpoint")
    )


def run_variant(sessions: pl.DataFrame, cost_bps: float) -> dict:
    x = (
        sessions.with_columns(pl.col("position").shift(1).fill_null(0.0).alias("prev_position"))
        .with_columns(
            (pl.col("position") - pl.col("prev_position")).abs().alias("turnover_units"),
            (pl.col("position") * pl.col("session_return")).alias("gross_session_return"),
        )
        .with_columns(
            (pl.col("turnover_units") * cost_bps / 10000.0).alias("cost_return")
        )
        .with_columns(
            (pl.col("gross_session_return") - pl.col("cost_return")).alias("net_session_return")
        )
    )

    daily = (
        x.group_by("date")
        .agg(
            ((pl.col("net_session_return") + 1.0).product() - 1.0).alias("net_return"),
            ((pl.col("gross_session_return") + 1.0).product() - 1.0).alias("gross_return"),
            pl.col("cost_return").sum().alias("cost_drag"),
            pl.col("turnover_units").sum().alias("turnover_units"),
            (pl.col("turnover_units") > 0).sum().alias("trade_events"),
        )
        .sort("date")
    )

    def metrics(frame: pl.DataFrame, ret_col: str) -> dict:
        vals = frame[ret_col].to_numpy()
        if len(vals) < 2:
            return {"n_days": len(vals)}
        mean = float(np.mean(vals))
        std = float(np.std(vals, ddof=1))
        sharpe = mean / std * math.sqrt(365.0) if std > 0 else 0.0
        downside = vals[vals < 0]
        downside_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0.0
        sortino = mean / downside_std * math.sqrt(365.0) if downside_std > 0 else 0.0
        equity = np.cumprod(1.0 + vals)
        peaks = np.maximum.accumulate(equity)
        dd = equity / peaks - 1.0
        max_dd = float(dd.min()) if len(dd) else 0.0
        total = float(equity[-1] - 1.0)
        cagr = float(equity[-1] ** (365.0 / len(vals)) - 1.0) if equity[-1] > 0 else -1.0
        calmar = cagr / abs(max_dd) if max_dd < 0 else 0.0
        positive = vals[vals > 0]
        negative = vals[vals < 0]
        pf = float(positive.sum() / abs(negative.sum())) if len(negative) and negative.sum() != 0 else None
        return {
            "n_days": int(len(vals)),
            "annualized_sharpe": sharpe,
            "sortino": sortino,
            "total_return": total,
            "cagr": cagr,
            "max_drawdown": max_dd,
            "calmar": calmar,
            "win_rate": float(np.mean(vals > 0)),
            "profit_factor": pf,
            "mean_daily_return": mean,
            "daily_volatility": std,
        }

    out = {
        "all": metrics(daily, "net_return"),
        "gross_all": metrics(daily, "gross_return"),
        "cost_drag_sum": float(daily["cost_drag"].sum()),
        "turnover_units": float(daily["turnover_units"].sum()),
        "trade_events": int(daily["trade_events"].sum()),
    }
    for year in (2025, 2026):
        part = daily.filter(pl.col("date").dt.year() == year)
        out[str(year)] = metrics(part, "net_return")
        out[f"gross_{year}"] = metrics(part, "gross_return")

    part_2026 = daily.filter(pl.col("date").dt.year() == 2026)
    monthly = (
        part_2026.with_columns(pl.col("date").dt.month().alias("month"))
        .group_by("month")
        .agg(((pl.col("net_return") + 1.0).product() - 1.0).alias("return"))
        .sort("return", descending=True)
    )
    if monthly.height:
        strongest_month = int(monthly.row(0, named=True)["month"])
        stripped = part_2026.filter(pl.col("date").dt.month() != strongest_month)
        out["2026_remove_strongest_month"] = {
            "removed_month": strongest_month,
            **metrics(stripped, "net_return"),
        }
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--start", default="2025-01-01T00:00:00Z")
    p.add_argument("--end-exclusive", default="2026-09-22T00:00:00Z")
    args = p.parse_args()

    df = load_prices(args.data, args.start, args.end_exclusive)
    data_summary = {
        "rows": df.height,
        "min_timestamp": df["timestamp"].min().isoformat(),
        "max_timestamp": df["timestamp"].max().isoformat(),
        "duplicates": int(df["timestamp"].is_duplicated().sum()),
        "timezone": str(df.schema["timestamp"]),
    }

    variants = {}
    base_sharpes = []
    for hour in (7, 8, 9):
        sessions = make_sessions(df, hour)
        variants[str(hour)] = {}
        for mult in (1.0, 2.0, 3.0):
            cost = 3.0 * mult
            result = run_variant(sessions, cost)
            variants[str(hour)][str(mult)] = result
            if mult == 1.0:
                base_sharpes.append(result["2026"]["annualized_sharpe"])

    canonical = variants["8"]["1.0"]
    dsr = compute_deflated_sharpe(
        canonical["2026"]["annualized_sharpe"],
        base_sharpes,
        n_obs_days=canonical["2026"]["n_days"],
    )
    payload = {
        "schema_version": 1,
        "strategy": "BTC 12h same-session Reversal/Reversal",
        "data": data_summary,
        "base_cost_per_turnover_unit_bps": 3.0,
        "variant_hours": [7, 8, 9],
        "variants": variants,
        "multiple_testing": {
            "strategy_trials": 3,
            "base_cost_2026_sharpes": base_sharpes,
            "dsr": dsr,
            "pbo": {"status": "N/A", "reason": "Only three pre-registered neighboring variants; no CPCV winner-selection exercise."},
        },
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
