from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from src.engine.combined_portfolio import (
    EVIDENCE_ROOT,
    build_portfolio,
    compose_returns,
    load_rule,
    rule_digest,
    validate_rule,
)
from src.engine.common import QuantError, file_hash
from src.engine.ts_casefile import build_casefile, write_casefile
from src.engine.ts_spec import TimeSeriesSpec

HASH = lambda char: char * 64
START = datetime(2024, 1, 1, tzinfo=UTC)


def make_rule(**overrides) -> dict:
    rule = {'schema_version': 1, 'portfolio_id': 'af30_combined_portfolio',
            'selection_family_id': 'af30_time_series',
            'inclusion': 'QUALIFIED_ONLY', 'per_class_weighting': 'equal_weight',
            'class_weights': {'indices': 1.0, 'metals': 0.0, 'crypto': 0.0}}
    rule.update(overrides)
    return rule


def make_spec(sleeve_id: str, book: int = 6, class_name: str = 'indices') -> TimeSeriesSpec:
    return TimeSeriesSpec.model_validate({
        'spec_kind': 'time_series', 'sleeve_id': sleeve_id,
        'selection_family_id': 'af30_time_series', 'book_strategy': book,
        'thesis': 'Combined portfolio test sleeve.',
        'market_classes': [{'name': class_name, 'symbols': ['DAX', 'NQ'],
                            'panel_root': f'data/vault/markets_20261015/{class_name}_1h',
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


def make_casefile(log: Path, sleeve_id: str, book: int, status: str = 'QUALIFIED',
                  returns: list[float] | None = None) -> Path:
    spec = make_spec(sleeve_id, book)
    folder = log / EVIDENCE_ROOT / 'indices' / sleeve_id
    folder.mkdir(parents=True, exist_ok=True)
    values = returns if returns is not None else [0.001 * ((i % 5) - 2) for i in range(10)]
    pl.DataFrame({'date': [START.date() + timedelta(days=i) for i in range(len(values))],
                  'equity': [100000.0 + i for i in range(len(values))],
                  'return': values}).write_parquet(folder / 'daily.parquet')
    casefile = build_casefile(
        spec=spec, market_class=spec.market_classes[0],
        feature_proof={'status': 'PASS', 'input_sha256': HASH('a'),
                       'output_sha256': HASH('b'), 'checks': ['2020-01-02T00:00:00+00:00']},
        qualification={'status': 'DECLARED_ASSUMPTIONS', 'costs': {'commission_bps_one_way': 1.0},
                       'assumptions': ('declared',), 'sha256': HASH('c')},
        carry_metadata={'status': 'OBSERVED', 'sign_convention': 'positive_rate_charges_longs'},
        gate_report={'status': status, 'checks': {'train_positive': {'value': 1.0, 'passed': True}}},
        disposition={'status': status},
        code_hash=HASH('d'), panel_hash=HASH('e'),
        vault_root='data/vault/markets_20261015/index_1h',
        attempts=[], last_hash=HASH('f'))
    write_casefile(casefile, folder)
    return folder


def test_rule_validates_and_hash_is_stable():
    rule = make_rule()
    validate_rule(rule)
    artifact = load_rule()
    validate_rule(artifact)
    assert rule_digest(artifact) == rule_digest(load_rule())
    with pytest.raises(QuantError):
        validate_rule(make_rule(class_weights={'indices': 0.5}))
    with pytest.raises(QuantError):
        validate_rule(make_rule(inclusion='ALL'))


def test_equal_weight_composes_exactly():
    returns = pl.DataFrame({'timestamp': [START + timedelta(days=i) for i in range(5)],
                            'a': [0.01, -0.02, 0.03, 0.0, 0.01],
                            'b': [0.02, 0.01, -0.01, 0.02, -0.02]})
    portfolio, weights = compose_returns(returns, {'a': 'QUALIFIED', 'b': 'QUALIFIED'}, make_rule())
    assert weights == {'a': 0.5, 'b': 0.5}
    assert portfolio.to_list() == pytest.approx([0.015, -0.005, 0.01, 0.01, -0.005])
    again, _ = compose_returns(returns, {'a': 'QUALIFIED', 'b': 'QUALIFIED'}, make_rule())
    assert again.equals(portfolio)


def test_equal_risk_weights_are_inverse_volatility():
    returns = pl.DataFrame({'timestamp': [START + timedelta(days=i) for i in range(20)],
                            'a': [0.01 * (1 if i % 2 else -1) for i in range(20)],
                            'b': [0.02 * (1 if i % 2 else -1) for i in range(20)]})
    rule = make_rule(per_class_weighting='equal_risk')
    _, weights = compose_returns(returns, {'a': 'QUALIFIED', 'b': 'QUALIFIED'}, rule)
    assert weights['a'] == pytest.approx(2 / 3, abs=1e-12)
    assert weights['b'] == pytest.approx(1 / 3, abs=1e-12)


def test_non_qualified_sleeve_is_rejected():
    returns = pl.DataFrame({'timestamp': [START + timedelta(days=i) for i in range(5)],
                            'a': [0.01] * 5, 'b': [0.02] * 5})
    with pytest.raises(QuantError) as exc:
        compose_returns(returns, {'a': 'QUALIFIED', 'b': 'FALSIFIED'}, make_rule())
    assert exc.value.status == 'INVALID_SPEC'
    assert 'b' in exc.value.reason


def test_portfolio_includes_only_qualified_casefiles(tmp_path: Path):
    log = tmp_path / 'run_log'
    make_casefile(log, 'af30_s06_slow_trend_long_short', 6)
    make_casefile(log, 'af30_s07_slow_trend_trend_strength', 7,
                  returns=[0.002 * ((i % 3) - 1) for i in range(10)])
    make_casefile(log, 'af30_s08_fast_trend_trend_strength', 8, status='FALSIFIED')
    record = build_portfolio(log, 'indices')
    assert record['status'] == 'COMPOSED'
    assert {item['sleeve_id'] for item in record['included']} == {
        'af30_s06_slow_trend_long_short', 'af30_s07_slow_trend_trend_strength'}
    assert record['weights'] == {'af30_s06_slow_trend_long_short': 0.5,
                                 'af30_s07_slow_trend_trend_strength': 0.5}
    assert record['class_dsr']['trials'] == 2
    assert record['class_dsr']['observations'] == 10
    daily = (log / 'portfolios' / record['portfolio_id'] / 'indices' / 'portfolio_daily.parquet')
    assert record['backtest_sha256'] == file_hash(daily)
    assert record['portfolio_psr']['trials'] == 1


def test_no_qualified_sleeve_blocks_composition(tmp_path: Path):
    log = tmp_path / 'run_log'
    make_casefile(log, 'af30_s06_slow_trend_long_short', 6, status='FALSIFIED')
    with pytest.raises(QuantError) as exc:
        build_portfolio(log, 'indices')
    assert exc.value.status == 'BLOCKED_DATA'
