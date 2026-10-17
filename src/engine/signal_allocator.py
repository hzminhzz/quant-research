"""Deterministic, PIT-only, dollar-neutral target weights; execution owns netting."""
from __future__ import annotations

import math

import polars as pl

from .common import QuantError
from .spec_parser import CandidateSpec

TARGET_COLUMNS = ['timestamp', 'symbol', 'target_weight', 'stop_loss_dist_pct']


def allocate(features: pl.DataFrame, spec: CandidateSpec, *, signal: str | None = None) -> pl.DataFrame:
    signal = signal or spec.signal
    anchor = int(spec.windows.train.start.timestamp())
    cadence = spec.bar_seconds * spec.allocation.rebalance_bars
    scheduled = features.filter(((pl.col('timestamp').dt.epoch('s') - anchor) % cadence) == 0)
    records = []
    for cross_section in scheduled.partition_by('timestamp', maintain_order=True):
        timestamp = cross_section['timestamp'][0]
        eligible = cross_section.filter(pl.col('in_pit_universe') & pl.col('is_tradable')
                                        & pl.col(signal).is_not_null() & pl.col(signal).is_finite()
                                        & pl.col(spec.allocation.atr_feature).is_not_null()
                                        & pl.col(spec.allocation.atr_feature).is_finite()
                                        & (pl.col(spec.allocation.atr_feature) > 0)
                                        # A 3x ATR long protective stop must remain
                                        # above zero. Exclude unrepresentable assets
                                        # before ranking, using decision-time prices.
                                        & (spec.allocation.atr_multiple *
                                           pl.col(spec.allocation.atr_feature) < pl.col('close')))
        ordered = eligible.sort([signal, 'symbol'], descending=[True, False])
        weights: dict[str, float] = {}
        if ordered.height >= max(spec.universe.minimum_assets,
                                 spec.allocation.long_count + spec.allocation.short_count):
            half = spec.allocation.gross_exposure / 2
            weights.update({s: half / spec.allocation.long_count
                            for s in ordered.head(spec.allocation.long_count)['symbol']})
            weights.update({s: -half / spec.allocation.short_count
                            for s in ordered.tail(spec.allocation.short_count)['symbol']})
        if abs(sum(weights.values())) > 1e-12:
            raise QuantError('INVALID_ALLOCATION', 'Market-neutral target failed')
        for row in cross_section.iter_rows(named=True):
            weight = weights.get(row['symbol'], 0.0)
            distance = (spec.allocation.atr_multiple * row[spec.allocation.atr_feature] / row['close']) if weight else 0.0
            if weight and (not math.isfinite(distance) or not 0 < distance < 1):
                raise QuantError('INVALID_ALLOCATION', 'Non-positive or unrepresentable ATR stop')
            records.append({'timestamp': timestamp, 'symbol': row['symbol'],
                            'target_weight': weight, 'stop_loss_dist_pct': distance})
    schema = {'timestamp': pl.Datetime('us', 'UTC'), 'symbol': pl.String,
              'target_weight': pl.Float64, 'stop_loss_dist_pct': pl.Float64}
    return pl.DataFrame(records, schema=schema).sort('timestamp', 'symbol')
