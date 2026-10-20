"""Edge-case contract regressions for the cross-sectional allocator.

``tests/test_signal_allocator_contract.py`` pins the main invariants. This module
adds the cases that module does not cover, each of which the differential
qualification (``scripts/qualify_ats_allocator_equivalence.py``) showed to be
either a real regression or an unexercised contract edge:

* a feature name that collides with a panel column (``atr_feature: close``) raised
  a Polars ``DuplicateError`` from the output projection instead of allocating;
* integer and Float32 feature dtypes are accepted and still emit the published
  Float64 target contract;
* cadence is anchored to ``windows.train.start`` even when the panel starts
  off-cadence, and a panel with no aligned timestamp emits an empty typed frame;
* the ``signal`` override argument selects the other declared feature;
* a duplicate symbol whose twin is ineligible is rejected as
  ``INVALID_ALLOCATION`` rather than crashing on a Python type error.

Synthetic fixtures only; no vault, protected window, casefile or market evidence.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

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


def make_spec(*, long_count=2, short_count=2, cadence=1, bar_seconds=3600,
              atr_feature='atr', signal='sig',
              features=('sig', 'bline', 'atr')) -> CandidateSpec:
    return CandidateSpec.model_validate({
        'candidate_id': 'allocator_edge', 'selection_family_id': 'allocator_edge',
        'source_spec_status': 'synthetic_test',
        'thesis': 'Allocator edge fixture; never market evidence.',
        'panel_root': 'unused-synthetic', 'bar_seconds': bar_seconds,
        'windows': {'train': {'start': START.isoformat(), 'end': '2025-07-01T00:00:00Z'},
                    'validation': {'start': '2025-07-01T00:00:00Z',
                                   'end': '2026-01-01T00:00:00Z'},
                    'protected': {'start': '2026-01-01T00:00:00Z',
                                  'end': '2026-04-01T00:00:00Z'}},
        'features': [{'name': name, 'expr': {'op': 'col', 'name': 'close'}}
                     for name in features],
        'signal': signal, 'baseline': 'bline',
        'universe': {'top_n': 5000, 'minimum_assets': long_count + short_count,
                     'lookback_bars': 1, 'minimum_history_bars': 1},
        'allocation': {'long_count': long_count, 'short_count': short_count,
                       'gross_exposure': 1.0, 'rebalance_bars': cadence,
                       'atr_feature': atr_feature, 'atr_multiple': 3.0},
        'costs': {'commission_bps_one_way': 1.0, 'slippage_bps_one_way': 1.0},
        'gates': {'minimum_ic_observations': 3, 'minimum_daily_observations': 10,
                  'minimum_completed_trades': 1},
        'label_horizon_bars': 1,
    })


def frame(rows: dict[str, list], *, dtypes: dict[str, pl.DataType] | None = None,
          ) -> pl.DataFrame:
    schema = {'timestamp': pl.Datetime('us', 'UTC'), 'symbol': pl.String,
              'close': pl.Float64, 'sig': pl.Float64, 'bline': pl.Float64,
              'atr': pl.Float64, 'in_pit_universe': pl.Boolean,
              'is_tradable': pl.Boolean}
    schema.update(dtypes or {})
    return pl.DataFrame({name: values for name, values in rows.items()}).cast(schema)


def basket(symbols: list[str], *, bars: int = 1, sig: list[float] | None = None,
           close: float = 100.0, atr: float = 1.0) -> pl.DataFrame:
    signals = sig if sig is not None else [float(len(symbols) - index)
                                           for index in range(len(symbols))]
    timestamps, names = [], []
    for bar in range(bars):
        for symbol in symbols:
            timestamps.append(START + timedelta(hours=bar))
            names.append(symbol)
    return frame({'timestamp': timestamps, 'symbol': names,
                  'close': [close] * len(names), 'sig': signals * bars,
                  'bline': [-value for value in signals] * bars,
                  'atr': [atr] * len(names),
                  'in_pit_universe': [True] * len(names),
                  'is_tradable': [True] * len(names)})


def test_atr_feature_named_close_collision_allocates():
    """Regression: the output projection raised DuplicateError for this spec."""
    panel = basket([f'S{index:02d}' for index in range(6)], close=100.0)
    panel = panel.with_columns(pl.lit(100.0).alias('atr'))
    spec = make_spec(atr_feature='close', long_count=1, short_count=1,
                     features=('sig', 'bline', 'close'))
    targets = allocate(panel, spec)
    assert targets.columns == TARGET_COLUMNS
    assert targets.schema == TARGET_SCHEMA
    # A 3x ATR stop at the decision-time price is not representable: flat basket.
    assert targets['target_weight'].abs().max() == 0.0


def test_atr_feature_aliasing_the_signal_is_supported():
    panel = basket([f'S{index:02d}' for index in range(6)], atr=1.0)
    panel = panel.with_columns(pl.col('sig').alias('atr'))
    targets = allocate(panel, make_spec(atr_feature='sig', long_count=1, short_count=1,
                                        features=('sig', 'bline')))
    assert targets.columns == TARGET_COLUMNS
    assert targets['target_weight'].abs().max() > 0


def test_signal_named_close_is_supported():
    panel = basket([f'S{index:02d}' for index in range(6)])
    targets = allocate(panel, make_spec(signal='close', long_count=1, short_count=1,
                                        features=('sig', 'bline', 'atr', 'close')))
    assert targets.columns == TARGET_COLUMNS
    # ``close`` is identical for every symbol, so ranking is purely symbol-ascending.
    weights = dict(zip(targets['symbol'].to_list(), targets['target_weight'].to_list()))
    assert weights['S00'] == 0.5 and weights['S05'] == -0.5


@pytest.mark.parametrize('dtype', [pl.Int64, pl.Float32])
def test_non_float64_feature_dtypes_keep_the_target_contract(dtype):
    panel = basket([f'S{index:02d}' for index in range(6)])
    panel = panel.with_columns(
        pl.col('close').cast(dtype), pl.col('sig').cast(dtype), pl.col('atr').cast(dtype))
    targets = allocate(panel, make_spec())
    assert targets.schema == TARGET_SCHEMA
    assert targets.columns == TARGET_COLUMNS


def test_cadence_is_anchored_to_train_start_with_off_cadence_panel_start():
    rows = [(START + timedelta(minutes=15 * step), f'S{index:02d}',
             float(10 - index - (step % 2))) for step in range(12) for index in range(6)]
    panel = frame({'timestamp': [item[0] for item in rows],
                   'symbol': [item[1] for item in rows],
                   'close': [100.0] * len(rows),
                   'sig': [item[2] for item in rows],
                   'bline': [-item[2] for item in rows],
                   'atr': [1.0] * len(rows),
                   'in_pit_universe': [True] * len(rows),
                   'is_tradable': [True] * len(rows)})
    # 15-minute bars, four bars per rebalance, anchored at midnight: only :00 aligns.
    targets = allocate(panel, make_spec(cadence=4, bar_seconds=900))
    aligned = targets['timestamp'].dt.minute().unique().to_list()
    assert aligned == [0]
    # 00:15 through 03:00 in 15-minute steps aligns at 01:00, 02:00 and 03:00.
    assert targets.height == 3 * 6


def test_no_scheduled_timestamp_returns_typed_empty_frame():
    panel = basket([f'S{index:02d}' for index in range(6)]).with_columns(
        (pl.col('timestamp') + pl.duration(minutes=30)).alias('timestamp'))
    targets = allocate(panel, make_spec())
    assert targets.height == 0
    assert targets.schema == TARGET_SCHEMA


def test_signal_override_selects_the_declared_baseline():
    panel = basket([f'S{index:02d}' for index in range(8)])
    defaults = dict(zip(*allocate(panel, make_spec(long_count=1, short_count=1))
                        .select('symbol', 'target_weight').to_dict(as_series=False).values()))
    overridden = dict(zip(*allocate(panel, make_spec(long_count=1, short_count=1),
                                    signal='bline')
                          .select('symbol', 'target_weight').to_dict(as_series=False).values()))
    assert defaults['S00'] == 0.5 and overridden['S00'] == -0.5
    assert defaults['S07'] == -0.5 and overridden['S07'] == 0.5


def test_duplicate_symbol_with_ineligible_twin_is_rejected_not_crashed():
    panel = frame({'timestamp': [START] * 8, 'symbol': ['DUP', 'DUP'] + [
        f'S{index:02d}' for index in range(6)],
        'close': [100.0] * 8, 'sig': [9.0, 9.0, 5.0, 4.0, 3.0, 2.0, 1.0, 0.0],
        'bline': [0.0] * 8, 'atr': [1.0, None, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        'in_pit_universe': [True] * 8, 'is_tradable': [True] * 8})
    with pytest.raises(QuantError) as excinfo:
        allocate(panel, make_spec(long_count=1, short_count=1))
    assert excinfo.value.status == 'INVALID_ALLOCATION'
