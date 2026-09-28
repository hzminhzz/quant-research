#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import polars as pl

from src.experiment import compute_deflated_sharpe

SYMBOLS = ("BTCUSDT","ETHUSDT","LTCUSDT","XRPUSDT","BNBUSDT","ADAUSDT","DOGEUSDT","SOLUSDT")
PAIRS = ((8,24),(16,48),(32,96))
ALPHAS = (0.5,1.0,2.0)
CANONICAL_ALPHA = 1.0
NORM = 30
COST = 10.0
DEV0 = np.datetime64("2022-01-01")
DEV1 = np.datetime64("2024-01-01")
OOS0 = np.datetime64("2024-01-01")
OOS1 = np.datetime64("2026-01-01")


def ema(x: np.ndarray, length: int) -> np.ndarray:
    out = np.full(len(x), np.nan, dtype=float)
    a = 1.0 - math.exp(-1.0 / float(length))
    last = np.nan
    for i, v in enumerate(x):
        if not np.isfinite(v):
            continue
        if not np.isfinite(last):
            last = float(v)
        else:
            last = a * float(v) + (1.0 - a) * last
        out[i] = last
    return out


def rolling_std(x: np.ndarray, window: int) -> np.ndarray:
    out = np.full(len(x), np.nan, dtype=float)
    for i in range(window - 1, len(x)):
        z = x[i-window+1:i+1]
        if np.isfinite(z).all():
            s = float(np.std(z, ddof=1))
            if s > 0:
                out[i] = s
    return out


def load_daily(path: Path) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    out = {}
    if path.is_dir():
        import glob
        for s in SYMBOLS:
            files = glob.glob(str(path / f"symbol={s}" / "year=*" / "month=*" / "data.parquet"))
            if not files:
                raise RuntimeError(f"missing symbol data: {s}")
            p = (
                pl.scan_parquet(files, hive_partitioning=False)
                .select("timestamp","close")
                .filter(pl.col("timestamp") < pl.datetime(2026,1,1,time_zone="UTC"))
                .with_columns(pl.col("timestamp").dt.date().alias("date"))
                .group_by("date")
                .agg(pl.col("close").last().alias("close"), pl.len().alias("hours"))
                .filter(pl.col("hours") == 24)
                .sort("date")
                .collect()
            )
            out[s] = (
                p["date"].cast(pl.Date).to_numpy().astype("datetime64[D]"),
                p["close"].to_numpy().astype(float),
            )
        return out

    df = (
        pl.scan_parquet(path)
        .filter(pl.col("symbol").is_in(SYMBOLS))
        .with_columns(pl.col("timestamp").dt.date().alias("date"))
        .group_by(["symbol","date"])
        .agg(pl.col("close").last().alias("close"), pl.len().alias("hours"))
        .filter(pl.col("hours") == 24)
        .sort(["symbol","date"])
        .collect()
    )
    for s in SYMBOLS:
        p = df.filter(pl.col("symbol") == s).sort("date")
        if p.height == 0:
            raise RuntimeError(f"missing symbol data: {s}")
        out[s] = (
            p["date"].cast(pl.Date).to_numpy().astype("datetime64[D]"),
            p["close"].to_numpy().astype(float),
        )
    return out


def signal(close: np.ndarray, alpha: float) -> np.ndarray:
    bounded = []
    for short, long in PAIRS:
        raw = ema(close, short) - ema(close, long)
        vol = rolling_std(raw, NORM)
        y = raw / vol
        z = ema(y, long)
        bounded.append(np.tanh(alpha * z))
    u = np.nanmean(np.vstack(bounded), axis=0)
    su = rolling_std(u, NORM)
    s = u / su
    return np.clip(s, -1.0, 1.0)


def build_panel(daily, alpha: float):
    common = None
    for dates, _ in daily.values():
        common = dates if common is None else np.intersect1d(common, dates)
    common = np.sort(common)
    closes = {}
    sigs = {}
    for s,(dates,close) in daily.items():
        m = {d: c for d,c in zip(dates,close)}
        c = np.array([m[d] for d in common], dtype=float)
        closes[s] = c
        sigs[s] = signal(c, alpha)
    ret = {s: np.r_[np.nan, closes[s][1:] / closes[s][:-1] - 1.0] for s in SYMBOLS}
    return common, closes, sigs, ret


def simulate(daily, alpha: float, start, end, cost_bps: float, delay: int = 0, exclude: set[str] | None = None):
    exclude = exclude or set()
    dates, closes, sigs, ret = build_panel(daily, alpha)
    active = [s for s in SYMBOLS if s not in exclude]
    prev = {s:0.0 for s in active}
    rows = []
    contrib = {s:0.0 for s in active}
    for i,d in enumerate(dates):
        if not (start <= d < end):
            continue
        j = i - 1 - delay
        if j < 0:
            continue
        vals = {s: sigs[s][j] for s in active}
        if not all(np.isfinite(v) for v in vals.values()):
            continue
        w = {s: float(vals[s]) / len(active) for s in active}
        turn = sum(abs(w[s] - prev[s]) for s in active)
        gross = 0.0
        for s in active:
            r = ret[s][i]
            if not np.isfinite(r):
                gross = np.nan
                break
            gross += w[s] * float(r)
            contrib[s] += w[s] * float(r)
        if not np.isfinite(gross):
            continue
        net = gross - turn * cost_bps / 10000.0
        rows.append((d,net,gross,turn))
        prev = w
    if not rows:
        return {"metrics":{"annualized_sharpe":0.0,"total_return":0.0,"max_drawdown":0.0,"n_days":0},"by_year":{},"asset_contribution":contrib}
    a = np.array([x[1] for x in rows],dtype=float)
    eq = np.cumprod(1.0+a)
    peak = np.maximum.accumulate(eq)
    dd = eq/peak - 1.0
    sd = float(np.std(a,ddof=1))
    by_year = {}
    for y in sorted({int(str(d)[:4]) for d,_,_,_ in rows}):
        q = np.array([r for d,r,_,_ in rows if int(str(d)[:4]) == y],dtype=float)
        qs = float(np.std(q,ddof=1)) if len(q)>1 else 0.0
        by_year[str(y)] = {
            "total_return": float(np.prod(1.0+q)-1.0),
            "sharpe": float(np.mean(q)/qs*math.sqrt(365.0)) if qs>0 else 0.0,
        }
    return {
        "metrics":{
            "annualized_sharpe": float(np.mean(a)/sd*math.sqrt(365.0)) if sd>0 else 0.0,
            "total_return": float(eq[-1]-1.0),
            "max_drawdown": float(dd.min()),
            "n_days": int(len(a)),
            "turnover": float(sum(x[3] for x in rows)),
            "avg_gross_exposure": float(np.mean([sum(abs(sigs[s][max(0,i-1)])/len(active) for s in active) for i in range(1,len(dates)) if start<=dates[i]<end and all(np.isfinite(sigs[s][i-1]) for s in active)])),
        },
        "by_year": by_year,
        "asset_contribution": contrib,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    args = ap.parse_args()
    daily = load_daily(args.data)

    dev = {str(a): simulate(daily,a,DEV0,DEV1,COST) for a in ALPHAS}
    can_dev = dev[str(CANONICAL_ALPHA)]["metrics"]
    gate = (
        can_dev["annualized_sharpe"] > 0.80
        and can_dev["total_return"] > 0
        and sum(dev[str(a)]["metrics"]["total_return"] > 0 for a in ALPHAS) >= 2
    )
    out = {
        "schema_version":1,
        "run_id":"20260928-paper-ema-tsmom-eight-majors",
        "symbols":list(SYMBOLS),
        "development":dev,
        "development_gate_passed":gate,
        "oos_consumed":False,
        "trial_accounting":{"previous_parameter_trials":77,"new_parameter_trials":3,"cumulative_parameter_trials":80},
    }
    if not gate:
        out.update(classification="REJECT",success_gate_candidate=False,conclusion="Development gate failed; OOS not consumed.")
        print(json.dumps(out,indent=2,default=str))
        return

    oos = {}
    sharpes = []
    for a in ALPHAS:
        oos[str(a)] = {}
        for mult in (1,2,3):
            oos[str(a)][str(mult)] = simulate(daily,a,OOS0,OOS1,COST*mult)
        sharpes.append(oos[str(a)]["1"]["metrics"]["annualized_sharpe"])

    base = oos[str(CANONICAL_ALPHA)]["1"]
    bm = base["metrics"]
    delay = simulate(daily,CANONICAL_ALPHA,OOS0,OOS1,COST,delay=1)
    strongest = max(base["asset_contribution"], key=lambda s: abs(base["asset_contribution"][s]))
    exstrong = simulate(daily,CANONICAL_ALPHA,OOS0,OOS1,COST,exclude={strongest})
    years_ok = all(base["by_year"].get(str(y),{}).get("total_return",-1.0) >= 0 for y in (2024,2025))
    stable = sum(oos[str(a)]["1"]["metrics"]["total_return"] > 0 for a in ALPHAS) >= 2
    qual = (
        bm["annualized_sharpe"] > 1.0
        and bm["total_return"] > 0
        and oos[str(CANONICAL_ALPHA)]["2"]["metrics"]["total_return"] > 0
        and stable
        and years_ok
        and bm["max_drawdown"] > -0.35
        and delay["metrics"]["total_return"] > 0
        and exstrong["metrics"]["total_return"] > 0
    )
    dsr = compute_deflated_sharpe(bm["annualized_sharpe"],sharpes,n_obs_days=max(bm["n_days"],1))
    global_dsr = compute_deflated_sharpe(bm["annualized_sharpe"],sharpes+[0.0]*77,n_obs_days=max(bm["n_days"],1))
    out.update(
        oos_consumed=True,
        oos_results=oos,
        one_day_delay=delay,
        strongest_asset=strongest,
        exclude_strongest=exstrong,
        multiple_testing={"family_dsr":dsr,"global_80_trial_proxy":global_dsr,"pbo":"N/A: three preregistered alpha variants"},
        success_gate_candidate=qual,
        classification="EXPLORATORY_PASS" if qual else "REJECT",
    )
    print(json.dumps(out,indent=2,default=str))


if __name__ == "__main__":
    main()
