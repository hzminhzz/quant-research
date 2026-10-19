"""Combined portfolio built only from sleeves with a QUALIFIED disposition.

The inclusion rule is frozen before composition: every column must carry a
QUALIFIED status, a non-qualified sleeve is a spec error, and weights follow a
declared per-class method. Class returns stay separate; the record reports that
class's DSR and the hashes of its inputs, never a pooled cross-class series.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import yaml

from .common import QuantError, digest, file_hash, read_json, write_json
from .ts_casefile import validate_casefile
from .ts_gates import class_dsr

REPO = Path(__file__).resolve().parents[2]
RULE_PATH = REPO / 'config/sleeves/advanced_futures_30/portfolio_rule.yaml'
EVIDENCE_ROOT = 'sleeves_advanced_futures_30'
PORTFOLIO_ROOT = 'portfolios'
PERIODS = {'indices': 252, 'metals': 252, 'crypto': 365}
METHODS = {'equal_weight', 'equal_risk'}


def load_rule(path: str | Path = RULE_PATH) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    except (OSError, yaml.YAMLError) as exc:
        raise QuantError('INVALID_SPEC', f'Portfolio rule unreadable: {exc}') from exc
    validate_rule(payload)
    return payload


def validate_rule(rule: dict[str, Any] | None) -> None:
    if not isinstance(rule, dict) or rule.get('schema_version') != 1:
        raise QuantError('INVALID_SPEC', 'Portfolio rule must declare schema_version 1')
    if rule.get('inclusion') != 'QUALIFIED_ONLY':
        raise QuantError('INVALID_SPEC', 'Portfolio inclusion must be QUALIFIED_ONLY')
    if rule.get('per_class_weighting') not in METHODS:
        raise QuantError('INVALID_SPEC', f'Unknown weighting method {rule.get("per_class_weighting")}')
    weights = rule.get('class_weights')
    if not isinstance(weights, dict) or not weights:
        raise QuantError('INVALID_SPEC', 'Portfolio rule requires class weights')
    if any(name not in PERIODS for name in weights):
        raise QuantError('INVALID_SPEC', 'Portfolio rule names an unknown class')
    if any(not isinstance(value, (int, float)) or value < 0 for value in weights.values()):
        raise QuantError('INVALID_SPEC', 'Class weights must be non-negative numbers')
    if abs(sum(weights.values()) - 1.0) > 1e-12:
        raise QuantError('INVALID_SPEC', 'Class weights must sum to one')


def rule_digest(rule: dict[str, Any]) -> str:
    return digest(rule)


def compose_returns(returns: pl.DataFrame, statuses: dict[str, str],
                    rule: dict[str, Any]) -> tuple[pl.Series, dict[str, float]]:
    """Validate every column, then weight it; nothing is computed before that."""
    if 'timestamp' not in returns.columns:
        raise QuantError('INVALID_SPEC', 'Portfolio returns need a timestamp column')
    sleeves = [name for name in returns.columns if name != 'timestamp']
    if not sleeves:
        raise QuantError('INVALID_SPEC', 'Portfolio returns need at least one sleeve column')
    if set(statuses) != set(sleeves):
        raise QuantError('INVALID_SPEC', 'Every sleeve column needs exactly one status')
    rejected = sorted(name for name in sleeves if statuses[name] != 'QUALIFIED')
    if rejected:
        raise QuantError('INVALID_SPEC', f'Non-qualified sleeves cannot enter the portfolio: {rejected}')
    if returns.height < 3:
        raise QuantError('INVALID_SPEC', 'Portfolio needs at least three aligned rows')
    matrix = returns.select(sleeves).to_numpy().astype(float)
    if not np.isfinite(matrix).all():
        raise QuantError('INVALID_SPEC', 'Portfolio returns contain nonfinite values')
    if rule['per_class_weighting'] == 'equal_weight':
        weights = {name: 1.0 / len(sleeves) for name in sleeves}
    else:
        deviations = {name: float(returns[name].std()) for name in sleeves}
        if any(not math.isfinite(value) or value <= 0 for value in deviations.values()):
            raise QuantError('INVALID_SPEC', 'Equal-risk weighting needs positive sleeve dispersion')
        inverse = {name: 1.0 / value for name, value in deviations.items()}
        total = sum(inverse.values())
        weights = {name: value / total for name, value in inverse.items()}
    portfolio = sum(returns[name] * weight for name, weight in weights.items())
    return portfolio.alias('portfolio'), weights


def qualified_casefiles(run_log: str | Path, market_class: str) -> list[dict[str, Any]]:
    root = Path(run_log) / EVIDENCE_ROOT / market_class
    if not root.is_dir():
        return []
    qualified = []
    for path in sorted(root.glob('*/casefile.json')):
        casefile = read_json(path)
        validate_casefile(casefile)
        if casefile['disposition']['status'] != 'QUALIFIED':
            continue
        returns_path = path.parent / 'daily.parquet'
        if not returns_path.is_file():
            raise QuantError('INVALID_EVIDENCE', f'Qualified sleeve has no returns artifact: {path}')
        qualified.append({'sleeve_id': casefile['identity']['sleeve_id'],
                          'spec_hash': casefile['identity']['spec_hash'],
                          'casefile_sha256': casefile['casefile_sha256'],
                          'returns_path': returns_path})
    return qualified


def build_portfolio(run_log: str | Path, market_class: str, *,
                    rule_path: str | Path = RULE_PATH) -> dict[str, Any]:
    rule = load_rule(rule_path)
    log = Path(run_log)
    included = qualified_casefiles(log, market_class)
    if not included:
        raise QuantError('BLOCKED_DATA', f'No QUALIFIED sleeve in {market_class}; nothing to compose')
    frames = []
    for item in included:
        frames.append(pl.read_parquet(item['returns_path'])
                      .select(pl.col('date').alias('timestamp'),
                              pl.col('return').alias(item['sleeve_id']))
                      .drop_nulls().sort('timestamp'))
    aligned = frames[0]
    for frame in frames[1:]:
        aligned = aligned.join(frame, on='timestamp', how='inner')
    statuses = {item['sleeve_id']: 'QUALIFIED' for item in included}
    portfolio, weights = compose_returns(aligned, statuses, rule)

    folder = log / PORTFOLIO_ROOT / rule['portfolio_id'] / market_class
    folder.mkdir(parents=True, exist_ok=True)
    daily_path = folder / 'portfolio_daily.parquet'
    temporary = folder / '.portfolio_daily.tmp.parquet'
    aligned.with_columns(portfolio).write_parquet(temporary)
    temporary.replace(daily_path)

    periods = PERIODS[market_class]
    family = class_dsr(aligned, periods)
    single = class_dsr(aligned.with_columns(portfolio).select('timestamp', 'portfolio'), periods)
    record = {
        'schema_version': 1,
        'portfolio_id': rule['portfolio_id'],
        'selection_family_id': rule['selection_family_id'],
        'market_class': market_class,
        'rule_sha256': rule_digest(rule),
        'included': [{'sleeve_id': item['sleeve_id'],
                      'casefile_sha256': item['casefile_sha256'],
                      'spec_hash': item['spec_hash']} for item in included],
        'weights': weights,
        'observations': aligned.height,
        'class_dsr': family,
        'portfolio_psr': single,
        'backtest_sha256': file_hash(daily_path),
        'status': 'COMPOSED',
    }
    write_json(folder / 'portfolio_record.json', record)
    return record
