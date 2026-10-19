from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from src.engine.common import QuantError
from src.engine.ts_allocator import allocate_ts, capped_budgets
from src.engine.ts_spec import TimeSeriesSpec

START = datetime(2020, 1, 1, tzinfo=UTC)
BARS = 4


def make_spec(symbols: tuple[str, ...] = ('A', 'B', 'C'), **allocation: object) -> TimeSeriesSpec:
    risk = {'method': 'inverse_volatility', 'per_instrument_cap': 0.4,
            'gross_exposure': 1.0, 'volatility_feature': 'vol_20'}
    risk.update(allocation)
    payload = {
        'spec_kind': 'time_series',
        'sleeve_id': 'af30_allocator_test',
        'selection_family_id': 'af30_time_series',
        'book_strategy': 6,
        'thesis': 'Allocator contract test.',
        'market_classes': [{
            'name': 'indices', 'symbols': list(symbols),
            'panel_root': 'data/vault/markets_20261015/index_1h',
            'bar_seconds': 3600, 'periods_per_year': 252,
        }],
        'windows': {
            'train': {'start': '2020-01-01T00:00:00Z', 'end': '2021-01-01T00:00:00Z'},
            'validation': {'start': '2021-01-01T00:00:00Z', 'end': '2022-01-01T00:00:00Z'},
            'protected': {'start': '2026-01-01T00:00:00Z', 'end': '2026-10-01T00:00:00Z'},
        },
        'features': [
            {'name': 'f', 'expr': {'op': 'col', 'name': 'close'}},
            {'name': 'atr_14', 'expr': {'op': 'col', 'name': 'close'}},
            {'name': 'vol_20', 'expr': {'op': 'col', 'name': 'close'}},
        ],
        'forecast': {'feature': 'f', 'horizon_bars': 1,
                     'scaling': {'kind': 'bounded_linear', 'scale': 10.0, 'cap': 2.0}},
        'risk_allocation': risk,
        'stops': {'feature': 'atr_14', 'multiple': 3.0},
        'costs': {'commission_bps_one_way': 1.0, 'slippage_bps_one_way': 1.0,
                  'spread_bps': 0.0, 'spread_included_in_slippage': True},
    }
    return TimeSeriesSpec.model_validate(payload)


def make_features(forecasts: dict[str, float | None], vols: dict[str, float],
                  *, untradable: tuple[str, ...] = ()) -> pl.DataFrame:
    rows = []
    for index in range(BARS):
        for symbol, forecast in forecasts.items():
            rows.append({
                'timestamp': START + timedelta(hours=index),
                'symbol': symbol,
                'close': 100.0,
                'is_tradable': symbol not in untradable,
                'in_pit_universe': symbol in vols,
                'forecast': forecast,
                'vol_20': vols.get(symbol, 0.2),
                'atr_14': 1.0,
            })
    return pl.DataFrame(rows).sort('symbol', 'timestamp')


BASE_FORECASTS = {'A': 1.0, 'B': -1.0, 'C': 0.5, 'D': 0.4, 'E': 0.3, 'F': None}
BASE_VOLS = {'A': 0.1, 'B': 0.2, 'C': 0.4}


def test_weights_sum_to_declared_gross_with_forecast_signs():
    spec = make_spec(per_instrument_cap=0.6)
    targets = allocate_ts(make_features(BASE_FORECASTS, BASE_VOLS, untradable=('E',)),
                          spec, spec.market_classes[0])
    assert targets.height == BARS * len(BASE_FORECASTS)
    for block in targets.partition_by('timestamp'):
        assert abs(block['target_weight'].abs().sum() - 1.0) < 1e-12
    latest = targets.filter(pl.col('timestamp') == targets['timestamp'].max()).sort('symbol')
    weights = dict(zip(latest['symbol'], latest['target_weight']))
    assert weights['A'] > 0 and weights['B'] < 0 and weights['C'] > 0
    assert weights['A'] == pytest.approx(10 / 17.5, abs=1e-12)
    assert weights['B'] == pytest.approx(-5 / 17.5, abs=1e-12)


def test_per_instrument_cap_is_respected_and_redistributed():
    spec = make_spec(symbols=('A', 'B', 'C', 'D'), per_instrument_cap=0.3)
    forecasts = {'A': 1.0, 'B': 1.0, 'C': 1.0, 'D': 1.0}
    vols = {'A': 0.1, 'B': 0.2, 'C': 0.4, 'D': 0.8}
    targets = allocate_ts(make_features(forecasts, vols), spec, spec.market_classes[0])
    latest = targets.filter(pl.col('timestamp') == targets['timestamp'].max())
    weights = latest['target_weight'].to_list()
    assert all(abs(weight) <= 0.3 + 1e-12 for weight in weights)
    assert abs(sum(abs(weight) for weight in weights) - 1.0) < 1e-12


def test_ineligible_symbols_receive_zero_weight_and_zero_stop():
    spec = make_spec()
    targets = allocate_ts(make_features(BASE_FORECASTS, BASE_VOLS, untradable=('E',)),
                          spec, spec.market_classes[0])
    latest = targets.filter(pl.col('timestamp') == targets['timestamp'].max()).sort('symbol')
    for symbol in ('D', 'E', 'F'):
        row = latest.filter(pl.col('symbol') == symbol).row(0, named=True)
        assert row['target_weight'] == 0.0
        assert row['stop_loss_dist_pct'] == 0.0


def test_allocation_is_bit_identical_across_runs():
    spec = make_spec()
    features = make_features(BASE_FORECASTS, BASE_VOLS, untradable=('E',))
    first = allocate_ts(features, spec, spec.market_classes[0])
    second = allocate_ts(features, spec, spec.market_classes[0])
    assert first.equals(second)
    assert first.to_dicts() == second.to_dicts()


def test_stop_distance_is_multiple_times_stop_feature_over_price():
    spec = make_spec()
    targets = allocate_ts(make_features(BASE_FORECASTS, BASE_VOLS, untradable=('E',)),
                          spec, spec.market_classes[0])
    latest = targets.filter(pl.col('timestamp') == targets['timestamp'].max()).sort('symbol')
    for row in latest.iter_rows(named=True):
        if row['target_weight'] == 0.0:
            assert row['stop_loss_dist_pct'] == 0.0
        else:
            assert row['stop_loss_dist_pct'] == pytest.approx(3.0 * 1.0 / 100.0, abs=1e-15)


def test_manual_weights_are_honored_for_eligible_symbols():
    spec = make_spec(method='manual', volatility_feature=None, per_instrument_cap=0.6,
                     weights={'A': 0.5, 'B': 0.3, 'C': 0.2})
    targets = allocate_ts(make_features(BASE_FORECASTS, BASE_VOLS, untradable=('E',)),
                          spec, spec.market_classes[0])
    latest = targets.filter(pl.col('timestamp') == targets['timestamp'].max()).sort('symbol')
    weights = dict(zip(latest['symbol'], latest['target_weight']))
    assert weights['A'] == pytest.approx(0.5, abs=1e-12)
    assert weights['B'] == pytest.approx(-0.3, abs=1e-12)
    assert weights['C'] == pytest.approx(0.2, abs=1e-12)


def test_gross_exposure_scales_the_target():
    spec = make_spec(gross_exposure=0.75)
    targets = allocate_ts(make_features(BASE_FORECASTS, BASE_VOLS, untradable=('E',)),
                          spec, spec.market_classes[0])
    latest = targets.filter(pl.col('timestamp') == targets['timestamp'].max())
    assert abs(latest['target_weight'].abs().sum() - 0.75) < 1e-12


def test_partial_eligibility_holds_flat_instead_of_raising():
    spec = make_spec(symbols=('A', 'B', 'C'), per_instrument_cap=0.5)
    features = make_features({'A': 1.0, 'B': None, 'C': None}, {'A': 0.1, 'B': 0.2, 'C': 0.3})
    targets = allocate_ts(features, spec, spec.market_classes[0])
    assert targets['target_weight'].abs().sum() == 0.0


def test_unreachable_cap_is_rejected():
    spec = make_spec(symbols=('A',), per_instrument_cap=0.5)
    with pytest.raises(QuantError) as exc:
        allocate_ts(make_features({'A': 1.0}, {'A': 0.1}), spec, spec.market_classes[0])
    assert exc.value.status == 'INVALID_ALLOCATION'


def test_capped_budgets_water_fill_is_exact():
    budgets = capped_budgets({'A': 10.0, 'B': 5.0, 'C': 2.5, 'D': 1.25}, 0.3)
    assert sum(budgets.values()) == pytest.approx(1.0, abs=1e-12)
    assert max(budgets.values()) <= 0.3 + 1e-12
    assert budgets == pytest.approx({'A': 0.3, 'B': 0.3, 'C': 4 / 15, 'D': 2 / 15}, abs=1e-12)
