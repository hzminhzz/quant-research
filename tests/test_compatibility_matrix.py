from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.engine.common import QuantError
from src.engine.sleeve_matrix import (
    BOOK_TITLES,
    expected_sleeve_id,
    freeze_matrix,
    load_frozen,
    load_matrix,
    matrix_digest,
    require_declaration,
    validate_matrix,
)
from src.engine.ts_spec import TimeSeriesSpec

MATRIX_DIR = Path(__file__).parents[1] / 'config/sleeves/advanced_futures_30'
AVAILABLE = {
    ('indices', '1h'): {'DAX', 'NQ'}, ('indices', '1m'): {'DAX', 'NQ'},
    ('metals', '1h'): {'XAUUSD'}, ('metals', '1m'): {'XAUUSD'},
    ('crypto', '1h'): {'BTCUSDT'}, ('crypto', '1m'): {'BTCUSDT'},
}


def make_spec(book: int = 6, *, cadence: int = 3600,
              class_name: str = 'indices', symbols: tuple[str, ...] = ('DAX', 'NQ')) -> TimeSeriesSpec:
    return TimeSeriesSpec.model_validate({
        'spec_kind': 'time_series',
        'sleeve_id': expected_sleeve_id(book),
        'selection_family_id': 'af30_time_series',
        'book_strategy': book,
        'thesis': 'Compatibility matrix test.',
        'market_classes': [{
            'name': class_name, 'symbols': list(symbols),
            'panel_root': 'data/vault/markets_20261015/index_1h',
            'bar_seconds': cadence, 'periods_per_year': 252,
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
    })


def test_frozen_artifact_covers_every_variant_and_pair():
    matrix = load_matrix(MATRIX_DIR / 'compatibility.yaml')
    validate_matrix(matrix, AVAILABLE)
    strategies = {variant['book_strategy'] for variant in matrix['variants']}
    assert strategies == set(BOOK_TITLES)
    assert len(matrix['variants']) == 25
    pairs = sum(len(variant['classes']) for variant in matrix['variants'])
    assert pairs == 72
    for variant in matrix['variants']:
        assert variant['cadence'] in {'1h', '1m'}
        for justification in variant['classes'].values():
            assert justification.strip()


def test_freeze_roundtrip_and_tamper_detection(tmp_path: Path):
    matrix = load_matrix(MATRIX_DIR / 'compatibility.yaml')
    written = freeze_matrix(matrix, tmp_path)
    loaded, sha = load_frozen(tmp_path)
    assert sha == written['sha256'] == matrix_digest(matrix)
    assert loaded['variants'][0]['sleeve_id'] == 'af30_s01_buy_hold_single'
    loaded['variants'][0]['classes']['indices'] = 'Rewritten after freezing.'
    (tmp_path / 'compatibility.yaml').write_text(yaml.safe_dump(loaded), encoding='utf-8')
    with pytest.raises(QuantError) as exc:
        load_frozen(tmp_path)
    assert exc.value.status == 'INVALID_EVIDENCE'


def test_runner_accepts_a_declared_pair():
    matrix = load_matrix(MATRIX_DIR / 'compatibility.yaml')
    sha = matrix_digest(matrix)
    spec = make_spec(6)
    declared = require_declaration(matrix, spec, spec.market_classes[0],
                                   matrix_sha=sha, expected_sha=sha)
    assert declared['cadence'] == '1h'
    assert declared['justification']


def test_runner_rejects_an_undeclared_pair():
    matrix = load_matrix(MATRIX_DIR / 'compatibility.yaml')
    sha = matrix_digest(matrix)
    spec = make_spec(19, class_name='metals', symbols=('XAUUSD',))
    with pytest.raises(QuantError) as exc:
        require_declaration(matrix, spec, spec.market_classes[0],
                            matrix_sha=sha, expected_sha=sha)
    assert exc.value.status == 'INVALID_SPEC'
    assert 'metals' in exc.value.reason


def test_runner_rejects_the_wrong_cadence():
    matrix = load_matrix(MATRIX_DIR / 'compatibility.yaml')
    sha = matrix_digest(matrix)
    spec = make_spec(6, cadence=60)
    with pytest.raises(QuantError) as exc:
        require_declaration(matrix, spec, spec.market_classes[0],
                            matrix_sha=sha, expected_sha=sha)
    assert '1h' in exc.value.reason


def test_runner_requires_the_frozen_hash():
    matrix = load_matrix(MATRIX_DIR / 'compatibility.yaml')
    sha = matrix_digest(matrix)
    spec = make_spec(6)
    with pytest.raises(QuantError) as exc:
        require_declaration(matrix, spec, spec.market_classes[0],
                            matrix_sha=sha, expected_sha='0' * 64)
    assert exc.value.status == 'INVALID_EVIDENCE'


def test_runner_rejects_a_sleeve_id_mismatch():
    matrix = load_matrix(MATRIX_DIR / 'compatibility.yaml')
    sha = matrix_digest(matrix)
    spec = make_spec(6).model_copy(update={'sleeve_id': 'af30_s06_wrong_name'})
    with pytest.raises(QuantError) as exc:
        require_declaration(matrix, spec, spec.market_classes[0],
                            matrix_sha=sha, expected_sha=sha)
    assert 'frozen declaration' in exc.value.reason


def test_availability_and_coverage_are_validated():
    matrix = load_matrix(MATRIX_DIR / 'compatibility.yaml')
    incomplete = {k: v for k, v in AVAILABLE.items() if k != ('metals', '1h')}
    with pytest.raises(QuantError):
        validate_matrix(matrix, incomplete)
    missing = {'schema_version': 1, 'selection_family_id': 'af30_time_series',
               'variants': matrix['variants'][:-1]}
    with pytest.raises(QuantError) as exc:
        validate_matrix(missing, AVAILABLE)
    assert 'misses strategies' in exc.value.reason
    duplicate = {'schema_version': 1, 'selection_family_id': 'af30_time_series',
                 'variants': matrix['variants'] + [matrix['variants'][0]]}
    with pytest.raises(QuantError):
        validate_matrix(duplicate, AVAILABLE)
    bad_cadence = {'schema_version': 1, 'selection_family_id': 'af30_time_series',
                   'variants': [{**matrix['variants'][0], 'cadence': '5m'}]}
    with pytest.raises(QuantError):
        validate_matrix(bad_cadence, AVAILABLE)
