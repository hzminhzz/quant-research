from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from src.engine.common import QuantError
from src.engine.ts_gates import (
    class_dsr,
    evaluate_class,
    forecast_return_hac,
    gate_checks,
    max_drawdown,
    net_sharpe,
)
from src.engine.ts_spec import TimeSeriesSpec

START = datetime(2020, 1, 1, tzinfo=UTC)


def make_spec() -> TimeSeriesSpec:
    return TimeSeriesSpec.model_validate({
        'spec_kind': 'time_series',
        'sleeve_id': 'af30_gates',
        'selection_family_id': 'af30_time_series',
        'book_strategy': 6,
        'thesis': 'Gate evaluator test.',
        'market_classes': [{
            'name': 'indices', 'symbols': ['A', 'B'],
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
        ],
        'forecast': {'feature': 'f', 'horizon_bars': 1,
                     'scaling': {'kind': 'bounded_linear', 'scale': 1.0, 'cap': 20.0}},
        'stops': {'feature': 'atr_14', 'multiple': 3.0},
        'costs': {'commission_bps_one_way': 1.0, 'slippage_bps_one_way': 1.0,
                  'spread_bps': 0.0, 'spread_included_in_slippage': True},
        'label_horizon_bars': 1,
    })


PASSING = {'train_sharpe': 1.0, 'validation_sharpe': 0.5, 'stress_sharpe': 0.2,
           'validation_drawdown': 0.10, 'forecast_t': 3.0, 'dsr_probability': 0.99}


def checks(**overrides):
    values = {**PASSING}
    values.update(overrides)
    return gate_checks(make_spec(), **values)


def test_all_seven_gates_pass_together():
    report = checks()
    assert report['status'] == 'QUALIFIED'
    assert report['missing'] == []
    assert set(report['checks']) == {'train_positive', 'validation_sharpe', 'validation_to_train',
                                     'cost_stress', 'validation_drawdown', 'forecast_hac',
                                     'class_dsr'}


def test_train_must_be_strictly_positive():
    assert checks(train_sharpe=0.0)['checks']['train_positive']['passed'] is False
    assert checks(train_sharpe=0.0001)['status'] == 'QUALIFIED'


def test_validation_sharpe_boundary():
    assert checks(validation_sharpe=0.299)['checks']['validation_sharpe']['passed'] is False
    assert checks(validation_sharpe=0.30)['checks']['validation_sharpe']['passed'] is True


def test_validation_to_train_ratio_boundary():
    assert checks(train_sharpe=1.0, validation_sharpe=0.49)['checks']['validation_to_train']['passed'] is False
    assert checks(train_sharpe=1.0, validation_sharpe=0.50)['checks']['validation_to_train']['passed'] is True


def test_cost_stress_must_be_positive():
    assert checks(stress_sharpe=-0.001)['checks']['cost_stress']['passed'] is False
    assert checks(stress_sharpe=0.001)['status'] == 'QUALIFIED'


def test_drawdown_boundary():
    assert checks(validation_drawdown=0.26)['checks']['validation_drawdown']['passed'] is False
    assert checks(validation_drawdown=0.25)['checks']['validation_drawdown']['passed'] is True


def test_forecast_hac_boundary():
    assert checks(forecast_t=1.99)['checks']['forecast_hac']['passed'] is False
    assert checks(forecast_t=2.0)['checks']['forecast_hac']['passed'] is True


def test_dsr_boundary():
    assert checks(dsr_probability=0.949)['checks']['class_dsr']['passed'] is False
    assert checks(dsr_probability=0.95)['checks']['class_dsr']['passed'] is True


def test_missing_statistics_are_named_not_silently_passed():
    report = checks(validation_sharpe=None, dsr_probability=None)
    assert report['status'] == 'FALSIFIED'
    assert report['missing'] == ['validation_sharpe', 'validation_to_train', 'class_dsr']


def returns_frame(columns: dict[str, np.ndarray]) -> pl.DataFrame:
    length = len(next(iter(columns.values())))
    return pl.DataFrame({'timestamp': [START + timedelta(days=i) for i in range(length)], **columns})


def test_class_dsr_reports_trials_and_is_deterministic():
    rng = np.random.default_rng(11)
    frame = returns_frame({
        'sleeve_a': rng.normal(0.0010, 0.01, 600),
        'sleeve_b': rng.normal(0.0002, 0.01, 600),
        'sleeve_c': rng.normal(-0.0004, 0.01, 600),
    })
    first = class_dsr(frame, 252)
    second = class_dsr(frame, 252)
    assert first == second
    assert first['trials'] == 3
    assert first['observations'] == 600
    assert 0.0 <= first['probability'] <= 1.0
    assert first['trials_declared'] == ['sleeve_a', 'sleeve_b', 'sleeve_c']


def test_class_dsr_rejects_unaligned_or_incomplete_matrices():
    rng = np.random.default_rng(12)
    unaligned = returns_frame({'a': rng.normal(size=50), 'b': rng.normal(size=50)})
    duplicated = pl.concat([unaligned, unaligned.head(1)])
    with pytest.raises(QuantError):
        class_dsr(duplicated, 252)
    with pytest.raises(QuantError):
        class_dsr(unaligned.with_columns(pl.lit(None, dtype=pl.Float64).alias('c')), 252)
    with pytest.raises(QuantError):
        class_dsr(unaligned.drop('timestamp'), 252)


def test_class_dsr_is_scoped_to_one_class():
    rng = np.random.default_rng(13)
    indices = returns_frame({'strong': rng.normal(0.0020, 0.01, 500),
                             'weak_a': rng.normal(-0.0002, 0.01, 500),
                             'weak_b': rng.normal(0.0001, 0.01, 500)})
    crypto = returns_frame({'drift': rng.normal(0.0000, 0.02, 500),
                            'flat': rng.normal(0.0000, 0.02, 500)})
    index_report = class_dsr(indices, 252)
    crypto_report = class_dsr(crypto, 365)
    assert index_report['trials_declared'] == ['strong', 'weak_a', 'weak_b']
    assert crypto_report['trials_declared'] == ['drift', 'flat']
    assert index_report != crypto_report


def make_panel(sign: int = 1, symbols: tuple[str, ...] = ('A', 'B')) -> pl.DataFrame:
    rng = np.random.default_rng(5)
    rows = []
    length = 90
    for symbol in symbols:
        steps = rng.normal(0.0, 0.01, length - 1)
        open_prices = 100.0 * np.cumprod(np.concatenate([[1.0], 1.0 + steps]))
        forward = open_prices[2:] / open_prices[1:-1] - 1.0
        forecast = sign * forward + rng.normal(0.0, 0.002, forward.size)
        for index in range(length):
            rows.append({
                'timestamp': START + timedelta(hours=index), 'symbol': symbol,
                'open': float(open_prices[index]),
                'forecast': float(forecast[index]) if index < forecast.size else None,
                'in_pit_universe': True,
            })
    return pl.DataFrame(rows).sort('symbol', 'timestamp')


def test_forecast_hac_detects_predictive_and_reversed_signals():
    positive = forecast_return_hac(make_panel(1), make_spec())
    reversed_ = forecast_return_hac(make_panel(-1), make_spec())
    assert positive['status'] == 'PASS'
    assert positive['t_stat'] > 5 and positive['spearman'] > 0.5
    assert reversed_['t_stat'] < -5 and reversed_['spearman'] < -0.5
    assert positive['lags'] == 1


def test_forecast_hac_insufficient_observations_is_inconclusive():
    short = make_panel().filter(pl.col('timestamp') < START + timedelta(hours=10))
    report = forecast_return_hac(short, make_spec())
    assert report['status'] == 'INCONCLUSIVE'


def test_net_sharpe_and_drawdown_guards():
    assert net_sharpe(np.array([0.01, 0.02]), 252) is None
    assert net_sharpe(np.array([0.01, float('nan'), 0.02]), 252) is None
    assert max_drawdown(np.array([0.1])) is None
    assert max_drawdown(np.array([0.5, -0.5])) == pytest.approx(0.5)


def test_evaluate_class_composes_and_is_deterministic():
    spec = make_spec()
    rng = np.random.default_rng(21)
    train = rng.normal(0.0015, 0.01, 400)
    validation = rng.normal(0.0010, 0.01, 300)
    stress = rng.normal(0.0005, 0.01, 300)
    forecast = forecast_return_hac(make_panel(1), spec)
    dsr = class_dsr(returns_frame({'a': train, 'b': rng.normal(0, 0.01, 400)}), 252)
    first = evaluate_class(spec, spec.market_classes[0], train_returns=train,
                           validation_returns=validation, stress_returns=stress,
                           forecast_check=forecast, class_dsr_result=dsr)
    second = evaluate_class(spec, spec.market_classes[0], train_returns=train,
                            validation_returns=validation, stress_returns=stress,
                            forecast_check=forecast, class_dsr_result=dsr)
    assert json.dumps(first, sort_keys=True, default=str) == json.dumps(second, sort_keys=True, default=str)
    assert first['market_class'] == 'indices'
    assert first['periods_per_year'] == 252
    assert set(first['checks']) == {'train_positive', 'validation_sharpe',
                                    'validation_to_train', 'cost_stress',
                                    'validation_drawdown', 'forecast_hac', 'class_dsr'}
    assert first['status'] in {'QUALIFIED', 'FALSIFIED', 'INCONCLUSIVE'}
    assert math.isfinite(first['checks']['class_dsr']['value'])
