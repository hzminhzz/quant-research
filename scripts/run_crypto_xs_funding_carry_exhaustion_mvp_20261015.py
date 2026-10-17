"""MVP for cross-sectional perpetual funding carry plus price exhaustion.

The MVP is fail-fast:
1. Materialize only 2020-2023 canonical Binance USD-M data.
2. Compute native ML4T ROCP(24) and ATR(24) per symbol.
3. Build causal 48-hour cross-sectional IC diagnostics.
4. Stop at REJECT when the frozen IC gate fails.
5. A portfolio stage is intentionally not executed unless the diagnostic gate passes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from ml4t.diagnostic.api import compute_ic_hac_stats, cross_sectional_ic_series
from ml4t.engineer import compute_features

ROOT = Path(__file__).resolve().parents[1]
SESSION = "crypto_xs_funding_carry_exhaustion_basket_mvp_20261015_v1"
DATA = ROOT / "data" / "processed" / SESSION
OUT = ROOT / "run_log" / "research_sessions" / SESSION / "mvp"

PRICE_STORE = Path(
    "/home/quant/dev/quant/ml4t-data/.data/store/"
    "crypto_futures_ohlcv_1h_BINANCE_UM_PERP"
)
STORE_ROOT = Path("/home/quant/dev/quant/ml4t-data/.data/store")
FUNDING_PREFIX = "crypto_futures_funding_"

WARMUP_START = datetime(2020, 1, 1, tzinfo=UTC)
DEV_START = datetime(2020, 6, 1, tzinfo=UTC)
DEV_END = datetime(2024, 1, 1, tzinfo=UTC)
YEARS = (2020, 2021, 2022, 2023)
MIN_HISTORY = 720
TOP_N = 40
MIN_CROSS_SECTION = 10
LABEL_HOURS = 48
REBALANCE_HOURS = 48
SHORT_FUNDING_MIN = 0.0003
IC_MIN = 0.015
IC_T_MIN = 2.0
MIN_CYCLES = 150


def sha256(path: Path) -> str:
    with path.open("rb") as fp:
        return hashlib.file_digest(fp, "sha256").hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False, default=str) + "\n")


def matched_funding_symbols() -> list[str]:
    symbols = []
    for path in STORE_ROOT.glob(FUNDING_PREFIX + "*_PERP"):
        if not path.is_dir():
            continue
        token = path.name[len(FUNDING_PREFIX):-len("_PERP")]
        if token.endswith("USDT"):
            symbols.append(token)
    return sorted(set(symbols))


def price_paths_for_year(year: int) -> list[str]:
    return [str(p) for p in PRICE_STORE.glob(f"symbol=*/year={year}/month=*/data.parquet")]


def funding_paths_for_year(symbols: list[str], year: int) -> list[str]:
    out: list[str] = []
    for symbol in symbols:
        base = STORE_ROOT / f"{FUNDING_PREFIX}{symbol}_PERP" / f"year={year}"
        out.extend(str(p) for p in base.glob("month=*/data.parquet"))
    return out


def _validate_price_frame(df: pl.DataFrame, year: int) -> dict[str, Any]:
    if df.is_empty():
        raise ValueError(f"{year}: no price rows")
    if df.schema["timestamp"].time_zone != "UTC":
        raise ValueError(f"{year}: prices must be UTC-aware")
    if df.filter(
        pl.col("timestamp") >= DEV_END
    ).height:
        raise AssertionError("Protected 2024+ price row materialized")
    if df.filter(
        (~pl.col("open").is_finite()) | (~pl.col("high").is_finite())
        | (~pl.col("low").is_finite()) | (~pl.col("close").is_finite())
        | (~pl.col("volume").is_finite()) | (pl.col("open") <= 0)
        | (pl.col("close") <= 0) | (pl.col("high") < pl.col("low"))
        | (pl.col("volume") < 0)
    ).height:
        raise ValueError(f"{year}: invalid OHLCV")
    dup = (
        df.group_by("symbol", "timestamp").len()
        .filter(pl.col("len") != 1).height
    )
    if dup:
        raise ValueError(f"{year}: duplicate symbol/timestamp rows: {dup}")
    return {
        "rows": df.height,
        "symbols": df["symbol"].n_unique(),
        "first": str(df["timestamp"].min()),
        "last": str(df["timestamp"].max()),
    }


def _validate_funding_frame(df: pl.DataFrame, year: int) -> dict[str, Any]:
    if df.is_empty():
        raise ValueError(f"{year}: no funding rows")
    if df.schema["timestamp"].time_zone != "UTC":
        raise ValueError(f"{year}: funding must be UTC-aware")
    if df.filter(pl.col("timestamp") >= DEV_END).height:
        raise AssertionError("Protected 2024+ funding row materialized")
    if df.filter(
        pl.col("funding_rate").is_null() | (~pl.col("funding_rate").is_finite())
        | (pl.col("funding_interval_hours") <= 0)
    ).height:
        raise ValueError(f"{year}: invalid funding")
    return {
        "rows": df.height,
        "symbols": df["symbol"].n_unique(),
        "first": str(df["timestamp"].min()),
        "last": str(df["timestamp"].max()),
        "non_8h_events": df.filter(pl.col("funding_interval_hours") != 8).height,
    }


def prepare() -> None:
    if DATA.exists() and any(DATA.iterdir()):
        raise FileExistsError(f"Frozen bounded inputs already exist: {DATA}")
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    funding_symbols = matched_funding_symbols()
    if len(funding_symbols) < TOP_N:
        raise ValueError(f"Only {len(funding_symbols)} matched USDT funding symbols")

    manifest: dict[str, Any] = {
        "session": SESSION,
        "price_store": str(PRICE_STORE),
        "funding_store_root": str(STORE_ROOT),
        "matched_usdt_funding_symbols": len(funding_symbols),
        "protected_boundary": DEV_END.isoformat(),
        "years": {},
    }

    for year in YEARS:
        ppaths = price_paths_for_year(year)
        if not ppaths:
            raise FileNotFoundError(f"No canonical OHLCV partitions for {year}")
        prices = (
            pl.scan_parquet(ppaths, hive_partitioning=True)
            .filter(pl.col("symbol").is_in(funding_symbols))
            .select("timestamp", "symbol", "open", "high", "low", "close", "volume")
            .sort("symbol", "timestamp")
            .collect()
        )
        pstats = _validate_price_frame(prices, year)
        ptarget = DATA / f"prices_{year}.parquet"
        prices.write_parquet(ptarget)

        fpaths = funding_paths_for_year(funding_symbols, year)
        if not fpaths:
            raise FileNotFoundError(f"No matched funding partitions for {year}")
        funding = (
            pl.scan_parquet(fpaths, hive_partitioning=True)
            .select("timestamp", "symbol", "funding_interval_hours", "funding_rate", "mark_price")
            .sort("symbol", "timestamp")
            .collect()
        )
        fstats = _validate_funding_frame(funding, year)
        ftarget = DATA / f"funding_{year}.parquet"
        funding.write_parquet(ftarget)

        manifest["years"][str(year)] = {
            "prices": {**pstats, "path": str(ptarget.relative_to(ROOT)), "sha256": sha256(ptarget)},
            "funding": {**fstats, "path": str(ftarget.relative_to(ROOT)), "sha256": sha256(ftarget)},
        }
        print("PREPARED", year, pstats, fstats, flush=True)

    write_json(OUT / "source_preflight.json", manifest)


def load_bounded() -> tuple[pl.DataFrame, pl.DataFrame]:
    price_files = [DATA / f"prices_{y}.parquet" for y in YEARS]
    funding_files = [DATA / f"funding_{y}.parquet" for y in YEARS]
    if not all(p.exists() for p in price_files + funding_files):
        raise FileNotFoundError("Bounded source files are incomplete")
    prices = pl.concat([pl.read_parquet(p) for p in price_files]).sort("symbol", "timestamp")
    funding = pl.concat([pl.read_parquet(p) for p in funding_files]).sort("symbol", "timestamp")
    if prices.filter(pl.col("timestamp") >= DEV_END).height:
        raise AssertionError("Protected prices loaded")
    if funding.filter(pl.col("timestamp") >= DEV_END).height:
        raise AssertionError("Protected funding loaded")
    return prices, funding


def native_price_features(prices: pl.DataFrame) -> pl.DataFrame:
    f = compute_features(
        prices,
        [
            {"name": "rocp", "params": {"timeperiod": 24}, "output": "ret24"},
            {"name": "atr", "params": {"period": 24}, "output": "atr24"},
        ],
        group_col="symbol",
        timestamp_col="timestamp",
    )
    # Explicit panel extension: trailing 720 completed hourly bars.
    # At a decision timestamp t, the 23:00 bar that closes at t is available.
    return (
        f.sort("symbol", "timestamp")
        .with_columns(
            ((pl.col("close") * pl.col("volume"))
             .rolling_sum(MIN_HISTORY, min_samples=MIN_HISTORY)
             .over("symbol")).alias("dollar_volume_720h"),
            pl.int_range(pl.len()).over("symbol").alias("symbol_row"),
        )
    )


def funding_features(funding: pl.DataFrame) -> pl.DataFrame:
    """Sum actual funding settlements in the causal trailing 24-hour window."""
    f = funding.sort("symbol", "timestamp")
    if f.group_by("symbol", "timestamp").len().filter(pl.col("len") > 1).height:
        raise ValueError("Duplicate exact funding timestamps")
    rolling = (
        f.rolling(index_column="timestamp", period="24h", group_by="symbol", closed="right")
        .agg(
            pl.col("funding_rate").sum().alias("cum_funding_24h"),
            pl.len().alias("funding_events_24h"),
        )
    )
    return f.join(rolling, on=["symbol", "timestamp"], how="left")


def decision_panel(prices: pl.DataFrame, funding: pl.DataFrame) -> pl.DataFrame:
    pf = native_price_features(prices)
    ff = funding_features(funding)

    # Price bar timestamp 23:00 closes at decision timestamp 00:00.
    p = (
        pf.filter(pl.col("timestamp").dt.hour() == 23)
        .with_columns((pl.col("timestamp") + pl.duration(hours=1)).alias("decision_ts"))
    )
    # Decision cadence is every 48 hours from 2020-06-01 00:00 UTC.
    epoch = int(DEV_START.timestamp())
    p = p.filter(
        (pl.col("decision_ts") >= DEV_START)
        & (pl.col("decision_ts") < DEV_END)
        & ((((pl.col("decision_ts").dt.epoch("s") - epoch) / 3600).cast(pl.Int64))
           % REBALANCE_HOURS == 0)
    )

    # Use the latest actual settlement known by the frozen 00:01 decision.
    decisions = p.with_columns(
        (pl.col("decision_ts") + pl.duration(minutes=1)).alias("decision_available_ts")
    ).sort("symbol", "decision_available_ts")
    f_asof = ff.select(
        "symbol",
        pl.col("timestamp").alias("funding_observed_ts"),
        "funding_rate",
        "funding_interval_hours",
        "cum_funding_24h",
        "funding_events_24h",
    ).sort("symbol", "funding_observed_ts")
    panel = decisions.join_asof(
        f_asof,
        left_on="decision_available_ts",
        right_on="funding_observed_ts",
        by="symbol",
        strategy="backward",
    )

    # Require contiguous trailing 720h history: row timestamp minus row 719 must be 719h.
    # Native feature nulls enforce row count; this gap check enforces continuity.
    trail_start = (
        prices.sort("symbol", "timestamp")
        .with_columns(
            pl.col("timestamp").shift(MIN_HISTORY - 1).over("symbol").alias("trail_start")
        )
        .filter(pl.col("timestamp").dt.hour() == 23)
        .with_columns((pl.col("timestamp") + pl.duration(hours=1)).alias("decision_ts"))
        .select("symbol", "decision_ts", "trail_start")
    )
    panel = panel.join(trail_start, on=["symbol", "decision_ts"], how="left").filter(
        pl.col("trail_start").is_not_null()
        & ((pl.col("timestamp") - pl.col("trail_start")) == pl.duration(hours=MIN_HISTORY - 1))
        & pl.col("dollar_volume_720h").is_not_null()
        & pl.col("ret24").is_not_null()
        & pl.col("atr24").is_not_null()
        & pl.col("cum_funding_24h").is_not_null()
    )

    # Funding snapshot must be causal and contain at least one actual event in 24h.
    panel = panel.filter(
        pl.col("funding_observed_ts").is_not_null()
        & (pl.col("funding_observed_ts") <= pl.col("decision_available_ts"))
        & (pl.col("funding_events_24h") > 0)
    )

    # Point-in-time top 40 by trailing close*base-volume proxy.
    panel = (
        panel.with_columns(
            pl.col("dollar_volume_720h")
            .rank(method="ordinal", descending=True)
            .over("decision_ts")
            .alias("liq_rank")
        )
        .filter(pl.col("liq_rank") <= TOP_N)
        .with_columns(
            pl.col("ret24").median().over("decision_ts").alias("xs_ret24_median")
        )
        .with_columns(
            (pl.col("ret24") - pl.col("xs_ret24_median")).alias("xs_return_diff_24h"),
            pl.col("cum_funding_24h").mean().over("decision_ts").alias("fund_mean"),
            pl.col("cum_funding_24h").std().over("decision_ts").alias("fund_std"),
        )
        .with_columns(
            pl.when(pl.col("fund_std") > 0)
            .then((pl.col("cum_funding_24h") - pl.col("fund_mean")) / pl.col("fund_std"))
            .otherwise(None)
            .alias("fund_z")
        )
    )

    # 48h forward label from next 01:00 open to 48h-later 01:00 open.
    opens = prices.select("symbol", "timestamp", pl.col("open").alias("entry_open"))
    panel = panel.with_columns(
        (pl.col("decision_ts") + pl.duration(hours=1)).alias("entry_ts"),
        (pl.col("decision_ts") + pl.duration(hours=1 + LABEL_HOURS)).alias("exit_ts"),
    )
    panel = (
        panel.join(opens.rename({"timestamp": "entry_ts"}), on=["symbol", "entry_ts"], how="left")
        .join(
            opens.rename({"timestamp": "exit_ts", "entry_open": "exit_open"}),
            on=["symbol", "exit_ts"],
            how="left",
        )
        .with_columns((pl.col("exit_open") / pl.col("entry_open") - 1).alias("forward_return_48h"))
        .filter(pl.col("forward_return_48h").is_finite())
    )

    # Strict candidate score only where price contradicts funding crowding.
    exhaustion = (
        ((pl.col("cum_funding_24h") > 0) & (pl.col("xs_return_diff_24h") <= 0))
        | ((pl.col("cum_funding_24h") < 0) & (pl.col("xs_return_diff_24h") >= 0))
    )
    return panel.with_columns(
        pl.when(exhaustion).then(-pl.col("fund_z")).otherwise(None).alias("candidate_score"),
        (-pl.col("fund_z")).alias("baseline_score"),
    ).sort("decision_ts", "symbol")


def _ic_stats(panel: pl.DataFrame, score_col: str) -> dict[str, Any]:
    pred = panel.select(
        pl.col("decision_ts").alias("date"),
        "symbol",
        pl.col(score_col).alias("prediction"),
    ).filter(pl.col("prediction").is_not_null())
    ret = panel.select(
        pl.col("decision_ts").alias("date"),
        "symbol",
        pl.col("forward_return_48h").alias("forward_return"),
    )
    series = cross_sectional_ic_series(
        pred, ret, pred_col="prediction", ret_col="forward_return",
        date_col="date", entity_col="symbol", method="spearman",
        min_obs=MIN_CROSS_SECTION,
    )
    stats = compute_ic_hac_stats(series, ic_col="ic", label_horizon=2, maxlags=2)
    ic_values = series["ic"].drop_nulls().to_numpy()
    return {
        "stats": {k: (float(v) if isinstance(v, (float, np.floating)) and math.isfinite(v) else
                      int(v) if isinstance(v, (int, np.integer)) else v)
                  for k, v in stats.items()},
        "ic_ir": float(np.mean(ic_values) / np.std(ic_values, ddof=1))
        if len(ic_values) > 1 and np.std(ic_values, ddof=1) > 0 else None,
        "dates": series.height,
        "series": series,
        "prediction_rows": pred.height,
    }


def _cycle_eligibility(panel: pl.DataFrame) -> pl.DataFrame:
    return (
        panel.group_by("decision_ts")
        .agg(
            pl.len().alias("top40_rows"),
            ((pl.col("cum_funding_24h") > SHORT_FUNDING_MIN)
             & (pl.col("xs_return_diff_24h") <= 0)).sum().alias("short_qualifiers"),
            ((pl.col("cum_funding_24h") < 0)
             & (pl.col("xs_return_diff_24h") >= 0)).sum().alias("strict_long_qualifiers"),
            (pl.col("xs_return_diff_24h") >= 0).sum().alias("resilient_long_pool"),
        )
        .with_columns(
            ((pl.col("top40_rows") >= TOP_N)
             & (pl.col("short_qualifiers") >= 3)
             & (pl.col("resilient_long_pool") >= 3)).alias("basket_eligible")
        )
        .sort("decision_ts")
    )


def run() -> None:
    frozen = ROOT / "run_log" / "research_sessions" / SESSION / "frozen_spec.json"
    if not frozen.exists():
        raise RuntimeError("Freeze the research session before diagnostic outcomes")
    if (OUT / "ic_gate_result.json").exists():
        raise FileExistsError("Terminal IC-gate evidence already exists; do not overwrite")
    prices, funding = load_bounded()
    panel = decision_panel(prices, funding)
    if panel.is_empty():
        raise RuntimeError("No causal matched decision panel")
    OUT.mkdir(parents=True, exist_ok=True)
    panel.write_parquet(OUT / "diagnostic_panel.parquet")

    candidate = _ic_stats(panel, "candidate_score")
    baseline = _ic_stats(panel, "baseline_score")
    candidate["series"].write_csv(OUT / "candidate_ic_series.csv")
    baseline["series"].write_csv(OUT / "baseline_ic_series.csv")
    candidate.pop("series")
    baseline.pop("series")

    cycles = _cycle_eligibility(panel)
    cycles.write_csv(OUT / "cycle_eligibility.csv")
    eligible_cycles = int(cycles["basket_eligible"].sum())
    min_top40 = int(cycles["top40_rows"].min()) if cycles.height else 0

    cstats = candidate["stats"]
    mean_ic = float(cstats.get("mean_ic", float("nan")))
    t_stat = float(cstats.get("t_stat", float("nan")))

    data_reasons = []
    economic_reasons = []
    if min_top40 < TOP_N:
        data_reasons.append(f"point-in-time matched universe falls below {TOP_N}")
    if eligible_cycles < MIN_CYCLES:
        economic_reasons.append(f"eligible 48h basket cycles {eligible_cycles} < {MIN_CYCLES}")
    if not math.isfinite(mean_ic) or mean_ic < IC_MIN:
        economic_reasons.append(f"candidate mean IC {mean_ic:.6f} < {IC_MIN:.3f}")
    if not math.isfinite(t_stat) or t_stat < IC_T_MIN:
        economic_reasons.append(f"candidate HAC t-stat {t_stat:.3f} < {IC_T_MIN:.1f}")

    # Data-contract failure takes precedence over an economic rejection because
    # the exact preregistered Top-40 experiment was not observed on all dates.
    verdict = "INCONCLUSIVE" if data_reasons else ("REJECT" if economic_reasons else "VALIDATE")
    reasons = data_reasons + economic_reasons
    # VALIDATE here means the diagnostic survived and the native portfolio trial
    # is the next required MVP step; it is not deployment approval.
    result = {
        "session": SESSION,
        "classification": "EXPLORATORY",
        "approval_status": "NOT_APPROVED",
        "development_start": DEV_START.isoformat(),
        "development_end_exclusive": DEV_END.isoformat(),
        "protected_2024_plus_accessed": False,
        "panel_rows": panel.height,
        "decision_dates": panel["decision_ts"].n_unique(),
        "matched_symbols": panel["symbol"].n_unique(),
        "min_top40_rows": min_top40,
        "eligible_basket_cycles": eligible_cycles,
        "candidate": candidate,
        "baseline": baseline,
        "ic_gate": {"mean_ic_min": IC_MIN, "hac_t_min": IC_T_MIN, "min_cycles": MIN_CYCLES},
        "decision": verdict,
        "reasons": reasons,
        "portfolio_stage_executed": False,
        "portfolio_stage_reason": (
            "Skipped because the preregistered data contract was not satisfied."
            if verdict == "INCONCLUSIVE"
            else "Skipped by preregistered fail-fast rule because IC gate rejected."
            if verdict == "REJECT"
            else "Required next: native ml4t.backtest candidate vs baseline with exact funding accounting qualification."
        ),
    }
    write_json(OUT / "ic_gate_result.json", result)

    report = [
        "# Cross-sectional funding carry + exhaustion MVP",
        "",
        f"**Decision: {verdict}.**",
        "",
        "## Diagnostic gate",
        f"- Development: 2020-06-01 to 2023-12-31. 2024+ not accessed.",
        f"- Matched decision-panel rows: {panel.height:,}.",
        f"- Decision dates: {result['decision_dates']}.",
        f"- Eligible 48h basket cycles: {eligible_cycles}.",
        f"- Candidate mean rank IC: {mean_ic:.6f}.",
        f"- Candidate HAC t-stat: {t_stat:.3f}.",
        f"- Candidate IC IR: {candidate['ic_ir']}.",
        f"- Baseline mean rank IC: {baseline['stats'].get('mean_ic')}.",
        f"- Baseline HAC t-stat: {baseline['stats'].get('t_stat')}.",
        "",
        "## Decision reasons",
    ]
    report.extend([f"- {r}" for r in reasons] or ["- Diagnostic gate passed; portfolio stage is still required."])
    report.extend([
        "",
        "## Integrity",
        "- Native ml4t.engineer ROCP(24) and ATR(24) are used per symbol.",
        "- Rank IC and HAC statistics use ml4t.diagnostic.",
        "- The point-in-time universe uses only trailing 720 completed 1h bars.",
        "- 00:00 funding events are accepted only if observed by 00:01; fills are labeled from 01:00 next-hour open.",
        "- This runner does not load any 2024+ price or funding partition.",
        "- No custom backtest simulator is used.",
        "",
    ])
    (OUT / "final_report.md").write_text("\n".join(report))
    print(json.dumps({"decision": verdict, "mean_ic": mean_ic, "t_stat": t_stat,
                      "eligible_cycles": eligible_cycles, "reasons": reasons}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.prepare == args.run:
        parser.error("Choose exactly one of --prepare or --run")
    if args.prepare:
        prepare()
    else:
        run()


if __name__ == "__main__":
    main()
