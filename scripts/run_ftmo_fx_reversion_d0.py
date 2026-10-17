"""Run the preregistered D0 event diagnostic for FTMO FX intraday reversion.

This script reads development data only. It never opens the frozen holdout files.
The diagnostic tests the fixed 60-minute fade return after completed 30-minute
five-bar range extremes. It is not a strategy backtest.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import statsmodels.api as sm

from ml4t.diagnostic.evaluation.stats import compute_return_statistics

ROOT = Path(__file__).resolve().parents[1]
SESSION_ID = "ftmo_fx_intraday_reversion_202610_v2"
TRIAL_ID = "D0_raw_event_diagnostic"
DATA_DIR = ROOT / "data/processed/ftmo_fx_reversion_202610"
OUT_DIR = ROOT / "run_log/ftmo_fx_intraday_reversion_202610_v2/D0_raw_event_diagnostic"
RESULT_PATH = OUT_DIR / "result.json"
EVENTS_PATH = OUT_DIR / "events.parquet"

SYMBOLS = ("EURUSD", "GBPUSD", "AUDUSD")
DEV_FILES = {
    symbol: (
        DATA_DIR / f"{symbol}_dev_2010_2017_5m.parquet",
        DATA_DIR / f"{symbol}_dev_2018_2024_5m.parquet",
    )
    for symbol in SYMBOLS
}
ROUND_TRIP_COST_BPS = 1.50
ROUND_TRIP_COST = ROUND_TRIP_COST_BPS / 10_000.0
HAC_MAXLAGS = 2
RESET_TIMEZONE = "Europe/Prague"
DEV_END_EXCLUSIVE = pl.datetime(2025, 1, 1, time_zone="UTC")


def _finite(value: float) -> float:
    if not math.isfinite(float(value)):
        raise ValueError(f"non-finite metric: {value}")
    return float(value)


def _hac_mean_stats(
    frame: pl.DataFrame,
    value_col: str,
    time_col: str,
    maxlags: int,
) -> dict[str, float | int | list[float]]:
    """Estimate an event-weighted mean with Newey-West HAC covariance.

    Contemporaneous multi-pair events are collapsed to timestamp cells. WLS weights
    each cell by its event count, so the intercept remains the pooled event mean.
    """
    grouped = (
        frame.group_by(time_col)
        .agg(
            pl.col(value_col).sum().alias("sum_value"),
            pl.len().alias("event_count"),
        )
        .sort(time_col)
        .with_columns(
            (pl.col("sum_value") / pl.col("event_count")).alias("cell_mean")
        )
    )
    if grouped.height < 4:
        raise ValueError("need at least four timestamp cells for HAC inference")

    y = grouped["cell_mean"].to_numpy()
    weights = grouped["event_count"].to_numpy().astype(float)
    x = np.ones((len(y), 1), dtype=float)
    lags = min(maxlags, max(1, len(y) // 2))

    fit = sm.WLS(y, x, weights=weights).fit(
        cov_type="HAC",
        cov_kwds={"maxlags": lags},
    )
    mean_value = float(fit.params[0])
    se = float(fit.bse[0])
    ci_low = mean_value - 1.96 * se
    ci_high = mean_value + 1.96 * se

    return {
        "n_events": int(frame.height),
        "n_timestamp_cells": int(grouped.height),
        "mean": _finite(mean_value),
        "hac_se": _finite(se),
        "hac_t_stat": _finite(float(fit.tvalues[0])),
        "hac_p_value": _finite(float(fit.pvalues[0])),
        "hac_maxlags": int(lags),
        "ci_95": [_finite(ci_low), _finite(ci_high)],
    }


def _build_symbol_events(symbol: str) -> pl.DataFrame:
    paths = DEV_FILES[symbol]
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
        if "holdout" in path.name.lower():
            raise RuntimeError(f"holdout path forbidden: {path}")

    bars5 = (
        pl.concat([pl.read_parquet(path) for path in paths], how="vertical")
        .filter(pl.col("timestamp") < DEV_END_EXCLUSIVE)
        .sort("timestamp")
    )
    if bars5.is_empty():
        raise RuntimeError(f"no development rows for {symbol}")
    if bars5["timestamp"].n_unique() != bars5.height:
        raise RuntimeError(f"duplicate 5m timestamps for {symbol}")
    if bars5["timestamp"].max().year >= 2025:
        raise RuntimeError(f"holdout leakage detected for {symbol}")

    bars30 = (
        bars5.group_by_dynamic(
            "timestamp",
            every="30m",
            period="30m",
            closed="left",
            label="left",
        )
        .agg(
            pl.col("open").first().alias("open"),
            pl.col("high").max().alias("high"),
            pl.col("low").min().alias("low"),
            pl.col("close").last().alias("close"),
            pl.col("volume").sum().alias("volume"),
            pl.len().alias("n_5m"),
            pl.col("source_rows").sum().alias("source_1m_rows"),
        )
        .filter((pl.col("n_5m") == 6) & (pl.col("source_1m_rows") == 30))
        .sort("timestamp")
        .with_columns(
            pl.col("high").rolling_max(window_size=5).shift(1).alias("prior_5bar_high"),
            pl.col("low").rolling_min(window_size=5).shift(1).alias("prior_5bar_low"),
        )
        .with_columns(
            pl.when(pl.col("close") > pl.col("prior_5bar_high"))
            .then(pl.lit(-1))
            .when(pl.col("close") < pl.col("prior_5bar_low"))
            .then(pl.lit(1))
            .otherwise(pl.lit(0))
            .alias("fade_direction")
        )
        .filter(pl.col("fade_direction") != 0)
        .with_columns(
            (pl.col("timestamp") + pl.duration(minutes=30)).alias("entry_timestamp"),
            pl.when(pl.col("fade_direction") == 1)
            .then(pl.lit("downside_extreme"))
            .otherwise(pl.lit("upside_extreme"))
            .alias("event_type"),
        )
    )

    price_lookup = bars5.select(
        pl.col("timestamp"),
        pl.col("open").alias("lookup_open"),
    )

    events = (
        bars30.join(
            price_lookup,
            left_on="entry_timestamp",
            right_on="timestamp",
            how="inner",
        )
        .rename({"lookup_open": "entry_open"})
        .with_columns(
            (pl.col("entry_timestamp") + pl.duration(minutes=60)).alias("exit_timestamp")
        )
        .join(
            price_lookup,
            left_on="exit_timestamp",
            right_on="timestamp",
            how="inner",
        )
        .rename({"lookup_open": "exit_open"})
        .with_columns(
            pl.col("entry_timestamp")
            .dt.convert_time_zone(RESET_TIMEZONE)
            .dt.date()
            .alias("entry_local_date"),
            pl.col("exit_timestamp")
            .dt.convert_time_zone(RESET_TIMEZONE)
            .dt.date()
            .alias("exit_local_date"),
        )
        .filter(pl.col("entry_local_date") == pl.col("exit_local_date"))
        .with_columns(
            pl.lit(symbol).alias("symbol"),
            (
                pl.col("fade_direction")
                * (pl.col("exit_open") / pl.col("entry_open") - 1.0)
            ).alias("gross_fade_return"),
        )
        .with_columns(
            (pl.col("gross_fade_return") - ROUND_TRIP_COST).alias("net_fade_return"),
            pl.col("entry_timestamp")
            .dt.convert_time_zone(RESET_TIMEZONE)
            .dt.year()
            .alias("local_year"),
        )
        .with_columns(
            pl.when(pl.col("local_year") <= 2013)
            .then(pl.lit("2010-2013"))
            .when(pl.col("local_year") <= 2017)
            .then(pl.lit("2014-2017"))
            .when(pl.col("local_year") <= 2021)
            .then(pl.lit("2018-2021"))
            .otherwise(pl.lit("2022-2024"))
            .alias("era")
        )
        .select(
            "symbol",
            "event_type",
            "fade_direction",
            "timestamp",
            "entry_timestamp",
            "exit_timestamp",
            "entry_open",
            "exit_open",
            "gross_fade_return",
            "net_fade_return",
            "era",
        )
        .sort("entry_timestamp")
    )
    if events.is_empty():
        raise RuntimeError(f"no eligible D0 events for {symbol}")
    if events["exit_timestamp"].max().year >= 2025:
        raise RuntimeError(f"holdout exit detected for {symbol}")
    return events


def _bps(value: float) -> float:
    return _finite(value * 10_000.0)


def _summary(frame: pl.DataFrame) -> dict[str, Any]:
    stats = _hac_mean_stats(frame, "net_fade_return", "entry_timestamp", HAC_MAXLAGS)
    gross_mean = float(frame["gross_fade_return"].mean())
    net_mean = float(frame["net_fade_return"].mean())
    native_sharpe, skewness, kurtosis, autocorr, n_samples = compute_return_statistics(
        frame["net_fade_return"].to_numpy()
    )
    return {
        "events": int(frame.height),
        "mean_gross_bps": _bps(gross_mean),
        "mean_net_bps": _bps(net_mean),
        "cost_drag_bps": _bps(gross_mean - net_mean),
        "hac_se_bps": _bps(float(stats["hac_se"])),
        "hac_t_stat": float(stats["hac_t_stat"]),
        "hac_p_value": float(stats["hac_p_value"]),
        "hac_ci_95_bps": [
            _bps(float(stats["ci_95"][0])),
            _bps(float(stats["ci_95"][1])),
        ],
        "hac_maxlags": int(stats["hac_maxlags"]),
        "timestamp_cells": int(stats["n_timestamp_cells"]),
        "native_event_sharpe": _finite(native_sharpe),
        "skewness": _finite(skewness),
        "kurtosis": _finite(kurtosis),
        "lag1_autocorrelation": _finite(autocorr),
        "return_observations": int(n_samples),
    }


def run() -> dict[str, Any]:
    frozen = ROOT / f"run_log/research_sessions/{SESSION_ID}/frozen_spec.json"
    if not frozen.is_file():
        raise RuntimeError(f"frozen session missing: {frozen}")

    events = pl.concat([_build_symbol_events(symbol) for symbol in SYMBOLS], how="vertical")
    events = events.sort(["entry_timestamp", "symbol"])

    pooled = _summary(events)
    by_pair = {
        symbol: _summary(events.filter(pl.col("symbol") == symbol))
        for symbol in SYMBOLS
    }
    by_era = {}
    for era in ("2010-2013", "2014-2017", "2018-2021", "2022-2024"):
        subset = events.filter(pl.col("era") == era)
        by_era[era] = {
            "events": int(subset.height),
            "mean_net_bps": _bps(float(subset["net_fade_return"].mean())),
            "mean_gross_bps": _bps(float(subset["gross_fade_return"].mean())),
        }

    pair_positive_count = sum(item["mean_net_bps"] > 0 for item in by_pair.values())
    era_positive_count = sum(item["mean_net_bps"] > 0 for item in by_era.values())
    pooled_ci_positive = pooled["hac_ci_95_bps"][0] > 0

    checks = {
        "pooled_net_mean_positive": pooled["mean_net_bps"] > 0,
        "pooled_hac_95_ci_excludes_zero_positive": pooled_ci_positive,
        "at_least_2_of_3_pairs_positive": pair_positive_count >= 2,
        "at_least_3_of_4_eras_positive": era_positive_count >= 3,
    }
    passed = all(checks.values())

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    events.write_parquet(EVENTS_PATH, compression="zstd")

    return {
        "schema_version": "ftmo-fx-reversion-d0-v1",
        "session_id": SESSION_ID,
        "trial_id": TRIAL_ID,
        "classification": "EXPLORATORY",
        "approval_status": "NOT_APPROVED",
        "trial_execution_status": "completed",
        "thesis_falsifier_verdict": "PASS" if passed else "REJECT",
        "holdout_scored": False,
        "holdout_opened_by_runner": False,
        "development_end_exclusive": "2025-01-01T00:00:00Z",
        "method": {
            "signal_bar": "30m from six complete 5m bars",
            "event": "close beyond prior five completed 30m highs/lows",
            "direction": "fade the extreme",
            "entry": "open of the immediately following 5m bar",
            "exit": "open exactly 60 minutes after entry",
            "eligibility": (
                "exact entry and exit timestamps must exist and both must be in the "
                "same Europe/Prague calendar day"
            ),
            "round_trip_cost_bps": ROUND_TRIP_COST_BPS,
            "hac": (
                "Newey-West HAC via statsmodels WLS on contemporaneous timestamp cells; "
                "event-count weights preserve pooled event expectancy"
            ),
            "hac_maxlags": HAC_MAXLAGS,
            "hac_lag_rationale": "60m forward horizon / 30m signal cadence = 2",
            "distribution_stats": "ml4t.diagnostic.evaluation.stats.compute_return_statistics",
        },
        "pooled": pooled,
        "by_pair": by_pair,
        "by_era": by_era,
        "pair_positive_count": int(pair_positive_count),
        "era_positive_count": int(era_positive_count),
        "falsifier_checks": checks,
        "events_artifact": EVENTS_PATH.relative_to(ROOT).as_posix(),
        "next_action": (
            "T1_raw_fade_baseline is eligible to proceed."
            if passed
            else "Stop this strategy family. Do not run T1 under this thesis."
        ),
    }


def main() -> None:
    result = run()
    RESULT_PATH.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
