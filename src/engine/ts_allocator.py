"""Deterministic time-series target weights; execution still owns netting.

Every rebalance emits one row per observed symbol at that timestamp, with a zero
weight for anything not eligible. Instrument risk budgets are volatility-aware,
capped, then scaled to the sleeve's declared gross exposure; direction comes from
the forecast sign. The declared `volatility_target` is the sleeve's risk level for
qualification evidence, not a weight input: scaling weights to a fixed gross
exposure is what makes the target contract reproducible.
"""
from __future__ import annotations

import math

import polars as pl

from .common import QuantError
from .signal_allocator import TARGET_COLUMNS
from .ts_spec import MarketClass, TimeSeriesSpec

SCHEMA = {'timestamp': pl.Datetime('us', 'UTC'), 'symbol': pl.String,
          'target_weight': pl.Float64, 'stop_loss_dist_pct': pl.Float64}


def _eligible(block: pl.DataFrame, spec: TimeSeriesSpec) -> pl.DataFrame:
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
    return block.filter(pl.all_horizontal(conditions))


def _raw_budgets(block: pl.DataFrame, spec: TimeSeriesSpec) -> dict[str, float]:
    rows = list(block.iter_rows(named=True))
    method = spec.risk_allocation.method
    if method == 'manual':
        declared = spec.risk_allocation.weights or {}
        return {row['symbol']: declared[row['symbol']] for row in rows}
    if method == 'equal_weight':
        return {row['symbol']: 1.0 for row in rows}
    vol_name = spec.risk_allocation.volatility_feature
    if method == 'inverse_volatility':
        return {row['symbol']: 1.0 / row[vol_name] for row in rows}
    return {row['symbol']: abs(row['forecast']) / row[vol_name] for row in rows}


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


def _weights(eligible: pl.DataFrame, spec: TimeSeriesSpec) -> dict[str, tuple[float, float]]:
    allocation = spec.risk_allocation
    budgets = capped_budgets(_raw_budgets(eligible, spec), allocation.per_instrument_cap)
    gross = allocation.gross_exposure
    result = {}
    for row in eligible.iter_rows(named=True):
        budget = budgets[row['symbol']]
        direction = 1.0 if row['forecast'] > 0 else -1.0
        weight = direction * budget * gross
        distance = spec.stops.multiple * row[spec.stops.feature] / row['close']
        if not math.isfinite(distance) or not 0 < distance < 1:
            raise QuantError('INVALID_ALLOCATION', 'Non-positive or unrepresentable stop distance')
        result[row['symbol']] = (weight, distance)
    if not result:
        return {}
    if abs(sum(abs(w) for w, _ in result.values()) - gross) > 1e-9:
        raise QuantError('INVALID_ALLOCATION', 'Allocated gross exposure does not match the declaration')
    return result


def allocate_ts(features: pl.DataFrame, spec: TimeSeriesSpec,
                market_class: MarketClass) -> pl.DataFrame:
    """Emit the native target-weight/stop contract for one market class."""
    anchor = int(spec.windows.train.start.timestamp())
    cadence = market_class.bar_seconds * spec.rebalance_bars
    scheduled = features.filter(((pl.col('timestamp').dt.epoch('s') - anchor) % cadence) == 0)
    records = []
    for block in scheduled.partition_by('timestamp', maintain_order=True):
        timestamp = block['timestamp'][0]
        weights = _weights(_eligible(block, spec), spec)
        for row in block.iter_rows(named=True):
            weight, distance = weights.get(row['symbol'], (0.0, 0.0))
            records.append({'timestamp': timestamp, 'symbol': row['symbol'],
                            'target_weight': weight, 'stop_loss_dist_pct': distance})
    return pl.DataFrame(records, schema=SCHEMA).select(TARGET_COLUMNS).sort('timestamp', 'symbol')
