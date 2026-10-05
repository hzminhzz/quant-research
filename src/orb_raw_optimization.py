"""Controlled optimization research around the corrected HK33/JP225 raw ORB.

The primary entry rule is treated as frozen.  The module runs six pre-registered
research families:
1) exit-management attribution on the frozen event ledger,
2) walk-forward factor bucket diagnostics,
3) causal volatility/correlation risk throttles,
4) 2026 regime forensics,
5) a small executable exit-parameter stability surface, and
6) rolling versus expanding strategy statistics.

2025-2026 is diagnostic only because prior research already opened that period.
No result from that period is eligible for parameter selection.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
import copy
import fcntl
from dataclasses import replace
from datetime import date, datetime, timedelta
from itertools import combinations
import json
import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import polars as pl
import yaml
from scipy import stats
from scipy.stats import wasserstein_distance

from src.eow_rebuild import (
    ORBTradeEvent,
    PreparedMarket,
    atomic_write_json,
    atomic_write_parquet,
    build_events,
    load_config as load_rebuild_config,
    parse_utc,
    preflight as rebuild_preflight,
    prepare_all_markets,
    sha256_file,
)
from src.experiment import compute_deflated_sharpe
from src.orb_ml_research import (
    enrich_events_with_point_in_time_features,
    portfolio_daily_mtm_sizes,
)
from src.session_calendar import last_exchange_session_of_week


class ORBRawOptimizationError(RuntimeError):
    """Fail-closed research contract error."""


def load_research_config(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text())
    if not isinstance(payload, dict):
        raise ORBRawOptimizationError("raw ORB optimization config must be a mapping")
    return payload


def _year(event: ORBTradeEvent) -> int:
    return parse_utc(event.decision_time).year


def _subset(
    events: Sequence[ORBTradeEvent],
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[ORBTradeEvent]:
    result = []
    for event in events:
        ts = parse_utc(event.decision_time)
        if start is not None and ts < start:
            continue
        if end is not None and ts > end:
            continue
        result.append(event)
    return result


def _restricted_rebuild_config(
    rebuild_config: dict[str, Any], universe: set[str]
) -> dict[str, Any]:
    restricted = copy.deepcopy(rebuild_config)
    restricted["data"]["instruments"] = [
        item
        for item in rebuild_config["data"]["instruments"]
        if str(item["symbol"]) in universe
    ]
    present = {str(item["symbol"]) for item in restricted["data"]["instruments"]}
    if present != universe:
        raise ORBRawOptimizationError(
            f"missing configured instruments: {sorted(universe - present)}"
        )
    return restricted


def _metrics(
    events: Sequence[ORBTradeEvent],
    markets: dict[str, PreparedMarket],
    *,
    risk_unit_pct: float,
    roundtrip_cost_bps: float,
    sizes: Sequence[float] | None = None,
) -> tuple[dict[str, Any], pl.DataFrame]:
    if sizes is None:
        sizes = np.ones(len(events), dtype=float)
    if len(events) == 0:
        return {
            "trades": 0,
            "net_r": 0.0,
            "win_rate_pct": 0.0,
            "mean_r": 0.0,
            "median_r": 0.0,
            "annualized_sharpe": 0.0,
            "max_drawdown": 0.0,
            "mean_size": 0.0,
        }, pl.DataFrame({"date": [], "return": [], "r_increment": []})

    daily, portfolio = portfolio_daily_mtm_sizes(
        events,
        sizes,
        markets,
        risk_unit_pct=risk_unit_pct,
        roundtrip_cost_bps=roundtrip_cost_bps,
    )
    r = np.asarray([event.r_multiple for event in events], dtype=float)
    weighted = r * np.asarray(sizes, dtype=float)
    exit_counts: dict[str, int] = {}
    for event in events:
        exit_counts[event.exit_reason] = exit_counts.get(event.exit_reason, 0) + 1
    by_symbol: dict[str, Any] = {}
    for symbol in sorted({event.symbol for event in events}):
        idx = [i for i, event in enumerate(events) if event.symbol == symbol]
        sr = r[idx]
        sw = np.asarray(sizes, dtype=float)[idx]
        by_symbol[symbol] = {
            "trades": len(idx),
            "net_r": float(np.sum(sr * sw)),
            "raw_net_r": float(np.sum(sr)),
            "win_rate_pct": float(np.mean(sr > 0) * 100.0),
            "mean_size": float(np.mean(sw)),
        }
    return {
        "trades": len(events),
        "net_r": float(np.sum(weighted)),
        "raw_net_r": float(np.sum(r)),
        "win_rate_pct": float(np.mean(r > 0) * 100.0),
        "mean_r": float(np.mean(weighted)),
        "median_r": float(np.median(weighted)),
        "annualized_sharpe": float(portfolio["annualized_sharpe"]),
        "max_drawdown": float(portfolio["max_drawdown"]),
        "mean_size": float(np.mean(sizes)),
        "risk_normalized_net_r": (
            float(np.sum(weighted)) / float(np.mean(sizes))
            if float(np.mean(sizes)) > 0
            else 0.0
        ),
        "exit_reasons": exit_counts,
        "by_symbol": by_symbol,
    }, daily


def _eow_index(market: PreparedMarket, session_date: date) -> int:
    scheduled = last_exchange_session_of_week(
        market.spec.exchange_calendar, session_date
    )
    indices = market.market_date_indices.get(scheduled)
    if indices:
        return indices[-1]
    monday = session_date - timedelta(days=session_date.weekday())
    observed = sorted(
        day
        for day in market.market_date_indices
        if monday <= day <= scheduled and day in market.scheduled_sessions
    )
    if not observed:
        raise ORBRawOptimizationError(
            f"{market.spec.symbol} {session_date}: no EOW session available"
        )
    return market.market_date_indices[observed[-1]][-1]


def _fixed_session_index(
    market: PreparedMarket, session_date: date, sessions: int
) -> int:
    available = sorted(
        day
        for day in market.scheduled_sessions
        if day >= session_date and day in market.market_date_indices
    )
    if not available:
        raise ORBRawOptimizationError(
            f"{market.spec.symbol} {session_date}: no future session"
        )
    target = available[min(max(sessions, 1) - 1, len(available) - 1)]
    return market.market_date_indices[target][-1]


def _entry_index(market: PreparedMarket, event: ORBTradeEvent) -> int:
    entry = parse_utc(event.entry_time)
    idx = bisect_left(market.timestamps, entry)
    if idx >= len(market.timestamps) or market.timestamps[idx] != entry:
        raise ORBRawOptimizationError(
            f"{event.symbol} {event.date}: entry timestamp missing from market"
        )
    return idx


def replay_exit(
    event: ORBTradeEvent,
    market: PreparedMarket,
    *,
    target_multiple: float,
    stop_multiple: float,
    breakeven_trigger_r: float,
    breakeven_offset_r: float,
    trailing_distance_r: float,
    use_target: bool = True,
    use_breakeven_step: bool = True,
    use_trailing: bool = True,
    fixed_hold_sessions: int | None = None,
    roundtrip_cost_bps: float,
) -> ORBTradeEvent:
    """Replay one frozen entry under alternative exit management."""
    entry_idx = _entry_index(market, event)
    end_idx = (
        _fixed_session_index(
            market, date.fromisoformat(event.date), fixed_hold_sessions
        )
        if fixed_hold_sessions is not None
        else _eow_index(market, date.fromisoformat(event.date))
    )
    if end_idx < entry_idx:
        raise ORBRawOptimizationError("exit horizon precedes entry")

    direction = int(event.direction)
    entry = float(event.entry_price)
    delta = float(event.delta)
    target = entry + direction * target_multiple * delta
    stop = entry - direction * stop_multiple * delta
    be_price = entry + direction * breakeven_offset_r * delta
    favorable = entry
    activated = False
    exit_price = float(market.closes[end_idx])
    exit_reason = "time_exit"
    exit_idx = end_idx

    for idx in range(entry_idx, end_idx + 1):
        high = float(market.highs[idx])
        low = float(market.lows[idx])
        close = float(market.closes[idx])
        hit_target = (
            (high >= target) if direction == 1 else (low <= target)
        ) if use_target else False
        hit_stop = (low <= stop) if direction == 1 else (high >= stop)

        if hit_target and hit_stop:
            exit_idx = idx
            exit_price = float(stop)
            exit_reason = "stop_loss_conflict"
            break
        if hit_stop:
            exit_idx = idx
            exit_price = float(stop)
            exit_reason = "stop_loss"
            break
        if hit_target:
            exit_idx = idx
            exit_price = float(target)
            exit_reason = "profit_target"
            break

        if direction == 1:
            favorable = max(favorable, high)
            if not activated and high >= entry + breakeven_trigger_r * delta:
                activated = True
                if use_breakeven_step:
                    stop = max(stop, be_price)
            if activated and use_trailing:
                stop = max(stop, favorable - trailing_distance_r * delta)
        else:
            favorable = min(favorable, low)
            if not activated and low <= entry - breakeven_trigger_r * delta:
                activated = True
                if use_breakeven_step:
                    stop = min(stop, be_price)
            if activated and use_trailing:
                stop = min(stop, favorable + trailing_distance_r * delta)

        if idx == end_idx:
            exit_idx = idx
            exit_price = close
            exit_reason = (
                "fixed_session_exit"
                if fixed_hold_sessions is not None
                else "eow_calendar_exit"
            )

    friction = roundtrip_cost_bps / 10_000.0
    raw_return = direction * (exit_price - entry) / entry - friction
    risk_fraction = delta / entry
    r_multiple = raw_return / risk_fraction
    return replace(
        event,
        exit_time=str(market.available_at[exit_idx]),
        exit_price=float(exit_price),
        upper_barrier=float(target),
        lower_barrier=float(stop),
        holding_bars=max(1, exit_idx - entry_idx + 1),
        exit_reason=exit_reason,
        label=1 if r_multiple > 0 else 0,
        realized_return=float(raw_return),
        r_multiple=float(r_multiple),
    )


def _replay_variant(
    events: Sequence[ORBTradeEvent],
    markets: dict[str, PreparedMarket],
    *,
    variant: str,
    base_strategy: dict[str, Any],
    fixed_hold_sessions: int,
    roundtrip_cost_bps: float,
) -> list[ORBTradeEvent]:
    if variant == "original":
        return list(events)

    kwargs: dict[str, Any] = {
        "target_multiple": float(base_strategy["target_multiple"]),
        "stop_multiple": float(base_strategy["stop_multiple"]),
        "breakeven_trigger_r": float(base_strategy["breakeven"]["trigger_r"]),
        "breakeven_offset_r": float(base_strategy["breakeven"]["offset_r"]),
        "trailing_distance_r": float(base_strategy["trailing"]["distance_r"]),
        "use_target": True,
        "use_breakeven_step": True,
        "use_trailing": True,
        "fixed_hold_sessions": None,
        "roundtrip_cost_bps": roundtrip_cost_bps,
    }
    if variant == "no_breakeven_step":
        kwargs["use_breakeven_step"] = False
    elif variant == "no_trailing":
        kwargs["use_trailing"] = False
    elif variant == "no_target":
        kwargs["use_target"] = False
    elif variant == "stop_eow_only":
        kwargs["use_target"] = False
        kwargs["use_breakeven_step"] = False
        kwargs["use_trailing"] = False
        kwargs["breakeven_trigger_r"] = 1e9
    elif variant == "fixed_3_session_hold":
        kwargs["fixed_hold_sessions"] = int(fixed_hold_sessions)
    else:
        raise ORBRawOptimizationError(f"unsupported exit attribution variant {variant}")

    return [
        replay_exit(event, markets[event.symbol], **kwargs)
        for event in events
    ]


def run_exit_attribution(
    events: Sequence[ORBTradeEvent],
    markets: dict[str, PreparedMarket],
    *,
    config: dict[str, Any],
    base_strategy: dict[str, Any],
    development_end: datetime,
    diagnostic_start: datetime,
    end: datetime,
    risk_unit_pct: float,
    roundtrip_cost_bps: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    results: dict[str, Any] = {}
    trial_records: list[dict[str, Any]] = []
    for variant in config["variants"]:
        replayed = _replay_variant(
            events,
            markets,
            variant=str(variant),
            base_strategy=base_strategy,
            fixed_hold_sessions=int(config["fixed_hold_sessions"]),
            roundtrip_cost_bps=roundtrip_cost_bps,
        )
        dev = _subset(replayed, end=development_end)
        diagnostic = _subset(
            replayed, start=diagnostic_start, end=end
        )
        dev_metrics, _ = _metrics(
            dev,
            markets,
            risk_unit_pct=risk_unit_pct,
            roundtrip_cost_bps=roundtrip_cost_bps,
        )
        diagnostic_metrics, _ = _metrics(
            diagnostic,
            markets,
            risk_unit_pct=risk_unit_pct,
            roundtrip_cost_bps=roundtrip_cost_bps,
        )
        results[str(variant)] = {
            "development_2017_2024": dev_metrics,
            "diagnostic_2025_2026": diagnostic_metrics,
            "diagnostic_used_for_selection": False,
            "entry_ledger_frozen": True,
            "caveat": (
                "Frozen-entry attribution isolates management mechanics. It does not "
                "create additional signals that a shorter exit might have made available."
            ),
        }
        trial_records.append(
            {
                "family": "exit_attribution",
                "variant": str(variant),
                "selection_trial": True,
                "sharpe": dev_metrics["annualized_sharpe"],
                "net_r": dev_metrics["net_r"],
            }
        )

    baseline = results["original"]["development_2017_2024"]
    for variant, payload in results.items():
        metric = payload["development_2017_2024"]
        metric["delta_net_r_vs_original"] = (
            metric["net_r"] - baseline["net_r"]
        )
        metric["delta_sharpe_vs_original"] = (
            metric["annualized_sharpe"] - baseline["annualized_sharpe"]
        )
        metric["delta_max_drawdown_vs_original"] = (
            metric["max_drawdown"] - baseline["max_drawdown"]
        )
    return {
        "schema_version": "orb_exit_attribution/v1",
        "selection_period": "2017-2024",
        "diagnostic_period": "2025-2026-07-31",
        "variants": results,
    }, trial_records


def _quantile_edges(values: np.ndarray, bins: int) -> np.ndarray:
    unique = np.unique(values)
    if len(unique) <= 1:
        return np.array([], dtype=float)
    if len(unique) <= bins:
        return (unique[:-1] + unique[1:]) / 2.0
    edges = np.quantile(values, np.arange(1, bins) / bins)
    return np.unique(edges)


def _bucket(values: np.ndarray, edges: np.ndarray) -> np.ndarray:
    return np.searchsorted(edges, values, side="right")


def _bucket_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"buckets": [], "monotonic_spearman": 0.0}
    frame = pl.DataFrame(rows)
    summary = (
        frame.group_by("bucket")
        .agg(
            pl.len().alias("trades"),
            pl.col("r_multiple").mean().alias("mean_r"),
            pl.col("r_multiple").sum().alias("net_r"),
            (pl.col("r_multiple") > 0).mean().mul(100.0).alias("win_rate_pct"),
            pl.col("feature_value").mean().alias("mean_feature"),
        )
        .sort("bucket")
    )
    buckets = summary["bucket"].to_numpy()
    means = summary["mean_r"].to_numpy()
    if len(buckets) >= 2 and np.std(means) > 1e-12:
        rho = stats.spearmanr(buckets, means).statistic
        monotonic = float(rho) if np.isfinite(rho) else 0.0
    else:
        monotonic = 0.0
    return {
        "buckets": summary.to_dicts(),
        "monotonic_spearman": monotonic,
        "spread_top_minus_bottom_r": (
            float(means[-1] - means[0]) if len(means) >= 2 else 0.0
        ),
    }


def run_factor_quintiles(
    events: Sequence[ORBTradeEvent],
    *,
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], pl.DataFrame]:
    evaluation_years = [int(y) for y in config["evaluation_years"]]
    bins = int(config["bins"])
    min_train = int(config["min_training_events"])
    feature_names = [str(name) for name in config["features"]]
    all_rows: list[dict[str, Any]] = []
    factor_results: dict[str, Any] = {}
    trials: list[dict[str, Any]] = []

    for feature in feature_names:
        rows: list[dict[str, Any]] = []
        fold_details: list[dict[str, Any]] = []
        for year in evaluation_years:
            training = [event for event in events if _year(event) < year]
            testing = [event for event in events if _year(event) == year]
            if not testing:
                continue
            if len(training) < min_train:
                raise ORBRawOptimizationError(
                    f"{feature}/{year}: insufficient training events"
                )
            train_values = np.asarray(
                [event.features[feature] for event in training], dtype=float
            )
            edges = _quantile_edges(train_values, bins)
            test_values = np.asarray(
                [event.features[feature] for event in testing], dtype=float
            )
            bucket_ids = _bucket(test_values, edges)
            fold_details.append(
                {
                    "year": year,
                    "train_count": len(training),
                    "test_count": len(testing),
                    "edges": edges.tolist(),
                    "effective_buckets": int(len(edges) + 1),
                }
            )
            for event, value, bucket_id in zip(
                testing, test_values, bucket_ids
            ):
                row = {
                    "feature": feature,
                    "year": year,
                    "symbol": event.symbol,
                    "decision_time": event.decision_time,
                    "bucket": int(bucket_id),
                    "feature_value": float(value),
                    "r_multiple": float(event.r_multiple),
                }
                rows.append(row)
                all_rows.append(row)

        aggregate = _bucket_summary(rows)
        yearly: dict[str, Any] = {}
        slope_signs: list[int] = []
        for year in evaluation_years:
            year_rows = [row for row in rows if row["year"] == year]
            if not year_rows:
                continue
            summary = _bucket_summary(year_rows)
            yearly[str(year)] = summary
            spread = float(summary["spread_top_minus_bottom_r"])
            slope_signs.append(1 if spread > 0 else (-1 if spread < 0 else 0))

        overall_spread = float(aggregate["spread_top_minus_bottom_r"])
        overall_sign = 1 if overall_spread > 0 else (-1 if overall_spread < 0 else 0)
        stable = (
            float(np.mean([sign == overall_sign for sign in slope_signs]))
            if slope_signs and overall_sign != 0
            else 0.0
        )
        factor_results[feature] = {
            **aggregate,
            "yearly": yearly,
            "walk_forward_folds": fold_details,
            "same_spread_sign_year_fraction": stable,
            "binary_or_low_cardinality": any(
                fold["effective_buckets"] < bins for fold in fold_details
            ),
        }
        trials.append(
            {
                "family": "factor_quintile",
                "variant": feature,
                "selection_trial": True,
                "monotonic_spearman": aggregate["monotonic_spearman"],
                "spread_top_minus_bottom_r": overall_spread,
            }
        )

    ordered = sorted(
        factor_results,
        key=lambda name: (
            abs(float(factor_results[name]["monotonic_spearman"]))
            * float(factor_results[name]["same_spread_sign_year_fraction"])
        ),
        reverse=True,
    )
    return {
        "schema_version": "orb_factor_quintiles/v1",
        "method": (
            "For each evaluation year, quantile edges are fit only on prior events "
            "and then applied to that year's OOS events."
        ),
        "selection_period": "2020-2024 walk-forward OOS",
        "features": factor_results,
        "descriptive_order": ordered,
    }, trials, pl.DataFrame(all_rows, infer_schema_length=None)


def _daily_close_map(market: PreparedMarket) -> tuple[list[date], np.ndarray]:
    dates: list[date] = []
    closes: list[float] = []
    for day in sorted(market.market_date_indices):
        indices = market.market_date_indices[day]
        if not indices:
            continue
        dates.append(day)
        closes.append(float(market.closes[indices[-1]]))
    return dates, np.asarray(closes, dtype=float)


def _vol_maps(
    market: PreparedMarket,
    windows: Sequence[int],
    *,
    min_history: int,
) -> dict[int, dict[date, float]]:
    dates, closes = _daily_close_map(market)
    returns = np.full(len(closes), np.nan, dtype=float)
    returns[1:] = closes[1:] / closes[:-1] - 1.0
    result: dict[int, dict[date, float]] = {}
    for window in windows:
        mapping: dict[date, float] = {}
        historical_vols: list[float] = []
        for idx, day in enumerate(dates):
            start = max(1, idx - int(window))
            sample = returns[start:idx]
            sample = sample[np.isfinite(sample)]
            current = (
                float(np.std(sample, ddof=1) * np.sqrt(252))
                if len(sample) >= max(10, int(window) // 2)
                else math.nan
            )
            if np.isfinite(current):
                historical_vols.append(current)
            if (
                np.isfinite(current)
                and len(historical_vols) >= min_history
            ):
                benchmark = float(np.median(historical_vols[:-1] or historical_vols))
                mapping[day] = benchmark / current if current > 0 else 1.0
            else:
                mapping[day] = 1.0
        result[int(window)] = mapping
    return result


def _correlation_map(
    left: PreparedMarket,
    right: PreparedMarket,
    *,
    window: int,
) -> dict[date, float]:
    left_dates, left_close = _daily_close_map(left)
    right_dates, right_close = _daily_close_map(right)
    lret = {
        left_dates[i]: float(left_close[i] / left_close[i - 1] - 1.0)
        for i in range(1, len(left_dates))
    }
    rret = {
        right_dates[i]: float(right_close[i] / right_close[i - 1] - 1.0)
        for i in range(1, len(right_dates))
    }
    common = sorted(set(lret) & set(rret))
    mapping: dict[date, float] = {}
    for idx, day in enumerate(common):
        prior = common[max(0, idx - window):idx]
        if len(prior) < max(10, window // 2):
            mapping[day] = 0.0
            continue
        x = np.asarray([lret[d] for d in prior], dtype=float)
        y = np.asarray([rret[d] for d in prior], dtype=float)
        corr = float(np.corrcoef(x, y)[0, 1])
        mapping[day] = corr if np.isfinite(corr) else 0.0
    return mapping


def _latest_on_or_before(mapping: dict[date, float], day: date, default: float) -> float:
    eligible = [key for key in mapping if key < day]
    if not eligible:
        return default
    return float(mapping[max(eligible)])


def run_risk_targeting(
    events: Sequence[ORBTradeEvent],
    markets: dict[str, PreparedMarket],
    *,
    config: dict[str, Any],
    development_end: datetime,
    diagnostic_start: datetime,
    end: datetime,
    risk_unit_pct: float,
    roundtrip_cost_bps: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    windows = [int(value) for value in config["volatility_windows"]]
    floor = float(config["size_floor"])
    ceiling = float(config["size_ceiling"])
    min_periods = int(config["expanding_median_min_periods"])
    vol_maps = {
        symbol: _vol_maps(
            market,
            windows,
            min_history=min_periods,
        )
        for symbol, market in markets.items()
    }
    symbols = sorted(markets)
    if len(symbols) != 2:
        raise ORBRawOptimizationError("correlation throttle expects exactly two assets")
    corr_map = _correlation_map(
        markets[symbols[0]],
        markets[symbols[1]],
        window=int(config["correlation_window"]),
    )
    corr_strength = float(config["correlation_strength"])

    variants: dict[str, np.ndarray] = {
        "raw": np.ones(len(events), dtype=float)
    }
    for window in windows:
        sizes = []
        for event in events:
            scalar = vol_maps[event.symbol][window].get(
                date.fromisoformat(event.date), 1.0
            )
            sizes.append(float(np.clip(scalar, floor, ceiling)))
        variants[f"vol_{window}d"] = np.asarray(sizes, dtype=float)

    anchor_window = 40 if 40 in windows else windows[len(windows) // 2]
    corr_sizes = []
    for idx, event in enumerate(events):
        vol_size = variants[f"vol_{anchor_window}d"][idx]
        corr = abs(
            _latest_on_or_before(
                corr_map, date.fromisoformat(event.date), 0.0
            )
        )
        corr_scalar = float(
            np.clip(1.0 - corr_strength * corr, floor, ceiling)
        )
        corr_sizes.append(max(floor, vol_size * corr_scalar))
    variants[f"vol_{anchor_window}d_corr_{int(config['correlation_window'])}d"] = (
        np.asarray(corr_sizes, dtype=float)
    )

    dev_indices = [
        i for i, event in enumerate(events)
        if parse_utc(event.decision_time) <= development_end
    ]
    diag_indices = [
        i for i, event in enumerate(events)
        if diagnostic_start <= parse_utc(event.decision_time) <= end
    ]
    results: dict[str, Any] = {}
    daily_by_variant: dict[str, pl.DataFrame] = {}
    trials: list[dict[str, Any]] = []
    for name, size_array in variants.items():
        dev_events = [events[i] for i in dev_indices]
        dev_sizes = size_array[dev_indices]
        diag_events = [events[i] for i in diag_indices]
        diag_sizes = size_array[diag_indices]
        dev_metrics, daily = _metrics(
            dev_events,
            markets,
            risk_unit_pct=risk_unit_pct,
            roundtrip_cost_bps=roundtrip_cost_bps,
            sizes=dev_sizes,
        )
        diag_metrics, _ = _metrics(
            diag_events,
            markets,
            risk_unit_pct=risk_unit_pct,
            roundtrip_cost_bps=roundtrip_cost_bps,
            sizes=diag_sizes,
        )
        results[name] = {
            "development_2017_2024": dev_metrics,
            "diagnostic_2025_2026": diag_metrics,
            "diagnostic_used_for_selection": False,
        }
        daily_by_variant[name] = daily
        trials.append(
            {
                "family": "risk_targeting",
                "variant": name,
                "selection_trial": True,
                "sharpe": dev_metrics["annualized_sharpe"],
                "net_r": dev_metrics["net_r"],
            }
        )

    sharpes = [
        float(results[name]["development_2017_2024"]["annualized_sharpe"])
        for name in variants
    ]
    for name in variants:
        daily = daily_by_variant[name]
        returns = daily["return"].to_numpy()
        results[name]["development_2017_2024"]["dsr_family"] = (
            compute_deflated_sharpe(
                float(results[name]["development_2017_2024"]["annualized_sharpe"]),
                sharpes,
                n_obs_days=max(len(returns), 2),
                skew=float(stats.skew(returns)) if len(returns) > 2 else 0.0,
                kurtosis=(
                    float(stats.kurtosis(returns, fisher=False))
                    if len(returns) > 3
                    else 3.0
                ),
            )
        )

    raw = results["raw"]["development_2017_2024"]
    candidates = []
    for name in variants:
        if name == "raw":
            continue
        metric = results[name]["development_2017_2024"]
        checks = {
            "sharpe_not_worse": metric["annualized_sharpe"] >= raw["annualized_sharpe"],
            "drawdown_not_worse": metric["max_drawdown"] >= raw["max_drawdown"],
            "risk_normalized_net_r_not_worse": (
                metric["risk_normalized_net_r"] >= raw["risk_normalized_net_r"]
            ),
        }
        results[name]["development_2017_2024"]["acceptance"] = checks
        if all(checks.values()):
            candidates.append(name)

    return {
        "schema_version": "orb_risk_targeting/v1",
        "selection_period": "2017-2024",
        "diagnostic_period": "2025-2026-07-31",
        "variants": results,
        "passing_development_variants": candidates,
        "production_approved": False,
        "policy": "Any passing variant still requires new prospective confirmation.",
    }, trials


def _path_excursions(
    event: ORBTradeEvent, market: PreparedMarket
) -> tuple[float, float]:
    entry_idx = _entry_index(market, event)
    exit_time = parse_utc(event.exit_time)
    right = bisect_right(market.available_at, exit_time)
    exit_idx = max(entry_idx, right - 1)
    highs = market.highs[entry_idx:exit_idx + 1]
    lows = market.lows[entry_idx:exit_idx + 1]
    if int(event.direction) == 1:
        mfe = (float(np.max(highs)) - event.entry_price) / event.delta
        mae = (float(np.min(lows)) - event.entry_price) / event.delta
    else:
        mfe = (event.entry_price - float(np.min(lows))) / event.delta
        mae = (event.entry_price - float(np.max(highs))) / event.delta
    return float(mfe), float(mae)


def _bh_adjust(p_values: dict[str, float]) -> dict[str, float]:
    names = list(p_values)
    if not names:
        return {}
    order = sorted(names, key=lambda name: p_values[name])
    m = len(order)
    adjusted: dict[str, float] = {}
    running = 1.0
    for rank_from_end, name in enumerate(reversed(order), start=1):
        rank = m - rank_from_end + 1
        value = min(1.0, p_values[name] * m / rank)
        running = min(running, value)
        adjusted[name] = running
    return adjusted


def run_2026_regime_forensics(
    events: Sequence[ORBTradeEvent],
    markets: dict[str, PreparedMarket],
    *,
    config: dict[str, Any],
    feature_names: Sequence[str],
) -> dict[str, Any]:
    current = [event for event in events if _year(event) == 2026]
    prior = [event for event in events if _year(event) < 2026]
    window = int(config["rolling_trade_window"])
    if len(current) != window:
        observed_window = len(current)
    else:
        observed_window = window
    observed = float(sum(event.r_multiple for event in current))

    prior_r = np.asarray([event.r_multiple for event in prior], dtype=float)
    rolling = np.asarray(
        [
            float(np.sum(prior_r[i:i + observed_window]))
            for i in range(0, len(prior_r) - observed_window + 1)
        ],
        dtype=float,
    )
    empirical_tail = (
        float(np.mean(rolling <= observed)) if len(rolling) else math.nan
    )

    rng = np.random.default_rng(int(config["random_seed"]))
    samples = int(config["bootstrap_samples"])
    block = int(config["bootstrap_block_trades"])
    bootstrap = np.zeros(samples, dtype=float)
    n = len(prior_r)
    for sample_idx in range(samples):
        values: list[float] = []
        while len(values) < observed_window:
            start = int(rng.integers(0, max(1, n - block + 1)))
            values.extend(prior_r[start:start + block].tolist())
        bootstrap[sample_idx] = float(np.sum(values[:observed_window]))
    bootstrap_tail = float(np.mean(bootstrap <= observed))

    p_values: dict[str, float] = {}
    feature_drift: dict[str, Any] = {}
    for feature in feature_names:
        x = np.asarray([event.features[feature] for event in prior], dtype=float)
        y = np.asarray([event.features[feature] for event in current], dtype=float)
        ks = stats.ks_2samp(x, y, alternative="two-sided", method="auto")
        p_values[feature] = float(ks.pvalue)
        std = float(np.std(x, ddof=1))
        feature_drift[feature] = {
            "prior_mean": float(np.mean(x)),
            "current_mean": float(np.mean(y)),
            "standardized_mean_shift": (
                float((np.mean(y) - np.mean(x)) / std) if std > 0 else 0.0
            ),
            "wasserstein_in_prior_sigma": (
                float(wasserstein_distance(x, y) / std) if std > 0 else 0.0
            ),
            "ks_stat": float(ks.statistic),
            "ks_p_value": float(ks.pvalue),
        }
    q_values = _bh_adjust(p_values)
    for feature, value in q_values.items():
        feature_drift[feature]["bh_q_value"] = float(value)
        feature_drift[feature]["fdr_significant"] = (
            value < float(config["fdr_alpha"])
        )

    prior_mfe_mae = np.asarray(
        [_path_excursions(event, markets[event.symbol]) for event in prior],
        dtype=float,
    )
    current_mfe_mae = np.asarray(
        [_path_excursions(event, markets[event.symbol]) for event in current],
        dtype=float,
    )
    mfe_test = stats.ks_2samp(
        prior_mfe_mae[:, 0], current_mfe_mae[:, 0]
    )
    mae_test = stats.ks_2samp(
        prior_mfe_mae[:, 1], current_mfe_mae[:, 1]
    )

    prior_wins = sum(event.r_multiple > 0 for event in prior)
    current_wins = sum(event.r_multiple > 0 for event in current)
    table = np.array(
        [
            [current_wins, len(current) - current_wins],
            [prior_wins, len(prior) - prior_wins],
        ]
    )
    fisher = stats.fisher_exact(table)

    significant_features = [
        feature
        for feature, payload in feature_drift.items()
        if payload["fdr_significant"]
    ]
    tail_event = bootstrap_tail < 0.05
    behavior_shift = (
        float(fisher.pvalue) < 0.05
        or float(mfe_test.pvalue) < 0.05
        or float(mae_test.pvalue) < 0.05
    )
    if tail_event and (len(significant_features) >= 2 or behavior_shift):
        assessment = "TAIL_DRAWDOWN_WITH_REGIME_SHIFT_EVIDENCE"
    elif tail_event:
        assessment = "TAIL_DRAWDOWN_WITHOUT_CLEAR_CONTEXT_SHIFT"
    else:
        assessment = "WITHIN_HISTORICAL_VARIATION"

    def summary(sample_events: Sequence[ORBTradeEvent], excursions: np.ndarray) -> dict[str, Any]:
        r = np.asarray([event.r_multiple for event in sample_events], dtype=float)
        return {
            "trades": len(sample_events),
            "net_r": float(np.sum(r)),
            "mean_r": float(np.mean(r)),
            "median_r": float(np.median(r)),
            "win_rate_pct": float(np.mean(r > 0) * 100.0),
            "mean_mfe_r": float(np.mean(excursions[:, 0])),
            "mean_mae_r": float(np.mean(excursions[:, 1])),
            "median_holding_bars": float(
                np.median([event.holding_bars for event in sample_events])
            ),
        }

    return {
        "schema_version": "orb_2026_regime_forensics/v1",
        "assessment": assessment,
        "assessment_is_diagnostic_not_parameter_selection": True,
        "current_2026": summary(current, current_mfe_mae),
        "prior_2017_2025": summary(prior, prior_mfe_mae),
        "rolling_trade_window": observed_window,
        "observed_2026_net_r": observed,
        "historical_rolling_window": {
            "count": int(len(rolling)),
            "minimum_net_r": float(np.min(rolling)) if len(rolling) else None,
            "median_net_r": float(np.median(rolling)) if len(rolling) else None,
            "empirical_lower_tail_probability": empirical_tail,
        },
        "block_bootstrap": {
            "samples": samples,
            "block_trades": block,
            "lower_tail_probability": bootstrap_tail,
            "q05_net_r": float(np.quantile(bootstrap, 0.05)),
            "median_net_r": float(np.median(bootstrap)),
        },
        "feature_drift": feature_drift,
        "fdr_significant_features": significant_features,
        "behavior_tests": {
            "win_rate_fisher_p": float(fisher.pvalue),
            "mfe_ks_p": float(mfe_test.pvalue),
            "mae_ks_p": float(mae_test.pvalue),
        },
        "interpretation": (
            "This test distinguishes an unusually bad path from measurable state/"
            "trade-behavior changes. It cannot establish permanent strategy decay."
        ),
    }


def _full_weekday_returns(
    daily: pl.DataFrame,
    start: date,
    end: date,
) -> np.ndarray:
    mapping = {
        date.fromisoformat(row["date"]): float(row["return"])
        for row in daily.to_dicts()
    }
    values: list[float] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            values.append(mapping.get(current, 0.0))
        current += timedelta(days=1)
    return np.asarray(values, dtype=float)


def _sharpe(values: np.ndarray) -> float:
    if len(values) < 2:
        return 0.0
    std = float(np.std(values, ddof=1))
    return float(np.mean(values) / std * np.sqrt(252)) if std > 0 else 0.0


def _surface_pbo(
    daily_by_variant: dict[str, pl.DataFrame],
    *,
    start_year: int,
    end_year: int,
) -> dict[str, Any]:
    names = list(daily_by_variant)
    years = list(range(start_year, end_year + 1))
    if len(years) < 4 or len(names) < 2:
        return {"pbo": None, "paths": 0}
    test_year_count = 2
    ranks: list[float] = []
    for test_years in combinations(years, test_year_count):
        train_years = [year for year in years if year not in test_years]
        is_scores = []
        oos_scores = []
        for name in names:
            frame = daily_by_variant[name]
            rows = frame.to_dicts()
            is_values = np.asarray(
                [
                    float(row["return"])
                    for row in rows
                    if int(str(row["date"])[:4]) in train_years
                ],
                dtype=float,
            )
            oos_values = np.asarray(
                [
                    float(row["return"])
                    for row in rows
                    if int(str(row["date"])[:4]) in test_years
                ],
                dtype=float,
            )
            is_scores.append(_sharpe(is_values))
            oos_scores.append(_sharpe(oos_values))
        winner = int(np.argmax(is_scores))
        descending = list(np.argsort(oos_scores)[::-1])
        rank = descending.index(winner)
        normalized = rank / max(len(names) - 1, 1)
        ranks.append(float(normalized))
    return {
        "pbo": float(np.mean(np.asarray(ranks) > 0.5)),
        "paths": len(ranks),
        "normalized_oos_ranks_of_is_winner": ranks,
    }


def run_exit_stability(
    markets: dict[str, PreparedMarket],
    rebuild_config: dict[str, Any],
    *,
    config: dict[str, Any],
    development_start: datetime,
    development_end: datetime,
    risk_unit_pct: float,
    roundtrip_cost_bps: float,
) -> tuple[dict[str, Any], list[dict[str, Any]], pl.DataFrame]:
    rows: list[dict[str, Any]] = []
    metrics_by_name: dict[str, Any] = {}
    daily_by_name: dict[str, pl.DataFrame] = {}
    trials: list[dict[str, Any]] = []

    for be in config["breakeven_trigger_r"]:
        for trail in config["trailing_distance_r"]:
            candidate = copy.deepcopy(rebuild_config)
            candidate["strategy"]["target_multiple"] = float(config["target_multiple"])
            candidate["strategy"]["stop_multiple"] = float(config["stop_multiple"])
            candidate["strategy"]["breakeven"]["trigger_r"] = float(be)
            candidate["strategy"]["breakeven"]["offset_r"] = float(
                config["breakeven_offset_r"]
            )
            candidate["strategy"]["trailing"]["distance_r"] = float(trail)
            built = build_events(
                markets,
                candidate,
                variant="corrected",
                roundtrip_cost_bps=roundtrip_cost_bps,
                decision_start=development_start,
                decision_end=development_end,
            )
            name = f"be_{float(be):.2f}_trail_{float(trail):.2f}"
            metric, daily = _metrics(
                built.events,
                markets,
                risk_unit_pct=risk_unit_pct,
                roundtrip_cost_bps=roundtrip_cost_bps,
            )
            metrics_by_name[name] = {
                **metric,
                "breakeven_trigger_r": float(be),
                "trailing_distance_r": float(trail),
            }
            daily_by_name[name] = daily
            rows.append(metrics_by_name[name])
            trials.append(
                {
                    "family": "exit_stability",
                    "variant": name,
                    "selection_trial": True,
                    "sharpe": metric["annualized_sharpe"],
                    "net_r": metric["net_r"],
                }
            )

    sharpes = [metrics_by_name[name]["annualized_sharpe"] for name in metrics_by_name]
    best_name = max(
        metrics_by_name,
        key=lambda name: metrics_by_name[name]["annualized_sharpe"],
    )
    best = metrics_by_name[best_name]
    for name, metric in metrics_by_name.items():
        daily = daily_by_name[name]
        returns = daily["return"].to_numpy()
        metric["dsr_family"] = compute_deflated_sharpe(
            float(metric["annualized_sharpe"]),
            [float(value) for value in sharpes],
            n_obs_days=max(len(returns), 2),
            skew=float(stats.skew(returns)) if len(returns) > 2 else 0.0,
            kurtosis=(
                float(stats.kurtosis(returns, fisher=False))
                if len(returns) > 3
                else 3.0
            ),
        )
        metric["within_10pct_of_best_sharpe"] = (
            metric["annualized_sharpe"] >= best["annualized_sharpe"] * 0.90
            if best["annualized_sharpe"] > 0
            else False
        )

    profitable_fraction = float(
        np.mean([metric["net_r"] > 0 for metric in metrics_by_name.values()])
    )
    near_best_fraction = float(
        np.mean(
            [
                bool(metric["within_10pct_of_best_sharpe"])
                for metric in metrics_by_name.values()
            ]
        )
    )
    center_name = "be_1.00_trail_1.00"
    pbo = _surface_pbo(
        daily_by_name, start_year=2017, end_year=2024
    )
    return {
        "schema_version": "orb_exit_stability/v1",
        "selection_period": "2017-2024 only",
        "surface": metrics_by_name,
        "best_by_sharpe": best_name,
        "center_current_parameters": (
            metrics_by_name.get(center_name)
        ),
        "profitable_surface_fraction": profitable_fraction,
        "near_best_sharpe_fraction": near_best_fraction,
        "pbo": pbo,
        "promotion_allowed": False,
        "policy": (
            "The surface is a development diagnostic. No parameter change is "
            "promoted without new prospective confirmation."
        ),
    }, trials, pl.DataFrame(rows, infer_schema_length=None)


def run_rolling_expanding(
    events: Sequence[ORBTradeEvent],
    markets: dict[str, PreparedMarket],
    *,
    config: dict[str, Any],
    research_start: datetime,
    end: datetime,
    risk_unit_pct: float,
    roundtrip_cost_bps: float,
) -> tuple[dict[str, Any], pl.DataFrame]:
    rows: list[dict[str, Any]] = []
    for endpoint_year in [int(y) for y in config["endpoint_years"]]:
        endpoint = (
            end
            if endpoint_year == end.year
            else datetime(endpoint_year, 12, 31, 23, 59, 59, tzinfo=end.tzinfo)
        )
        if endpoint > end:
            continue
        expanding_events = _subset(
            events, start=research_start, end=endpoint
        )
        expanding, _ = _metrics(
            expanding_events,
            markets,
            risk_unit_pct=risk_unit_pct,
            roundtrip_cost_bps=roundtrip_cost_bps,
        )
        rows.append(
            {
                "endpoint_year": endpoint_year,
                "window": "expanding",
                "start": research_start.isoformat(),
                "end": endpoint.isoformat(),
                **{
                    key: expanding[key]
                    for key in (
                        "trades",
                        "net_r",
                        "mean_r",
                        "win_rate_pct",
                        "annualized_sharpe",
                        "max_drawdown",
                    )
                },
            }
        )
        for years in [int(value) for value in config["rolling_years"]]:
            start_year = endpoint_year - years + 1
            start = datetime(start_year, 1, 1, tzinfo=end.tzinfo)
            rolling_events = _subset(events, start=start, end=endpoint)
            metric, _ = _metrics(
                rolling_events,
                markets,
                risk_unit_pct=risk_unit_pct,
                roundtrip_cost_bps=roundtrip_cost_bps,
            )
            rows.append(
                {
                    "endpoint_year": endpoint_year,
                    "window": f"rolling_{years}y",
                    "start": start.isoformat(),
                    "end": endpoint.isoformat(),
                    **{
                        key: metric[key]
                        for key in (
                            "trades",
                            "net_r",
                            "mean_r",
                            "win_rate_pct",
                            "annualized_sharpe",
                            "max_drawdown",
                        )
                    },
                }
            )

    frame = pl.DataFrame(rows, infer_schema_length=None)
    latest = frame.filter(pl.col("endpoint_year") == frame["endpoint_year"].max())
    return {
        "schema_version": "orb_rolling_expanding/v1",
        "latest_endpoint": int(frame["endpoint_year"].max()),
        "latest": latest.to_dicts(),
        "interpretation": (
            "Rolling windows are monitoring diagnostics for non-stationarity; "
            "they are not used to retune the entry rule."
        ),
    }, frame


def run_research(
    root: Path,
    research_config_path: Path,
    *,
    run_id: str,
) -> dict[str, Any]:
    config = load_research_config(research_config_path)
    rebuild_path = root / str(config["research"]["source_rebuild_config"])
    rebuild_config = load_rebuild_config(rebuild_path)
    preflight = rebuild_preflight(root, rebuild_path)
    if preflight["status"] != "READY":
        raise ORBRawOptimizationError("source EOW rebuild preflight is not READY")

    output = root / str(config["artifacts"]["root"]) / run_id
    result_path = output / "summary.json"
    snapshot_path = output / "config.snapshot.yaml"
    if result_path.is_file():
        return json.loads(result_path.read_text())
    output.mkdir(parents=True, exist_ok=True)
    if snapshot_path.is_file() and (
        snapshot_path.read_bytes() != research_config_path.read_bytes()
    ):
        raise ORBRawOptimizationError("existing run has a different config snapshot")
    snapshot_path.write_bytes(research_config_path.read_bytes())

    lock_handle = (output / ".run.lock").open("w")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        lock_handle.close()
        raise ORBRawOptimizationError(
            f"research run {run_id} is already in progress"
        ) from exc

    universe = set(map(str, config["research"]["universe"]))
    restricted = _restricted_rebuild_config(rebuild_config, universe)
    start = parse_utc(config["period"]["start"])
    development_end = parse_utc(config["period"]["development_end"])
    diagnostic_start = parse_utc(config["period"]["diagnostic_start"])
    end = parse_utc(config["period"]["end"])
    cost_bps = float(rebuild_config["execution"]["authoritative_roundtrip_bps"])
    risk_unit_pct = float(config["execution"]["risk_unit_pct"])

    markets = prepare_all_markets(root, restricted, end=end)
    built = build_events(
        markets,
        restricted,
        variant="corrected",
        roundtrip_cost_bps=cost_bps,
        decision_start=start,
        decision_end=end,
    )
    events, feature_diag = enrich_events_with_point_in_time_features(
        built.events,
        markets,
        {
            "names": list(config["factor_quintiles"]["features"]),
            "rvol_lookback_sessions": 20,
            "garman_klass_lookback_bars": 20,
        },
    )

    exit_attr, trials_exit = run_exit_attribution(
        events,
        markets,
        config=config["exit_attribution"],
        base_strategy=restricted["strategy"],
        development_end=development_end,
        diagnostic_start=diagnostic_start,
        end=end,
        risk_unit_pct=risk_unit_pct,
        roundtrip_cost_bps=cost_bps,
    )
    atomic_write_json(output / "01_exit_attribution.json", exit_attr)

    factors, trials_factor, factor_rows = run_factor_quintiles(
        events,
        config=config["factor_quintiles"],
    )
    atomic_write_json(output / "02_factor_quintiles.json", factors)
    atomic_write_parquet(output / "02_factor_quintile_events.parquet", factor_rows)

    risk, trials_risk = run_risk_targeting(
        events,
        markets,
        config=config["risk_targeting"],
        development_end=development_end,
        diagnostic_start=diagnostic_start,
        end=end,
        risk_unit_pct=risk_unit_pct,
        roundtrip_cost_bps=cost_bps,
    )
    atomic_write_json(output / "03_risk_targeting.json", risk)

    regime = run_2026_regime_forensics(
        events,
        markets,
        config=config["regime_2026"],
        feature_names=list(config["factor_quintiles"]["features"]),
    )
    atomic_write_json(output / "04_2026_regime_forensics.json", regime)

    stability, trials_surface, surface_rows = run_exit_stability(
        markets,
        restricted,
        config=config["exit_stability"],
        development_start=start,
        development_end=development_end,
        risk_unit_pct=risk_unit_pct,
        roundtrip_cost_bps=cost_bps,
    )
    atomic_write_json(output / "05_exit_stability.json", stability)
    atomic_write_parquet(output / "05_exit_stability.parquet", surface_rows)

    rolling, rolling_rows = run_rolling_expanding(
        events,
        markets,
        config=config["rolling_expanding"],
        research_start=start,
        end=end,
        risk_unit_pct=risk_unit_pct,
        roundtrip_cost_bps=cost_bps,
    )
    atomic_write_json(output / "06_rolling_expanding.json", rolling)
    atomic_write_parquet(output / "06_rolling_expanding.parquet", rolling_rows)

    all_trials = trials_exit + trials_factor + trials_risk + trials_surface
    (output / "trials.jsonl").write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in all_trials) + "\n"
    )

    base_dev = _subset(events, end=development_end)
    base_diag = _subset(events, start=diagnostic_start, end=end)
    base_dev_metrics, _ = _metrics(
        base_dev,
        markets,
        risk_unit_pct=risk_unit_pct,
        roundtrip_cost_bps=cost_bps,
    )
    base_diag_metrics, _ = _metrics(
        base_diag,
        markets,
        risk_unit_pct=risk_unit_pct,
        roundtrip_cost_bps=cost_bps,
    )
    summary = {
        "schema_version": "orb_raw_optimization_summary/v1",
        "run_id": run_id,
        "status": "RESEARCH_COMPLETE",
        "source": {
            "research_config_sha256": sha256_file(research_config_path),
            "rebuild_config_sha256": sha256_file(rebuild_path),
            "roundtrip_cost_bps": cost_bps,
        },
        "baseline": {
            "development_2017_2024": base_dev_metrics,
            "diagnostic_2025_2026": base_diag_metrics,
            "diagnostic_used_for_selection": False,
        },
        "feature_diagnostics": feature_diag,
        "exit_attribution": {
            "artifact": "01_exit_attribution.json",
        },
        "factor_quintiles": {
            "artifact": "02_factor_quintiles.json",
            "descriptive_order": factors["descriptive_order"],
        },
        "risk_targeting": {
            "artifact": "03_risk_targeting.json",
            "passing_development_variants": risk["passing_development_variants"],
        },
        "regime_2026": {
            "artifact": "04_2026_regime_forensics.json",
            "assessment": regime["assessment"],
            "bootstrap_lower_tail_probability": regime["block_bootstrap"][
                "lower_tail_probability"
            ],
            "fdr_significant_features": regime["fdr_significant_features"],
        },
        "exit_stability": {
            "artifact": "05_exit_stability.json",
            "best_by_sharpe": stability["best_by_sharpe"],
            "pbo": stability["pbo"]["pbo"],
            "profitable_surface_fraction": stability[
                "profitable_surface_fraction"
            ],
        },
        "rolling_expanding": {
            "artifact": "06_rolling_expanding.json",
            "latest": rolling["latest"],
        },
        "new_selection_trial_count": len(all_trials),
        "production_change_authorized": False,
        "policy": (
            "No optimization is automatically promoted. 2025-2026 is diagnostic "
            "only, and any development winner requires new prospective evidence."
        ),
    }
    atomic_write_json(result_path, summary)
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    lock_handle.close()
    return summary
