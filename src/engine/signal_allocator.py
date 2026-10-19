"""Deterministic, PIT-only, dollar-neutral target weights; execution owns netting."""
from __future__ import annotations

import polars as pl

from .common import QuantError
from .spec_parser import CandidateSpec

TARGET_COLUMNS = ['timestamp', 'symbol', 'target_weight', 'stop_loss_dist_pct']

_NEUTRALITY_TOLERANCE = 1e-12


def allocate(features: pl.DataFrame, spec: CandidateSpec, *, signal: str | None = None) -> pl.DataFrame:
    signal = signal or spec.signal
    anchor = int(spec.windows.train.start.timestamp())
    cadence = spec.bar_seconds * spec.allocation.rebalance_bars
    scheduled = features.filter(((pl.col('timestamp').dt.epoch('s') - anchor) % cadence) == 0)
    atr_feature = spec.allocation.atr_feature
    atr_multiple = spec.allocation.atr_multiple
    long_count = spec.allocation.long_count
    short_count = spec.allocation.short_count
    half = spec.allocation.gross_exposure / 2
    minimum_assets = max(spec.universe.minimum_assets, long_count + short_count)

    # Eligible rows are ranked cross-sectionally. The whole expression is evaluated
    # once by Polars; rank/order are the same [signal desc, symbol asc] contract as
    # the former per-timestamp Python sort.
    eligible = scheduled.filter(
        pl.col('in_pit_universe') & pl.col('is_tradable')
        & pl.col(signal).is_not_null() & pl.col(signal).is_finite()
        & pl.col(atr_feature).is_not_null()
        & pl.col(atr_feature).is_finite()
        & (pl.col(atr_feature) > 0)
        # A 3x ATR long protective stop must remain above zero. Exclude
        # unrepresentable assets before ranking, using decision-time prices.
        & (atr_multiple * pl.col(atr_feature) < pl.col('close'))
    ).select('timestamp', 'symbol', signal)

    ranked = eligible.sort(['timestamp', signal, 'symbol'],
                           descending=[False, True, False], maintain_order=True)
    ranked = ranked.with_columns(
        pl.int_range(pl.len()).over('timestamp').alias('_rank'),
        pl.len().over('timestamp').cast(pl.Int64).alias('_count'),
    ).with_columns(
        (pl.col('_rank') < long_count).alias('_head'),
        (pl.col('_rank') >= pl.col('_count') - short_count).alias('_tail'),
    ).filter((pl.col('_count') >= minimum_assets)
             & (pl.col('_head') | pl.col('_tail')))

    # Head weights are inserted first, then short weights override on a repeated
    # symbol, matching the former per-symbol dict assignment order.
    weights = ranked.with_columns(
        pl.when(pl.col('_head')).then(pl.lit(half / long_count))
        .otherwise(pl.lit(-half / short_count)).alias('target_weight'),
        pl.when(pl.col('_head')).then(0).otherwise(1).alias('_phase'),
    ).sort(['timestamp', '_phase', '_rank'], maintain_order=True).unique(
        subset=['timestamp', 'symbol'], keep='last', maintain_order=True,
    ).select('timestamp', 'symbol', 'target_weight')

    exposure = weights.group_by('timestamp').agg(pl.col('target_weight').sum())
    if (exposure['target_weight'].abs() > _NEUTRALITY_TOLERANCE).any():
        raise QuantError('INVALID_ALLOCATION', 'Market-neutral target failed')

    distance = atr_multiple * pl.col(atr_feature) / pl.col('close')
    weighted = pl.col('target_weight') != 0
    targeted = scheduled.select('timestamp', 'symbol', 'close', atr_feature).join(
        weights, on=['timestamp', 'symbol'], how='left',
    ).with_columns(pl.col('target_weight').fill_null(0.0))

    invalid = targeted.filter(
        weighted & (distance.is_null() | ~distance.is_finite()
                    | (distance <= 0) | (distance >= 1))
    )
    if invalid.height:
        raise QuantError('INVALID_ALLOCATION', 'Non-positive or unrepresentable ATR stop')

    return targeted.select(
        pl.col('timestamp').cast(pl.Datetime('us', 'UTC')),
        pl.col('symbol').cast(pl.String),
        pl.col('target_weight').cast(pl.Float64),
        pl.when(weighted).then(distance).otherwise(0.0).alias('stop_loss_dist_pct'),
    ).sort('timestamp', 'symbol')
