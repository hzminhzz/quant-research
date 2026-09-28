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

from src.experiment import compute_deflated_sharpe

LOOKBACKS = (12, 24, 48)
CAN = 24
LIQ = 720
TOPN = 50
MIN_XS = 10
COST = 10.0
DEV0 = date(2022, 1, 1)
DEV1 = date(2024, 1, 1)
OOS0 = date(2024, 1, 1)
OOS1 = date(2026, 1, 1)


def load_panel(root: Path) -> tuple[list[str], pl.DataFrame]:
    manifest = json.load(open(root / "dataset_manifest.json"))
    sy = sorted(
        s for s, v in manifest["symbol_summaries"].items()
        if s.endswith("USDT") and s != "BTCDOMUSDT" and v["first_timestamp"] <= "2021-12-31T23:59:59+00:00"
    )
    pattern = str(root / "symbol=*" / "year=*" / "month=*" / "data.parquet")
    h = (
        pl.scan_parquet(pattern, hive_partitioning=True)
        .filter(
            pl.col("symbol").is_in(sy)
            & (pl.col("timestamp") >= pl.datetime(2021, 11, 1, time_zone="UTC"))
            & (pl.col("timestamp") < pl.datetime(2026, 1, 2, time_zone="UTC"))
        )
        .select("timestamp", "symbol", "open", "close", "quote_volume")
        .sort(["symbol", "timestamp"])
        .collect(engine="streaming")
    )
    return sy, h


def feature_frame(h: pl.DataFrame, w: int) -> pl.DataFrame:
    x = (
        h.sort(["symbol", "timestamp"])
        .with_columns(
            pl.col("close").shift(1).over("symbol").alias("_pc"),
            pl.col("timestamp").shift(1).over("symbol").alias("_pts"),
        )
        .with_columns(
            pl.when(pl.col("timestamp") - pl.col("_pts") == pl.duration(hours=1))
            .then(pl.col("close") / pl.col("_pc") - 1.0)
            .otherwise(None)
            .alias("_ret1")
        )
        .with_columns(
            (-pl.col("_ret1").shift(1).rolling_max(w).over("symbol")).alias("signal"),
            pl.col("quote_volume").shift(1).rolling_sum(LIQ).over("symbol").alias("_liq"),
            pl.col("timestamp").shift(max(w, LIQ)).over("symbol").alias("_anchor"),
            pl.col("open").shift(-4).over("symbol").alias("_exit"),
            pl.col("timestamp").shift(-4).over("symbol").alias("_exit_ts"),
            pl.col("open").shift(-8).over("symbol").alias("_delay_exit"),
            pl.col("timestamp").shift(-8).over("symbol").alias("_delay_exit_ts"),
            pl.col("open").shift(-4).over("symbol").alias("_delay_entry"),
            pl.col("timestamp").shift(-4).over("symbol").alias("_delay_entry_ts"),
        )
        .with_columns(
            (pl.col("_exit") / pl.col("open") - 1.0).alias("fwd_ret"),
            (pl.col("_delay_exit") / pl.col("_delay_entry") - 1.0).alias("delay_ret"),
        )
        .filter(
            (pl.col("timestamp").dt.hour() % 4 == 0)
            & pl.col("signal").is_finite()
            & pl.col("_liq").is_finite()
            & (pl.col("_anchor") == pl.col("timestamp") - pl.duration(hours=max(w, LIQ)))
            & (pl.col("_exit_ts") == pl.col("timestamp") + pl.duration(hours=4))
            & (pl.col("_delay_entry_ts") == pl.col("timestamp") + pl.duration(hours=4))
            & (pl.col("_delay_exit_ts") == pl.col("timestamp") + pl.duration(hours=8))
        )
    )
    return (
        x.with_columns(
            pl.col("_liq").rank(method="ordinal", descending=True).over("timestamp").alias("_liq_rank"),
            pl.len().over("timestamp").alias("_n"),
        )
        .filter((pl.col("_n") >= MIN_XS) & (pl.col("_liq_rank") <= TOPN))
        .select("timestamp", "symbol", "signal", "fwd_ret", "delay_ret")
        .sort(["timestamp", "symbol"])
    )


def hac(a: np.ndarray, max_lag: int = 6) -> tuple[float, float]:
    if len(a) < 20:
        return 0.0, 1.0
    c = a - a.mean()
    n = len(a)
    lrv = float(np.dot(c, c) / n)
    for lag in range(1, min(max_lag, n - 1) + 1):
        lrv += 2.0 * (1.0 - lag / (max_lag + 1.0)) * float(np.dot(c[lag:], c[:-lag]) / n)
    if lrv <= 0:
        return 0.0, 1.0
    t = float(a.mean() / math.sqrt(lrv / n))
    return t, float(2.0 * stats.norm.sf(abs(t)))


def diagnostic(f: pl.DataFrame, start: date, end: date) -> dict:
    ics = []
    spreads = []
    ff = f.filter((pl.col("timestamp").dt.date() >= start) & (pl.col("timestamp").dt.date() < end))
    for p in ff.partition_by("timestamp", maintain_order=True):
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
        "n_slots": int(len(a)),
        "mean_ic": m,
        "ic_ir": m / sd if sd > 0 else 0.0,
        "hac_t": t,
        "hac_p": pval,
        "low_max_minus_high_max": float(np.mean(spreads)) if spreads else 0.0,
    }


def portfolio(f: pl.DataFrame, start: date, end: date, retcol: str = "fwd_ret", exclude: set[str] | None = None):
    ex = exclude or set()
    out = []
    ff = f.filter((pl.col("timestamp").dt.date() >= start) & (pl.col("timestamp").dt.date() < end))
    for p in ff.partition_by("timestamp", maintain_order=True):
        rows = sorted(
            [r for r in p.iter_rows(named=True) if str(r["symbol"]) not in ex],
            key=lambda r: float(r["signal"]),
        )
        if len(rows) < MIN_XS:
            continue
        k = max(2, len(rows) // 5)
        weights = {}
        gross = 0.0
        contrib = {}
        for r in rows[:k]:
            s = str(r["symbol"])
            ww = -0.5 / k
            rr = float(r[retcol])
            weights[s] = ww
            gross += ww * rr
            contrib[s] = ww * rr
        for r in rows[-k:]:
            s = str(r["symbol"])
            ww = 0.5 / k
            rr = float(r[retcol])
            weights[s] = ww
            gross += ww * rr
            contrib[s] = ww * rr
        out.append((p["timestamp"][0], weights, gross, contrib))
    return out


def sim(rows, cost_bps: float) -> dict:
    prev = {}
    slots = []
    cont = {}
    turnover = 0.0
    for ts, w, gross, cc in rows:
        tr = sum(abs(w.get(s, 0.0) - prev.get(s, 0.0)) for s in set(w) | set(prev))
        turnover += tr
        net = gross - tr * cost_bps / 10000.0
        slots.append((ts, net))
        for s, v in cc.items():
            cont[s] = cont.get(s, 0.0) + v
        prev = w
    if not slots:
        return {"metrics": {"annualized_sharpe": 0.0, "total_return": 0.0, "max_drawdown": 0.0, "n_days": 0, "n_slots": 0, "turnover": 0.0}, "by_year": {}, "asset_contribution": {}}

    daily = {}
    for ts, r in slots:
        daily.setdefault(ts.date(), []).append(r)
    dr = [(d, float(np.prod(1.0 + np.asarray(rs)) - 1.0)) for d, rs in sorted(daily.items())]
    a = np.asarray([r for _, r in dr], dtype=float)
    eq = np.cumprod(1.0 + a)
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    sd = float(np.std(a, ddof=1))
    by_year = {}
    for y in sorted({d.year for d, _ in dr}):
        q = np.asarray([r for d, r in dr if d.year == y], dtype=float)
        qs = float(np.std(q, ddof=1)) if len(q) > 1 else 0.0
        by_year[str(y)] = {
            "total_return": float(np.prod(1.0 + q) - 1.0),
            "sharpe": float(q.mean() / qs * math.sqrt(365.0)) if qs > 0 else 0.0,
        }
    return {
        "metrics": {
            "annualized_sharpe": float(a.mean() / sd * math.sqrt(365.0)) if sd > 0 else 0.0,
            "total_return": float(eq[-1] - 1.0),
            "max_drawdown": float(dd.min()),
            "n_days": int(len(a)),
            "n_slots": int(len(slots)),
            "turnover": float(turnover),
        },
        "by_year": by_year,
        "asset_contribution": cont,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()

    sy, h = load_panel(args.root)
    fs = {w: feature_frame(h, w) for w in LOOKBACKS}
    di = {w: diagnostic(fs[w], DEV0, DEV1) for w in LOOKBACKS}
    dev = {w: sim(portfolio(fs[w], DEV0, DEV1), COST) for w in LOOKBACKS}

    cd = di[CAN]
    cm = dev[CAN]["metrics"]
    gate = (
        cd["mean_ic"] > 0.02
        and cd["hac_p"] < 0.05
        and cd["low_max_minus_high_max"] > 0
        and cm["annualized_sharpe"] > 0.70
        and cm["total_return"] > 0
        and sum(dev[w]["metrics"]["total_return"] > 0 for w in LOOKBACKS) >= 2
    )

    out = {
        "schema_version": 1,
        "run_id": "20260928-intraday-max-lottery-4h",
        "strategy_family": "intraday_max_lottery_demand",
        "research_archetype": "cross_sectional_intraday_factor",
        "universe_symbols": len(sy),
        "development_diagnostics": {str(w): di[w] for w in LOOKBACKS},
        "development": {str(w): dev[w] for w in LOOKBACKS},
        "development_gate_passed": gate,
        "oos_consumed": False,
        "trial_accounting": {"previous_parameter_trials": 151, "new_parameter_trials": 3, "cumulative_parameter_trials": 154},
    }

    if not gate:
        out.update(
            classification="REJECT",
            success_gate_candidate=False,
            multiple_testing={"dsr_probability": None, "pbo": "N/A: development gate failed before OOS."},
            conclusion="REJECT. Development gate failed; OOS not consumed.",
        )
        print(json.dumps(out, indent=2, default=str))
        return

    res = {}
    sharpes = []
    for w in LOOKBACKS:
        res[str(w)] = {str(m): sim(portfolio(fs[w], OOS0, OOS1), COST * m) for m in (1, 2, 3)}
        sharpes.append(res[str(w)]["1"]["metrics"]["annualized_sharpe"])

    base = res[str(CAN)]["1"]
    bm = base["metrics"]
    odi = diagnostic(fs[CAN], OOS0, OOS1)
    ex = sim(portfolio(fs[CAN], OOS0, OOS1, exclude={"BTCUSDT", "ETHUSDT"}), COST)
    strongest = max(base["asset_contribution"], key=lambda s: abs(base["asset_contribution"][s])) if base["asset_contribution"] else None
    exs = sim(portfolio(fs[CAN], OOS0, OOS1, exclude={strongest} if strongest else set()), COST) if strongest else None
    delayed = sim(portfolio(fs[CAN], OOS0, OOS1, retcol="delay_ret"), COST)
    years_ok = all(base["by_year"].get(str(y), {}).get("total_return", -1.0) >= 0 for y in (2024, 2025))
    stable = sum(res[str(w)]["1"]["metrics"]["total_return"] > 0 for w in LOOKBACKS) >= 2
    dsr = compute_deflated_sharpe(bm["annualized_sharpe"], sharpes, n_obs_days=max(bm["n_days"], 1))
    gdsr = compute_deflated_sharpe(bm["annualized_sharpe"], sharpes + [0.0] * 151, n_obs_days=max(bm["n_days"], 1))

    qual = (
        bm["annualized_sharpe"] > 1.0
        and odi["mean_ic"] > 0.02
        and res[str(CAN)]["2"]["metrics"]["total_return"] > 0
        and stable
        and years_ok
        and bm["max_drawdown"] > -0.35
        and ex["metrics"]["total_return"] > 0
        and delayed["metrics"]["total_return"] > 0
        and (exs is None or exs["metrics"]["total_return"] > 0)
        and dsr["dsr_probability"] >= 0.95
        and gdsr["dsr_probability"] >= 0.95
    )
    out.update(
        oos_consumed=True,
        oos_diagnostics=odi,
        oos_results=res,
        exclude_btc_eth=ex,
        strongest_asset=strongest,
        exclude_strongest=exs,
        delay_one_slot=delayed,
        multiple_testing={"family_dsr": dsr, "global_154_trial_proxy": gdsr, "pbo": "N/A: three preregistered lookbacks"},
        success_gate_candidate=qual,
        classification="EXPLORATORY_PASS" if qual else "REJECT",
        conclusion=(
            "EXPLORATORY_PASS. Meets preregistered exploratory gate; sealed confirmation remains untouched."
            if qual
            else "REJECT. OOS or robustness/multiple-testing gate failed."
        ),
    )
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
