#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats
from scipy.stats import spearmanr

from src.experiment import compute_deflated_sharpe

WINDOWS = (5, 7, 14)
CAN = 7
THETA = 0.1
DELTA = 0.7
COST = 10.0
TOPN = 50
MIN_XS = 10
DEV0 = date(2022, 1, 1)
DEV1 = date(2024, 1, 1)
OOS0 = date(2024, 1, 1)
OOS1 = date(2026, 1, 1)
RESULT_PATH = Path("run_log/crypto_research/runs/20260928-salience-theory-weekly-result.json")


def emit(out: dict) -> None:
    payload = json.dumps(out, indent=2, default=str)
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(payload + "\n", encoding="utf-8")
    print(payload)


def load_daily(root: Path) -> pl.DataFrame:
    pattern = str(root / "symbol=*" / "year=*" / "month=*" / "data.parquet")
    d = (
        pl.scan_parquet(pattern, hive_partitioning=True)
        .filter(
            pl.col("symbol").str.ends_with("USDT")
            & (pl.col("symbol") != "BTCDOMUSDT")
            & (pl.col("timestamp") >= pl.datetime(2020, 6, 1, time_zone="UTC"))
            & (pl.col("timestamp") < pl.datetime(2026, 1, 9, time_zone="UTC"))
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
        .collect()
    )
    b = (
        d.with_columns(
            pl.col("close").shift(1).over("symbol").alias("_pc"),
            pl.col("date").shift(1).over("symbol").alias("_pd"),
            pl.col("qv").shift(1).rolling_sum(30).over("symbol").alias("_liq"),
            pl.col("date").shift(30).over("symbol").alias("_a30"),
        )
        .with_columns(
            pl.when(pl.col("date") - pl.col("_pd") == pl.duration(days=1))
            .then(pl.col("close") / pl.col("_pc") - 1.0)
            .otherwise(None)
            .alias("ret")
        )
    )
    market = b.group_by("date").agg(pl.col("ret").mean().alias("mkt_ret"))
    return b.join(market, on="date", how="left").sort(["symbol", "date"])


def salience_signal(asset_ret: np.ndarray, market_ret: np.ndarray) -> float:
    sigma = np.abs(asset_ret - market_ret) / (
        np.abs(asset_ret) + np.abs(market_ret) + THETA
    )
    order = np.argsort(-sigma, kind="mergesort")
    ranks = np.empty(len(order), dtype=int)
    ranks[order] = np.arange(1, len(order) + 1)
    raw = DELTA ** ranks
    salient_mean = float(np.sum(raw * asset_ret) / np.sum(raw))
    equal_mean = float(np.mean(asset_ret))
    st = salient_mean - equal_mean
    return -st


def feature_frame(base: pl.DataFrame, window: int) -> pl.DataFrame:
    rows = []
    for p in base.partition_by("symbol", maintain_order=True):
        p = p.sort("date")
        dates = p["date"].to_list()
        opens = p["open"].to_numpy().astype(float)
        rets = p["ret"].to_numpy().astype(float)
        mkt = p["mkt_ret"].to_numpy().astype(float)
        liq = p["_liq"].to_numpy().astype(float)
        a30 = p["_a30"].to_list()
        sym = str(p["symbol"][0])
        for i, d in enumerate(dates):
            if d.weekday() != 0 or i < max(window, 30) or i + 8 >= len(dates):
                continue
            if dates[i - window] != d - timedelta(days=window):
                continue
            if a30[i] != d - timedelta(days=30):
                continue
            if dates[i + 7] != d + timedelta(days=7):
                continue
            if dates[i + 1] != d + timedelta(days=1) or dates[i + 8] != d + timedelta(days=8):
                continue
            ar = rets[i - window : i]
            mr = mkt[i - window : i]
            if not np.isfinite(ar).all() or not np.isfinite(mr).all():
                continue
            if not np.isfinite(liq[i]) or opens[i] <= 0 or opens[i + 7] <= 0:
                continue
            sig = salience_signal(ar, mr)
            fwd = float(opens[i + 7] / opens[i] - 1.0)
            delay = float(opens[i + 8] / opens[i + 1] - 1.0)
            if np.isfinite(sig) and np.isfinite(fwd) and np.isfinite(delay):
                rows.append((d, sym, sig, float(liq[i]), fwd, delay))

    if not rows:
        return pl.DataFrame()
    x = pl.DataFrame(
        rows,
        schema=["date", "symbol", "signal", "_liq", "fwd_ret", "delay_ret"],
        orient="row",
    )
    out = []
    for p in x.partition_by("date", maintain_order=True):
        p = p.sort("_liq", descending=True).head(TOPN)
        if p.height >= MIN_XS:
            out.append(p.select("date", "symbol", "signal", "fwd_ret", "delay_ret"))
    return pl.concat(out, how="vertical").sort(["date", "symbol"]) if out else pl.DataFrame()


def hac(a: np.ndarray, max_lag: int = 4) -> tuple[float, float]:
    if len(a) < 12:
        return 0.0, 1.0
    c = a - a.mean()
    n = len(a)
    lrv = float(np.dot(c, c) / n)
    for lag in range(1, min(max_lag, n - 1) + 1):
        lrv += 2 * (1 - lag / (max_lag + 1)) * float(np.dot(c[lag:], c[:-lag]) / n)
    if lrv <= 0:
        return 0.0, 1.0
    t = float(a.mean() / math.sqrt(lrv / n))
    return t, float(2 * stats.norm.sf(abs(t)))


def diagnostic(f: pl.DataFrame, start: date, end: date) -> dict:
    ics = []
    spreads = []
    for p in f.filter((pl.col("date") >= start) & (pl.col("date") < end)).partition_by(
        "date", maintain_order=True
    ):
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
    a = np.asarray(ics, dtype=float)
    m = float(a.mean()) if len(a) else 0.0
    sd = float(a.std(ddof=1)) if len(a) > 1 else 0.0
    t, pval = hac(a)
    return {
        "n_weeks": len(a),
        "mean_ic": m,
        "ic_ir": m / sd if sd > 0 else 0.0,
        "hac_t": t,
        "hac_p": pval,
        "high_minus_low": float(np.mean(spreads)) if spreads else 0.0,
    }


def portfolio(
    f: pl.DataFrame,
    start: date,
    end: date,
    retcol: str = "fwd_ret",
    exclude: set[str] | None = None,
):
    ex = exclude or set()
    out = []
    for p in f.filter((pl.col("date") >= start) & (pl.col("date") < end)).partition_by(
        "date", maintain_order=True
    ):
        rows = sorted(
            [r for r in p.iter_rows(named=True) if str(r["symbol"]) not in ex],
            key=lambda z: float(z["signal"]),
        )
        if len(rows) < MIN_XS:
            continue
        k = max(2, len(rows) // 5)
        w = {}
        gross = 0.0
        contrib = {}
        for r in rows[:k]:
            s = str(r["symbol"])
            ww = -0.5 / k
            rr = float(r[retcol])
            w[s] = ww
            gross += ww * rr
            contrib[s] = ww * rr
        for r in rows[-k:]:
            s = str(r["symbol"])
            ww = 0.5 / k
            rr = float(r[retcol])
            w[s] = ww
            gross += ww * rr
            contrib[s] = ww * rr
        out.append((p["date"][0], w, gross, contrib))
    return out


def sim(rows, cost_bps: float) -> dict:
    prev = {}
    rr = []
    cont = {}
    turnover = 0.0
    for d, w, gross, cc in rows:
        tr = sum(abs(w.get(s, 0.0) - prev.get(s, 0.0)) for s in set(w) | set(prev))
        turnover += tr
        rr.append((d, gross - tr * cost_bps / 10000.0))
        for s, v in cc.items():
            cont[s] = cont.get(s, 0.0) + v
        prev = w
    if not rr:
        return {
            "metrics": {"annualized_sharpe": 0.0, "total_return": 0.0, "max_drawdown": 0.0, "n_weeks": 0},
            "by_year": {},
            "asset_contribution": {},
        }
    a = np.array([r for _, r in rr], dtype=float)
    eq = np.cumprod(1.0 + a)
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    sd = float(np.std(a, ddof=1))
    by_year = {}
    for y in sorted({d.year for d, _ in rr}):
        q = np.array([r for d, r in rr if d.year == y], dtype=float)
        qs = float(np.std(q, ddof=1)) if len(q) > 1 else 0.0
        by_year[str(y)] = {
            "total_return": float(np.prod(1.0 + q) - 1.0),
            "sharpe": float(np.mean(q) / qs * math.sqrt(52)) if qs > 0 else 0.0,
        }
    return {
        "metrics": {
            "annualized_sharpe": float(np.mean(a) / sd * math.sqrt(52)) if sd > 0 else 0.0,
            "total_return": float(eq[-1] - 1.0),
            "max_drawdown": float(dd.min()),
            "n_weeks": len(a),
            "turnover": turnover,
        },
        "by_year": by_year,
        "asset_contribution": cont,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()

    base = load_daily(args.root)
    frames = {w: feature_frame(base, w) for w in WINDOWS}
    dev_diag = {w: diagnostic(frames[w], DEV0, DEV1) for w in WINDOWS}
    dev = {w: sim(portfolio(frames[w], DEV0, DEV1), COST) for w in WINDOWS}

    cd = dev_diag[CAN]
    cm = dev[CAN]["metrics"]
    gate = (
        cd["mean_ic"] > 0.02
        and cd["hac_p"] < 0.05
        and cd["high_minus_low"] > 0
        and cm["annualized_sharpe"] > 0.70
        and cm["total_return"] > 0
        and sum(dev[w]["metrics"]["total_return"] > 0 for w in WINDOWS) >= 2
    )

    out = {
        "schema_version": 1,
        "run_id": "20260928-salience-theory-weekly",
        "strategy_family": "salience_theory",
        "research_archetype": "cross_sectional_behavioral_factor",
        "universe_symbols": base["symbol"].n_unique(),
        "development_diagnostics": {str(w): dev_diag[w] for w in WINDOWS},
        "development": {str(w): dev[w] for w in WINDOWS},
        "development_gate_passed": gate,
        "oos_consumed": False,
        "trial_accounting": {
            "previous_parameter_trials": 103,
            "new_parameter_trials": 3,
            "cumulative_parameter_trials": 106,
        },
    }
    if not gate:
        out.update(
            classification="REJECT",
            success_gate_candidate=False,
            conclusion="Development gate failed; OOS not consumed.",
        )
        emit(out)
        return

    results = {}
    sharpes = []
    for w in WINDOWS:
        rows = portfolio(frames[w], OOS0, OOS1)
        results[str(w)] = {str(m): sim(rows, COST * m) for m in (1, 2, 3)}
        sharpes.append(results[str(w)]["1"]["metrics"]["annualized_sharpe"])

    base_oos = results[str(CAN)]["1"]
    bm = base_oos["metrics"]
    oos_diag = diagnostic(frames[CAN], OOS0, OOS1)
    ex = sim(portfolio(frames[CAN], OOS0, OOS1, exclude={"BTCUSDT", "ETHUSDT"}), COST)
    strongest = (
        max(base_oos["asset_contribution"], key=lambda s: abs(base_oos["asset_contribution"][s]))
        if base_oos["asset_contribution"]
        else None
    )
    exs = (
        sim(portfolio(frames[CAN], OOS0, OOS1, exclude={strongest}), COST)
        if strongest
        else None
    )
    delayed = sim(portfolio(frames[CAN], OOS0, OOS1, retcol="delay_ret"), COST)
    years_ok = all(
        base_oos["by_year"].get(str(y), {}).get("total_return", -1.0) >= 0 for y in (2024, 2025)
    )
    stable = sum(results[str(w)]["1"]["metrics"]["total_return"] > 0 for w in WINDOWS) >= 2
    dsr = compute_deflated_sharpe(
        bm["annualized_sharpe"], sharpes, n_obs_days=max(bm["n_weeks"] * 7, 1)
    )
    global_dsr = compute_deflated_sharpe(
        bm["annualized_sharpe"], sharpes + [0.0] * 103, n_obs_days=max(bm["n_weeks"] * 7, 1)
    )
    qual = (
        bm["annualized_sharpe"] > 1.0
        and oos_diag["mean_ic"] > 0.02
        and results[str(CAN)]["2"]["metrics"]["total_return"] > 0
        and stable
        and years_ok
        and bm["max_drawdown"] > -0.35
        and ex["metrics"]["total_return"] > 0
        and delayed["metrics"]["total_return"] > 0
        and (exs is None or exs["metrics"]["total_return"] > 0)
    )
    out.update(
        oos_consumed=True,
        oos_diagnostics=oos_diag,
        oos_results=results,
        exclude_btc_eth=ex,
        strongest_asset=strongest,
        exclude_strongest=exs,
        delay_one_day=delayed,
        multiple_testing={
            "family_dsr": dsr,
            "global_106_trial_proxy": global_dsr,
            "pbo": "N/A: three preregistered estimation windows.",
        },
        success_gate_candidate=qual,
        classification="EXPLORATORY_PASS" if qual else "REJECT",
    )
    emit(out)


if __name__ == "__main__":
    main()
