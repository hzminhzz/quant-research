from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from src.engine.combined_portfolio import EVIDENCE_ROOT, build_portfolio
from src.engine.common import QuantError, file_hash
from src.engine.holdout import (
    claim_path,
    evaluate_portfolio_holdout,
    guard_development_read,
    read_claim,
    reserve_claim,
)
from src.engine.ts_casefile import build_casefile, write_casefile
from src.engine.ts_spec import TimeSeriesSpec

HASH = lambda char: char * 64
START = datetime(2024, 1, 1, tzinfo=UTC)


def make_spec(sleeve_id: str, book: int) -> TimeSeriesSpec:
    return TimeSeriesSpec.model_validate({
        'spec_kind': 'time_series', 'sleeve_id': sleeve_id,
        'selection_family_id': 'af30_time_series', 'book_strategy': book,
        'thesis': 'Protected read test sleeve.',
        'market_classes': [{'name': 'indices', 'symbols': ['DAX', 'NQ'],
                            'panel_root': 'data/vault/markets_20261015/index_1h',
                            'bar_seconds': 3600, 'periods_per_year': 252,
                            'carry': {'mode': 'observed'}}],
        'windows': {
            'train': {'start': '2020-01-01T00:00:00Z', 'end': '2021-01-01T00:00:00Z'},
            'validation': {'start': '2021-01-01T00:00:00Z', 'end': '2022-01-01T00:00:00Z'},
            'protected': {'start': '2026-01-01T00:00:00Z', 'end': '2026-10-01T00:00:00Z'},
        },
        'features': [{'name': 'f', 'expr': {'op': 'col', 'name': 'close'}},
                     {'name': 'atr_14', 'expr': {'op': 'col', 'name': 'close'}}],
        'forecast': {'feature': 'f', 'horizon_bars': 1,
                     'scaling': {'kind': 'bounded_linear', 'scale': 1.0, 'cap': 20.0}},
        'stops': {'feature': 'atr_14', 'multiple': 3.0},
        'costs': {'commission_bps_one_way': 1.0, 'slippage_bps_one_way': 1.0,
                  'spread_bps': 0.0, 'spread_included_in_slippage': True},
    })


def make_casefile(log: Path, sleeve_id: str, book: int) -> None:
    spec = make_spec(sleeve_id, book)
    folder = log / EVIDENCE_ROOT / 'indices' / sleeve_id
    folder.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({'date': [START.date() + timedelta(days=i) for i in range(10)],
                  'equity': [100000.0 + i for i in range(10)],
                  'return': [0.001 * ((i % 5) - 2) for i in range(10)]}).write_parquet(folder / 'daily.parquet')
    casefile = build_casefile(
        spec=spec, market_class=spec.market_classes[0],
        feature_proof={'status': 'PASS', 'input_sha256': HASH('a'),
                       'output_sha256': HASH('b'), 'checks': ['2020-01-02T00:00:00+00:00']},
        qualification={'status': 'DECLARED_ASSUMPTIONS', 'costs': {'commission_bps_one_way': 1.0},
                       'assumptions': ('declared',), 'sha256': HASH('c')},
        carry_metadata={'status': 'OBSERVED', 'sign_convention': 'positive_rate_charges_longs'},
        gate_report={'status': 'QUALIFIED', 'checks': {'train_positive': {'value': 1.0, 'passed': True}}},
        disposition={'status': 'QUALIFIED'},
        code_hash=HASH('d'), panel_hash=HASH('e'),
        vault_root='data/vault/markets_20261015/index_1h',
        attempts=[], last_hash=HASH('f'))
    write_casefile(casefile, folder)


def prepared_portfolio(tmp_path: Path) -> Path:
    log = tmp_path / 'run_log'
    make_casefile(log, 'af30_s06_slow_trend_long_short', 6)
    make_casefile(log, 'af30_s07_slow_trend_trend_strength', 7)
    build_portfolio(log, 'indices')
    return log


def protected_returns(sleeve_id: str) -> pl.DataFrame:
    return pl.DataFrame({'date': [START.date() + timedelta(days=i) for i in range(8)],
                         'return': [0.001 * ((i + len(sleeve_id)) % 4 - 1) for i in range(8)]})


def test_claim_is_reserved_once_and_never_overwritten(tmp_path: Path):
    path = claim_path(tmp_path, 'af30_combined_portfolio', 'indices')
    reserved = reserve_claim(path, {'portfolio_id': 'af30_combined_portfolio'})
    assert reserved['status'] == 'RESERVED'
    before = file_hash(path)
    with pytest.raises(QuantError) as exc:
        reserve_claim(path, {'portfolio_id': 'af30_combined_portfolio'})
    assert exc.value.status == 'HOLDOUT_DENIED'
    assert file_hash(path) == before


def test_single_successful_protected_read(tmp_path: Path):
    log = prepared_portfolio(tmp_path)
    result = evaluate_portfolio_holdout(log, 'indices', protected_returns)
    assert result['status'] == 'READ_COMPLETE'
    assert result['observations'] == 8
    assert result['class_dsr']['trials'] == 2
    daily = log / 'portfolios' / result['portfolio_id'] / 'indices' / 'protected_daily.parquet'
    assert result['protected_daily_sha256'] == file_hash(daily)
    claim = read_claim(claim_path(log, result['portfolio_id'], 'indices'))
    assert claim['status'] == 'READ_COMPLETE'
    assert claim['output_sha256']
    with pytest.raises(QuantError) as exc:
        evaluate_portfolio_holdout(log, 'indices', protected_returns)
    assert exc.value.status == 'HOLDOUT_DENIED'


def test_a_crash_consumes_the_claim_and_records_the_failure(tmp_path: Path):
    log = prepared_portfolio(tmp_path)

    def failing(_sleeve_id: str) -> pl.DataFrame:
        raise RuntimeError('simulated read failure')

    with pytest.raises(RuntimeError):
        evaluate_portfolio_holdout(log, 'indices', failing)
    claim = read_claim(claim_path(log, 'af30_combined_portfolio', 'indices'))
    assert claim['status'] == 'FAILED'
    assert 'simulated read failure' in claim['reason']
    assert not (log / 'portfolios' / 'af30_combined_portfolio' / 'indices' / 'holdout_record.json').exists()
    with pytest.raises(QuantError) as exc:
        evaluate_portfolio_holdout(log, 'indices', protected_returns)
    assert exc.value.status == 'HOLDOUT_DENIED'


def test_sleeve_development_reads_cannot_cross_the_protected_start():
    protected = datetime(2026, 1, 1, tzinfo=UTC)
    guard_development_read(datetime(2025, 12, 31, tzinfo=UTC), protected)
    with pytest.raises(QuantError) as exc:
        guard_development_read(datetime(2026, 1, 2, tzinfo=UTC), protected)
    assert exc.value.status == 'INVALID_SPEC'


def test_a_changed_rule_blocks_the_read_before_the_claim(tmp_path: Path):
    log = prepared_portfolio(tmp_path)
    rule = (Path(__file__).parents[1] / 'config/sleeves/advanced_futures_30/portfolio_rule.yaml')
    changed = tmp_path / 'rule.yaml'
    changed.write_text(rule.read_text().replace('per_class_weighting: equal_weight',
                                                'per_class_weighting: equal_risk'), encoding='utf-8')
    with pytest.raises(QuantError) as exc:
        evaluate_portfolio_holdout(log, 'indices', protected_returns, rule_path=changed)
    assert exc.value.status == 'INVALID_EVIDENCE'
    assert not claim_path(log, 'af30_combined_portfolio', 'indices').exists()
