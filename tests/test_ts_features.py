from __future__ import annotations

import hashlib
import math
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cloudpickle
import polars as pl
import pytest

from src.engine.common import QuantError
from src.engine.ts_features import TimeSeriesFeatureCompiler, compile_ts_and_verify
from src.engine.ts_spec import TimeSeriesSpec

NEEDS_BWRAP = pytest.mark.skipif(shutil.which('bwrap') is None, reason='bubblewrap unavailable')


def spec_payload(**forecast: object) -> dict:
    return {
        'spec_kind': 'time_series',
        'sleeve_id': 'af30_s06_test',
        'selection_family_id': 'af30_time_series',
        'book_strategy': 6,
        'thesis': 'Test sleeve for time-series feature compilation.',
        'market_classes': [{
            'name': 'indices',
            'symbols': ['DAX', 'NQ', 'ES'],
            'panel_root': 'data/vault/markets_20261015/index_1h',
            'bar_seconds': 3600,
            'periods_per_year': 252,
        }],
        'windows': {
            'train': {'start': '2020-01-01T00:00:00Z', 'end': '2021-01-01T00:00:00Z'},
            'validation': {'start': '2021-01-01T00:00:00Z', 'end': '2022-01-01T00:00:00Z'},
            'protected': {'start': '2026-01-01T00:00:00Z', 'end': '2026-10-01T00:00:00Z'},
        },
        'features': [
            {'name': 'close_minus_100', 'expr': {
                'op': 'sub',
                'args': [{'op': 'col', 'name': 'close'}, {'op': 'lit', 'value': 100.0}],
            }},
            {'name': 'atr_14', 'native': 'atr', 'params': {'period': 3}},
            {'name': 'vol_20', 'expr': {'op': 'rolling_std', 'window': 3, 'args': [
                {'op': 'pct_change', 'periods': 1, 'args': [{'op': 'col', 'name': 'close'}]},
            ]}},
        ],
        'forecast': {
            'feature': 'close_minus_100',
            'horizon_bars': 1,
            'scaling': {'kind': 'bounded_linear', 'scale': 10.0, 'cap': 2.0},
        },
        'risk_allocation': {'method': 'inverse_volatility', 'volatility_feature': 'vol_20'},
        'stops': {'feature': 'atr_14', 'multiple': 3.0},
        'costs': {
            'commission_bps_one_way': 1.0,
            'slippage_bps_one_way': 1.0,
            'spread_bps': 0.0,
            'spread_included_in_slippage': True,
        },
        'label_horizon_bars': 1,
    }


def make_spec(**forecast: object) -> TimeSeriesSpec:
    payload = spec_payload()
    payload['forecast'].update(forecast)
    return TimeSeriesSpec.model_validate(payload)


def make_panel(values: list[float], symbols: tuple[str, ...] = ('DAX', 'NQ', 'ES')) -> pl.DataFrame:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    rows = []
    for symbol in symbols:
        for index, value in enumerate(values):
            close = 100.0 + value
            rows.append({
                'timestamp': start + timedelta(hours=index),
                'symbol': symbol,
                'open': close, 'high': close, 'low': close, 'close': close,
                'volume': 1.0, 'carry_rate': 0.0, 'spread_bps': 0.0,
                'session_id': '24x7', 'bar_in_session': index, 'is_tradable': True,
            })
    return pl.DataFrame(rows).sort('symbol', 'timestamp')


VALUES = [0.0, 5.0, -5.0, 10.0, 20.0, -20.0, 40.0]


def forecast_values(spec: TimeSeriesSpec, values: list[float]) -> list[float | None]:
    """Reference implementation of the declared projection."""
    scaling = spec.forecast.scaling
    out: list[float | None] = []
    for value in values:
        scaled = value / scaling.scale
        if scaling.kind == 'bounded_linear':
            out.append(max(-scaling.cap, min(scaling.cap, scaled)))
        else:
            out.append(scaling.cap * math.tanh(scaled))
    return out


def test_bounded_linear_matches_reference_exactly():
    spec = make_spec(scaling={'kind': 'bounded_linear', 'scale': 10.0, 'cap': 2.0})
    result = TimeSeriesFeatureCompiler(spec, spec.market_classes[0])(make_panel(VALUES))
    observed = result.filter(pl.col('symbol') == 'DAX')['forecast'].to_list()
    assert observed == forecast_values(spec, VALUES)
    assert observed == [0.0, 0.5, -0.5, 1.0, 2.0, -2.0, 2.0]


def test_bounded_tanh_matches_reference_exactly():
    spec = make_spec(scaling={'kind': 'bounded_tanh', 'scale': 10.0, 'cap': 2.0})
    result = TimeSeriesFeatureCompiler(spec, spec.market_classes[0])(make_panel(VALUES))
    observed = result.filter(pl.col('symbol') == 'DAX')['forecast'].to_list()
    expected = [0.0] + [2.0 * math.tanh(v / 10.0) for v in VALUES[1:]]
    assert observed == pytest.approx(expected, rel=0, abs=1e-12)


def test_undeclared_symbol_is_ineligible_but_rows_are_retained():
    panel = make_panel(VALUES, symbols=('DAX', 'NQ', 'ES', 'HK33'))
    spec = make_spec()
    result = TimeSeriesFeatureCompiler(spec, spec.market_classes[0])(panel)
    assert result.height == panel.height
    assert result.filter(pl.col('symbol') == 'HK33')['in_pit_universe'].to_list() == [False] * len(VALUES)
    assert result.filter(pl.col('symbol').is_in(['DAX', 'NQ', 'ES']))['in_pit_universe'].all()


def test_compile_runs_three_cutoff_proofs():
    spec = make_spec()
    panel = make_panel(VALUES)
    full, evidence = compile_ts_and_verify(panel, spec, spec.market_classes[0], isolate=False)
    assert evidence.status == 'PASS'
    assert len(evidence.cutoffs) == 3
    assert 'forecast' in full.columns
    assert full['forecast'].null_count() == 0


def test_cross_sectional_operation_requires_declaration():
    payload = spec_payload()
    payload['features'] = [
        {'name': 'rank_close', 'expr': {
            'op': 'xs_rank', 'args': [{'op': 'col', 'name': 'close'}],
        }},
        {'name': 'atr_14', 'expr': {'op': 'col', 'name': 'close'}},
        {'name': 'vol_20', 'expr': {'op': 'col', 'name': 'close'}},
    ]
    payload['forecast']['feature'] = 'rank_close'
    spec = TimeSeriesSpec.model_validate(payload)
    with pytest.raises(QuantError) as exc:
        TimeSeriesFeatureCompiler(spec, spec.market_classes[0])(make_panel(VALUES))
    assert exc.value.status == 'INVALID_SPEC'

    payload['cross_sectional'] = True
    spec = TimeSeriesSpec.model_validate(payload)
    ranked = TimeSeriesFeatureCompiler(spec, spec.market_classes[0])(make_panel(VALUES))
    last = ranked.filter(pl.col('timestamp') == ranked['timestamp'].max()).sort('symbol')
    assert last['rank_close'].to_list() == [2.0, 2.0, 2.0]


def test_look_ahead_expression_is_rejected():
    payload = spec_payload()
    payload['features'] = [
        {'name': 'future_close', 'expr': {
            'op': 'shift', 'periods': -1, 'args': [{'op': 'col', 'name': 'close'}],
        }},
        {'name': 'atr_14', 'expr': {'op': 'col', 'name': 'close'}},
        {'name': 'vol_20', 'expr': {'op': 'col', 'name': 'close'}},
    ]
    payload['forecast']['feature'] = 'future_close'
    spec = TimeSeriesSpec.model_validate(payload)
    with pytest.raises(QuantError) as exc:
        TimeSeriesFeatureCompiler(spec, spec.market_classes[0])(make_panel(VALUES))
    assert exc.value.status == 'INVALID_SPEC'


@NEEDS_BWRAP
def test_declared_python_artifact_compiles_and_proves_causality(tmp_path: Path):
    def artifact(panel: pl.DataFrame) -> pl.DataFrame:
        return panel.with_columns(
            pl.col('is_tradable').alias('in_pit_universe'),
            (pl.col('close') - 100.0).alias('raw_signal'),
        )

    path = tmp_path / 'artifact.pkl'
    path.write_bytes(cloudpickle.dumps(artifact))
    payload = spec_payload()
    payload['features'] = [
        {'name': 'raw_signal', 'expr': {
            'op': 'sub', 'args': [{'op': 'col', 'name': 'close'}, {'op': 'lit', 'value': 100.0}],
        }},
        {'name': 'atr_14', 'expr': {'op': 'col', 'name': 'close'}},
        {'name': 'vol_20', 'expr': {'op': 'col', 'name': 'close'}},
    ]
    payload['forecast']['feature'] = 'raw_signal'
    payload['python_feature_artifact'] = {
        'path': path.name,
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    spec = TimeSeriesSpec.model_validate(payload)
    spec._base_dir = tmp_path

    full, evidence = compile_ts_and_verify(make_panel(VALUES), spec, spec.market_classes[0])
    assert evidence.status == 'PASS'
    assert full.filter(pl.col('symbol') == 'DAX')['forecast'].to_list() == [
        0.0, 0.5, -0.5, 1.0, 2.0, -2.0, 2.0,
    ]


@NEEDS_BWRAP
def test_artifact_reading_future_rows_fails_causality(tmp_path: Path):
    def look_ahead(panel: pl.DataFrame) -> pl.DataFrame:
        return panel.with_columns(
            pl.col('is_tradable').alias('in_pit_universe'),
            pl.col('close').shift(-1).over('symbol').alias('raw_signal'),
        )

    path = tmp_path / 'lookahead.pkl'
    path.write_bytes(cloudpickle.dumps(look_ahead))
    payload = spec_payload()
    payload['features'] = [
        {'name': 'raw_signal', 'expr': {'op': 'col', 'name': 'close'}},
        {'name': 'atr_14', 'expr': {'op': 'col', 'name': 'close'}},
        {'name': 'vol_20', 'expr': {'op': 'col', 'name': 'close'}},
    ]
    payload['forecast']['feature'] = 'raw_signal'
    payload['python_feature_artifact'] = {
        'path': path.name,
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    spec = TimeSeriesSpec.model_validate(payload)
    spec._base_dir = tmp_path

    with pytest.raises(QuantError) as exc:
        compile_ts_and_verify(make_panel(VALUES), spec, spec.market_classes[0])
    assert exc.value.status == 'INVALID_CAUSALITY'
