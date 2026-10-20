"""Focused contract regressions for the cross-sectional target allocator.

These pin the invariants that the vectorized implementation must preserve and
that the pre-vectorization loop defined: PIT/eligibility gating, the minimum
universe barrier, deterministic tie-breaking, cadence scheduling, row
multiplicity/order and the exact ``TARGET_COLUMNS`` schema. Synthetic fixtures
only; no vault, protected window or market evidence.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from src.engine.common import QuantError
from src.engine.signal_allocator import TARGET_COLUMNS, allocate
from src.engine.spec_parser import CandidateSpec

START = datetime(2025, 1, 1, tzinfo=UTC)
TARGET_SCHEMA = {
    'timestamp': pl.Datetime('us', 'UTC'), 'symbol': pl.String,
    'target_weight': pl.Float64, 'stop_loss_dist_pct': pl.Float64,
}


def make_spec(*, long_count=2, short_count=2, minimum_assets=4, atr_multiple=3.0,
              gross=1.0, cadence=1):
    return CandidateSpec.model_validate({
        'candidate_id': 'allocator_contract', 'selection_family_id': 'allocator_contract',
        'source_spec_status': 'synthetic_test',
        'thesis': 'Allocator contract fixture; never market evidence.',
        'panel_root': 'unused-synthetic',
        'windows': {'train': {'start': START.isoformat(), 'end': '2025-07-01T00:00:00Z'},
                    'validation': {'start': '2025-07-01T00:00:00Z', 'end': '2026-01-01T00:00:00Z'},
                    'protected': {'start': '2026-01-01T00:00:00Z', 'end': '2026-04-01T00:00:00Z'}},
        'features': [{'name': name, 'expr': {'op': 'col', 'name': 'close'}}
                     for name in ('sig', 'bline', 'atr')],
        'signal': 'sig', 'baseline': 'bline',
        'universe': {'top_n': 5000, 'minimum_assets': minimum_assets,
                     'lookback_bars': 1, 'minimum_history_bars': 1},
        'allocation': {'long_count': long_count, 'short_count': short_count,
                       'gross_exposure': gross, 'rebalance_bars': cadence,
                       'atr_feature': 'atr', 'atr_multiple': atr_multiple},
        'costs': {'commission_bps_one_way': 1.0, 'slippage_bps_one_way': 1.0},
        'gates': {'minimum_ic_observations': 3, 'minimum_daily_observations': 10,
                  'minimum_completed_trades': 1},
        'label_horizon_bars': 1,
    })


def frame(rows, *, time_unit='us'):
    data = {}
    for name, values in rows.items():
        if name == 'timestamp':
            data[name] = pl.Series(name, values, dtype=pl.Datetime(time_unit, 'UTC'))
        elif name == 'symbol':
            data[name] = pl.Series(name, values, dtype=pl.String)
        else:
            data[name] = values
    return pl.DataFrame(data)


def basket(symbols, *, sig=None, atr=1.0, close=100.0, bars=1, step=timedelta(hours=1)):
    """One cross-section per bar, identical membership in every bar."""
    sig = sig if sig is not None else [float(index) for index in range(len(symbols))]
    return frame({
        'timestamp': [START + step * bar for bar in range(bars) for _ in symbols],
        'symbol': list(symbols) * bars,
        'close': [close] * (len(symbols) * bars),
        'sig': list(sig) * bars,
        'atr': [atr] * (len(symbols) * bars),
        'in_pit_universe': [True] * (len(symbols) * bars),
        'is_tradable': [True] * (len(symbols) * bars),
    })


def per_timestamp(targets):
    return targets.group_by('timestamp', maintain_order=True).agg(
        pl.col('target_weight').sum().alias('net'),
        pl.col('target_weight').abs().sum().alias('gross'),
    )


def test_target_schema_is_stable_for_float32_feature_columns():
    """A Float32 feature panel must not coarsen the published target schema.

    The pre-vectorization loop read values as Python floats (exact Float32 ->
    Float64 widening), so `stop_loss_dist_pct` was always Float64 and the stop
    distance was computed in double precision. The vectorized path must cast the
    operands explicitly instead of inheriting Float32 column dtypes.
    """
    closes = [101.7, 99.3, 105.1, 98.4, 110.2, 97.6]
    atrs = [1.3, 0.9, 1.7, 0.8, 2.1, 0.7]
    panel = frame({
        'timestamp': [START] * 6, 'symbol': list('ABCDEF'),
        'close': np.asarray(closes, dtype=np.float32),
        'sig': np.asarray([3.5, 2.5, 1.5, 0.5, -0.5, -1.5], dtype=np.float32),
        'atr': np.asarray(atrs, dtype=np.float32),
        'in_pit_universe': [True] * 6, 'is_tradable': [True] * 6,
    })
    targets = allocate(panel, make_spec())
    assert targets.schema == TARGET_SCHEMA
    assert targets.columns == TARGET_COLUMNS
    reference = {symbol: (float(np.float32(close)), float(np.float32(atr)))
                 for symbol, close, atr in zip('ABCDEF', closes, atrs)}
    longs = targets.filter(pl.col('target_weight') > 0)
    assert longs.height == 2
    for symbol, distance in zip(longs['symbol'].to_list(),
                               longs['stop_loss_dist_pct'].to_list()):
        close, atr = reference[symbol]
        assert distance == 3.0 * atr / close  # exact bit pattern, not approx


def test_empty_frame_returns_empty_targets_with_published_schema():
    empty = pl.DataFrame(schema={'timestamp': pl.Datetime('us', 'UTC'),
                                 'symbol': pl.String, 'close': pl.Float64,
                                 'sig': pl.Float64, 'atr': pl.Float64,
                                 'in_pit_universe': pl.Boolean, 'is_tradable': pl.Boolean})
    targets = allocate(empty, make_spec())
    assert targets.height == 0
    assert targets.schema == TARGET_SCHEMA


def test_no_eligible_row_emits_zero_weights_for_every_scheduled_row():
    panel = basket(list('ABCD'), bars=3).with_columns(
        pl.lit(False).alias('in_pit_universe'), pl.lit(False).alias('is_tradable'))
    targets = allocate(panel, make_spec())
    assert targets.height == panel.height
    assert targets['target_weight'].abs().max() == 0.0
    assert targets['stop_loss_dist_pct'].abs().max() == 0.0


def test_minimum_universe_barrier_allocates_only_at_the_threshold():
    spec = make_spec(long_count=2, short_count=2, minimum_assets=4)
    below = allocate(basket(list('ABC')), spec)
    assert below.height == 3 and below['target_weight'].abs().max() == 0.0

    at_threshold = allocate(basket(list('ABCD')), spec)
    assert sorted(at_threshold['target_weight'].to_list()) == [-0.25, -0.25, 0.25, 0.25]
    assert per_timestamp(at_threshold)['net'].abs().max() < 1e-12


def test_signal_ties_break_on_symbol_ascending_and_baskets_stay_disjoint():
    symbols = list('ABCDEF')
    targets = allocate(basket(symbols, sig=[0.0] * len(symbols)), make_spec())
    weights = dict(zip(targets['symbol'].to_list(), targets['target_weight'].to_list()))
    # Sorted by [signal desc, symbol asc]: head=A,B (long), tail=E,F (short).
    assert weights == {'A': 0.25, 'B': 0.25, 'C': 0.0, 'D': 0.0, 'E': -0.25, 'F': -0.25}


def test_nonfinite_and_null_signals_never_displace_eligible_assets():
    symbols = list('ABCDEFGH')
    panel = basket(symbols, sig=[1.0] * len(symbols))
    panel = panel.with_columns(
        pl.when(pl.col('symbol') == 'A').then(float('nan'))
        .when(pl.col('symbol') == 'B').then(float('inf'))
        .when(pl.col('symbol') == 'C').then(None)
        .otherwise(pl.col('sig')).alias('sig'))
    targets = allocate(panel, make_spec())
    weights = dict(zip(targets['symbol'].to_list(), targets['target_weight'].to_list()))
    assert weights['A'] == weights['B'] == weights['C'] == 0.0
    # Five eligible assets tie; head/tail are the alphabetical ends D,E and G,H.
    assert weights == {'A': 0.0, 'B': 0.0, 'C': 0.0, 'D': 0.25, 'E': 0.25,
                       'F': 0.0, 'G': -0.25, 'H': -0.25}


def test_unrepresentable_atr_stop_is_excluded_before_ranking():
    symbols = list('ABCDE')
    spec = make_spec(long_count=1, short_count=1, minimum_assets=4)
    # 'E' has the best signal but a 3x ATR stop at/above the decision price.
    panel = basket(symbols, sig=[1.0, 2.0, 3.0, 4.0, 5.0])
    panel = panel.with_columns(
        pl.when(pl.col('symbol') == 'E').then(pl.lit(100.0 / 3.0))
        .otherwise(pl.col('atr')).alias('atr'))
    targets = allocate(panel, spec)
    weights = dict(zip(targets['symbol'].to_list(), targets['target_weight'].to_list()))
    assert weights['E'] == 0.0
    assert weights['D'] == 0.5 and weights['A'] == -0.5


def test_cadence_emits_only_aligned_timestamps():
    spec = make_spec(cadence=3)
    panel = basket(list('ABCD'), bars=7)
    targets = allocate(panel, spec)
    anchor = int(START.timestamp())
    aligned = [(int(ts.timestamp()) - anchor) % (3600 * 3) == 0
               for ts in targets['timestamp'].unique().sort().to_list()]
    assert all(aligned)
    assert targets['timestamp'].n_unique() == 3


def test_duplicate_timestamp_symbol_rows_are_preserved_and_keep_the_neutrality_guard():
    """Duplicate (timestamp, symbol) rows are contract violations.

    The historical loop collapsed weights into a per-symbol dict, so a duplicate
    inside a weighted basket silently lost one leg and tripped the neutrality
    assertion. The vectorized path must reproduce that guard (a duplicate in the
    long head is rejected) while still emitting one output row per input row when
    the duplicate is outside both baskets.
    """
    head_duplicate = {
        'timestamp': [START] * 6, 'symbol': ['A', 'A', 'B', 'C', 'D', 'E'],
        'close': [100.0] * 6, 'sig': [5.0, 1.0, 4.0, 3.0, 2.0, 0.0], 'atr': [1.0] * 6,
        'in_pit_universe': [True] * 6, 'is_tradable': [True] * 6,
    }
    with pytest.raises(QuantError, match='Market-neutral target failed'):
        allocate(frame(head_duplicate), make_spec())

    middle_duplicate = {
        'timestamp': [START] * 8,
        'symbol': ['A', 'B', 'C', 'D', 'D', 'E', 'F', 'G'],
        'close': [100.0] * 8, 'sig': [6.0, 5.0, 3.0, 2.0, 2.0, 1.0, 0.5, 0.0],
        'atr': [1.0] * 8,
        'in_pit_universe': [True] * 8, 'is_tradable': [True] * 8,
    }
    targets = allocate(frame(middle_duplicate), make_spec())
    assert targets.height == 8  # one output row per scheduled input row
    weights = dict(zip(targets['symbol'].to_list(), targets['target_weight'].to_list()))
    assert weights == {'A': 0.25, 'B': 0.25, 'C': 0.0, 'D': 0.0, 'E': 0.0,
                       'F': -0.25, 'G': -0.25}


def test_output_is_sorted_by_timestamp_then_symbol_and_gross_is_neutral():
    spec = make_spec(long_count=3, short_count=1, gross=2.0, minimum_assets=8)
    panel = basket([f'S{index:02d}' for index in range(8)], bars=5,
                   sig=[float(index) for index in range(8)])
    shuffled = panel.sample(fraction=1.0, shuffle=True, seed=13)
    targets = allocate(shuffled, spec)
    assert targets.height == panel.height
    assert targets.select('timestamp', 'symbol').equals(
        targets.select('timestamp', 'symbol').sort('timestamp', 'symbol'))
    stats = per_timestamp(targets)
    assert stats['net'].abs().max() < 1e-12
    assert stats['gross'].to_list() == pytest.approx([2.0] * 5)
