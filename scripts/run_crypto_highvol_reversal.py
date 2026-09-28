#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import polars as pl

from scripts.run_crypto_nearness52 import diagnostic, portfolio, sim, MIN_XS
from src.experiment import compute_deflated_sharpe

FORMATIONS = (56, 63, 70)
CAN = 63
VOLW = 30
TOPN = 50
COST = 10.0
DEV0 = date(2022, 1, 1)
DEV1 = date(2024, 1, 1)
OOS0 = date(2024, 1, 1)
OOS1 = date(2026, 1, 1)


def load_daily_range(root: Path, start_y: int, start_m: int, start_d: int, end_y: int, end_m: int, end_d: int) -> pl.DataFrame:
    pattern = str(root / "symbol=*" / "year=*" / "month=*" / "data.parquet")
    return (
        pl.scan_parquet(pattern, hive_partitioning=True)
        .filter(
            pl.col("symbol").str.ends_with("USDT")
            & (pl.col("symbol") != "BTCDOMUSDT")
            & (pl.col("timestamp") >= pl.datetime(start_y, start_m, start_d, time_zone="UTC"))
            & (pl.col("timestamp") < pl.datetime(end_y, end_m, end_d, time_zone="UTC"))
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


def base_frame(d: pl.DataFrame) -> pl.DataFrame:
    return (
        d.sort(["symbol", "date"])
        .with_columns(
            pl.col("close").shift(1).over("symbol").alias("_pc"),
            pl.col("date").shift(1).over("symbol").alias("_pd"),
        )
        .with_columns(
            pl.when(pl.col("date") - pl.col("_pd") == pl.duration(days=1))
            .then(pl.col("close") / pl.col("_pc") - 1.0)
            .otherwise(None)
            .alias("_ret")
        )
    )


def feature_frame(b: pl.DataFrame, formation: int) -> pl.DataFrame:
    hist = max(formation + 1, VOLW + 1)
    x = (
        b.with_columns(
            pl.col("close").shift(1).over("symbol").alias("_c1"),
            pl.col("close").shift(formation + 1).over("symbol").alias("_c0"),
            pl.col("_ret").shift(1).rolling_std(VOLW).over("symbol").alias("_vol"),
            pl.col("qv").shift(1).rolling_sum(VOLW).over("symbol").alias("_liq"),
            pl.col("date").shift(formation + 1).over("symbol").alias("_form_anchor"),
            pl.col("date").shift(VOLW + 1).over("symbol").alias("_vol_anchor"),
            pl.col("open").shift(-7).over("symbol").alias("_next_open"),
            pl.col("date").shift(-7).over("symbol").alias("_next_date"),
            pl.col("open").shift(-1).over("symbol").alias("_delay_entry"),
            pl.col("date").shift(-1).over("symbol").alias("_delay_entry_date"),
            pl.col("open").shift(-8).over("symbol").alias("_delay_exit"),
            pl.col("date").shift(-8).over("symbol").alias("_delay_exit_date"),
        )
        .with_columns(
            (-(pl.col("_c1") / pl.col("_c0") - 1.0)).alias("signal"),
            (pl.col("_next_open") / pl.col("open") - 1.0).alias("fwd_ret"),
            (pl.col("_delay_exit") / pl.col("_delay_entry") - 1.0).alias("delay_ret"),
        )
        .filter(
            (pl.col("date").dt.weekday() == 1)
            & pl.col("signal").is_finite()
            & pl.col("_vol").is_finite()
            & pl.col("_liq").is_finite()
            & (pl.col("_form_anchor") == pl.col("date") - pl.duration(days=formation + 1))
            & (pl.col("_vol_anchor") == pl.col("date") - pl.duration(days=VOLW + 1))
            & (pl.col("_next_date") == pl.col("date") + pl.duration(days=7))
            & (pl.col("_delay_entry_date") == pl.col("date") + pl.duration(days=1))
            & (pl.col("_delay_exit_date") == pl.col("date") + pl.duration(days=8))
        )
    )

    out = []
    for p in x.partition_by("date", maintain_order=True):
        liquid = p.sort("_liq", descending=True).head(TOPN)
        if liquid.height < MIN_XS:
            continue
        highvol_n = max(MIN_XS, liquid.height // 2)
        conditioned = liquid.sort("_vol", descending=True).head(highvol_n)
        if conditioned.height >= MIN_XS:
            out.append(conditioned.select("date", "symbol", "signal", "fwd_ret", "delay_ret"))
    return pl.concat(out, how="vertical").sort(["date", "symbol"]) if out else pl.DataFrame()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()

    d = load_daily_range(args.root, 2021, 9, 1, 2024, 1, 8)
    b = base_frame(d)
    fs = {w: feature_frame(b, w) for w in FORMATIONS}
    di = {w: diagnostic(fs[w], DEV0, DEV1) for w in FORMATIONS}
    dev = {w: sim(portfolio(fs[w], DEV0, DEV1), COST) for w in FORMATIONS}

    cd = di[CAN]
    cm = dev[CAN]["metrics"]
    gate = (
        cd["mean_ic"] > 0.02
        and cd["hac_p"] < 0.05
        and cd["high_minus_low"] > 0
        and cm["annualized_sharpe"] > 0.70
        and cm["total_return"] > 0
        and sum(dev[w]["metrics"]["total_return"] > 0 for w in FORMATIONS) >= 2
    )

    out = {
        "schema_version": 1,
        "run_id": "20260928-highvol-reversal-9w",
        "strategy_family": "high_volatility_long_horizon_reversal",
        "research_archetype": "cross_sectional_conditional_reversal",
        "universe_symbols": int(d["symbol"].n_unique()),
        "development_diagnostics": {str(w): di[w] for w in FORMATIONS},
        "development": {str(w): dev[w] for w in FORMATIONS},
        "development_gate_passed": gate,
        "oos_consumed": False,
        "trial_accounting": {"previous_parameter_trials": 157, "new_parameter_trials": 3, "cumulative_parameter_trials": 160},
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

    d_oos = load_daily_range(args.root, 2023, 9, 1, 2026, 1, 8)
    b_oos = base_frame(d_oos)
    fs_oos = {w: feature_frame(b_oos, w) for w in FORMATIONS}

    res = {}
    sharpes = []
    for w in FORMATIONS:
        rows = portfolio(fs_oos[w], OOS0, OOS1)
        res[str(w)] = {str(m): sim(rows, COST * m) for m in (1, 2, 3)}
        sharpes.append(res[str(w)]["1"]["metrics"]["annualized_sharpe"])

    base = res[str(CAN)]["1"]
    bm = base["metrics"]
    odi = diagnostic(fs_oos[CAN], OOS0, OOS1)
    ex = sim(portfolio(fs_oos[CAN], OOS0, OOS1, exclude={"BTCUSDT", "ETHUSDT"}), COST)
    strongest = max(base["asset_contribution"], key=lambda s: abs(base["asset_contribution"][s])) if base["asset_contribution"] else None
    exs = sim(portfolio(fs_oos[CAN], OOS0, OOS1, exclude={strongest} if strongest else set()), COST) if strongest else None
    delayed = sim(portfolio(fs_oos[CAN], OOS0, OOS1, retcol="delay_ret"), COST)
    years_ok = all(base["by_year"].get(str(y), {}).get("total_return", -1.0) >= 0 for y in (2024, 2025))
    stable = sum(res[str(w)]["1"]["metrics"]["total_return"] > 0 for w in FORMATIONS) >= 2
    dsr = compute_deflated_sharpe(bm["annualized_sharpe"], sharpes, n_obs_days=max(bm["n_weeks"] * 7, 1))
    gdsr = compute_deflated_sharpe(bm["annualized_sharpe"], sharpes + [0.0] * 157, n_obs_days=max(bm["n_weeks"] * 7, 1))

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
        delay_one_day=delayed,
        multiple_testing={"family_dsr": dsr, "global_160_trial_proxy": gdsr, "pbo": "N/A: three preregistered formation windows"},
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
