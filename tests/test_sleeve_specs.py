from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from src.engine.sleeve_matrix import (
    expected_sleeve_id,
    load_matrix,
    matrix_digest,
    require_declaration,
)
from src.engine.ts_spec import parse_ts_spec

SPEC_DIR = Path(__file__).parents[1] / 'config/sleeves/advanced_futures_30'
BASIC = tuple(range(1, 12))


def specs() -> dict[int, Path]:
    found = {}
    for path in sorted(SPEC_DIR.glob('af30_s*.yaml')):
        spec = parse_ts_spec(path)
        if spec.book_strategy in BASIC:
            found[spec.book_strategy] = path
    return found


def test_all_eleven_basic_specs_exist_and_parse():
    files = specs()
    assert set(files) == set(BASIC)
    for book, path in files.items():
        spec = parse_ts_spec(path)
        assert spec.sleeve_id == expected_sleeve_id(book)
        assert spec.book_strategy == book
        assert spec.windows.protected.start.year == 2026
        assert spec.windows.train.end <= spec.windows.validation.start
        assert spec.forecast.feature in {f.name for f in spec.features}
        assert spec.stops.feature in {f.name for f in spec.features}


def test_every_declared_pair_is_in_the_frozen_matrix():
    matrix = load_matrix(SPEC_DIR / 'compatibility.yaml')
    sha = matrix_digest(matrix)
    for book, path in specs().items():
        spec = parse_ts_spec(path)
        for market_class in spec.market_classes:
            declared = require_declaration(matrix, spec, market_class,
                                           matrix_sha=sha, expected_sha=sha)
            assert declared['book_strategy'] == book
            assert declared['market_class'] == market_class.name
            assert declared['cadence'] == '1h'
            assert market_class.bar_seconds == 3600


def test_no_spec_uses_zero_cost_or_unknown_financing_placeholders():
    for path in specs().values():
        spec = parse_ts_spec(path)
        assert spec.costs.commission_bps_one_way > 0
        assert spec.costs.slippage_bps_one_way > 0
        assert spec.costs.spread_bps > 0 or spec.costs.spread_included_in_slippage
        for market_class in spec.market_classes:
            carry = market_class.carry
            assert carry.mode in {'modeled', 'observed'}
            if carry.mode == 'modeled':
                assert carry.curve and carry.tenor


def test_carry_signals_require_a_financing_source_for_every_class():
    carry_books = {10, 11}
    for book, path in specs().items():
        spec = parse_ts_spec(path)
        uses_carry = any('carry_rate' in str(feature.expr) for feature in spec.features)
        if book in carry_books:
            assert uses_carry, f'{spec.sleeve_id} should build its signal from carry_rate'
        if uses_carry:
            assert all(c.carry.mode in {'modeled', 'observed'} for c in spec.market_classes)


@pytest.mark.parametrize('book', BASIC)
def test_cli_validates_each_spec(book: int):
    path = specs()[book]
    run = subprocess.run([sys.executable, 'scripts/quant.py', 'validate', str(path)],
                         cwd=path.parents[3], capture_output=True, text=True, timeout=120, check=False)
    assert run.returncode == 0, run.stderr
    assert '"VALID_SPEC"' in run.stdout
    assert f'"book_strategy": {book}' in run.stdout
