from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.engine.common import QuantError
from src.engine.sleeve_matrix import (
    expected_sleeve_id,
    load_frozen,
    matrix_digest,
    require_declaration,
    require_symbols,
)
from src.engine.ts_spec import parse_ts_spec

SPEC_DIR = Path(__file__).parents[1] / 'config/sleeves/advanced_futures_30'
VAULT = Path(__file__).parents[1] / 'data/vault/markets_20261015'
STORE = Path('/home/quant/dev/quant/ml4t-data/.data/store')
FAST = (21, 22, 23, 26, 27)
MINUTE = {26, 27}


def specs() -> dict[int, Path]:
    found = {}
    for path in sorted(SPEC_DIR.glob('af30_s*.yaml')):
        spec = parse_ts_spec(path)
        if spec.book_strategy in FAST:
            found[spec.book_strategy] = path
    return found


def vault_symbols(name: str) -> set[str]:
    manifest = json.loads((VAULT / name / 'manifest.json').read_text())
    return {entry['symbol'] for entry in manifest['entries'] if entry.get('symbol')}


def test_all_five_specs_exist_and_follow_the_frozen_matrix():
    files = specs()
    assert set(files) == set(FAST)
    matrix, sha = load_frozen(SPEC_DIR)
    assert sha == matrix_digest(matrix)
    for book, path in files.items():
        spec = parse_ts_spec(path)
        assert spec.sleeve_id == expected_sleeve_id(book)
        variant = next(v for v in matrix['variants'] if v['book_strategy'] == book)
        assert {c.name for c in spec.market_classes} == set(variant['classes'])
        for market_class in spec.market_classes:
            require_declaration(matrix, spec, market_class,
                                matrix_sha=sha, expected_sha=sha)
            assert market_class.carry.mode in {'modeled', 'observed'}


def test_minute_variants_declare_60_second_bars_and_minute_vaults():
    for book, path in specs().items():
        spec = parse_ts_spec(path)
        expected = 60 if book in MINUTE else 3600
        for market_class in spec.market_classes:
            assert market_class.bar_seconds == expected
            suffix = '1m' if book in MINUTE else '1h'
            assert market_class.panel_root.endswith(f'_{suffix}')


def test_declared_symbols_exist_in_the_materialized_vaults():
    for book in MINUTE:
        spec = parse_ts_spec(specs()[book])
        for market_class in spec.market_classes:
            if market_class.name in ('indices', 'metals'):
                name = ('index_1m' if market_class.name == 'indices' else 'metals_1m')
                require_symbols(market_class, vault_symbols(name))


def test_crypto_minute_sources_exist_for_declared_symbols():
    if not STORE.is_dir():
        pytest.skip('external ml4t-data store is not mounted')
    spec = parse_ts_spec(specs()[26])
    crypto = next(c for c in spec.market_classes if c.name == 'crypto')
    missing = [s for s in crypto.symbols
               if not (STORE / f'crypto_futures_minute_{s}_PERP').is_dir()]
    assert missing == []


def test_absent_symbol_or_cadence_is_rejected():
    spec = parse_ts_spec(specs()[26])
    market_class = next(c for c in spec.market_classes if c.name == 'indices')
    with pytest.raises(QuantError) as exc:
        require_symbols(market_class, set(market_class.symbols) - {market_class.symbols[0]})
    assert exc.value.status == 'INVALID_SPEC'
    assert market_class.symbols[0] in exc.value.reason

    matrix, sha = load_frozen(SPEC_DIR)
    hourly = market_class.model_copy(update={'bar_seconds': 3600})
    with pytest.raises(QuantError) as cadence:
        require_declaration(matrix, spec, hourly, matrix_sha=sha, expected_sha=sha)
    assert '1m' in cadence.value.reason


def test_no_zero_cost_or_unknown_financing():
    for path in specs().values():
        spec = parse_ts_spec(path)
        assert spec.costs.commission_bps_one_way > 0
        assert spec.costs.slippage_bps_one_way > 0
        assert spec.costs.spread_bps > 0 or spec.costs.spread_included_in_slippage
        for market_class in spec.market_classes:
            assert market_class.carry.mode in {'modeled', 'observed'}


@pytest.mark.parametrize('book', FAST)
def test_cli_validates_each_spec(book: int):
    path = specs()[book]
    run = subprocess.run([sys.executable, 'scripts/quant.py', 'validate', str(path)],
                         cwd=path.parents[3], capture_output=True, text=True,
                         timeout=120, check=False)
    assert run.returncode == 0, run.stderr
    assert '"VALID_SPEC"' in run.stdout
    assert f'"book_strategy": {book}' in run.stdout
