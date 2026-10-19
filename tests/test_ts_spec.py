from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.engine.common import QuantError
from src.engine.ts_spec import export_ts_spec, parse_ts_spec


def payload() -> dict:
    return {
        'schema_version': 1,
        'spec_kind': 'time_series',
        'sleeve_id': 'af30_s06_slow_trend_long_short',
        'selection_family_id': 'af30_time_series',
        'book_strategy': 6,
        'thesis': 'Slow trend following harvests persistent directional drift on index and metal futures proxies.',
        'market_classes': [
            {
                'name': 'indices',
                'symbols': ['DAX', 'NQ'],
                'panel_root': 'data/vault/markets_20261015/index_1h',
                'bar_seconds': 3600,
                'periods_per_year': 252,
            },
            {
                'name': 'metals',
                'symbols': ['XAUUSD'],
                'panel_root': 'data/vault/markets_20261015/metals_1h',
                'bar_seconds': 3600,
                'periods_per_year': 252,
            },
        ],
        'windows': {
            'train': {'start': '2015-01-01T00:00:00Z', 'end': '2021-12-31T00:00:00Z'},
            'validation': {'start': '2022-01-01T00:00:00Z', 'end': '2026-01-01T00:00:00Z'},
            'protected': {'start': '2026-01-01T00:00:00Z', 'end': '2026-10-01T00:00:00Z'},
        },
        'features': [
            {'name': 'ema_32', 'native': 'ema', 'params': {'period': 32}},
            {'name': 'atr_14', 'native': 'atr', 'params': {'period': 14}},
            {'name': 'vol_20', 'expr': {'op': 'rolling_std', 'window': 20, 'args': [
                {'op': 'pct_change', 'periods': 1, 'args': [{'op': 'col', 'name': 'close'}]},
            ]}},
        ],
        'forecast': {
            'feature': 'ema_32',
            'horizon_bars': 1,
            'scaling': {'kind': 'bounded_linear', 'scale': 1.0, 'cap': 20.0},
        },
        'volatility_target': 0.10,
        'risk_allocation': {'method': 'inverse_volatility', 'per_instrument_cap': 0.5,
                            'volatility_feature': 'vol_20'},
        'stops': {'feature': 'atr_14', 'multiple': 3.0},
        'costs': {
            'commission_bps_one_way': 2.0,
            'slippage_bps_one_way': 3.0,
            'spread_bps': 0.0,
            'spread_included_in_slippage': True,
        },
        'label_horizon_bars': 1,
        'seed': 42,
        'cutoff_checks': 3,
        'assumptions': ['Prices are research proxies, not exchange-certified contracts.'],
    }


def load(tmp_path: Path, data: dict):
    path = tmp_path / 'sleeve.yaml'
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
    return parse_ts_spec(path)


def rejected(tmp_path: Path, data: dict) -> QuantError:
    with pytest.raises(QuantError) as exc:
        load(tmp_path, data)
    assert exc.value.status == 'INVALID_SPEC'
    return exc.value


def test_valid_spec_parses_and_round_trips(tmp_path: Path):
    spec = load(tmp_path, payload())
    assert spec.book_strategy == 6
    assert [c.name for c in spec.market_classes] == ['indices', 'metals']
    exported = export_ts_spec(spec, tmp_path / 'exported.yaml')
    assert parse_ts_spec(exported).spec_hash == spec.spec_hash


def test_hash_is_stable_and_field_sensitive(tmp_path: Path):
    first = load(tmp_path, payload())
    second = load(tmp_path, payload())
    assert first.spec_hash == second.spec_hash
    changed = payload()
    changed['thesis'] = changed['thesis'] + ' Alternative wording.'
    assert load(tmp_path, changed).spec_hash != first.spec_hash


def test_missing_forecast_is_rejected(tmp_path: Path):
    data = payload()
    data.pop('forecast')
    rejected(tmp_path, data)


def test_overlapping_windows_are_rejected(tmp_path: Path):
    data = payload()
    data['windows']['validation']['start'] = '2021-06-01T00:00:00Z'
    rejected(tmp_path, data)


def test_undeclared_market_class_is_rejected(tmp_path: Path):
    data = payload()
    data['market_classes'][0]['name'] = 'equities'
    rejected(tmp_path, data)


def test_symbol_in_two_classes_is_rejected(tmp_path: Path):
    data = payload()
    data['market_classes'][1]['symbols'] = ['DAX']
    rejected(tmp_path, data)


def test_v1_allocation_field_is_rejected(tmp_path: Path):
    data = payload()
    data['long_count'] = 5
    rejected(tmp_path, data)


def test_forecast_must_name_a_declared_feature(tmp_path: Path):
    data = payload()
    data['forecast']['feature'] = 'undeclared'
    rejected(tmp_path, data)


def test_zero_commission_is_rejected(tmp_path: Path):
    data = payload()
    data['costs']['commission_bps_one_way'] = 0
    rejected(tmp_path, data)


def test_two_way_spread_required_when_not_in_slippage(tmp_path: Path):
    data = payload()
    data['costs']['spread_included_in_slippage'] = False
    rejected(tmp_path, data)
    data['costs']['spread_bps'] = 1.0
    assert load(tmp_path, data).costs.spread_bps == 1.0


def test_modeled_carry_requires_curve_and_tenor(tmp_path: Path):
    data = payload()
    data['market_classes'][0]['carry'] = {'mode': 'modeled'}
    rejected(tmp_path, data)
    data['market_classes'][0]['carry'] = {'mode': 'modeled', 'curve': 'bonds_daily_US10Y', 'tenor': '3m'}
    assert load(tmp_path, data).market_classes[0].carry.curve == 'bonds_daily_US10Y'


def test_manual_allocation_requires_exact_symbol_weights(tmp_path: Path):
    data = payload()
    data['risk_allocation'] = {'method': 'manual', 'per_instrument_cap': 1.0}
    rejected(tmp_path, data)
    data['risk_allocation']['weights'] = {'DAX': 0.5, 'NQ': 0.3}
    rejected(tmp_path, data)
    data['risk_allocation']['weights'] = {'DAX': 0.5, 'NQ': 0.3, 'XAUUSD': 0.2}
    assert load(tmp_path, data).risk_allocation.method == 'manual'


def test_feature_cannot_be_native_and_expression(tmp_path: Path):
    data = payload()
    data['features'][0]['expr'] = {'op': 'col', 'name': 'close'}
    rejected(tmp_path, data)


def test_missing_spec_kind_is_rejected(tmp_path: Path):
    data = payload()
    data.pop('spec_kind')
    rejected(tmp_path, data)


def test_forecast_horizon_cannot_exceed_label_horizon(tmp_path: Path):
    data = payload()
    data['forecast']['horizon_bars'] = 5
    rejected(tmp_path, data)


def test_unknown_carry_cannot_name_a_curve(tmp_path: Path):
    data = payload()
    data['market_classes'][1]['carry'] = {'mode': 'unknown', 'curve': 'bonds_daily_US10Y'}
    rejected(tmp_path, data)
