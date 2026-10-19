"""Run a time-series sleeve on the native engine with modeled carry applied.

The native lifecycle adapter is shared with v1: this module only builds the
attribute surface `run_native` needs, aligns modeled settlement events to the
native event clock, and validates them before any simulation state exists.
"""
from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from .backtest_runner import NativeRun, run_native
from .common import QuantError
from .ts_spec import MarketClass, TimeSeriesSpec

CARRY_COLUMNS = ['timestamp', 'symbol', 'funding_rate', 'mark_price', 'source_event_at']


@dataclass(frozen=True)
class TSRunSpec:
    """The subset of v1 spec attributes the shared native adapter reads."""
    initial_cash: float
    bar_seconds: int
    periods_per_year: int
    costs: object
    barrier_overlay_enabled: bool = False


def align_carry_events(events: pl.DataFrame, panel: pl.DataFrame) -> pl.DataFrame:
    """Snap each settlement to the first native clock instant at or after it.

    A modeled settlement can fall outside a session-bound feed (indices and metals
    do not trade at 00:00 UTC). The cashflow becomes effective at the first bar the
    engine actually sees, and the scheduled instant is retained as provenance.
    """
    if events.is_empty():
        raise QuantError('BLOCKED_DATA', 'Carry integration requires at least one settlement event')
    missing = {'timestamp', 'symbol', 'funding_rate', 'mark_price'} - set(events.columns)
    if missing:
        raise QuantError('BLOCKED_DATA', f'Carry events are missing columns: {sorted(missing)}')
    rate = pl.col('funding_rate')
    mark = pl.col('mark_price')
    invalid = events.filter(rate.is_null() | rate.is_finite().not_()
                            | mark.is_null() | mark.is_finite().not_() | (mark <= 0))
    if invalid.height:
        raise QuantError('BLOCKED_DATA', 'Carry event has a nonfinite rate or an invalid mark')
    feed = pl.DataFrame({'feed_at': panel['timestamp'].unique().sort()})
    if feed.is_empty():
        raise QuantError('BLOCKED_DATA', 'Native panel has no timestamps')
    aligned = (events.sort('timestamp')
               .join_asof(feed, left_on='timestamp', right_on='feed_at', strategy='forward'))
    if aligned['feed_at'].null_count():
        raise QuantError('BLOCKED_DATA', 'A carry settlement falls after the last native instant')
    # Session-bound feeds skip nights and weekends, so several calendar
    # settlements can become effective at the same bar. Their accrual sums; the
    # last causal mark is used and the count is retained for provenance.
    aggregations = [
        pl.col('funding_rate').sum().alias('funding_rate'),
        pl.col('mark_price').last().alias('mark_price'),
        pl.col('timestamp').min().alias('source_event_at'),
        pl.col('timestamp').max().alias('last_scheduled_at'),
        pl.len().alias('settlement_count'),
    ]
    for name in ('curve_at', 'mark_at', 'curve_name'):
        if name in aligned.columns:
            aggregations.append(pl.col(name).last())
    return (aligned.group_by('feed_at', 'symbol').agg(aggregations)
            .with_columns(pl.col('feed_at').alias('timestamp')).drop('feed_at')
            .sort('timestamp', 'symbol'))


def run_native_ts(panel: pl.DataFrame, targets: pl.DataFrame, spec: TimeSeriesSpec,
                  market_class: MarketClass, *,
                  carry_events: pl.DataFrame | None = None,
                  carry_metadata: dict | None = None) -> NativeRun:
    """Native simulation for one class panel; carry is applied when declared modeled."""
    adapter = TSRunSpec(initial_cash=spec.initial_cash,
                        bar_seconds=market_class.bar_seconds,
                        periods_per_year=market_class.periods_per_year,
                        costs=spec.costs)
    funding = align_carry_events(carry_events, panel) if carry_events is not None else None
    result = run_native(panel, targets, adapter, funding=funding)
    if carry_events is not None:
        mode = (carry_metadata or {}).get('status', 'MODELED')
        result.metrics['carry_status'] = mode
        result.metrics['carry_events'] = funding.height if funding is not None else 0
        result.metrics['carry_curve'] = (carry_metadata or {}).get('curve', {}).get('name')
        result.metrics['carry_sign_convention'] = (carry_metadata or {}).get('sign_convention')
    else:
        result.metrics['carry_status'] = 'NOT_APPLIED'
    return result
