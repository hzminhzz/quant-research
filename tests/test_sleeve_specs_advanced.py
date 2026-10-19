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
ADVANCED = tuple(range(12, 21))
CROSS_SECTIONAL = {19, 20}


def specs() -> dict[int, Path]:
    found = {}
    for path in sorted(SPEC_DIR.glob('af30_s*.yaml')):
        spec = parse_ts_spec(path)
        if spec.book_strategy in ADVANCED:
            found[spec.book_strategy] = path
    return found


def matrix() -> dict:
    return load_matrix(SPEC_DIR / 'compatibility.yaml')


def matrix_classes(book: int) -> set[str]:
    variant = next(v for v in matrix()['variants'] if v['book_strategy'] == book)
    return set(variant['classes'])


def uses(feature, name: str) -> bool:
    return name in str(feature.expr)


def test_all_nine_advanced_specs_exist_parse_and_follow_the_matrix():
    files = specs()
    assert set(files) == set(ADVANCED)
    data = matrix()
    sha = matrix_digest(data)
    for book, path in files.items():
        spec = parse_ts_spec(path)
        assert spec.sleeve_id == expected_sleeve_id(book)
        assert {c.name for c in spec.market_classes} == matrix_classes(book)
        for market_class in spec.market_classes:
            require_declaration(data, spec, market_class, matrix_sha=sha, expected_sha=sha)
            assert market_class.bar_seconds == 3600
            assert market_class.carry.mode in {'modeled', 'observed'}


def test_cross_sectional_mode_is_declared_only_where_required():
    for book, path in specs().items():
        spec = parse_ts_spec(path)
        has_xs = any(uses(f, 'xs_rank') or uses(f, 'xs_mean') for f in spec.features)
        assert spec.cross_sectional is (book in CROSS_SECTIONAL)
        assert has_xs is (book in CROSS_SECTIONAL)
        if book in CROSS_SECTIONAL:
            assert any(uses(f, 'xs_rank') for f in spec.features)
            assert any(uses(f, 'xs_mean') for f in spec.features)


def test_signals_use_their_declared_family():
    for book, path in specs().items():
        spec = parse_ts_spec(path)
        references_carry = any(uses(f, 'carry_rate') for f in spec.features)
        if book in {15, 16, 20}:
            assert references_carry, f'{spec.sleeve_id} must use financing'
        if book == 19:
            assert not references_carry
            assert any(uses(f, 'pct_change') for f in spec.features)


def test_no_zero_cost_or_unknown_financing():
    for path in specs().values():
        spec = parse_ts_spec(path)
        assert spec.costs.commission_bps_one_way > 0
        assert spec.costs.slippage_bps_one_way > 0
        assert spec.costs.spread_bps > 0 or spec.costs.spread_included_in_slippage
        for market_class in spec.market_classes:
            assert market_class.carry.mode in {'modeled', 'observed'}


@pytest.mark.parametrize('book', ADVANCED)
def test_cli_validates_each_spec(book: int):
    path = specs()[book]
    run = subprocess.run([sys.executable, 'scripts/quant.py', 'validate', str(path)],
                         cwd=path.parents[3], capture_output=True, text=True,
                         timeout=120, check=False)
    assert run.returncode == 0, run.stderr
    assert '"VALID_SPEC"' in run.stdout
    assert f'"book_strategy": {book}' in run.stdout
