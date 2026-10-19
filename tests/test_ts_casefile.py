from __future__ import annotations

from pathlib import Path

import pytest

from src.engine.common import QuantError, digest
from src.engine.ts_casefile import (
    active_outcomes,
    build_casefile,
    classify_gate_change,
    read_trials,
    record_attempt,
    validate_casefile,
    write_casefile,
)
from src.engine.ts_spec import TimeSeriesSpec

HASH = lambda char: char * 64


def make_spec() -> TimeSeriesSpec:
    return TimeSeriesSpec.model_validate({
        'spec_kind': 'time_series',
        'sleeve_id': 'af30_casefile',
        'selection_family_id': 'af30_time_series',
        'book_strategy': 11,
        'thesis': 'Casefile contract test.',
        'market_classes': [{
            'name': 'indices', 'symbols': ['DAX', 'NQ'],
            'panel_root': 'data/vault/markets_20261015/index_1h',
            'bar_seconds': 3600, 'periods_per_year': 252,
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


def inputs() -> dict:
    spec = make_spec()
    return {
        'spec': spec,
        'market_class': spec.market_classes[0],
        'feature_proof': {'status': 'PASS', 'input_sha256': HASH('a'),
                          'output_sha256': HASH('b'),
                          'checks': ['2020-01-02T00:00:00+00:00']},
        'qualification': {'status': 'DECLARED_ASSUMPTIONS', 'costs': {'commission_bps_one_way': 1.0},
                          'assumptions': ('commission declared',), 'sha256': HASH('c')},
        'carry_metadata': {'status': 'MODELED', 'curve': {'name': 'US10Y', 'sha256': HASH('d')},
                           'sign_convention': 'positive_rate_charges_longs', 'sha256': HASH('e')},
        'gate_report': {'status': 'QUALIFIED',
                        'checks': {'train_positive': {'value': 1.0, 'passed': True}}},
        'disposition': {'status': 'QUALIFIED'},
        'code_hash': HASH('f'),
        'panel_hash': HASH('0'),
        'vault_root': 'data/vault/markets_20261015/index_1h',
        'attempts': [],
        'last_hash': HASH('1'),
    }


def test_complete_casefile_validates_hashes_and_writes(tmp_path: Path):
    casefile = build_casefile(**inputs())
    validate_casefile(casefile)
    assert len(casefile['casefile_sha256']) == 64
    assert casefile['casefile_sha256'] == digest(
        {k: v for k, v in casefile.items() if k != 'casefile_sha256'})
    written = write_casefile(casefile, tmp_path / 'sleeve')
    assert Path(written['path']).is_file()
    assert written['sha256'] == casefile['casefile_sha256']


def test_build_is_deterministic():
    first = build_casefile(**inputs())
    second = build_casefile(**inputs())
    assert first['casefile_sha256'] == second['casefile_sha256']


def test_missing_required_section_is_rejected():
    complete = build_casefile(**inputs())
    broken = {k: v for k, v in complete.items() if k != 'feature_proof'}
    with pytest.raises(QuantError) as exc:
        validate_casefile(broken)
    assert exc.value.status == 'INVALID_EVIDENCE'
    assert 'feature_proof' in exc.value.reason


def test_blocked_disposition_requires_a_reason():
    broken = build_casefile(**inputs())
    broken['disposition'] = {'status': 'BLOCKED'}
    with pytest.raises(QuantError) as exc:
        validate_casefile(broken)
    assert 'reason' in exc.value.reason


def test_tampered_hash_is_not_written(tmp_path: Path):
    casefile = build_casefile(**inputs())
    casefile['gates'] = {**casefile['gates'], 'status': 'FALSIFIED'}
    with pytest.raises(QuantError) as exc:
        write_casefile(casefile, tmp_path / 'sleeve')
    assert exc.value.status == 'INVALID_EVIDENCE'
    assert not (tmp_path / 'sleeve').exists()


def test_rejected_attempt_appends_one_entry_and_no_artifact(tmp_path: Path):
    spec = make_spec()
    record_attempt(tmp_path, spec=spec, market_class=spec.market_classes[0],
                   event='qualification', status='REJECTED',
                   reason='financing UNKNOWN_NOT_MODELLED')
    entries = read_trials(tmp_path)
    assert len(entries) == 1
    assert entries[0]['status'] == 'REJECTED'
    assert entries[0]['holdout_access'] is False
    assert [p.name for p in tmp_path.iterdir()] == ['trial_ledger.jsonl']


def test_gate_change_after_an_outcome_is_a_new_trial_that_invalidates_it(tmp_path: Path):
    spec = make_spec()
    record_attempt(tmp_path, spec=spec, market_class=spec.market_classes[0],
                   event='outcome', status='QUALIFIED')
    outcome = read_trials(tmp_path)[-1]
    record = classify_gate_change(tmp_path, selection_family_id='af30_time_series',
                                  spec_hash=spec.spec_hash,
                                  change={'minimum_validation_net_sharpe': 0.30})
    assert record['event'] == 'new_trial'
    assert record['invalidates'] == [outcome['record_hash']]
    assert active_outcomes(tmp_path, 'af30_time_series') == []


def test_gate_change_before_any_outcome_is_a_predeclared_variation(tmp_path: Path):
    spec = make_spec()
    record = classify_gate_change(tmp_path, selection_family_id='af30_time_series',
                                  spec_hash=spec.spec_hash,
                                  change={'minimum_validation_net_sharpe': 0.30})
    assert record['event'] == 'predeclared_variation'
    assert record['invalidates'] == []


def test_ledger_tampering_is_detected(tmp_path: Path):
    spec = make_spec()
    record_attempt(tmp_path, spec=spec, market_class=spec.market_classes[0],
                   event='outcome', status='FALSIFIED')
    path = tmp_path / 'trial_ledger.jsonl'
    path.write_text(path.read_text().replace('FALSIFIED', 'QUALIFIED'))
    with pytest.raises(QuantError) as exc:
        read_trials(tmp_path)
    assert exc.value.status == 'INVALID_EVIDENCE'
