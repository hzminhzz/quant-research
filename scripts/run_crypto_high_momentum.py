#!/usr/bin/env python3
"""Pre-registered cross-sectional crypto factor research runner."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats

from src.experiment import compute_deflated_sharpe

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


def build_targets(frame: pl.DataFrame, start: datetime, end: datetime, exclude: set[str] | None = None, delay_hours: int = 0) -> dict[datetime, dict[str, float]]:
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
        k = max(1, math.ceil(len(rows) * 0.20))
        weights: dict[str, float] = {}
        for sym, _ in rows[-k:]:
            weights[sym] = 0.5 / k
        for sym, _ in rows[:k]:
            weights[sym] = -0.5 / k
        targets[part["timestamp"][0] + timedelta(hours=delay_hours)] = weights
    return targets


def equity_metrics(points: list[tuple[datetime, float]]) -> dict:
    if len(points) < 3:
        return {"n_days": len(points), "annualized_sharpe": None}
    equity = np.asarray([v for _, v in points], dtype=float)
    returns = equity[1:] / equity[:-1] - 1.0
    mean = float(np.mean(returns))
    std = float(np.std(returns, ddof=1))
    sharpe = mean / std * math.sqrt(365.0) if std > 0 else 0.0
    downside = returns[returns < 0]
    downside_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0.0
    sortino = mean / downside_std * math.sqrt(365.0) if downside_std > 0 else 0.0
    peaks = np.maximum.accumulate(equity)
    drawdowns = equity / peaks - 1.0
    return {
        "n_days": int(len(returns)),
        "annualized_sharpe": sharpe,
        "sortino": sortino,
        "total_return": float(equity[-1] / equity[0] - 1.0),
        "max_drawdown": float(np.min(drawdowns)),
        "mean_daily_return": mean,
        "daily_volatility": std,
    }


def simulate(prices: pl.DataFrame, targets: dict[datetime, dict[str, float]], cost_bps: float, start: datetime, end: datetime) -> dict:
    panel = prices.filter(
        (pl.col("timestamp") >= start) & (pl.col("timestamp") < end)
    ).select("timestamp", "symbol", "open").sort(["timestamp", "symbol"])
    qty: dict[str, float] = {}
    cash = 1.0
    last_price: dict[str, float] = {}
    prev_price: dict[str, float] = {}
    contribution: dict[str, float] = {}
    daily: list[tuple[datetime, float]] = []
    turnover = 0.0
    costs = 0.0
    rebalances = 0
    for part in panel.partition_by("timestamp", maintain_order=True):
        ts = part["timestamp"][0]
        current = {r["symbol"]: float(r["open"]) for r in part.iter_rows(named=True)}
        for sym, px in current.items():
            if sym in prev_price and sym in qty:
                contribution[sym] = contribution.get(sym, 0.0) + qty[sym] * (px - prev_price[sym])
            last_price[sym] = px
        if ts in targets:
            equity_before = cash + sum(q * last_price[s] for s, q in qty.items() if s in last_price)
            desired = targets[ts]
            trades: list[tuple[str, float, float]] = []
            for sym in sorted(set(qty) | set(desired)):
                px = current.get(sym)
                if px is None or px <= 0:
                    if abs(qty.get(sym, 0.0)) > 1e-12:
                        raise ValueError(f"missing execution price for held asset {sym} at {ts}")
                    continue
                current_notional = qty.get(sym, 0.0) * px
                target_notional = desired.get(sym, 0.0) * equity_before
                delta = target_notional - current_notional
                if abs(delta) > 1e-12:
                    trades.append((sym, delta, px))
            cost = sum(abs(delta) for _, delta, _ in trades) * cost_bps / 10000.0
            cash -= cost
            costs += cost
            turnover += sum(abs(delta) for _, delta, _ in trades)
            for sym, delta, px in trades:
                cash -= delta
                qty[sym] = qty.get(sym, 0.0) + delta / px
                contribution[sym] = contribution.get(sym, 0.0) - abs(delta) * cost_bps / 10000.0
                if abs(qty[sym]) < 1e-12:
                    qty.pop(sym, None)
            rebalances += 1
        equity_now = cash + sum(q * last_price[s] for s, q in qty.items() if s in last_price)
        if ts.hour == 0:
            daily.append((ts, equity_now))
        prev_price.update(current)
    overall = equity_metrics(daily)
    by_year = {
        str(year): equity_metrics([(t, v) for t, v in daily if t.year == year])
        for year in (2024, 2025)
    }
    return {
        "metrics": overall,
        "by_year": by_year,
        "rebalances": rebalances,
        "turnover_on_initial_equity": turnover,
        "cost_on_initial_equity": costs,
        "asset_contribution": dict(sorted(contribution.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    args = parser.parse_args()
    df = pl.read_parquet(args.data).sort(["symbol", "timestamp"])
    integrity = validate_panel(df)
    # Do not construct factor outcomes from the primary OOS until the fixed
    # development gate passes. One extra week is needed only to label the
    # final pre-2024 development rebalance.
    dev_source = df.filter(pl.col("timestamp") < datetime(2024, 1, 8, tzinfo=timezone.utc))
    frames = {w: make_weekly_factor_frame(dev_source, w) for w in WINDOWS}
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
    if not gate:
        payload["classification"] = "REJECT"
        payload["conclusion"] = "Development factor diagnostics failed; primary OOS was not consumed."
        print(json.dumps(payload, indent=2, default=str))
        return 0

    # The fixed development gate passed. Only now construct and consume the
    # pre-registered 2024-2025 OOS portfolio evidence.
    full_frames = {w: make_weekly_factor_frame(df, w) for w in WINDOWS}
    results: dict[str, dict[str, dict]] = {}
    base_sharpes: list[float] = []
    for window in WINDOWS:
        targets = build_targets(full_frames[window], OOS_START, OOS_END)
        results[str(window)] = {}
        for mult in (1.0, 2.0, 3.0):
            results[str(window)][str(mult)] = simulate(
                df, targets, BASE_COST_BPS * mult, OOS_START, OOS_END
            )
        base_sharpes.append(float(results[str(window)]["1.0"]["metrics"]["annualized_sharpe"]))

    canonical_result = results["168"]["1.0"]
    contributions = canonical_result["asset_contribution"]
    strongest = max(contributions, key=contributions.get) if contributions else None
    ablations: dict[str, object] = {}
    if strongest is not None:
        ablations["exclude_strongest_asset"] = {
            "asset": strongest,
            "result": simulate(
                df,
                build_targets(full_frames[168], OOS_START, OOS_END, exclude={strongest}),
                BASE_COST_BPS,
                OOS_START,
                OOS_END,
            ),
        }
    ablations["exclude_btc_eth"] = simulate(
        df,
        build_targets(full_frames[168], OOS_START, OOS_END, exclude={"BTCUSDT", "ETHUSDT"}),
        BASE_COST_BPS,
        OOS_START,
        OOS_END,
    )
    ablations["delay_one_hour"] = simulate(
        df,
        build_targets(full_frames[168], OOS_START, OOS_END, delay_hours=1),
        BASE_COST_BPS,
        OOS_START,
        OOS_END,
    )
    dsr = compute_deflated_sharpe(
        float(canonical_result["metrics"]["annualized_sharpe"]),
        base_sharpes,
        n_obs_days=int(canonical_result["metrics"]["n_days"]),
    )
    base = canonical_result["metrics"]
    two_x = results["168"]["2.0"]["metrics"]
    neighbor_positive = sum(results[str(w)]["1.0"]["metrics"]["total_return"] > 0 for w in WINDOWS)
    breadth_ok = (
        ablations["exclude_btc_eth"]["metrics"]["total_return"] > 0
        and ablations["delay_one_hour"]["metrics"]["total_return"] > 0
        and (
            strongest is None
            or ablations["exclude_strongest_asset"]["result"]["metrics"]["total_return"] > 0
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
            "current_family_base_cost_sharpes": base_sharpes,
            "dsr": dsr,
            "pbo": {"status": "N/A", "reason": "Only three pre-registered windows; no winner-selection CPCV."},
        },
        "success_gate_candidate": qualifies,
        "classification": "EXPLORATORY_PASS" if qualifies else "REJECT",
        "conclusion": (
            "Candidate clears the pre-registered exploratory gates; funding omission and repeated-search contamination still require manual confirmation."
            if qualifies else
            "Candidate failed one or more pre-registered OOS or robustness requirements."
        ),
    })
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
