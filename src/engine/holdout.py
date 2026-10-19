"""One-shot protected read for the frozen combined portfolio.

The claim is reserved *before* any protected row is opened and is never deleted:
a successful read marks it complete, a crash marks it failed, and either way a
second attempt is refused. Sleeve research is development-only and is stopped by
`guard_development_read` if a window would cross the protected start.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import polars as pl

from .combined_portfolio import PERIODS, RULE_PATH, load_rule, rule_digest
from .common import QuantError, digest, file_hash, read_json, write_json
from .ts_gates import class_dsr

CLAIM_ROOT = 'holdout'
PORTFOLIO_ROOT = 'portfolios'


def guard_development_read(end, protected_start) -> None:
    """A development read may not touch the protected window."""
    if end > protected_start:
        raise QuantError('INVALID_SPEC',
                         f'Development read ends at {end} but the protected window starts at {protected_start}')


def claim_path(run_log: str | Path, portfolio_id: str, market_class: str) -> Path:
    return Path(run_log) / CLAIM_ROOT / f'{portfolio_id}.{market_class}.claim.json'


def read_claim(path: str | Path) -> dict[str, Any]:
    return read_json(Path(path))


def reserve_claim(path: str | Path, identity: dict[str, Any]) -> dict[str, Any]:
    """Reserve exactly once; an existing claim is a refusal, never an overwrite."""
    target = Path(path)
    payload = {'schema_version': 1, 'status': 'RESERVED',
               'identity': identity, 'identity_sha256': digest(identity)}
    try:
        write_json(target, payload, exclusive=True)
    except FileExistsError as exc:
        raise QuantError('HOLDOUT_DENIED',
                         f'Protected claim already consumed: {target}') from exc
    return payload


def update_claim(path: str | Path, status: str, **extra: Any) -> dict[str, Any]:
    target = Path(path)
    payload = read_json(target)
    payload.update(extra)
    payload['status'] = status
    write_json(target, payload)
    return payload


def _portfolio_record(run_log: Path, market_class: str) -> dict[str, Any]:
    matches = sorted((run_log / PORTFOLIO_ROOT).glob(f'*/{market_class}/portfolio_record.json'))
    if not matches:
        raise QuantError('BLOCKED_DATA', f'No frozen portfolio record for {market_class}')
    record = read_json(matches[-1])
    if record.get('status') != 'COMPOSED':
        raise QuantError('BLOCKED_DATA', 'Portfolio record is not composed')
    return record


def evaluate_portfolio_holdout(run_log: str | Path, market_class: str,
                               protected_loader: Callable[[str], pl.DataFrame],
                               *, rule_path: str | Path = RULE_PATH) -> dict[str, Any]:
    """Read the protected window once, for the frozen portfolio composition."""
    log = Path(run_log)
    record = _portfolio_record(log, market_class)
    rule = load_rule(rule_path)
    if record.get('rule_sha256') != rule_digest(rule):
        raise QuantError('INVALID_EVIDENCE',
                         'Portfolio rule changed after composition; composition is not frozen')
    included = [item['sleeve_id'] for item in record['included']]
    if set(record['weights']) != set(included):
        raise QuantError('INVALID_EVIDENCE', 'Frozen weights do not match the included sleeves')
    identity = {'portfolio_id': record['portfolio_id'], 'market_class': market_class,
                'rule_sha256': record['rule_sha256'],
                'included': [{'sleeve_id': item['sleeve_id'],
                              'casefile_sha256': item['casefile_sha256']} for item in record['included']]}
    path = claim_path(log, record['portfolio_id'], market_class)
    reserve_claim(path, identity)
    try:
        frames = []
        for sleeve_id in included:
            frame = protected_loader(sleeve_id)
            if not {'date', 'return'} <= set(frame.columns):
                raise QuantError('INVALID_EVIDENCE', 'Protected returns need date and return columns')
            frames.append(frame.select(pl.col('date').alias('timestamp'),
                                       pl.col('return').alias(sleeve_id))
                          .drop_nulls().sort('timestamp'))
        aligned = frames[0]
        for frame in frames[1:]:
            aligned = aligned.join(frame, on='timestamp', how='inner')
        if aligned.height < 3:
            raise QuantError('INCONCLUSIVE', 'Protected window has too few aligned observations')
        weights = record['weights']
        portfolio = sum(aligned[sleeve_id] * weight for sleeve_id, weight in weights.items())
        folder = log / PORTFOLIO_ROOT / record['portfolio_id'] / market_class
        daily_path = folder / 'protected_daily.parquet'
        temporary = folder / '.protected_daily.tmp.parquet'
        aligned.with_columns(portfolio.alias('portfolio')).write_parquet(temporary)
        temporary.replace(daily_path)
        periods = PERIODS[market_class]
        result = {
            'schema_version': 1,
            'portfolio_id': record['portfolio_id'],
            'market_class': market_class,
            'rule_sha256': record['rule_sha256'],
            'included': included,
            'observations': aligned.height,
            'class_dsr': class_dsr(aligned, periods),
            'portfolio_psr': class_dsr(
                aligned.with_columns(portfolio.alias('portfolio')).select('timestamp', 'portfolio'),
                periods),
            'protected_daily_sha256': file_hash(daily_path),
            'status': 'READ_COMPLETE',
        }
        write_json(folder / 'holdout_record.json', result)
        update_claim(path, 'READ_COMPLETE', output_sha256=digest(result))
        return result
    except Exception as exc:
        update_claim(path, 'FAILED', reason=f'{type(exc).__name__}: {exc}')
        raise
