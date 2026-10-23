"""Deterministic time-series target weights; execution still owns netting.

Every rebalance emits one row per observed symbol at that timestamp, with a zero
weight for anything not eligible. Instrument risk budgets are volatility-aware,
capped, then scaled to the sleeve's declared gross exposure; direction comes from
the forecast sign. The declared `volatility_target` is the sleeve's risk level for
qualification evidence, not a weight input: scaling weights to a fixed gross
exposure is what makes the target contract reproducible.

The scheduler, eligibility filter and output assembly are evaluated once by
Polars. Per-rebalance budget arithmetic stays in Python on the same values and in
the same order as the former per-timestamp loop, so the emitted frame is
bit-identical (the benchmark harness fingerprints every repeat).
"""
from __future__ import annotations

import math

import numpy as np
import polars as pl

from .common import QuantError
from .signal_allocator import TARGET_COLUMNS
from .ts_spec import MarketClass, TimeSeriesSpec

SCHEMA = {'timestamp': pl.Datetime('us', 'UTC'), 'symbol': pl.String,
          'target_weight': pl.Float64, 'stop_loss_dist_pct': pl.Float64}


def _eligible_expr(spec: TimeSeriesSpec) -> pl.Expr:
    stop = pl.col(spec.stops.feature)
    conditions = [
        pl.col('in_pit_universe'),
        pl.col('is_tradable'),
        pl.col('forecast').is_not_null() & pl.col('forecast').is_finite() & (pl.col('forecast') != 0),
        stop.is_not_null() & stop.is_finite() & (stop > 0),
        spec.stops.multiple * stop < pl.col('close'),
    ]
    vol_name = spec.risk_allocation.volatility_feature
    if vol_name is not None:
        vol = pl.col(vol_name)
        conditions.append(vol.is_not_null() & vol.is_finite() & (vol > 0))
    return pl.all_horizontal(conditions)


def _eligible(block: pl.DataFrame, spec: TimeSeriesSpec) -> pl.DataFrame:
    return block.filter(_eligible_expr(spec))


def _raw_budgets_from_values(symbols: list[str], forecasts: list[float],
                             vols: list[float] | None,
                             spec: TimeSeriesSpec) -> dict[str, float]:
    method = spec.risk_allocation.method
    if method == 'manual':
        declared = spec.risk_allocation.weights or {}
        return {symbol: declared[symbol] for symbol in symbols}
    if method == 'equal_weight':
        return {symbol: 1.0 for symbol in symbols}
    if method == 'inverse_volatility':
        return {symbol: 1.0 / vol for symbol, vol in zip(symbols, vols, strict=True)}
    return {symbol: abs(forecast) / vol
            for symbol, forecast, vol in zip(symbols, forecasts, vols, strict=True)}


def _raw_budgets(block: pl.DataFrame, spec: TimeSeriesSpec) -> dict[str, float]:
    vol_name = spec.risk_allocation.volatility_feature
    return _raw_budgets_from_values(
        block['symbol'].to_list(), block['forecast'].to_list(),
        block[vol_name].to_list() if vol_name is not None else None, spec)


def capped_budgets(raw: dict[str, float], cap: float) -> dict[str, float]:
    """Normalize to one and enforce the per-instrument cap by water-filling."""
    symbols = sorted(raw)
    if not symbols:
        return {}
    if len(symbols) * cap < 1 - 1e-12:
        raise QuantError('INVALID_ALLOCATION',
                         'Per-instrument caps make the declared gross exposure unreachable')
    total = sum(raw.values())
    if not math.isfinite(total) or total <= 0:
        raise QuantError('INVALID_ALLOCATION', 'Risk budgets must be finite and positive')
    budgets = {symbol: raw[symbol] / total for symbol in symbols}
    frozen: set[str] = set()
    for _ in range(len(symbols) + 1):
        over = [symbol for symbol in symbols
                if symbol not in frozen and budgets[symbol] > cap + 1e-12]
        if not over:
            break
        for symbol in over:
            budgets[symbol] = cap
        frozen.update(over)
        free = [symbol for symbol in symbols if symbol not in frozen]
        if not free:
            break
        remaining = 1.0 - cap * len(frozen)
        pool = sum(raw[symbol] for symbol in free)
        if pool <= 0:
            if remaining > 1e-12:
                raise QuantError('INVALID_ALLOCATION',
                                 'Zero uncapped budgets cannot absorb the residual risk')
            for symbol in free:
                budgets[symbol] = 0.0
            break
        for symbol in free:
            budgets[symbol] = raw[symbol] / pool * remaining
    if any(budgets[symbol] > cap + 1e-9 for symbol in symbols):
        raise QuantError('INVALID_ALLOCATION', 'Per-instrument cap could not be satisfied')
    return budgets


def _weights_from_values(symbols: list[str], forecasts: list[float], stops: list[float],
                         closes: list[float], vols: list[float] | None,
                         spec: TimeSeriesSpec, declared_count: int,
                         ) -> dict[str, tuple[float, float]]:
    allocation = spec.risk_allocation
    if declared_count * allocation.per_instrument_cap < 1 - 1e-12:
        raise QuantError('INVALID_ALLOCATION',
                         'Per-instrument caps make the declared gross exposure unreachable '
                         'for the declared universe')
    if len(set(symbols)) * allocation.per_instrument_cap < 1 - 1e-12:
        # Warm-up or a session gap can leave too few eligible names at one
        # rebalance; hold flat rather than emit an under-invested book.
        return {}
    budgets = capped_budgets(
        _raw_budgets_from_values(symbols, forecasts, vols, spec),
        allocation.per_instrument_cap)
    gross = allocation.gross_exposure
    multiple = spec.stops.multiple
    result = {}
    for symbol, forecast, stop, close in zip(symbols, forecasts, stops, closes, strict=True):
        budget = budgets[symbol]
        direction = 1.0 if forecast > 0 else -1.0
        weight = direction * budget * gross
        distance = multiple * stop / close
        if not math.isfinite(distance) or not 0 < distance < 1:
            raise QuantError('INVALID_ALLOCATION', 'Non-positive or unrepresentable stop distance')
        result[symbol] = (weight, distance)
    if not result:
        return {}
    if abs(sum(abs(w) for w, _ in result.values()) - gross) > 1e-9:
        raise QuantError('INVALID_ALLOCATION', 'Allocated gross exposure does not match the declaration')
    return result


def _weights(eligible: pl.DataFrame, spec: TimeSeriesSpec,
             declared_count: int) -> dict[str, tuple[float, float]]:
    vol_name = spec.risk_allocation.volatility_feature
    return _weights_from_values(
        eligible['symbol'].to_list(), eligible['forecast'].to_list(),
        eligible[spec.stops.feature].to_list(), eligible['close'].to_list(),
        eligible[vol_name].to_list() if vol_name is not None else None,
        spec, declared_count)


def allocate_ts(features: pl.DataFrame, spec: TimeSeriesSpec,
                market_class: MarketClass) -> pl.DataFrame:
    """Emit the native target-weight/stop contract for one market class."""
    anchor = int(spec.windows.train.start.timestamp())
    cadence = market_class.bar_seconds * spec.rebalance_bars
    scheduled = features.filter(((pl.col('timestamp').dt.epoch('s') - anchor) % cadence) == 0)
    if scheduled.is_empty():
        return pl.DataFrame(schema=SCHEMA).select(TARGET_COLUMNS).sort('timestamp', 'symbol')

    stop_name = spec.stops.feature
    vol_name = spec.risk_allocation.volatility_feature
    value_names = list(dict.fromkeys(
        ['forecast', stop_name, 'close'] + ([vol_name] if vol_name is not None else [])))
    # One evaluation of the exact eligibility expression. A null result means
    # "not eligible", matching ``DataFrame.filter``; cast to a plain boolean mask
    # so the per-rebalance loop does no further Polars work.
    prepared = scheduled.with_row_index('_row').select(
        pl.col('timestamp'), pl.col('symbol'), *[pl.col(name) for name in value_names],
        pl.col('_row'), _eligible_expr(spec).fill_null(False).alias('_eligible'),
    ).sort('timestamp', maintain_order=True)

    symbols = prepared['symbol'].to_list()
    forecasts = prepared['forecast'].to_list()
    stops = prepared[stop_name].to_list()
    closes = prepared['close'].to_list()
    vols = prepared[vol_name].to_list() if vol_name is not None else None
    eligible = prepared['_eligible'].to_numpy()
    ticks = prepared['timestamp'].cast(pl.Int64).to_numpy()
    original_rows = prepared['_row'].to_numpy()

    weight_values = np.zeros(len(symbols), dtype=np.float64)
    distance_values = np.zeros(len(symbols), dtype=np.float64)

    # ``timestamp`` is sorted above, so identical timestamps are contiguous and
    # stable within a section, exactly like ``partition_by(maintain_order=True)``
    # on the scheduled frame.
    if ticks.size:
        changes = np.flatnonzero(ticks[1:] != ticks[:-1]) + 1
        starts = np.concatenate(([0], changes))
        ends = np.concatenate((changes, [ticks.size]))
    else:  # pragma: no cover - guarded by the empty-frame return above
        starts = ends = np.empty(0, dtype=np.int64)

    declared_count = len(market_class.symbols)
    # The former loop raised before reading any rebalance, even one with no
    # eligible row; preserve that check and its precedence.
    if declared_count * spec.risk_allocation.per_instrument_cap < 1 - 1e-12:
        raise QuantError('INVALID_ALLOCATION',
                         'Per-instrument caps make the declared gross exposure unreachable '
                         'for the declared universe')

    # Rebalances are traversed in first-appearance order, like
    # ``partition_by(maintain_order=True)`` on the scheduled frame; the emitted
    # frame is sorted afterwards, so only error precedence depends on this.
    group_order = np.argsort(original_rows[starts], kind='stable') if starts.size else starts
    for group in group_order.tolist():
        start, end = int(starts[group]), int(ends[group])
        local = np.flatnonzero(eligible[start:end])
        if local.size == 0:
            continue
        eligible_positions = (local + start).tolist()
        weights = _weights_from_values(
            [symbols[position] for position in eligible_positions],
            [forecasts[position] for position in eligible_positions],
            [stops[position] for position in eligible_positions],
            [closes[position] for position in eligible_positions],
            [vols[position] for position in eligible_positions] if vols is not None else None,
            spec, declared_count)
        # The former loop looked the symbol up for every row of the section, not
        # only the eligible ones, so a repeated (timestamp, symbol) row inherited
        # its twin's assignment. Duplicate rows are an upstream contract
        # violation, but the emitted values still have to match.
        for position in range(start, end):
            weight, distance = weights.get(symbols[position], (0.0, 0.0))
            weight_values[position] = weight
            distance_values[position] = distance

    return pl.DataFrame({
        'timestamp': prepared['timestamp'],
        'symbol': prepared['symbol'].cast(pl.String),
        'target_weight': weight_values,
        'stop_loss_dist_pct': distance_values,
    }).select(
        pl.col('timestamp').cast(pl.Datetime('us', 'UTC')),
        pl.col('symbol'),
        pl.col('target_weight'),
        pl.col('stop_loss_dist_pct'),
    ).sort('timestamp', 'symbol')
