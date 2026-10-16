import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from src.engine.event_protocol import (
    SOURCE_SHA256,
    _development_data,
    independent_signal_oracle,
)
from src.oracle.research_protocols import parse_research_spec

ROOT = Path(__file__).resolve().parents[1]


def test_independent_oracle_uses_strict_completed_prior_50_high(monkeypatch):
    import src.engine.event_protocol as protocol

    monkeypatch.setattr(protocol, 'cash_session_signal_eligible', lambda *_a, **_k: True)
    start = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    rows = []
    for index in range(52):
        high = 101.0 if index == 51 else 100.0
        close = 101.0 if index == 51 else 100.0
        rows.append({'timestamp': start + timedelta(minutes=30 * index), 'symbol': 'x',
                     'open': close, 'high': high, 'low': close - 1, 'close': close, 'volume': 1.0})
    data = pl.DataFrame(rows)
    # Equality at row 50 is not a signal; row 51 exceeds the completed prior window.
    assert independent_signal_oracle(data) == [start + timedelta(minutes=30 * 51)]


def test_source_authority_mismatch_fails_before_parquet_decode(monkeypatch):
    import src.engine.event_protocol as protocol

    monkeypatch.setattr(protocol, 'SOURCE_SHA256', '0' * 64)
    with pytest.raises(ValueError, match='frozen authority changed'):
        _development_data()


def test_event_factory_skips_all_cross_sectional_gates_and_reconciles_history(tmp_path, monkeypatch):
    import src.engine.funnel as funnel_module
    import src.engine.signal_allocator as allocator_module
    import src.oracle.stage2_diagnostic as stage2_module
    import src.oracle.stage3_falsifier as stage3_module

    def forbidden(*_args, **_kwargs):
        raise AssertionError('cross-sectional-only gate was invoked for M8 event protocol')

    monkeypatch.setattr(stage2_module, 'stage2', forbidden)
    monkeypatch.setattr(stage3_module, 'stage3', forbidden)
    monkeypatch.setattr(allocator_module, 'allocate', forbidden)
    monkeypatch.setattr(funnel_module, 'stage2', forbidden)
    monkeypatch.setattr(funnel_module, 'stage3', forbidden)
    monkeypatch.setattr(funnel_module, 'allocate', forbidden)
    result = funnel_module.ResearchFunnel(run_log=tmp_path, isolate=False).run(
        ROOT / 'config/candidates/ats4_m8_n8_cash.yaml')

    assert result['status'] == 'PARTIALLY_QUALIFIED'
    evidence = result['stages']['event']
    assert evidence['parity']['status'] == 'PASS'
    assert evidence['economics_status'] == 'FALSIFIED_NONPOSITIVE_GROSS_OR_BASE_NET_EXPECTANCY'
    assert evidence['cost_status'] == 'ASSUMED_NOT_QUALIFIED'
    assert evidence['mark_status'].startswith('30M_SOURCE_CLOSE_MARKS_RECONCILED')
    assert evidence['source_bridge']['source_sha256'] == SOURCE_SHA256
    assert evidence['source_bridge']['protected_read'] is False
    assert evidence['eligible_signal_count'] == 1127
    assert evidence['executed_signal_count'] == 805
    assert evidence['execution_count'] == [805, 805, 805]
    assert result['holdout_access'] is False
    artifacts = evidence['native_artifacts']
    assert artifacts['orders_1x.parquet']['rows'] == 1610
    assert artifacts['accounting_1x.parquet']['rows'] == 57_504
    assert artifacts['portfolio_state_1x.parquet']['rows'] == 57_504
    assert artifacts['event_oracle.json']['candidate_signals'] == 1127
    assert artifacts['event_oracle.json']['executions'] == 805
    history = evidence['known_trial_history']
    assert len(history['known_attempts']) == 9
    assert len(history['trial_disclosure']['missing_outcome_ids']) == 1
    assert history['trial_disclosure']['unknown_count'] is None
    assert any(item['kind'] == 'freeze_only' and item['outcome'] is None
               for item in history['known_attempts'])
    assert sum(item['kind'] == 'preflight' for item in history['known_attempts']) == 2
    assert evidence['ats4_previous_attempt_lineage']['current_registration']['status'] == 'RUNNING'
    sleeves = evidence['sleeve_evidence']
    assert sleeves['status'] == 'DAILY_SLEEVE_BRIDGE_COMPLETE'
    assert sleeves['sample']['session_count'] == 1258
    assert sleeves['sample']['interpolated_marks'] is False
    assert sleeves['sample']['valuation_policy'].startswith('last actual native equity mark')
    assert sleeves['resampling']['same_indices_for_all_m8_cash_and_cost_cases'] is True
    assert all(row['native_daily_marks'] == 1258 for row in sleeves['native_scenarios'])
    assert sleeves['selection_adjustment'] == 'UNAVAILABLE_NOT_COMPUTED'
    assert artifacts['portfolio_sleeves.json']['sleeves'] == 4
    assert evidence['event_runtime_identity']['before'] == evidence['event_runtime_identity']['after']
    ledger = (tmp_path / 'trial_ledger.jsonl').read_text()
    assert 'registered' in ledger and 'completed' in ledger


def test_workbench_rejects_ic_for_event_without_loading_source(tmp_path, monkeypatch):
    import src.engine.event_protocol as protocol
    from src.workbench import Workbench

    def forbidden(*_args, **_kwargs):
        raise AssertionError('source load is not needed for an inapplicable IC request')

    monkeypatch.setattr(protocol, '_development_data', forbidden)
    workbench = Workbench(ROOT / 'config/candidates/ats4_m8_n8_cash.yaml', run_log=tmp_path)
    with pytest.raises(Exception, match='not an M8 event gate'):
        workbench.ic()


def test_workbench_load_features_and_export_share_typed_protocol(tmp_path):
    from src.workbench import Workbench

    workbench = Workbench(ROOT / 'config/candidates/ats4_m8_n8_cash.yaml', run_log=tmp_path)
    data = workbench.load()
    features = workbench.features()
    assert data.height == 57_504
    assert 'prior_high_50' in features.columns
    assert features['available_at'].min() == features['timestamp'].min() + timedelta(minutes=30)
    trial_events = [json.loads(line) for line in (tmp_path / 'trial_ledger.jsonl').read_text().splitlines()]
    feature_event = next(item for item in trial_events if item['event'] == 'workbench_features')
    assert len(feature_event['feature_set_sha256']) == 64
    assert feature_event['provider_versions']
    assert feature_event['checks']
    exported = workbench.export_yaml(tmp_path / 'event.yaml')
    assert parse_research_spec(exported).spec_hash == workbench.spec.spec_hash


def test_workbench_backtest_records_content_bound_artifacts(tmp_path, monkeypatch):
    from src.engine import event_protocol
    from src.workbench import Workbench

    def fake_run(_spec, *, output_dir):
        output_dir.mkdir(parents=True)
        (output_dir / 'event_evidence.json').write_text('{}')
        return {'status': 'PARTIALLY_QUALIFIED', 'native_artifacts': {'fills_1x.parquet': {'sha256': 'a' * 64}}}

    monkeypatch.setattr(event_protocol, 'run_m8_n8_event', fake_run)
    workbench = Workbench(ROOT / 'config/candidates/ats4_m8_n8_cash.yaml', run_log=tmp_path)
    result = workbench.backtest()
    assert result['status'] == 'PARTIALLY_QUALIFIED'
    trial_events = [json.loads(line) for line in (tmp_path / 'trial_ledger.jsonl').read_text().splitlines()]
    backtest_event = next(item for item in trial_events if item['event'] == 'workbench_backtest'
                          and item['status'] == 'PARTIALLY_QUALIFIED')
    assert len(backtest_event['evidence_sha256']) == 64
    assert backtest_event['artifacts']['fills_1x.parquet']['sha256'] == 'a' * 64
