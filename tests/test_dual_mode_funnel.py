"""Four-stage integration: use actual native features, diagnostics and execution."""
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from src.data_vault import DataVault, PanelBuilder
from src.engine.common import QuantError, read_json
from src.engine.feature_compiler import FeatureCompiler
from src.engine.funnel import ResearchFunnel
from src.engine.spec_parser import CandidateSpec, export_spec, parse_spec
from src.workbench import Workbench
from tests.dual_mode_fixtures import make_panel
from tests.dual_mode_fixtures import test_spec as spec_fixture


def positive_fixture(tmp_path):
    """Synthetic known edge: funding[t] predicts the next full price bar.

    This is an adversarial plumbing fixture, not a claimed real-market strategy.
    Zero costs and a loose beta ceiling are explicit synthetic-test settings.
    """
    rng = np.random.default_rng(99)
    start = datetime(2025, 9, 1, tzinfo=UTC)
    hours = (datetime(2026, 1, 4, tzinfo=UTC) - start).days * 24
    records, events = [], []
    for index, symbol in enumerate(('BTCUSDT_PERP', 'ETHUSDT_PERP', 'A_PERP', 'B_PERP')):
        price, previous = 100. + index * 20, 0.
        for h in range(hours):
            timestamp = start + timedelta(hours=h)
            opening = price
            price *= 1 + .0005 * previous + float(rng.normal(0., .00005))
            pressure = float(rng.normal())
            rate = pressure * 1e-7
            records.append({'timestamp': timestamp, 'symbol': symbol, 'open': opening,
                            'high': max(opening, price) * 1.002, 'low': min(opening, price) * .998,
                            'close': price, 'volume': 1000., 'carry_rate': rate,
                            'spread_bps': 0., 'session_id': timestamp.strftime('%Y-%m-%d'),
                            'bar_in_session': h % 24, 'is_tradable': True})
            events.append({'timestamp': timestamp, 'symbol': symbol, 'funding_rate': rate,
                           'mark_price': opening, 'funding_interval_hours': 1})
            previous = pressure
    panel = pl.DataFrame(records)
    funding = pl.DataFrame(events)
    output = tmp_path / 'vault'
    PanelBuilder(tmp_path / 'raw', output).publish(panel, funding=funding,
                                                  provenance={'source_spec_status': 'synthetic_test'})
    spec = spec_fixture(output, start).model_dump(mode='json')
    spec['windows']['train']['end'] = '2025-11-01T00:00:00Z'
    spec['windows']['validation']['start'] = '2025-11-01T00:00:00Z'
    spec['features'][1]['expr'] = {'op': 'col', 'name': 'carry_rate'}
    spec['features'][2]['expr'] = {'op': 'neg', 'args': [{'op': 'col', 'name': 'carry_rate'}]}
    spec['label_horizon_bars'] = 1
    spec['allocation']['rebalance_bars'] = 1
    spec['gates']['maximum_abs_beta'] = 2.0
    spec['gates']['minimum_daily_observations'] = 30
    spec['gates']['minimum_ic_observations'] = 100
    spec['assumptions'] = ['Synthetic predictive generator, zero test fees, beta ceiling 2; not a historical alpha claim.']
    return CandidateSpec.model_validate(spec)


def test_stage4_claim_with_explicit_synthetic_dsr_stub(tmp_path, monkeypatch):
    # Stage 4 exercises the real native broker, receipt verification and one-shot
    # claim. Its DSR is a declared synthetic stub, NOT a historical promotion.
    # The separate negative test below asserts that genuine single-trial
    # selection evidence cannot unlock a protected evaluation.
    from src.oracle import stage3_falsifier

    def synthetic_selection_dsr(candidate, others, periods_per_year, *, historical_trial_count=0):
        return {'status': 'COMPUTED', 'probability': 1.0,
                'has_adequate_sample': True, 'scope': 'test-stub-only',
                'n_trials_aligned': 10, 'n_trials_raw': 10, 'n_trials_effective': 10.0}

    monkeypatch.setattr(stage3_falsifier, 'scoped_dsr', synthetic_selection_dsr)
    spec = positive_fixture(tmp_path)
    log = tmp_path / 'logs'
    result = ResearchFunnel(run_log=log, isolate=False).run(spec)
    assert result['status'] == 'HOLDOUT_EVALUATED', result
    assert [result['stages'][str(i)]['status'] for i in (1, 2, 3)] == ['PASS'] * 3
    assert result['holdout_access'] is True
    assert result['stages']['4']['metrics']['independent_accounting']['status'] == 'PASS'
    output = Path(result['output_path'])
    vault = DataVault(spec.panel_root, run_log=log, receipt_dir=output)
    with pytest.raises(QuantError, match='already reserved'):
        vault.unlock_holdout(spec.candidate_id, spec.spec_hash)
    claim = read_json(log / '_holdout_claims' / (result['holdout_claim'] + '.json'))
    with pytest.raises(QuantError, match='already released'):
        vault.load_holdout(claim)
    receipt = output / 'stage2_evidence.json'
    receipt.write_text('{}')
    with pytest.raises(QuantError) as rejected:
        vault.unlock_holdout(spec.candidate_id, spec.spec_hash)
    assert rejected.value.status == 'HOLDOUT_DENIED'


def test_native_single_trial_dsr_never_unlocks_holdout(tmp_path):
    spec = positive_fixture(tmp_path)
    log = tmp_path / 'logs'
    result = ResearchFunnel(run_log=log, isolate=False).run(spec)
    assert result['stages']['2']['status'] == 'PASS'
    assert result['status'] == 'INCONCLUSIVE_STAGE_3'
    assert result['stages']['3']['splits']['train']['dsr']['status'] == 'INCONCLUSIVE'
    assert result['holdout_access'] is False
    assert not (log / '_holdout_claims').exists()


def test_stage2_falsification_cli_exits_zero_without_stage3(tmp_path):
    panel = make_panel(hours=240, dynamic=True)
    output = tmp_path / 'vault'
    PanelBuilder(tmp_path / 'raw', output).publish(panel, provenance={'source_spec_status': 'synthetic_test'})
    spec = spec_fixture(output).model_dump(mode='json')
    spec['gates']['minimum_ic'] = 1.0  # frozen requirement for perfect IC rejects this noisy fixture
    candidate = CandidateSpec.model_validate(spec)
    path = export_spec(candidate, tmp_path / 'candidate.yaml')
    cli = Path(__file__).resolve().parents[1] / 'scripts' / 'quant.py'
    process = subprocess.run([sys.executable, str(cli), 'run', str(path), '--run-log', str(tmp_path / 'logs')],
                             text=True, capture_output=True, timeout=90, check=False)
    assert process.returncode == 0, process.stdout + process.stderr
    result = json.loads(process.stdout)
    assert result['status'] == 'FALSIFIED_STAGE_2'
    case = read_json(Path(result['casefile']))
    assert '3' not in case['stages'] and not case['holdout_access']
    assert not (tmp_path / 'logs' / '_holdout_claims').exists()


def test_workbench_declarative_export_and_no_holdout(tmp_path):
    output = tmp_path / 'vault'
    PanelBuilder(tmp_path / 'raw', output).publish(make_panel(hours=24 * 16, dynamic=True),
                                                  provenance={'source_spec_status': 'synthetic_test'})
    spec = spec_fixture(output)
    wb = Workbench(spec, run_log=tmp_path / 'logs', isolate=False)
    data = wb.load(end='2026-10-01')
    assert data['timestamp'].max() < datetime(2026, 1, 1, tzinfo=UTC)
    wb.features()
    report = wb.ic()
    assert 'report' in report
    saved = wb.export_yaml(tmp_path / 'thesis_candidate.yaml')
    assert parse_spec(saved).spec_hash == spec.spec_hash


def test_workbench_python_feature_exports_hashed_replayable_artifact(tmp_path):
    output = tmp_path / 'vault'
    PanelBuilder(tmp_path / 'raw', output).publish(make_panel(hours=40, dynamic=True),
                                                  provenance={'source_spec_status': 'synthetic_test'})
    spec = spec_fixture(output)
    compiler = FeatureCompiler(spec)
    def custom(frame):
        return compiler(frame).with_columns((pl.col('candidate') * 2).alias('candidate'))
    wb = Workbench(spec, run_log=tmp_path / 'logs', isolate=True)
    first = wb.features(custom)
    path = wb.export_yaml(tmp_path / 'exported' / 'thesis_candidate.yaml')
    exported = parse_spec(path)
    assert exported.python_feature_artifact is not None
    replay = Workbench(path, run_log=tmp_path / 'replay', isolate=True)
    assert replay.features().equals(first)
    (path.parent / exported.python_feature_artifact.path).write_bytes(b'tampered')
    with pytest.raises(QuantError, match='changed'):
        Workbench(path, run_log=tmp_path / 'tampered').features()
