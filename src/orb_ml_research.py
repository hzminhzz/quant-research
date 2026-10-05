"""Leakage-resistant ML sizing research for corrected HK33/JP225 ORB events.

This module is deliberately separate from the historical meta-classifier.  It keeps
raw ORB rules fixed, predicts net R rather than a binary win label, and only throttles
risk between a configured floor and ceiling.  Development selection uses 2020-2024
walk-forward OOS data; the already-opened 2025-2026 period is diagnostic only.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
import copy
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
import json
import math
from pathlib import Path
from typing import Any, Sequence

import lightgbm as lgb
import numpy as np
import polars as pl
import yaml
from scipy import stats
from sklearn.linear_model import HuberRegressor
from sklearn.preprocessing import StandardScaler

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
from src.session_calendar import anchor_window
from src.validation import fold_uniqueness_weights, purge_and_embargo


MODEL_NAMES = ("huber", "lightgbm", "catboost")


class ORBMLResearchError(RuntimeError):
    """Fail-closed contract error for the ML sizing experiment."""


@dataclass(frozen=True)
class SessionHistory:
    dates: tuple[date, ...]
    opening_volume: dict[date, float]
    daily_range: dict[date, float]


@dataclass
class Predictor:
    name: str
    model: Any
    scaler: StandardScaler | None = None

    def predict(self, X: np.ndarray) -> np.ndarray:
        values = self.scaler.transform(X) if self.scaler is not None else X
        return np.asarray(self.model.predict(values), dtype=float)


def load_research_config(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text())
    if not isinstance(payload, dict):
        raise ORBMLResearchError("ML research config must be a mapping")
    return payload


def _duration(value: str) -> timedelta:
    unit = value[-1].lower()
    amount = float(value[:-1])
    if unit == "d":
        return timedelta(days=amount)
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "m":
        return timedelta(minutes=amount)
    raise ORBMLResearchError(f"unsupported duration {value}")


def _opening_indices(market: PreparedMarket, trading_date: date) -> list[int]:
    window = anchor_window(trading_date, market.spec.anchor)
    indices = market.market_date_indices.get(trading_date, [])
    opening = [
        idx
        for idx in indices
        if window.anchor_utc <= market.timestamps[idx] < window.opening_range_end_utc
    ]
    expected = int(
        market.spec.anchor.opening_range.total_seconds()
        / market.spec.bar_duration.total_seconds()
    )
    if len(opening) != expected:
        raise ORBMLResearchError(
            f"{market.spec.symbol} {trading_date}: expected {expected} opening bars, got {len(opening)}"
        )
    return opening


def _candidate_index(market: PreparedMarket, event: ORBTradeEvent) -> int:
    decision = parse_utc(event.decision_time)
    idx = bisect_left(market.available_at, decision)
    if idx >= len(market.available_at) or market.available_at[idx] != decision:
        raise ORBMLResearchError(
            f"{event.symbol} {event.date}: decision timestamp does not map to an available bar"
        )
    return idx


def _build_session_history(market: PreparedMarket) -> SessionHistory:
    opening_volume: dict[date, float] = {}
    daily_range: dict[date, float] = {}
    for trading_date in sorted(market.market_date_indices):
        if trading_date not in market.scheduled_sessions:
            continue
        try:
            opening = _opening_indices(market, trading_date)
        except ORBMLResearchError:
            continue
        volume = float(np.nansum(market.volumes[opening]))
        if np.isfinite(volume) and volume > 0:
            opening_volume[trading_date] = volume

        indices = market.market_date_indices.get(trading_date, [])
        if indices:
            high = float(np.nanmax(market.highs[indices]))
            low = float(np.nanmin(market.lows[indices]))
            if np.isfinite(high) and np.isfinite(low) and high >= low:
                daily_range[trading_date] = high - low

    dates = tuple(sorted(set(opening_volume) & set(daily_range)))
    return SessionHistory(
        dates=dates,
        opening_volume=opening_volume,
        daily_range=daily_range,
    )


def _rolling_garman_klass(
    market: PreparedMarket,
    candidate_idx: int,
    lookback_bars: int,
) -> float:
    start = max(0, candidate_idx - lookback_bars + 1)
    sl = slice(start, candidate_idx + 1)
    o = market.opens[sl]
    h = market.highs[sl]
    low = market.lows[sl]
    c = market.closes[sl]
    valid = (
        np.isfinite(o)
        & np.isfinite(h)
        & np.isfinite(low)
        & np.isfinite(c)
        & (o > 0)
        & (h > 0)
        & (low > 0)
        & (c > 0)
    )
    if not np.any(valid):
        return 0.0
    log_hl = np.log(h[valid] / low[valid])
    log_co = np.log(c[valid] / o[valid])
    variance = 0.5 * log_hl**2 - (2.0 * np.log(2.0) - 1.0) * log_co**2
    return float(np.sqrt(max(float(np.mean(variance)), 0.0)))


def _prior_dates(history: SessionHistory, current: date) -> list[date]:
    stop = bisect_left(history.dates, current)
    return list(history.dates[:stop])


def point_in_time_feature_vector(
    event: ORBTradeEvent,
    market: PreparedMarket,
    history: SessionHistory,
    *,
    rvol_lookback_sessions: int,
    gk_lookback_bars: int,
) -> tuple[dict[str, float], dict[str, bool]]:
    """Build the eight canonical ML features using information available at decision time."""
    trading_date = date.fromisoformat(event.date)
    opening = _opening_indices(market, trading_date)
    candidate_idx = _candidate_index(market, event)

    computed_high = float(np.nanmax(market.highs[opening]))
    computed_low = float(np.nanmin(market.lows[opening]))
    computed_range = computed_high - computed_low
    tolerance = max(1e-9, abs(event.or_range) * 1e-8)
    if abs(computed_range - float(event.or_range)) > tolerance:
        raise ORBMLResearchError(
            f"{event.symbol} {event.date}: opening range does not reconcile with event ledger"
        )

    opening_volume = float(np.nansum(market.volumes[opening]))
    prior = _prior_dates(history, trading_date)
    prior_for_rvol = [
        history.opening_volume[d]
        for d in prior[-rvol_lookback_sessions:]
        if d in history.opening_volume and history.opening_volume[d] > 0
    ]
    rvol_fallback = not prior_for_rvol
    baseline_volume = (
        float(np.mean(prior_for_rvol)) if prior_for_rvol else opening_volume
    )
    rvol = (
        opening_volume / baseline_volume
        if baseline_volume > 0 and np.isfinite(baseline_volume)
        else 1.0
    )

    volumes = market.volumes[opening]
    closes = market.closes[opening]
    total_volume = float(np.nansum(volumes))
    if total_volume > 0:
        vwap_1h = float(np.nansum(closes * volumes) / total_volume)
    else:
        vwap_1h = float(np.nanmean(closes))
    vwap_loc = (
        (vwap_1h - computed_low) / computed_range if computed_range > 0 else 0.5
    )
    vwap_alignment = vwap_loc if event.direction == 1 else 1.0 - vwap_loc

    open_1h = float(market.opens[opening[0]])
    close_1h = float(market.closes[opening[-1]])
    wick_upper = (
        (computed_high - max(open_1h, close_1h)) / computed_range
        if computed_range > 0
        else 0.0
    )
    wick_lower = (
        (min(open_1h, close_1h) - computed_low) / computed_range
        if computed_range > 0
        else 0.0
    )
    wick_exhaustion = wick_upper if event.direction == 1 else wick_lower

    range_to_atr = (
        float(event.or_range) / float(event.atr20) if event.atr20 > 0 else 1.0
    )
    gk_norm = _rolling_garman_klass(
        market, candidate_idx, gk_lookback_bars
    ) * 100.0

    spx_close = float(market.canonical_spx_close[candidate_idx])
    spx_vwap = float(market.canonical_spx_vwap[candidate_idx])
    if (
        np.isfinite(spx_close)
        and np.isfinite(spx_vwap)
        and spx_vwap > 0
    ):
        spx_alignment = ((spx_close - spx_vwap) / spx_vwap * 100.0) * event.direction
    else:
        spx_alignment = 0.0

    previous_seven = [
        history.daily_range[d]
        for d in prior[-7:]
        if d in history.daily_range
    ]
    nr7_available = len(previous_seven) == 7
    nr7 = (
        1.0
        if nr7_available
        and previous_seven[-1] <= min(previous_seven[:-1])
        else 0.0
    )

    bar_range = float(market.highs[candidate_idx] - market.lows[candidate_idx])
    bar_range_ratio = (
        bar_range / (computed_range / len(opening))
        if computed_range > 0
        else 1.0
    )

    features = {
        "rvol_1h": float(np.clip(rvol, 0.1, 10.0)),
        "vwap_alignment": float(np.clip(vwap_alignment, 0.0, 1.0)),
        "wick_exhaustion": float(np.clip(wick_exhaustion, 0.0, 1.0)),
        "range_to_atr20": float(range_to_atr),
        "garman_klass_norm": float(np.clip(gk_norm, 0.0, 50.0)),
        "spx_alignment": float(spx_alignment),
        "nr7_flag": nr7,
        "breakout_bar_range_ratio": float(np.clip(bar_range_ratio, 0.2, 5.0)),
    }
    if not all(np.isfinite(value) for value in features.values()):
        raise ORBMLResearchError(
            f"{event.symbol} {event.date}: non-finite point-in-time feature"
        )
    return features, {
        "rvol_fallback": rvol_fallback,
        "nr7_available": nr7_available,
    }


def enrich_events_with_point_in_time_features(
    events: Sequence[ORBTradeEvent],
    markets: dict[str, PreparedMarket],
    feature_config: dict[str, Any],
) -> tuple[list[ORBTradeEvent], dict[str, Any]]:
    histories = {
        symbol: _build_session_history(market)
        for symbol, market in markets.items()
        if symbol in {event.symbol for event in events}
    }
    enriched: list[ORBTradeEvent] = []
    rvol_fallbacks = 0
    nr7_available = 0
    for event in events:
        market = markets[event.symbol]
        features, flags = point_in_time_feature_vector(
            event,
            market,
            histories[event.symbol],
            rvol_lookback_sessions=int(feature_config["rvol_lookback_sessions"]),
            gk_lookback_bars=int(feature_config["garman_klass_lookback_bars"]),
        )
        rvol_fallbacks += int(flags["rvol_fallback"])
        nr7_available += int(flags["nr7_available"])
        enriched.append(replace(event, features=features))

    names = list(feature_config["names"])
    X = np.asarray(
        [[event.features[name] for name in names] for event in enriched],
        dtype=float,
    )
    diagnostics = {
        "event_count": len(enriched),
        "rvol_fallback_count": rvol_fallbacks,
        "nr7_available_count": nr7_available,
        "feature_summary": {
            name: {
                "min": float(np.min(X[:, idx])),
                "max": float(np.max(X[:, idx])),
                "mean": float(np.mean(X[:, idx])),
                "std": float(np.std(X[:, idx])),
                "constant": bool(np.std(X[:, idx]) <= 1e-12),
            }
            for idx, name in enumerate(names)
        },
    }
    diagnostics["constant_features"] = [
        name
        for name, item in diagnostics["feature_summary"].items()
        if item["constant"]
    ]
    return enriched, diagnostics


def _feature_matrix(
    events: Sequence[ORBTradeEvent],
    feature_names: Sequence[str],
    indices: Sequence[int],
) -> np.ndarray:
    return np.asarray(
        [
            [events[idx].features[name] for name in feature_names]
            for idx in indices
        ],
        dtype=float,
    )


def _fit_predictor(
    name: str,
    X: np.ndarray,
    y: np.ndarray,
    weights: np.ndarray,
    model_config: dict[str, Any],
) -> Predictor:
    random_state = int(model_config["random_state"])
    if name == "huber":
        cfg = model_config["huber"]
        scaler = StandardScaler()
        transformed = scaler.fit_transform(X)
        model = HuberRegressor(
            epsilon=float(cfg["epsilon"]),
            alpha=float(cfg["alpha"]),
            max_iter=int(cfg["max_iter"]),
        )
        model.fit(transformed, y, sample_weight=weights)
        return Predictor(name=name, model=model, scaler=scaler)

    if name == "lightgbm":
        cfg = model_config["lightgbm"]
        model = lgb.LGBMRegressor(
            objective=str(cfg["objective"]),
            learning_rate=float(cfg["learning_rate"]),
            n_estimators=int(cfg["n_estimators"]),
            num_leaves=int(cfg["num_leaves"]),
            max_depth=int(cfg["max_depth"]),
            min_child_samples=int(cfg["min_child_samples"]),
            subsample=float(cfg["subsample"]),
            colsample_bytree=float(cfg["colsample_bytree"]),
            reg_alpha=float(cfg["reg_alpha"]),
            reg_lambda=float(cfg["reg_lambda"]),
            random_state=random_state,
            verbosity=-1,
        )
        model.fit(X, y, sample_weight=weights)
        return Predictor(name=name, model=model)

    if name == "catboost":
        try:
            from catboost import CatBoostRegressor
        except ImportError as exc:
            raise ORBMLResearchError(
                "catboost is required for the fixed model comparison; run with "
                "'uv run --with catboost python scripts/run_orb_ml_research.py ...'"
            ) from exc
        cfg = model_config["catboost"]
        model = CatBoostRegressor(
            loss_function=str(cfg["loss_function"]),
            iterations=int(cfg["iterations"]),
            depth=int(cfg["depth"]),
            learning_rate=float(cfg["learning_rate"]),
            l2_leaf_reg=float(cfg["l2_leaf_reg"]),
            random_seed=random_state,
            verbose=False,
            allow_writing_files=False,
        )
        model.fit(X, y, sample_weight=weights)
        return Predictor(name=name, model=model)

    raise ORBMLResearchError(f"unsupported model {name}")


def _robust_target_scale(y: np.ndarray, floor_r: float) -> float:
    median = float(np.median(y))
    mad = float(np.median(np.abs(y - median)))
    return max(1.4826 * mad, float(floor_r))


def risk_throttle(
    predicted_r: np.ndarray,
    *,
    scale_r: float,
    floor: float,
    ceiling: float,
) -> np.ndarray:
    """Map expected-R forecasts monotonically to nonzero risk sizes."""
    if not 0.0 < floor <= ceiling:
        raise ORBMLResearchError("risk throttle requires 0 < floor <= ceiling")
    scaled = np.clip(np.asarray(predicted_r, dtype=float) / scale_r, -30.0, 30.0)
    logistic = 1.0 / (1.0 + np.exp(-scaled))
    return floor + (ceiling - floor) * logistic


def _spearman(prediction: np.ndarray, realized: np.ndarray) -> float:
    if len(prediction) < 3 or np.std(prediction) <= 1e-12 or np.std(realized) <= 1e-12:
        return 0.0
    value = stats.spearmanr(prediction, realized).statistic
    return float(value) if np.isfinite(value) else 0.0


def _score_fold(
    events: Sequence[ORBTradeEvent],
    feature_names: Sequence[str],
    train_indices: Sequence[int],
    test_indices: Sequence[int],
    *,
    embargo: timedelta,
    model_config: dict[str, Any],
    throttle_config: dict[str, Any],
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    purged_train, split_diag = purge_and_embargo(
        events,
        train_indices=train_indices,
        test_indices=test_indices,
        embargo=embargo,
    )
    if len(purged_train) == 0:
        raise ORBMLResearchError("purging removed every training event")

    X_train = _feature_matrix(events, feature_names, purged_train)
    y_train = np.asarray([events[idx].r_multiple for idx in purged_train], dtype=float)
    X_test = _feature_matrix(events, feature_names, test_indices)
    y_test = np.asarray([events[idx].r_multiple for idx in test_indices], dtype=float)
    weights = fold_uniqueness_weights(events, purged_train)
    scale = _robust_target_scale(
        y_train, float(throttle_config["robust_scale_floor_r"])
    )

    result: dict[str, np.ndarray] = {}
    model_diag: dict[str, Any] = {}
    for name in MODEL_NAMES:
        predictor = _fit_predictor(
            name, X_train, y_train, weights, model_config
        )
        prediction = predictor.predict(X_test)
        sizes = risk_throttle(
            prediction,
            scale_r=scale,
            floor=float(throttle_config["floor"]),
            ceiling=float(throttle_config["ceiling"]),
        )
        result[name] = np.column_stack((prediction, sizes))
        model_diag[name] = {
            "spearman_ic": _spearman(prediction, y_test),
            "prediction_mean": float(np.mean(prediction)),
            "prediction_std": float(np.std(prediction)),
            "size_mean": float(np.mean(sizes)),
            "size_min": float(np.min(sizes)),
            "size_max": float(np.max(sizes)),
        }

    return result, {
        "train_count_before_purge": int(len(train_indices)),
        "train_count_after_purge": int(len(purged_train)),
        "test_count": int(len(test_indices)),
        "purged_count": int(split_diag.purged_count),
        "embargoed_count": int(split_diag.embargoed_count),
        "exact_overlap_count": int(split_diag.exact_overlap_count),
        "target_scale_r": scale,
        "models": model_diag,
    }


def walk_forward_predictions(
    events: Sequence[ORBTradeEvent],
    feature_names: Sequence[str],
    *,
    evaluation_years: Sequence[int],
    embargo: timedelta,
    min_train_events: int,
    model_config: dict[str, Any],
    throttle_config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    decision_year = np.asarray(
        [parse_utc(event.decision_time).year for event in events], dtype=int
    )
    rows: list[dict[str, Any]] = []
    folds: list[dict[str, Any]] = []

    for year in evaluation_years:
        train_idx = np.flatnonzero(decision_year < int(year))
        test_idx = np.flatnonzero(decision_year == int(year))
        if len(test_idx) == 0:
            continue
        if len(train_idx) < min_train_events:
            raise ORBMLResearchError(
                f"{year}: only {len(train_idx)} training events; need {min_train_events}"
            )
        scored, fold_diag = _score_fold(
            events,
            feature_names,
            train_idx,
            test_idx,
            embargo=embargo,
            model_config=model_config,
            throttle_config=throttle_config,
        )
        fold_diag["year"] = int(year)
        folds.append(fold_diag)
        for idx in test_idx:
            event = events[int(idx)]
            rows.append(
                {
                    "lane": "development_oos",
                    "year": int(year),
                    "event_index": int(idx),
                    "model": "raw_orb",
                    "symbol": event.symbol,
                    "decision_time": event.decision_time,
                    "entry_time": event.entry_time,
                    "exit_time": event.exit_time,
                    "r_multiple": float(event.r_multiple),
                    "prediction_r": None,
                    "size": 1.0,
                }
            )
        for name in MODEL_NAMES:
            values = scored[name]
            for position, idx in enumerate(test_idx):
                event = events[int(idx)]
                rows.append(
                    {
                        "lane": "development_oos",
                        "year": int(year),
                        "event_index": int(idx),
                        "model": name,
                        "symbol": event.symbol,
                        "decision_time": event.decision_time,
                        "entry_time": event.entry_time,
                        "exit_time": event.exit_time,
                        "r_multiple": float(event.r_multiple),
                        "prediction_r": float(values[position, 0]),
                        "size": float(values[position, 1]),
                    }
                )
    return rows, folds


def historical_diagnostic_predictions(
    events: Sequence[ORBTradeEvent],
    feature_names: Sequence[str],
    *,
    diagnostic_start: datetime,
    diagnostic_end: datetime,
    embargo: timedelta,
    min_train_events: int,
    model_config: dict[str, Any],
    throttle_config: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    timestamps = np.asarray(
        [parse_utc(event.decision_time).timestamp() for event in events], dtype=float
    )
    start_ts = diagnostic_start.timestamp()
    end_ts = diagnostic_end.timestamp()
    train_idx = np.flatnonzero(timestamps < start_ts)
    test_idx = np.flatnonzero((timestamps >= start_ts) & (timestamps <= end_ts))
    if len(train_idx) < min_train_events or len(test_idx) == 0:
        raise ORBMLResearchError("insufficient diagnostic train/test events")

    scored, diagnostics = _score_fold(
        events,
        feature_names,
        train_idx,
        test_idx,
        embargo=embargo,
        model_config=model_config,
        throttle_config=throttle_config,
    )
    rows: list[dict[str, Any]] = []
    for idx in test_idx:
        event = events[int(idx)]
        rows.append(
            {
                "lane": "historical_diagnostic",
                "year": parse_utc(event.decision_time).year,
                "event_index": int(idx),
                "model": "raw_orb",
                "symbol": event.symbol,
                "decision_time": event.decision_time,
                "entry_time": event.entry_time,
                "exit_time": event.exit_time,
                "r_multiple": float(event.r_multiple),
                "prediction_r": None,
                "size": 1.0,
            }
        )
    for name in MODEL_NAMES:
        values = scored[name]
        for position, idx in enumerate(test_idx):
            event = events[int(idx)]
            rows.append(
                {
                    "lane": "historical_diagnostic",
                    "year": parse_utc(event.decision_time).year,
                    "event_index": int(idx),
                    "model": name,
                    "symbol": event.symbol,
                    "decision_time": event.decision_time,
                    "entry_time": event.entry_time,
                    "exit_time": event.exit_time,
                    "r_multiple": float(event.r_multiple),
                    "prediction_r": float(values[position, 0]),
                    "size": float(values[position, 1]),
                }
            )
    diagnostics["period"] = {
        "start": diagnostic_start.isoformat(),
        "end": diagnostic_end.isoformat(),
        "used_for_selection": False,
        "reason": "This historical holdout was already opened by prior research and is diagnostic only.",
    }
    return rows, diagnostics


def portfolio_daily_mtm_sizes(
    events: Sequence[ORBTradeEvent],
    sizes: Sequence[float],
    markets: dict[str, PreparedMarket],
    *,
    risk_unit_pct: float,
    roundtrip_cost_bps: float,
) -> tuple[pl.DataFrame, dict[str, Any]]:
    """Mark every selected trade daily, scaling the full path by its risk throttle."""
    if len(events) != len(sizes):
        raise ORBMLResearchError("event/size length mismatch")
    daily_r: dict[date, float] = {}
    cost_fraction = roundtrip_cost_bps / 10_000.0

    for event, size in zip(events, sizes):
        size = float(size)
        if not 0.0 < size <= 1.0 + 1e-12:
            raise ORBMLResearchError(f"invalid risk size {size}")
        market = markets[event.symbol]
        entry_time = parse_utc(event.entry_time)
        exit_time = parse_utc(event.exit_time)
        entry_price = float(event.entry_price)
        direction = int(event.direction)
        delta = float(event.delta)
        if delta <= 0:
            raise ORBMLResearchError("non-positive event delta")
        risk_fraction = delta / entry_price
        half_cost_r = (cost_fraction / 2.0) / risk_fraction

        current = entry_time.date()
        end_date = exit_time.date()
        previous_mark_r = -half_cost_r
        daily_r[current] = daily_r.get(current, 0.0) + previous_mark_r * size

        while current <= end_date:
            day_end = datetime.combine(
                current, time(23, 59, 59, 999999), tzinfo=entry_time.tzinfo
            )
            if day_end < entry_time:
                current += timedelta(days=1)
                continue
            right = bisect_right(market.available_at, min(day_end, exit_time))
            left = bisect_left(market.available_at, entry_time)
            if right <= left:
                current += timedelta(days=1)
                continue
            mark_idx = right - 1
            mark_price = (
                float(event.exit_price)
                if market.available_at[mark_idx] >= exit_time
                else float(market.closes[mark_idx])
            )
            mark_r = direction * (mark_price - entry_price) / delta - half_cost_r
            if day_end >= exit_time:
                mark_r -= half_cost_r
            increment = (mark_r - previous_mark_r) * size
            daily_r[current] = daily_r.get(current, 0.0) + increment
            previous_mark_r = mark_r
            current += timedelta(days=1)

    if not daily_r:
        return pl.DataFrame({"date": [], "return": [], "r_increment": []}), {
            "annualized_sharpe": 0.0,
            "max_drawdown": 0.0,
            "net_r_reconciled": 0.0,
        }

    first = min(daily_r)
    last = max(daily_r)
    rows: list[dict[str, Any]] = []
    current = first
    while current <= last:
        if current.weekday() < 5:
            r_increment = float(daily_r.get(current, 0.0))
            rows.append(
                {
                    "date": current.isoformat(),
                    "r_increment": r_increment,
                    "return": r_increment * (risk_unit_pct / 100.0),
                }
            )
        current += timedelta(days=1)

    frame = pl.DataFrame(rows)
    returns = frame["return"].to_numpy()
    std = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
    sharpe = float(np.mean(returns) / std * np.sqrt(252)) if std > 0 else 0.0
    equity = np.cumprod(1.0 + returns)
    path = np.concatenate(([1.0], equity))
    peaks = np.maximum.accumulate(path)
    drawdown = path / peaks - 1.0
    expected_r = float(sum(e.r_multiple * float(s) for e, s in zip(events, sizes)))
    reconciled_r = float(frame["r_increment"].sum())
    return frame, {
        "annualized_sharpe": sharpe,
        "max_drawdown": float(np.min(drawdown)),
        "net_r": expected_r,
        "net_r_reconciled": reconciled_r,
        "reconciliation_error_r": reconciled_r - expected_r,
        "mean_size": float(np.mean(sizes)),
        "risk_unit_pct": float(risk_unit_pct),
    }


def _rows_for(
    prediction_frame: pl.DataFrame,
    *,
    lane: str,
    model: str,
) -> pl.DataFrame:
    return (
        prediction_frame
        .filter((pl.col("lane") == lane) & (pl.col("model") == model))
        .sort(["decision_time", "symbol"])
    )


def _lane_metrics(
    prediction_frame: pl.DataFrame,
    events: Sequence[ORBTradeEvent],
    markets: dict[str, PreparedMarket],
    *,
    lane: str,
    risk_unit_pct: float,
    roundtrip_cost_bps: float,
) -> tuple[dict[str, Any], dict[str, pl.DataFrame]]:
    raw = _rows_for(prediction_frame, lane=lane, model="raw_orb")
    if raw.is_empty():
        raise ORBMLResearchError(f"prediction lane {lane} is empty")
    raw_indices = raw["event_index"].to_list()
    lane_events = [events[int(idx)] for idx in raw_indices]
    raw_sizes = np.ones(len(lane_events), dtype=float)
    raw_daily, raw_portfolio = portfolio_daily_mtm_sizes(
        lane_events,
        raw_sizes,
        markets,
        risk_unit_pct=risk_unit_pct,
        roundtrip_cost_bps=roundtrip_cost_bps,
    )
    raw_by_year = {
        int(row["year"]): float(row["net_r"])
        for row in raw.group_by("year").agg(pl.col("r_multiple").sum().alias("net_r")).to_dicts()
    }

    metrics: dict[str, Any] = {
        "raw_orb": {
            **raw_portfolio,
            "trade_count": len(lane_events),
            "spearman_ic": None,
            "selectivity_gain_r": 0.0,
            "positive_selectivity_years": None,
        }
    }
    daily_frames = {"raw_orb": raw_daily}

    for name in MODEL_NAMES:
        model_rows = _rows_for(prediction_frame, lane=lane, model=name)
        if model_rows.height != raw.height:
            raise ORBMLResearchError(f"{lane}/{name}: missing model predictions")
        if model_rows["event_index"].to_list() != raw_indices:
            raise ORBMLResearchError(f"{lane}/{name}: event ordering mismatch")
        sizes = model_rows["size"].to_numpy()
        prediction = model_rows["prediction_r"].to_numpy()
        daily, portfolio = portfolio_daily_mtm_sizes(
            lane_events,
            sizes,
            markets,
            risk_unit_pct=risk_unit_pct,
            roundtrip_cost_bps=roundtrip_cost_bps,
        )
        mean_size = float(np.mean(sizes))
        selectivity_gain = float(portfolio["net_r"] - raw_portfolio["net_r"] * mean_size)
        positive_years = 0
        yearly: dict[str, Any] = {}
        for year in sorted(set(model_rows["year"].to_list())):
            year_rows = model_rows.filter(pl.col("year") == year)
            model_net = float(
                (year_rows["r_multiple"] * year_rows["size"]).sum()
            )
            year_mean_size = float(year_rows["size"].mean())
            raw_net = raw_by_year[int(year)]
            year_gain = model_net - raw_net * year_mean_size
            positive_years += int(year_gain > 0)
            yearly[str(year)] = {
                "trades": year_rows.height,
                "net_r": model_net,
                "mean_size": year_mean_size,
                "raw_net_r": raw_net,
                "selectivity_gain_r": float(year_gain),
            }

        metrics[name] = {
            **portfolio,
            "trade_count": len(lane_events),
            "spearman_ic": _spearman(
                prediction, model_rows["r_multiple"].to_numpy()
            ),
            "selectivity_gain_r": selectivity_gain,
            "risk_normalized_net_r": (
                float(portfolio["net_r"]) / mean_size if mean_size > 0 else 0.0
            ),
            "positive_selectivity_years": positive_years,
            "yearly": yearly,
        }
        daily_frames[name] = daily
    return metrics, daily_frames


def _apply_acceptance(
    development: dict[str, Any],
    acceptance: dict[str, Any],
) -> dict[str, Any]:
    raw = development["raw_orb"]
    passed: list[str] = []
    decisions: dict[str, Any] = {}
    for name in MODEL_NAMES:
        metric = development[name]
        checks = {
            "positive_selectivity_gain": metric["selectivity_gain_r"] > 0,
            "positive_spearman_ic": (
                metric["spearman_ic"] > 0
                if acceptance["require_positive_spearman_ic"]
                else True
            ),
            "sharpe_not_worse": (
                metric["annualized_sharpe"] >= raw["annualized_sharpe"]
                if acceptance["require_sharpe_not_worse_than_raw"]
                else True
            ),
            "drawdown_not_worse": (
                metric["max_drawdown"] >= raw["max_drawdown"]
                if acceptance["require_drawdown_not_worse_than_raw"]
                else True
            ),
            "positive_selectivity_years": (
                metric["positive_selectivity_years"]
                >= int(acceptance["min_positive_selectivity_years"])
            ),
            "never_deletes_trades": metric["trade_count"] == raw["trade_count"],
        }
        is_pass = all(checks.values())
        decisions[name] = {"passed": is_pass, "checks": checks}
        if is_pass:
            passed.append(name)

    provisional = (
        max(
            passed,
            key=lambda name: development[name]["selectivity_gain_r"],
        )
        if passed
        else None
    )
    return {
        "passed_models": passed,
        "provisional_candidate": provisional,
        "production_approved": False,
        "production_policy": (
            "Raw ORB remains authority. Any passing model is development-only until "
            "new prospective data confirms it."
        ),
        "models": decisions,
    }


def _add_dsr(
    metrics: dict[str, Any],
    daily_frames: dict[str, pl.DataFrame],
) -> None:
    all_sharpes = [
        float(metrics[name]["annualized_sharpe"])
        for name in ("raw_orb", *MODEL_NAMES)
    ]
    for name in ("raw_orb", *MODEL_NAMES):
        daily = daily_frames[name]
        returns = daily["return"].to_numpy()
        skew = float(stats.skew(returns)) if len(returns) > 2 else 0.0
        kurtosis = (
            float(stats.kurtosis(returns, fisher=False))
            if len(returns) > 3
            else 3.0
        )
        metrics[name]["dsr"] = compute_deflated_sharpe(
            float(metrics[name]["annualized_sharpe"]),
            all_sharpes,
            n_obs_days=max(len(returns), 2),
            skew=skew,
            kurtosis=kurtosis,
        )


def _raw_historical_summary(events: Sequence[ORBTradeEvent]) -> dict[str, Any]:
    r = np.asarray([event.r_multiple for event in events], dtype=float)
    by_symbol: dict[str, Any] = {}
    for symbol in sorted({event.symbol for event in events}):
        selected = [event for event in events if event.symbol == symbol]
        values = np.asarray([event.r_multiple for event in selected], dtype=float)
        by_symbol[symbol] = {
            "trades": len(selected),
            "net_r": float(np.sum(values)),
            "win_rate_pct": float(np.mean(values > 0) * 100.0),
        }
    by_year: dict[str, Any] = {}
    for year in sorted({event.date[:4] for event in events}):
        selected = [event for event in events if event.date.startswith(year)]
        values = np.asarray([event.r_multiple for event in selected], dtype=float)
        by_year[year] = {
            "trades": len(selected),
            "net_r": float(np.sum(values)),
            "win_rate_pct": float(np.mean(values > 0) * 100.0),
        }
    return {
        "trades": len(events),
        "net_r": float(np.sum(r)),
        "win_rate_pct": float(np.mean(r > 0) * 100.0),
        "by_symbol": by_symbol,
        "by_year": by_year,
    }


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
        raise ORBMLResearchError("source EOW rebuild preflight is not READY")

    output = root / str(config["artifacts"]["root"]) / run_id
    result_path = output / "result.json"
    snapshot_path = output / "config.snapshot.yaml"
    if result_path.is_file():
        return json.loads(result_path.read_text())
    if output.exists():
        unexpected = sorted(
            path.name
            for path in output.iterdir()
            if path.name != "config.snapshot.yaml"
        )
        if unexpected:
            raise ORBMLResearchError(
                f"incomplete run directory contains unexpected artifacts: {unexpected}"
            )
        if snapshot_path.is_file() and (
            snapshot_path.read_bytes() != research_config_path.read_bytes()
        ):
            raise ORBMLResearchError(
                "incomplete run directory has a different config snapshot"
            )
    else:
        output.mkdir(parents=True)
    snapshot_path.write_bytes(research_config_path.read_bytes())

    start = parse_utc(config["period"]["start"])
    end = parse_utc(config["period"]["end"])
    universe = set(map(str, config["research"]["universe"]))
    authoritative_cost = float(
        rebuild_config["execution"]["authoritative_roundtrip_bps"]
    )
    experiment_rebuild_config = copy.deepcopy(rebuild_config)
    experiment_rebuild_config["data"]["instruments"] = [
        item
        for item in rebuild_config["data"]["instruments"]
        if str(item["symbol"]) in universe
    ]
    configured_symbols = {
        str(item["symbol"])
        for item in experiment_rebuild_config["data"]["instruments"]
    }
    if configured_symbols != universe:
        missing = sorted(universe - configured_symbols)
        raise ORBMLResearchError(
            f"research universe missing from rebuild config: {missing}"
        )
    markets = prepare_all_markets(root, experiment_rebuild_config, end=end)
    built = build_events(
        markets,
        experiment_rebuild_config,
        variant="corrected",
        roundtrip_cost_bps=authoritative_cost,
        decision_start=start,
        decision_end=end,
    )
    events = [event for event in built.events if event.symbol in universe]
    if not events:
        raise ORBMLResearchError("no corrected events in configured universe")
    if any(abs(float(event.realized_return)) == math.inf for event in events):
        raise ORBMLResearchError("non-finite corrected event return")

    events, feature_diagnostics = enrich_events_with_point_in_time_features(
        events,
        markets,
        config["features"],
    )
    feature_names = list(config["features"]["names"])
    embargo = _duration(str(config["validation"]["embargo_duration"]))
    min_train_events = int(config["validation"]["min_train_events"])

    development_rows, walk_forward = walk_forward_predictions(
        events,
        feature_names,
        evaluation_years=list(config["period"]["development_evaluation_years"]),
        embargo=embargo,
        min_train_events=min_train_events,
        model_config=config["models"],
        throttle_config=config["risk_throttle"],
    )
    diagnostic_rows, diagnostic_split = historical_diagnostic_predictions(
        events,
        feature_names,
        diagnostic_start=parse_utc(config["period"]["historical_diagnostic_start"]),
        diagnostic_end=end,
        embargo=embargo,
        min_train_events=min_train_events,
        model_config=config["models"],
        throttle_config=config["risk_throttle"],
    )
    prediction_frame = pl.DataFrame(
        development_rows + diagnostic_rows,
        infer_schema_length=None,
    ).sort(["lane", "model", "decision_time", "symbol"])
    atomic_write_parquet(output / "predictions.parquet", prediction_frame)

    risk_unit_pct = float(rebuild_config["validation"]["risk_unit_pct"])
    development_metrics, development_daily = _lane_metrics(
        prediction_frame,
        events,
        markets,
        lane="development_oos",
        risk_unit_pct=risk_unit_pct,
        roundtrip_cost_bps=authoritative_cost,
    )
    _add_dsr(development_metrics, development_daily)
    diagnostic_metrics, diagnostic_daily = _lane_metrics(
        prediction_frame,
        events,
        markets,
        lane="historical_diagnostic",
        risk_unit_pct=risk_unit_pct,
        roundtrip_cost_bps=authoritative_cost,
    )
    acceptance = _apply_acceptance(
        development_metrics, config["acceptance"]
    )

    for lane, frames in (
        ("development_oos", development_daily),
        ("historical_diagnostic", diagnostic_daily),
    ):
        for name, frame in frames.items():
            atomic_write_parquet(
                output / f"{lane}_{name}_daily_mtm.parquet",
                frame,
            )

    data_fingerprints = {
        item["file"]: item["sha256"] for item in preflight["files"]
    }
    result = {
        "schema_version": "orb_ml_research_result/v1",
        "run_id": run_id,
        "status": (
            "PROVISIONAL_ML_CANDIDATE"
            if acceptance["provisional_candidate"]
            else "NO_ML_VALUE"
        ),
        "deep_learning_tested": False,
        "source": {
            "rebuild_config_sha256": sha256_file(rebuild_path),
            "research_config_sha256": sha256_file(research_config_path),
            "authoritative_roundtrip_bps": authoritative_cost,
            "data_fingerprints": data_fingerprints,
        },
        "target": "net R multiple after authoritative 6 bps roundtrip costs",
        "sizing_policy": (
            "No trade deletion. Expected-R predictions map monotonically to "
            f"{config['risk_throttle']['floor']:.2f}x-"
            f"{config['risk_throttle']['ceiling']:.2f}x risk."
        ),
        "raw_historical": _raw_historical_summary(events),
        "feature_diagnostics": feature_diagnostics,
        "walk_forward": walk_forward,
        "development_oos": development_metrics,
        "historical_diagnostic": {
            "used_for_selection": False,
            "split": diagnostic_split,
            "metrics": diagnostic_metrics,
        },
        "acceptance": acceptance,
        "selection_trial_count": 4,
        "interpretation": (
            "Only 2020-2024 walk-forward OOS metrics determine the development "
            "decision. 2025-2026 is reported for diagnosis only because it was "
            "already opened in prior research. No model is production-approved "
            "without new prospective evidence."
        ),
    }
    atomic_write_json(output / "feature_diagnostics.json", feature_diagnostics)
    atomic_write_json(output / "result.json", result)

    trial_lines = []
    for name in ("raw_orb", *MODEL_NAMES):
        metric = development_metrics[name]
        trial_lines.append(
            json.dumps(
                {
                    "schema_version": "orb_ml_research_trial/v1",
                    "run_id": run_id,
                    "lane": "development_oos",
                    "model": name,
                    "selection_trial": True,
                    "annualized_sharpe": metric["annualized_sharpe"],
                    "max_drawdown": metric["max_drawdown"],
                    "net_r": metric["net_r"],
                    "selectivity_gain_r": metric["selectivity_gain_r"],
                    "dsr": metric["dsr"],
                },
                sort_keys=True,
            )
        )
    (output / "trials.jsonl").write_text("\n".join(trial_lines) + "\n")
    return result
