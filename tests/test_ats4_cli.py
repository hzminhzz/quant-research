"""ATS-4 public CLI behavior without market-data access."""
from __future__ import annotations

import json
from pathlib import Path

from scripts import quant


def test_event_candidate_validates_through_public_cli(capsys):
    candidate = Path(__file__).resolve().parents[1] / 'config/candidates/ats4_m8_n8_cash.yaml'
    assert quant.main(['validate', str(candidate)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'VALID_SPEC'
    assert report['protocol'] == 'event'
    assert report['candidate_id'] == 'm8_n8_cash_session_v7'


def test_event_partial_qualification_is_not_an_engineering_exit(capsys, monkeypatch, tmp_path):
    candidate = Path(__file__).resolve().parents[1] / 'config/candidates/ats4_m8_n8_cash.yaml'
    report = {'status': 'PARTIALLY_QUALIFIED', 'candidate_id': 'm8_n8_cash_session_v7',
              'output_path': str(tmp_path / 'event'), 'holdout_access': False,
              'stages': {'event': {'status': 'PARTIALLY_QUALIFIED'}}}
    monkeypatch.setattr(quant.ResearchFunnel, 'run', lambda self, spec: report)
    assert quant.main(['run', str(candidate), '--run-log', str(tmp_path)]) == 3
    output = json.loads(capsys.readouterr().out)
    assert output['status'] == 'PARTIALLY_QUALIFIED'
    assert output['holdout_access'] is False
    assert output['casefile'] == str(tmp_path / 'event' / 'casefile.json')


def test_cli_dispatches_typed_event_through_real_funnel(capsys, monkeypatch, tmp_path):
    from src.engine import event_protocol

    candidate = Path(__file__).resolve().parents[1] / 'config/candidates/ats4_m8_n8_cash.yaml'
    seen = []

    def bounded_evaluation(spec, *, output_dir):
        seen.append((spec.strategy_id, str(output_dir)))
        return {'status': 'PARTIALLY_QUALIFIED', 'holdout_access': False}

    monkeypatch.setattr(event_protocol, 'run_m8_n8_event', bounded_evaluation)
    code = quant.main(['run', str(candidate), '--run-log', str(tmp_path)])
    assert code == 3
    report = json.loads(capsys.readouterr().out)
    assert seen and seen[0][0] == 'm8_n8_cash_session_v7'
    assert report['holdout_access'] is False
    assert Path(report['casefile']).is_file()
    assert 'completed' in (tmp_path / 'trial_ledger.jsonl').read_text()


def test_event_cli_never_rebuilds_frozen_source(capsys, monkeypatch, tmp_path):
    candidate = Path(__file__).resolve().parents[1] / 'config/candidates/ats4_m8_n8_cash.yaml'

    def forbidden(*args, **kwargs):
        raise AssertionError('immutable event source must not be rebuilt')

    monkeypatch.setattr(quant.PanelBuilder, 'build', forbidden)
    assert quant.main(['run', str(candidate), '--run-log', str(tmp_path), '--build-if-missing']) == 2
    assert json.loads(capsys.readouterr().err)['status'] == 'INVALID_SPEC'
