"""Frozen variant x asset-class compatibility matrix and cadence table.

The matrix is authored data, not inference: each declared pair carries a one-line
economic justification, and the runner refuses a pair or cadence that is not in
the frozen artifact. Validation and freezing happen before any file is written.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .common import QuantError, digest, read_json, safe_name, write_json
from .ts_spec import MarketClass, TimeSeriesSpec

CLASSES = ('indices', 'metals', 'crypto')
CADENCES = {'1h': 3600, '1m': 60}
BOOK_TITLES = {
    1: 'buy_hold_single', 2: 'buy_hold_risk_scaled', 3: 'buy_hold_variable_risk',
    4: 'buy_hold_portfolio_scaling', 5: 'slow_trend_long_only',
    6: 'slow_trend_long_short', 7: 'slow_trend_trend_strength',
    8: 'fast_trend_trend_strength', 9: 'multiple_trend_rules', 10: 'basic_carry',
    11: 'combined_carry_trend', 12: 'adjusted_trend', 13: 'trend_carry_regimes',
    14: 'spot_trend', 15: 'accurate_carry', 16: 'trend_carry_allocation',
    17: 'normalised_trend', 18: 'trend_asset_classes', 19: 'xs_momentum',
    20: 'xs_carry', 21: 'breakout', 22: 'value', 23: 'acceleration',
    26: 'fast_mean_reversion', 27: 'safer_fast_mean_reversion',
}
REQUIRED_STRATEGIES = frozenset(BOOK_TITLES)


def expected_sleeve_id(book_strategy: int) -> str:
    return f'af30_s{book_strategy:02d}_{BOOK_TITLES[book_strategy]}'


def load_matrix(path: str | Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    except (OSError, yaml.YAMLError) as exc:
        raise QuantError('INVALID_SPEC', f'Compatibility matrix unreadable: {exc}') from exc
    if not isinstance(payload, dict):
        raise QuantError('INVALID_SPEC', 'Compatibility matrix must be a mapping')
    return payload


def validate_matrix(matrix: dict[str, Any],
                    available: dict[tuple[str, str], set[str]] | None = None) -> None:
    if matrix.get('schema_version') != 1:
        raise QuantError('INVALID_SPEC', 'Compatibility matrix schema_version must be 1')
    safe_name(str(matrix.get('selection_family_id', '')))
    variants = matrix.get('variants')
    if not isinstance(variants, list):
        raise QuantError('INVALID_SPEC', 'Compatibility matrix requires a variant list')
    seen: dict[int, dict[str, Any]] = {}
    for variant in variants:
        book = variant.get('book_strategy')
        if not isinstance(book, int) or book not in REQUIRED_STRATEGIES:
            raise QuantError('INVALID_SPEC', f'Unknown book strategy: {book}')
        if book in seen:
            raise QuantError('INVALID_SPEC', f'Duplicate book strategy: {book}')
        if variant.get('sleeve_id') != expected_sleeve_id(book):
            raise QuantError('INVALID_SPEC',
                             f'Strategy {book} must use sleeve_id {expected_sleeve_id(book)}')
        cadence = variant.get('cadence')
        if cadence not in CADENCES:
            raise QuantError('INVALID_SPEC', f'Strategy {book} declares unknown cadence {cadence}')
        classes = variant.get('classes')
        if not isinstance(classes, dict) or not classes:
            raise QuantError('INVALID_SPEC', f'Strategy {book} declares no class')
        for name, justification in classes.items():
            if name not in CLASSES:
                raise QuantError('INVALID_SPEC', f'Strategy {book} declares unknown class {name}')
            if not isinstance(justification, str) or not justification.strip():
                raise QuantError('INVALID_SPEC',
                                 f'Strategy {book}/{name} needs an economic justification')
        if available is not None:
            for name in classes:
                if not available.get((name, cadence)):
                    raise QuantError('INVALID_SPEC',
                                     f'Strategy {book}/{name} has no symbols available at {cadence}')
        seen[book] = variant
    missing = REQUIRED_STRATEGIES - seen.keys()
    if missing:
        raise QuantError('INVALID_SPEC', f'Compatibility matrix misses strategies {sorted(missing)}')
    for name in CLASSES:
        if not any(name in variant['classes'] for variant in seen.values()):
            raise QuantError('INVALID_SPEC', f'No variant declares class {name}')


def matrix_digest(matrix: dict[str, Any]) -> str:
    return digest(matrix)


def freeze_matrix(matrix: dict[str, Any], directory: str | Path,
                  available: dict[tuple[str, str], set[str]] | None = None) -> dict[str, Any]:
    """Validate, then write the matrix and its freeze record atomically enough."""
    validate_matrix(matrix, available)
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    sha = matrix_digest(matrix)
    matrix_path = target / 'compatibility.yaml'
    temporary = target / '.compatibility.tmp.yaml'
    temporary.write_text(yaml.safe_dump(matrix, sort_keys=False), encoding='utf-8')
    temporary.replace(matrix_path)
    record = {'sha256': sha, 'variant_count': len(matrix['variants'])}
    write_json(target / 'compatibility.freeze.json', record)
    return {'matrix': str(matrix_path),
            'freeze': str(target / 'compatibility.freeze.json'), 'sha256': sha}


def load_frozen(directory: str | Path) -> tuple[dict[str, Any], str]:
    target = Path(directory)
    matrix = load_matrix(target / 'compatibility.yaml')
    record = read_json(target / 'compatibility.freeze.json')
    sha = matrix_digest(matrix)
    if record.get('sha256') != sha:
        raise QuantError('INVALID_EVIDENCE', 'Compatibility matrix changed after freezing')
    return matrix, sha


def require_declaration(matrix: dict[str, Any], spec: TimeSeriesSpec,
                        market_class: MarketClass, *, matrix_sha: str,
                        expected_sha: str) -> dict[str, Any]:
    """The runner's gate: a pair, cadence and frozen identity must all be declared."""
    if matrix_sha != expected_sha:
        raise QuantError('INVALID_EVIDENCE', 'Compatibility matrix hash does not match the freeze')
    variant = next((v for v in matrix.get('variants', [])
                    if v.get('book_strategy') == spec.book_strategy), None)
    if variant is None:
        raise QuantError('INVALID_SPEC', f'Book strategy {spec.book_strategy} is not declared')
    if variant.get('sleeve_id') != spec.sleeve_id:
        raise QuantError('INVALID_SPEC',
                         f'Sleeve {spec.sleeve_id} does not match the frozen declaration')
    justification = (variant.get('classes') or {}).get(market_class.name)
    if justification is None:
        raise QuantError('INVALID_SPEC',
                         f'Strategy {spec.book_strategy} is not declared for {market_class.name}')
    cadence = variant.get('cadence')
    if cadence not in CADENCES:
        raise QuantError('INVALID_SPEC', f'{spec.sleeve_id} declares unknown cadence {cadence}')
    if market_class.bar_seconds != CADENCES[cadence]:
        raise QuantError('INVALID_SPEC',
                         f'{spec.sleeve_id}/{market_class.name} must run at {cadence}')
    return {'book_strategy': spec.book_strategy, 'sleeve_id': spec.sleeve_id,
            'market_class': market_class.name, 'cadence': cadence,
            'justification': justification, 'matrix_sha256': matrix_sha}
