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
from scipy import stats
from scipy.stats import spearmanr

from scripts.run_crypto_highvol_reversal import load_daily_range
from src.experiment import compute_deflated_sharpe

FORMATION_WEEKS = (10, 20, 25)
CAN = 20
LIQ_DAYS = 30
TOPN = 50
STRICT_TOPN = 30
MIN_XS = 15
COST = 10.0
DEV0 = date(2022, 1, 1)
DEV1 = date(2024, 1, 1)
OOS0 = date(2024, 1, 1)
OOS1 = date(2026, 1, 1)


def base_frame(d: pl.DataFrame) -> pl.DataFrame:
    return (
        d.sort(["symbol", "date"])
        .with_columns(
            pl.col("close").shift(1).over("symbol").alias("_prev_close"),
            pl.col("date").shift(1).over("symbol").alias("_prev_date"),
            pl.col("date").dt.weekday().alias("_weekday"),
            pl.col("qv").shift(1).rolling_sum(LIQ_DAYS).over("symbol").alias("_liq"),
            pl.col("date").shift(LIQ_DAYS).over("symbol").alias("_liq_anchor"),
            pl.col("open").shift(-1).over("symbol").alias("_next_open"),
            pl.col("date").shift(-1).over("symbol").alias("_next_date"),
        )
        .with_columns(
            pl.when(pl.col("date") - pl.col("_prev_date") == pl.duration(days=1))
            .then(pl.col("close") / pl.col("_prev_close") - 1.0)
            .otherwise(None)
            .alias("_ret"),
            (pl.col("_next_open") / pl.col("open") - 1.0).alias("fwd_ret"),
        )
    )


def feature_frame(b: pl.DataFrame, formation_weeks: int, topn: int = TOPN) -> pl.DataFrame:
    x = (
        b.sort(["symbol", "date"])
        .with_columns(
            pl.col("_ret")
            .shift(1)
            .rolling_mean(formation_weeks)
            .over(["symbol", "_weekday"])
            .alias("signal"),
            pl.col("date")
            .shift(formation_weeks)
            .over(["symbol", "_weekday"])
            .alias("_season_anchor"),
        )
        .filter(
            pl.col("signal").is_finite()
            & pl.col("_liq").is_finite()
            & pl.col("fwd_ret").is_finite()
            & (
                pl.col("_season_anchor")
                == pl.col("date") - pl.duration(days=7 * formation_weeks)
            )
            & (
                pl.col("_liq_anchor")
                == pl.col("date") - pl.duration(days=LIQ_DAYS)
            )
            & (pl.col("_next_date") == pl.col("date") + pl.duration(days=1))
        )
    )

    out: list[pl.DataFrame] = []
    for p in x.partition_by("date", maintain_order=True):
        liquid = p.sort("_liq", descending=True).head(topn)
        if liquid.height >= MIN_XS:
            out.append(
                liquid.select("date", "symbol", "signal", "fwd_ret", "_liq")
            )
    if not out:
        return pl.DataFrame()
    return pl.concat(out, how="vertical").sort(["date", "symbol"])


def hac_mean_test(a: np.ndarray, max_lag: int = 7) -> tuple[float, float]:
    if len(a) < 20:
        return 0.0, 1.0
    c = a - a.mean()
    n = len(a)
    lrv = float(np.dot(c, c) / n)
    max_lag = min(max_lag, n - 1)
    for lag in range(1, max_lag + 1):
        weight = 1.0 - lag / (max_lag + 1)
        lrv += 2.0 * weight * float(np.dot(c[lag:], c[:-lag]) / n)
    if not np.isfinite(lrv) or lrv <= 0:
        return 0.0, 1.0
    t = float(a.mean() / math.sqrt(lrv / n))
    return t, float(2.0 * stats.norm.sf(abs(t)))


def diagnostic(f: pl.DataFrame, start: date, end: date) -> dict:
    ics: list[float] = []
    spreads: list[float] = []
    counts: list[int] = []
    ff = f.filter((pl.col("date") >= start) & (pl.col("date") < end))
    for p in ff.partition_by("date", maintain_order=True):
        if p.height < MIN_XS:
            continue
        s = p["signal"].to_numpy()
        y = p["fwd_ret"].to_numpy()
        ic = float(spearmanr(s, y).statistic)
        if np.isfinite(ic):
            ics.append(ic)
        ix = np.argsort(s)
        k = max(2, len(ix) // 5)
        spreads.append(float(y[ix[-k:]].mean() - y[ix[:k]].mean()))
        counts.append(int(len(ix)))

    a = np.asarray(ics, dtype=float)
    mean_ic = float(a.mean()) if len(a) else 0.0
    sd_ic = float(a.std(ddof=1)) if len(a) > 1 else 0.0
    hac_t, hac_p = hac_mean_test(a)
    return {
        "n_days": int(len(a)),
        "mean_ic": mean_ic,
        "ic_ir": float(mean_ic / sd_ic) if sd_ic > 0 else 0.0,
        "hac_t": hac_t,
        "hac_p": hac_p,
        "high_minus_low_raw_mean": float(np.mean(spreads)) if spreads else 0.0,
        "mean_cross_section": float(np.mean(counts)) if counts else 0.0,
        "min_cross_section": int(min(counts)) if counts else 0,
    }


def portfolio(
    f: pl.DataFrame,
    start: date,
    end: date,
    exclude: set[str] | None = None,
) -> list[tuple[date, dict[str, float], float, dict[str, float]]]:
    ex = exclude or set()
    out = []
    ff = f.filter((pl.col("date") >= start) & (pl.col("date") < end))
    for p in ff.partition_by("date", maintain_order=True):
        rows = sorted(
            [
                r
                for r in p.iter_rows(named=True)
                if str(r["symbol"]) not in ex
                and np.isfinite(float(r["signal"]))
                and np.isfinite(float(r["fwd_ret"]))
            ],
            key=lambda r: float(r["signal"]),
        )
        if len(rows) < MIN_XS:
            continue
        k = max(2, len(rows) // 5)
        weights: dict[str, float] = {}
        gross = 0.0
        contribution: dict[str, float] = {}

        for r in rows[:k]:
            symbol = str(r["symbol"])
            w = -0.5 / k
            ret = float(r["fwd_ret"])
            weights[symbol] = w
            gross += w * ret
            contribution[symbol] = w * ret

        for r in rows[-k:]:
            symbol = str(r["symbol"])
            w = 0.5 / k
            ret = float(r["fwd_ret"])
            weights[symbol] = w
            gross += w * ret
            contribution[symbol] = w * ret

        out.append((p["date"][0], weights, gross, contribution))
    return out


def sim(rows, cost_bps_per_turnover: float) -> dict:
    prev: dict[str, float] = {}
    prev_date: date | None = None
    rr: list[tuple[date, float]] = []
    total_turnover = 0.0
    contribution: dict[str, float] = {}

    for d, weights, gross, contrib in rows:
        if prev_date is None:
            turnover = sum(abs(v) for v in weights.values())
        elif (d - prev_date).days == 1:
            turnover = sum(
                abs(weights.get(s, 0.0) - prev.get(s, 0.0))
                for s in (set(weights) | set(prev))
            )
        else:
            turnover = sum(abs(v) for v in prev.values()) + sum(
                abs(v) for v in weights.values()
            )

        total_turnover += turnover
        net = gross - turnover * cost_bps_per_turnover / 10_000.0
        rr.append((d, net))
        for symbol, value in contrib.items():
            contribution[symbol] = contribution.get(symbol, 0.0) + value

        prev = weights
        prev_date = d

    if not rr:
        return {
            "metrics": {
                "annualized_sharpe": 0.0,
                "total_return": 0.0,
                "max_drawdown": 0.0,
                "n_days": 0,
                "turnover": 0.0,
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

    by_year: dict[str, dict[str, float]] = {}
    for year in sorted({d.year for d, _ in rr}):
        q = np.asarray([r for d, r in rr if d.year == year], dtype=float)
        qs = float(np.std(q, ddof=1)) if len(q) > 1 else 0.0
        by_year[str(year)] = {
            "total_return": float(np.prod(1.0 + q) - 1.0),
            "sharpe": float(q.mean() / qs * math.sqrt(365.0)) if qs > 0 else 0.0,
            "n_days": int(len(q)),
        }

    return {
        "metrics": {
            "annualized_sharpe": float(a.mean() / sd * math.sqrt(365.0))
            if sd > 0
            else 0.0,
            "total_return": float(eq[-1] - 1.0),
            "max_drawdown": float(dd.min()),
            "n_days": int(len(a)),
            "turnover": float(total_turnover),
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()

    # Development-first loading preserves exploratory OOS unless the
    # preregistered diagnostic and economic gates pass.
    d_dev = load_daily_range(args.root, 2021, 4, 1, 2024, 1, 3)
    b_dev = base_frame(d_dev)
    fs_dev = {w: feature_frame(b_dev, w) for w in FORMATION_WEEKS}

    diagnostics_dev = {
        w: diagnostic(fs_dev[w], DEV0, DEV1) for w in FORMATION_WEEKS
    }
    development = {
        w: sim(portfolio(fs_dev[w], DEV0, DEV1), COST)
        for w in FORMATION_WEEKS
    }

    cd = diagnostics_dev[CAN]
    cm = development[CAN]["metrics"]
    dev_years_ok = all(
        development[CAN]["by_year"].get(str(y), {}).get("total_return", -1.0)
        >= 0.0
        for y in (2022, 2023)
    )
    development_gate = (
        cd["mean_ic"] >= 0.02
        and cd["hac_p"] < 0.05
        and cd["high_minus_low_raw_mean"] > 0.0
        and cm["annualized_sharpe"] > 0.70
        and cm["total_return"] > 0.0
        and dev_years_ok
        and sum(
            development[w]["metrics"]["total_return"] > 0.0
            for w in FORMATION_WEEKS
        )
        >= 2
    )

    out = {
        "schema_version": 1,
        "run_id": "20260928-xs-weekday-seasonality-20w",
        "strategy_family": "same_weekday_cross_sectional_seasonality",
        "research_archetype": "cross_sectional_calendar_factor",
        "development_universe_symbols": int(d_dev["symbol"].n_unique()),
        "development_diagnostics": {
            str(w): diagnostics_dev[w] for w in FORMATION_WEEKS
        },
        "development": {
            str(w): compact(development[w]) for w in FORMATION_WEEKS
        },
        "development_gate_passed": development_gate,
        "oos_consumed": False,
        "trial_accounting": {
            "previous_parameter_trials": 168,
            "new_parameter_trials": 3,
            "cumulative_parameter_trials": 171,
        },
    }

    if not development_gate:
        out.update(
            classification="REJECT",
            success_gate_candidate=False,
            multiple_testing={
                "family_dsr": None,
                "global_dsr": None,
                "pbo": "N/A: development gate failed before OOS.",
            },
            conclusion=(
                "REJECT. Preregistered diagnostic/economic development gate failed; "
                "2024-2025 exploratory OOS was not consumed."
            ),
        )
        print(json.dumps(out, indent=2, default=str))
        return

    d_oos = load_daily_range(args.root, 2023, 4, 1, 2026, 1, 3)
    b_oos = base_frame(d_oos)
    fs_oos = {w: feature_frame(b_oos, w) for w in FORMATION_WEEKS}

    results: dict[str, dict[str, dict]] = {}
    sharpes: list[float] = []
    for w in FORMATION_WEEKS:
        rows = portfolio(fs_oos[w], OOS0, OOS1)
        results[str(w)] = {
            str(mult): sim(rows, COST * mult) for mult in (1, 2, 3)
        }
        sharpes.append(results[str(w)]["1"]["metrics"]["annualized_sharpe"])

    base = results[str(CAN)]["1"]
    bm = base["metrics"]
    oos_diag = diagnostic(fs_oos[CAN], OOS0, OOS1)

    ex_majors = sim(
        portfolio(fs_oos[CAN], OOS0, OOS1, exclude={"BTCUSDT", "ETHUSDT"}),
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
                fs_oos[CAN],
                OOS0,
                OOS1,
                exclude={strongest},
            ),
            COST,
        )
        if strongest
        else None
    )

    strict_frame = feature_frame(b_oos, CAN, topn=STRICT_TOPN)
    strict_liquidity = sim(portfolio(strict_frame, OOS0, OOS1), COST)

    years_ok = all(
        base["by_year"].get(str(y), {}).get("total_return", -1.0) >= 0.0
        for y in (2024, 2025)
    )
    stable = (
        sum(
            results[str(w)]["1"]["metrics"]["total_return"] > 0.0
            for w in FORMATION_WEEKS
        )
        >= 2
    )

    family_dsr = compute_deflated_sharpe(
        bm["annualized_sharpe"],
        sharpes,
        n_obs_days=max(bm["n_days"], 1),
    )
    global_dsr = compute_deflated_sharpe(
        bm["annualized_sharpe"],
        sharpes + [0.0] * 168,
        n_obs_days=max(bm["n_days"], 1),
    )

    qual = (
        bm["annualized_sharpe"] > 1.0
        and oos_diag["mean_ic"] >= 0.02
        and results[str(CAN)]["2"]["metrics"]["total_return"] > 0.0
        and years_ok
        and bm["max_drawdown"] > -0.35
        and stable
        and strict_liquidity["metrics"]["total_return"] > 0.0
        and ex_majors["metrics"]["total_return"] > 0.0
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
        oos_diagnostics=oos_diag,
        oos_results={
            w: {cost: compact(v) for cost, v in costs.items()}
            for w, costs in results.items()
        },
        strict_top30_liquidity=compact(strict_liquidity),
        exclude_btc_eth=compact(ex_majors),
        strongest_asset=strongest,
        exclude_strongest=compact(ex_strongest) if ex_strongest else None,
        multiple_testing={
            "family_dsr": family_dsr,
            "global_171_trial_proxy": global_dsr,
            "pbo": "N/A: three fixed preregistered formation windows; no parameter winner was selected post hoc.",
        },
        success_gate_candidate=qual,
        classification=(
            "PROMOTE_TO_MANUAL_CONFIRMATION" if qual else "REJECT"
        ),
        conclusion=(
            "PROMOTE_TO_MANUAL_CONFIRMATION. All preregistered exploratory success gates passed; sealed confirmation remains untouched."
            if qual
            else "REJECT. Exploratory OOS and/or robustness/multiple-testing gate failed."
        ),
    )

    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
