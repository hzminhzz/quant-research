"""One pre-registered FX support-hold -> new-high event diagnostic.

No order simulation or trade-return model is used. All input price files are
development-only. The 2025-2026 holdout is never loaded in this script.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import polars as pl
import statsmodels.api as sm
from numpy.lib.stride_tricks import sliding_window_view
from statsmodels.stats.proportion import proportion_confint

ROOT = Path(__file__).resolve().parents[1]
SESSION_ID = "fx_support_reclaim_newhigh_20261008"
TRIAL_ID = "D0_support_hold_new_high"
OUT = ROOT / "run_log" / SESSION_ID / TRIAL_ID
RESULT_FILE = OUT / "result.json"
EVENT_FILE = OUT / "event_labels.parquet"
SYMBOLS = ("EURUSD", "GBPUSD", "AUDUSD")
INPUT_DIR = ROOT / "data/processed/ftmo_fx_reversion_202610"

PREVIOUS_HIGH_BARS = 40
SUPPORT_BARS = 12
ATR_BARS = 20
PIVOT_RIGHT_BARS = 3
BREAKOUT_ATR_MULT = 0.5
LAUNCH_ATR_MULT = 2.0
RETEST_ATR_TOLERANCE = 0.25
MAX_RETEST_BARS = 60
HORIZONS = (48, 240, 960)
MAX_HORIZON = 960
ONE_TICK = 0.00001
DEVELOPMENT_END = "2025-01-01T00:00:00Z"
ERAS = ((2010, 2013), (2014, 2017), (2018, 2021), (2022, 2024))


def _read_development(symbol: str) -> pl.DataFrame:
    filenames = [
        INPUT_DIR / f"{symbol}_dev_2010_2017_5m.parquet",
        INPUT_DIR / f"{symbol}_dev_2018_2024_5m.parquet",
    ]
    if any(not p.exists() or "holdout" in p.name for p in filenames):
        raise RuntimeError("Missing development file or attempted holdout read")
    frame = (
        pl.concat([pl.scan_parquet(p) for p in filenames], how="vertical")
        .sort("timestamp")
        .filter(pl.col("timestamp") < pl.lit(DEVELOPMENT_END).str.to_datetime(time_zone="UTC"))
        .collect()
    )
    if frame.is_empty() or frame["timestamp"].n_unique() != frame.height:
        raise RuntimeError(f"invalid development dataset for {symbol}")
    if set(frame["symbol"].unique().to_list()) != {symbol}:
        raise RuntimeError(f"wrong instrument data for {symbol}")
    if frame["timestamp"].max().year > 2024:
        raise RuntimeError("Holdout leakage")
    return frame


def _build_complete_30m(bars: pl.DataFrame) -> pl.DataFrame:
    result = (
        bars.group_by_dynamic(
            "timestamp", every="30m", period="30m", closed="left", label="left"
        )
        .agg(
            pl.col("open").first().alias("open"),
            pl.col("high").max().alias("high"),
            pl.col("low").min().alias("low"),
            pl.col("close").last().alias("close"),
            pl.len().alias("component_5m_bars"),
            pl.col("source_rows").sum().alias("component_1m_bars"),
        )
        .filter(
            (pl.col("component_5m_bars") == 6)
            & (pl.col("component_1m_bars") == 30)
        )
        .sort("timestamp")
        .with_columns(
            pl.max_horizontal(
                pl.col("high") - pl.col("low"),
                (pl.col("high") - pl.col("close").shift(1)).abs(),
                (pl.col("low") - pl.col("close").shift(1)).abs(),
            ).alias("true_range"),
            pl.col("high").rolling_max(PREVIOUS_HIGH_BARS).shift(1).alias("prior_40_high"),
            pl.col("low").rolling_min(SUPPORT_BARS).shift(1).alias("support"),
        )
        .with_columns(
            pl.col("true_range").rolling_mean(ATR_BARS).alias("atr20")
        )
    )
    if result.is_empty() or result["timestamp"].n_unique() != result.height:
        raise RuntimeError("invalid complete 30m bars")
    return result


def _candidate_pivots(bars30: pl.DataFrame) -> np.ndarray:
    highs = bars30["high"].to_numpy()
    prior = bars30["prior_40_high"].to_numpy()
    atr = bars30["atr20"].to_numpy()
    support = bars30["support"].to_numpy()
    n = len(highs)

    # Future bars confirm the pivot. The signal cannot occur until index h+3.
    candidate = np.isfinite(prior) & np.isfinite(atr) & np.isfinite(support)
    candidate &= (highs > prior + BREAKOUT_ATR_MULT * atr)
    candidate &= (highs - support >= LAUNCH_ATR_MULT * atr)
    for r in range(1, PIVOT_RIGHT_BARS + 1):
        # h+r may not exist at the tail: those indices remain ineligible.
        candidate[:-r] &= highs[:-r] > highs[r:]
    candidate[n - PIVOT_RIGHT_BARS :] = False
    return np.flatnonzero(candidate)


def _select_first_retests(bars30: pl.DataFrame) -> pl.DataFrame:
    """Vectorized first-touch extraction, not a trade simulation."""
    highs = bars30["high"].to_numpy()
    lows = bars30["low"].to_numpy()
    closes = bars30["close"].to_numpy()
    supports = bars30["support"].to_numpy()
    atr = bars30["atr20"].to_numpy()
    pivots = _candidate_pivots(bars30)

    if len(pivots) == 0:
        return pl.DataFrame()

    confirmations = pivots + PIVOT_RIGHT_BARS
    next_confirm = np.concatenate([confirmations[1:], [len(highs)]])
    offsets = np.arange(1, MAX_RETEST_BARS + 1, dtype=np.int64)
    retest_index = confirmations[:, None] + offsets[None, :]
    inside = (
        (retest_index < next_confirm[:, None])
        & (retest_index < len(highs))
    )
    safe_index = np.minimum(retest_index, len(highs) - 1)
    support_level = supports[pivots]
    high_level = highs[pivots]
    touches = inside & (
        lows[safe_index] <= support_level[:, None]
        + RETEST_ATR_TOLERANCE * atr[pivots, None]
    )
    high_already_retaken = inside & (highs[safe_index] > high_level[:, None] + ONE_TICK)
    first_touch_offset = np.where(touches, offsets[None, :], MAX_RETEST_BARS + 1).min(axis=1)
    first_high_offset = np.where(high_already_retaken, offsets[None, :], MAX_RETEST_BARS + 1).min(axis=1)
    eligible = (
        (first_touch_offset <= MAX_RETEST_BARS)
        & (first_touch_offset < first_high_offset)
    )
    pivots = pivots[eligible]
    confirmation = confirmations[eligible]
    touches_at = confirmation + first_touch_offset[eligible]

    # Full follow-up must fit within development; never use holdout bars.
    full_horizon = touches_at + MAX_HORIZON < len(highs)
    pivots = pivots[full_horizon]
    touches_at = touches_at[full_horizon]
    if len(pivots) == 0:
        return pl.DataFrame()

    h = highs[pivots]
    s = supports[pivots]
    close_on_touch = closes[touches_at]
    held = close_on_touch > s

    # Row i starts at the first bar strictly after the completed signal bar.
    fw_high = sliding_window_view(highs, MAX_HORIZON)[touches_at + 1]
    fw_close = sliding_window_view(closes, MAX_HORIZON)[touches_at + 1]
    hit = fw_high > (h[:, None] + ONE_TICK)
    invalid = fw_close < s[:, None]
    first_high = np.where(hit.any(axis=1), hit.argmax(axis=1) + 1, MAX_HORIZON + 1)
    first_invalid = np.where(invalid.any(axis=1), invalid.argmax(axis=1) + 1, MAX_HORIZON + 1)

    event_ts = bars30["timestamp"].gather(pl.Series(touches_at.astype(np.uint32))).to_list()
    high_ts = bars30["timestamp"].gather(pl.Series(pivots.astype(np.uint32))).to_list()
    result = pl.DataFrame(
        {
            "event_timestamp": event_ts,
            "reference_high_timestamp": high_ts,
            "reference_high": h,
            "origin_support": s,
            "close_on_touch": close_on_touch,
            "support_held": held,
            "first_new_high_bars": first_high,
            "first_support_invalid_bars": first_invalid,
            "within_48_bars": first_high <= 48,
            "within_240_bars": first_high <= 240,
            "within_960_bars": first_high <= 960,
            "target_before_support_invalidation_240": (
                (first_high <= 240) & (first_high < first_invalid)
            ),
        },
        schema_overrides={
            "event_timestamp": pl.Datetime(time_zone="UTC"),
            "reference_high_timestamp": pl.Datetime(time_zone="UTC"),
        },
    )
    return result.with_columns(
        pl.col("event_timestamp").dt.year().alias("year"),
        pl.col("event_timestamp").dt.strftime("%Y-%m").alias("month"),
    )


def _rate(rows: pl.DataFrame, col: str) -> dict[str, object] | None:
    if rows.height == 0:
        return None
    n = rows.height
    hits = int(rows[col].sum())
    lower, upper = proportion_confint(hits, n, alpha=0.05, method="wilson")
    return {
        "n": n,
        "hits": hits,
        "rate_pct": 100.0 * hits / n,
        "wilson_95_pct": [100.0 * float(lower), 100.0 * float(upper)],
    }


def _cluster_intercept(
    rows: pl.DataFrame, col: str
) -> dict[str, object] | None:
    if rows.height < 4 or rows["month"].n_unique() < 4:
        return None
    y = rows[col].cast(pl.Int8).to_numpy().astype(float)
    fit = sm.OLS(y, np.ones((len(y), 1))).fit(
        cov_type="cluster", cov_kwds={"groups": rows["month"].to_numpy()}
    )
    mean, se = float(fit.params[0]), float(fit.bse[0])
    return {
        "rate_pct": 100 * mean,
        "se_cluster_pct": 100 * se,
        "cluster_months": rows["month"].n_unique(),
        "cluster_95_pct": [
            100 * max(0.0, mean - 1.96 * se),
            100 * min(1.0, mean + 1.96 * se),
        ],
    }


def _cluster_lift(rows: pl.DataFrame) -> dict[str, object] | None:
    hold = rows["support_held"].cast(pl.Int8).to_numpy().astype(float)
    if rows.height < 6 or len(np.unique(hold)) < 2 or rows["month"].n_unique() < 4:
        return None
    outcome = rows["within_240_bars"].cast(pl.Int8).to_numpy().astype(float)
    fit = sm.OLS(outcome, sm.add_constant(hold)).fit(
        cov_type="cluster", cov_kwds={"groups": rows["month"].to_numpy()}
    )
    diff, se = float(fit.params[1]), float(fit.bse[1])
    return {
        "hold_minus_break_lift_percentage_points": 100 * diff,
        "cluster_se_percentage_points": 100 * se,
        "cluster_95_pp": [100 * (diff - 1.96 * se), 100 * (diff + 1.96 * se)],
        "cluster_months": rows["month"].n_unique(),
    }


def _cohort_rates(rows: pl.DataFrame) -> dict[str, object]:
    hold = rows.filter(pl.col("support_held"))
    control = rows.filter(~pl.col("support_held"))
    return {
        "all_touches": rows.height,
        "hold_events": hold.height,
        "break_control_events": control.height,
        "hold_hit_rate": {str(h): _rate(hold, f"within_{h}_bars") for h in HORIZONS},
        "break_control_hit_rate": {
            str(h): _rate(control, f"within_{h}_bars") for h in HORIZONS
        },
        "hold_target_before_invalidation_240": _rate(
            hold, "target_before_support_invalidation_240"
        ),
    }


def run() -> dict[str, object]:
    freeze = ROOT / "run_log/research_sessions" / SESSION_ID / "frozen_spec.json"
    if not freeze.is_file():
        raise RuntimeError("Immutable session must be initialized before event evaluation")
    frozen = json.loads(freeze.read_text(encoding="utf-8"))
    if frozen["session_id"] != SESSION_ID:
        raise RuntimeError("Session identity mismatch")
    if RESULT_FILE.exists() or EVENT_FILE.exists():
        raise RuntimeError("Immutable D0 result already exists; no rerun/overwrite")

    by_symbol: list[pl.DataFrame] = []
    quality: dict[str, object] = {}
    for symbol in SYMBOLS:
        input_5m = _read_development(symbol)
        bars = _build_complete_30m(input_5m)
        pivots = _candidate_pivots(bars)
        event = _select_first_retests(bars)
        if event.is_empty():
            raise RuntimeError(f"No eligible events for {symbol}")
        by_symbol.append(event.with_columns(pl.lit(symbol).alias("symbol")))
        quality[symbol] = {
            "source_5m_bars": input_5m.height,
            "complete_30m_bars": bars.height,
            "confirmed_significant_high_candidates": len(pivots),
            "eligible_first_touches": event.height,
            "last_event": str(event["event_timestamp"].max()),
        }

    all_events = pl.concat(by_symbol).sort(["event_timestamp", "symbol"])
    holds = all_events.filter(pl.col("support_held"))
    breaks = all_events.filter(~pl.col("support_held"))
    pooled = _cohort_rates(all_events)
    pair_rates = {
        s: _cohort_rates(all_events.filter(pl.col("symbol") == s))
        for s in SYMBOLS
    }
    eras = {
        f"{lo}-{hi}": _cohort_rates(
            all_events.filter(pl.col("year").is_between(lo, hi))
        )
        for lo, hi in ERAS
    }
    held_cluster = _cluster_intercept(holds, "within_240_bars")
    control_cluster = _cluster_intercept(breaks, "within_240_bars")
    lift = _cluster_lift(all_events)

    if held_cluster is None or lift is None:
        verdict = "INCONCLUSIVE"
        checks: dict[str, bool] = {}
    else:
        n_hold = holds.height
        pair_n = [pair_rates[s]["hold_events"] for s in SYMBOLS]
        pair_rate = [
            pair_rates[s]["hold_hit_rate"]["240"]["rate_pct"]
            if pair_rates[s]["hold_hit_rate"]["240"] is not None else float("nan")
            for s in SYMBOLS
        ]
        checks = {
            "min_150_hold_events": n_hold >= 150,
            "min_30_holds_per_pair": all(n >= 30 for n in pair_n),
            "min_30_control_events": breaks.height >= 30,
            "pooled_hit_rate_at_least_90pct": pooled["hold_hit_rate"]["240"]["rate_pct"] >= 90.0,
            "cluster_95_lower_bound_above_80pct": held_cluster["cluster_95_pct"][0] > 80.0,
            "lift_at_least_10_percentage_points": lift["hold_minus_break_lift_percentage_points"] >= 10.0,
            "per_pair_hit_rate_at_least_80pct": all(r >= 80.0 for r in pair_rate),
        }
        sufficient = all(checks[k] for k in (
            "min_150_hold_events", "min_30_holds_per_pair", "min_30_control_events"
        ))
        verdict = ("PASS" if all(checks.values()) else "REJECT") if sufficient else "INCONCLUSIVE"

    OUT.mkdir(parents=True, exist_ok=False)
    all_events.write_parquet(EVENT_FILE, compression="zstd")
    results = {
        "schema_version": "support-origin-newhigh-v1",
        "session_id": SESSION_ID,
        "trial_id": TRIAL_ID,
        "trial_execution_status": "completed",
        "classification": "EXPLORATORY",
        "approval_status": "NOT_APPROVED",
        "hypothesis_verdict": verdict,
        "holdout_scored": False,
        "holdout_opened": False,
        "development_end_exclusive": DEVELOPMENT_END,
        "interpretation": (
            "Origin support from lowest low of the prior 12 complete 30m bars; "
            "significant H is a +0.5ATR breakout of prior 40-bar high confirmed 3 bars later; "
            "first support-zone retest closes above S; new high > H+1 tick after event"
        ),
        "primary_horizon": 240,
        "secondary_horizons": [48, 960],
        "quality": quality,
        "pooled": pooled,
        "per_symbol": pair_rates,
        "eras": eras,
        "held_primary_cluster_ci": held_cluster,
        "break_control_primary_cluster_ci": control_cluster,
        "primary_hit_rate_lift": lift,
        "preregistered_checks": checks,
        "event_ledger": EVENT_FILE.relative_to(ROOT).as_posix(),
        "limitations": [
            "Not a strategy backtest, fill simulation, or profit claim.",
            "Significant high and support are one explicit interpretation of ambiguous verbal definitions.",
            "Probability of a new high can be high even when payoffs after costs are negative.",
            "Overlapping horizons and correlated events limit independent evidence.",
            "Monthly clustered CI addresses within-calendar-month correlation but may understate longer-horizon dependence.",
            "Missing/partial 30m bars are excluded rather than filled.",
            "The same FX development years have been used for other hypotheses; these are exploratory results.",
        ],
    }
    RESULT_FILE.write_text(
        json.dumps(results, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(results, indent=2, sort_keys=True, allow_nan=False))
    return results


if __name__ == "__main__":
    run()
