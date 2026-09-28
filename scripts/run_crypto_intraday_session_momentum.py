#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
import math
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import polars as pl

from scripts.run_crypto_aggressor_flow import symbols
from src.experiment import compute_deflated_sharpe

BLOCKS = (4, 8, 12)
CAN = 8
LIQ = 720
TOPN = 30
MIN_XS = 8
COST = 10.0
DEV0 = date(2022, 1, 1)
DEV1 = date(2024, 1, 1)
OOS0 = date(2024, 1, 1)
OOS1 = date(2026, 1, 1)


def load_panel(root: Path) -> tuple[list[str], pl.DataFrame]:
    sy = symbols(root)
    frames = []
    for s in sy:
        paths = glob.glob(str(root / f"symbol={s}" / "year=*" / "month=*" / "data.parquet"))
        if not paths:
            continue
        x = (
            pl.scan_parquet(paths, hive_partitioning=False)
            .filter(
                (pl.col("timestamp") >= pl.datetime(2021, 11, 25, time_zone="UTC"))
                & (pl.col("timestamp") < pl.datetime(2026, 1, 2, time_zone="UTC"))
            )
            .select("timestamp", "open", "close", "quote_volume")
            .collect()
            .sort("timestamp")
            .with_columns(pl.lit(s).alias("symbol"))
        )
        frames.append(x)
    return sy, pl.concat(frames, how="vertical").sort(["symbol", "timestamp"])


def feature_frame(h: pl.DataFrame, block: int) -> pl.DataFrame:
    x = (
        h.sort(["symbol", "timestamp"])
        .with_columns(
            pl.col("timestamp").dt.date().alias("_date"),
            pl.col("timestamp").dt.hour().alias("_hour"),
            pl.col("open").first().over(["symbol", pl.col("timestamp").dt.date()]).alias("_day_open"),
            pl.col("close").shift(1).over("symbol").alias("_prev_close"),
            pl.col("timestamp").shift(1).over("symbol").alias("_prev_ts"),
            pl.col("quote_volume").shift(1).rolling_sum(LIQ).over("symbol").alias("_liq"),
            pl.col("timestamp").shift(LIQ).over("symbol").alias("_liq_anchor"),
            pl.col("open").shift(-1).over("symbol").alias("_entry"),
            pl.col("timestamp").shift(-1).over("symbol").alias("_entry_ts"),
            pl.col("open").shift(-(block + 1)).over("symbol").alias("_exit"),
            pl.col("timestamp").shift(-(block + 1)).over("symbol").alias("_exit_ts"),
            pl.col("open").shift(-2).over("symbol").alias("_delay_entry"),
            pl.col("timestamp").shift(-2).over("symbol").alias("_delay_entry_ts"),
            pl.col("open").shift(-(block + 2)).over("symbol").alias("_delay_exit"),
            pl.col("timestamp").shift(-(block + 2)).over("symbol").alias("_delay_exit_ts"),
        )
        .with_columns(
            (pl.col("_prev_close") / pl.col("_day_open") - 1.0).alias("signal"),
            (pl.col("_exit") / pl.col("_entry") - 1.0).alias("fwd_ret"),
            (pl.col("_delay_exit") / pl.col("_delay_entry") - 1.0).alias("delay_ret"),
        )
        .filter(
            (pl.col("_hour") == block)
            & pl.col("signal").is_finite()
            & pl.col("_liq").is_finite()
            & (pl.col("_prev_ts") == pl.col("timestamp") - pl.duration(hours=1))
            & (pl.col("_liq_anchor") == pl.col("timestamp") - pl.duration(hours=LIQ))
            & (pl.col("_entry_ts") == pl.col("timestamp") + pl.duration(hours=1))
            & (pl.col("_exit_ts") == pl.col("timestamp") + pl.duration(hours=block + 1))
            & (pl.col("_delay_entry_ts") == pl.col("timestamp") + pl.duration(hours=2))
            & (pl.col("_delay_exit_ts") == pl.col("timestamp") + pl.duration(hours=block + 2))
        )
        .with_columns(
            pl.col("_liq").rank(method="ordinal", descending=True).over("timestamp").alias("_liq_rank"),
            pl.len().over("timestamp").alias("_n"),
        )
        .filter((pl.col("_n") >= MIN_XS) & (pl.col("_liq_rank") <= TOPN))
        .select("timestamp", "symbol", "signal", "fwd_ret", "delay_ret")
        .sort(["timestamp", "symbol"])
    )
    return x


def portfolio(f: pl.DataFrame, start: date, end: date, retcol: str = "fwd_ret", exclude: set[str] | None = None):
    ex = exclude or set()
    out = []
    ff = f.filter((pl.col("timestamp").dt.date() >= start) & (pl.col("timestamp").dt.date() < end))
    for p in ff.partition_by("timestamp", maintain_order=True):
        rows = [r for r in p.iter_rows(named=True) if str(r["symbol"]) not in ex and abs(float(r["signal"])) > 1e-12]
        if len(rows) < MIN_XS:
            continue
        weight = 1.0 / len(rows)
        w = {}
        gross = 0.0
        contrib = {}
        for r in rows:
            s = str(r["symbol"])
            ww = weight if float(r["signal"]) > 0 else -weight
            rr = float(r[retcol])
            w[s] = ww
            gross += ww * rr
            contrib[s] = ww * rr
        out.append((p["timestamp"][0], w, gross, contrib))
    return out


def sim(rows, cost_bps: float) -> dict:
    rr = []
    cont = {}
    total_turnover = 0.0
    for ts, w, gross, cc in rows:
        gross_exposure = sum(abs(v) for v in w.values())
        turnover = 2.0 * gross_exposure
        total_turnover += turnover
        net = gross - turnover * cost_bps / 10000.0
        rr.append((ts.date(), net))
        for s, v in cc.items():
            cont[s] = cont.get(s, 0.0) + v
    if not rr:
        return {
            "metrics": {"annualized_sharpe": 0.0, "total_return": 0.0, "max_drawdown": 0.0, "n_days": 0, "turnover": 0.0},
            "by_year": {},
            "asset_contribution": {},
        }

    a = np.asarray([r for _, r in rr], dtype=float)
    eq = np.cumprod(1.0 + a)
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    sd = float(np.std(a, ddof=1))
    by_year = {}
    for y in sorted({d.year for d, _ in rr}):
        q = np.asarray([r for d, r in rr if d.year == y], dtype=float)
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
            "turnover": float(total_turnover),
        },
        "by_year": by_year,
        "asset_contribution": cont,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()

    sy, h = load_panel(args.root)
    fs = {b: feature_frame(h, b) for b in BLOCKS}
    dev = {b: sim(portfolio(fs[b], DEV0, DEV1), COST) for b in BLOCKS}
    cm = dev[CAN]["metrics"]
    dev_years_ok = all(dev[CAN]["by_year"].get(str(y), {}).get("total_return", -1.0) >= 0 for y in (2022, 2023))
    gate = (
        cm["annualized_sharpe"] > 0.70
        and cm["total_return"] > 0
        and sum(dev[b]["metrics"]["total_return"] > 0 for b in BLOCKS) >= 2
        and dev_years_ok
    )

    out = {
        "schema_version": 1,
        "run_id": "20260928-intraday-session-momentum-daily",
        "strategy_family": "intraday_session_momentum",
        "research_archetype": "time_series_intraday_rule",
        "universe_symbols": len(sy),
        "development": {str(b): dev[b] for b in BLOCKS},
        "development_gate_passed": gate,
        "oos_consumed": False,
        "trial_accounting": {"previous_parameter_trials": 154, "new_parameter_trials": 3, "cumulative_parameter_trials": 157},
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
    for b in BLOCKS:
        res[str(b)] = {str(m): sim(portfolio(fs[b], OOS0, OOS1), COST * m) for m in (1, 2, 3)}
        sharpes.append(res[str(b)]["1"]["metrics"]["annualized_sharpe"])

    base = res[str(CAN)]["1"]
    bm = base["metrics"]
    ex = sim(portfolio(fs[CAN], OOS0, OOS1, exclude={"BTCUSDT", "ETHUSDT"}), COST)
    strongest = max(base["asset_contribution"], key=lambda s: abs(base["asset_contribution"][s])) if base["asset_contribution"] else None
    exs = sim(portfolio(fs[CAN], OOS0, OOS1, exclude={strongest} if strongest else set()), COST) if strongest else None
    delayed = sim(portfolio(fs[CAN], OOS0, OOS1, retcol="delay_ret"), COST)
    years_ok = all(base["by_year"].get(str(y), {}).get("total_return", -1.0) >= 0 for y in (2024, 2025))
    stable = sum(res[str(b)]["1"]["metrics"]["total_return"] > 0 for b in BLOCKS) >= 2
    dsr = compute_deflated_sharpe(bm["annualized_sharpe"], sharpes, n_obs_days=max(bm["n_days"], 1))
    gdsr = compute_deflated_sharpe(bm["annualized_sharpe"], sharpes + [0.0] * 154, n_obs_days=max(bm["n_days"], 1))

    qual = (
        bm["annualized_sharpe"] > 1.0
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
        oos_results=res,
        exclude_btc_eth=ex,
        strongest_asset=strongest,
        exclude_strongest=exs,
        delay_one_hour=delayed,
        multiple_testing={"family_dsr": dsr, "global_157_trial_proxy": gdsr, "pbo": "N/A: three preregistered block lengths"},
        success_gate_candidate=qual,
        classification="EXPLORATORY_PASS" if qual else "REJECT",
        conclusion=(
            "EXPLORATORY_PASS. Meets preregistered exploratory gate; sealed confirmation remains untouched."
            if qual else "REJECT. OOS or robustness/multiple-testing gate failed."
        ),
    )
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
