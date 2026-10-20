"""End-to-end contract for remotely trained cross-sectional model artifacts.

These are synthetic plumbing tests. They are NOT evidence of market performance.
The Colab CLI is faked only at the transport boundary; feature compilation,
serialized prediction, the bwrap worker, Stage 1 causality and Stage 2 diagnostics
are the real implementations.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import cloudpickle
import numpy as np
import polars as pl
import pytest

from src.data_vault import DataVault, PanelBuilder
from src.engine.colab_trainer import ColabTrainer
from src.engine.common import QuantError, file_hash
from src.engine.default_train_script import build_and_train
from src.engine.feature_compiler import (
    FeatureCompiler,
    ModelFeatureContract,
    compose_model_output,
    composed_model_pipeline,
)
from src.engine.funnel import ResearchFunnel
from src.engine.isolation import feature_function
from src.engine.spec_parser import (
    CandidateSpec,
    PythonFeatureArtifact,
    export_spec,
    parse_spec,
)
from src.workbench import Workbench
from tests.dual_mode_fixtures import make_panel

ROOT = Path(__file__).resolve().parents[1]


def _panel() -> pl.DataFrame:
    """55 days of hourly, four-symbol synthetic bars: enough for 24h labels."""
    return make_panel(hours=24 * 55, start=datetime(2025, 10, 1, tzinfo=UTC), dynamic=True)


def _publish_vault(tmp_path: Path) -> tuple[Path, pl.DataFrame]:
    panel = _panel()
    output = tmp_path / 'vault'
    PanelBuilder(tmp_path / 'raw', output).publish(
        panel, provenance={'source_spec_status': 'synthetic_test'})
    return output, panel


def _spec(panel_root: Path) -> CandidateSpec:
    return CandidateSpec.model_validate({
        'candidate_id': 'synthetic_remote_lgb_contract',
        'selection_family_id': 'synthetic-remote-lgb-family',
        'source_spec_status': 'synthetic_test',
        'thesis': 'Synthetic remote model contract fixture; not a market thesis.',
        'panel_root': str(panel_root),
        'windows': {
            'train': {'start': '2025-10-03T00:00:00Z', 'end': '2025-11-10T00:00:00Z'},
            'validation': {'start': '2025-11-10T00:00:00Z', 'end': '2025-11-25T00:00:00Z'},
            'protected': {'start': '2026-01-01T00:00:00Z', 'end': '2026-01-05T00:00:00Z'},
        },
        'features': [
            {'name': 'lgb_signal', 'expr': {'op': 'col', 'name': 'close'}},
            {'name': 'baseline_mom', 'expr': {
                'op': 'pct_change', 'periods': 24,
                'args': [{'op': 'col', 'name': 'close'}]}},
            {'name': 'atr_24h', 'native': 'atr', 'params': {'period': 24}},
        ],
        'signal': 'lgb_signal',
        'baseline': 'baseline_mom',
        'allocation': {'long_count': 1, 'short_count': 1, 'rebalance_bars': 24,
                       'atr_feature': 'atr_24h', 'atr_multiple': 3.0},
        'universe': {'top_n': 4, 'minimum_assets': 4, 'lookback_bars': 24,
                     'minimum_history_bars': 24},
        'costs': {'commission_bps_one_way': 0, 'spread_bps': 0,
                  'slippage_bps_one_way': 0},
        'gates': {'minimum_ic': 1.0, 'minimum_ic_observations': 20,
                  'minimum_hac_t': 2.0, 'require_baseline_ic_improvement': True},
        'label_horizon_bars': 24,
        'bar_seconds': 3600,
        'seed': 42,
    })


def _train_default(tmp_path: Path, trainer: ColabTrainer, *, name: str = 'model') -> tuple[Path, dict]:
    arrow = tmp_path / f'{name}.arrow'
    trainer.prepare_training_data(arrow)
    meta = trainer.training_contract()
    meta_path = tmp_path / f'{name}.meta.json'
    meta_path.write_text(json.dumps(meta, sort_keys=True), encoding='utf-8')
    model = tmp_path / f'{name}.pkl'
    build_and_train(input_data=arrow, output_model=model, meta_data=meta_path)
    return model, meta


def _install_artifact(run_log: Path, model: Path, trainer: ColabTrainer) -> PythonFeatureArtifact:
    sha = file_hash(model)
    folder = run_log / 'python_features'
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / f'{sha}.pkl'
    destination.write_bytes(model.read_bytes())
    contract_file = trainer.write_model_contract(sha)
    return PythonFeatureArtifact(path=f'python_features/{sha}.pkl', sha256=sha,
                                 contract_sha256=file_hash(contract_file))


# 1. Real LightGBM training, local process, no Colab credentials.
def test_default_lightgbm_trains_and_returns_declared_signal(tmp_path: Path):
    panel_root, _ = _publish_vault(tmp_path)
    spec = _spec(panel_root)
    trainer = ColabTrainer(spec, run_log=tmp_path / 'logs')
    model_path, meta = _train_default(tmp_path, trainer)

    assert model_path.is_file() and model_path.stat().st_size > 0
    assert meta['signal'] == 'lgb_signal'
    predictor = cloudpickle.loads(model_path.read_bytes())
    compiled = FeatureCompiler(spec)(make_panel(hours=120))
    output = predictor(compiled)
    assert output.columns == ['timestamp', 'symbol', 'lgb_signal']
    assert output.height == compiled.height
    assert output['lgb_signal'].is_not_null().all()
    assert output['lgb_signal'].is_finite().all()
    assert 'lgb_return_pred' not in output.columns


# 2. Fake Colab CLI only: real data preparation, real local training, portable export.
def test_cli_exports_portable_hashed_model_sidecar_from_another_directory(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    panel_root, _ = _publish_vault(tmp_path)
    spec = _spec(panel_root)
    template = tmp_path / 'template.yaml'
    export_spec(spec, template)
    run_log = tmp_path / 'logs'
    output_yaml = tmp_path / 'elsewhere' / 'trained_candidate.yaml'

    uploads: dict[str, bytes] = {}
    seen_download = {}

    def fake_run(command, *args, **kwargs):
        verb = command[1] if len(command) > 1 else ''
        if verb == 'upload':
            source, remote = Path(command[-2]), command[-1]
            uploads[remote] = source.read_bytes()
        elif verb == 'download':
            destination = Path(command[-1])
            arrow = tmp_path / 'fake-upload-train.arrow'
            arrow.write_bytes(uploads['/content/train.arrow'])
            meta = tmp_path / 'fake-upload-meta.json'
            meta.write_bytes(uploads['/content/train_meta.json'])
            build_and_train(input_data=arrow, output_model=destination, meta_data=meta)
            seen_download['source'] = arrow
            seen_download['meta'] = json.loads(meta.read_text())
        return subprocess.CompletedProcess(command, returncode=0, stdout='OK', stderr='')

    native_run, native_which = subprocess.run, shutil.which
    monkeypatch.setattr('shutil.which', lambda name: '/bin/sh')
    monkeypatch.setattr(subprocess, 'run', fake_run)

    original_load = DataVault.load
    loads: list[tuple[object, object]] = []

    def recording_load(self, start=None, end=None, **kwargs):
        loads.append((start, end))
        return original_load(self, start, end, **kwargs)

    monkeypatch.setattr(DataVault, 'load', recording_load)

    from scripts.quant import main
    code = main([
        'train-remote', str(template), '--run-log', str(run_log),
        '-o', str(output_yaml),
    ])
    assert code == 0

    # Only the training partition was ever requested or uploaded.
    assert loads and all(end == spec.windows.train.end for _, end in loads)
    assert '/content/train.arrow' in uploads
    uploaded = pl.read_ipc(tmp_path / 'fake-upload-train.arrow')
    assert uploaded['timestamp'].max() < spec.windows.train.end
    assert uploaded.height > 0
    assert seen_download['meta']['train_end'] == spec.windows.train.end.isoformat()

    # Export landed outside run_log and re-parses without depending on run_log CWD.
    parsed = parse_spec(output_yaml)
    assert parsed.python_feature_artifact is not None
    artifact = parsed.python_feature_artifact
    artifact_file = output_yaml.parent / artifact.path
    assert artifact_file.is_file()
    assert file_hash(artifact_file) == artifact.sha256
    assert not artifact.path.startswith('python_features/')
    sidecar = artifact_file.with_suffix('.json')
    assert sidecar.is_file()
    contract = json.loads(sidecar.read_text())
    assert contract['schema'] == 'model_feature_contract_v1'
    assert contract['model_sha256'] == artifact.sha256
    assert artifact.contract_sha256 == file_hash(sidecar)
    assert contract['signal'] == parsed.signal
    assert contract['baseline'] == parsed.baseline
    assert contract['atr_feature'] == parsed.allocation.atr_feature
    assert contract['training_provenance']['training_data_sha256'] == hashlib.sha256(
        uploads['/content/train.arrow']).hexdigest()
    assert contract['training_provenance']['training_script_sha256'] == file_hash(
        ROOT / 'src/engine/default_train_script.py')
    # The exported spec is self-consistent at its own location.
    assert parsed._base_dir == output_yaml.parent.resolve()

    # Complete the transport -> remote-trained model -> portable exported YAML
    # -> genuine bwrap causal Stage 1 -> genuine native Stage 2 chain.
    # Restore the real subprocess/bwrap machinery; only Colab transport was mocked.
    monkeypatch.setattr(subprocess, 'run', native_run)
    monkeypatch.setattr(shutil, 'which', native_which)
    native_case = ResearchFunnel(run_log=tmp_path / 'native_replay', isolate=True).run(
        output_yaml, development_only=True)
    assert native_case['stages']['1']['status'] == 'PASS'
    assert native_case['stages']['2']['status'] == 'FALSIFIED_STAGE_2'
    assert set(native_case['stages']['2']['diagnostics']) == {'lgb_signal', 'baseline_mom'}
    assert native_case['holdout_access'] is False


# 3. Real bwrap Stage 1 and real native Stage 2, with train/validation separation.
def test_trained_artifact_passes_real_stage1_and_reaches_stage2(tmp_path: Path):
    panel_root, _ = _publish_vault(tmp_path)
    spec = _spec(panel_root)
    run_log = tmp_path / 'logs'
    trainer = ColabTrainer(spec, run_log=run_log)
    model, _ = _train_default(tmp_path, trainer)
    training_rows = trainer.prepare_training_data(tmp_path / 'training_count.arrow')['rows']
    artifact = _install_artifact(run_log, model, trainer)
    frozen = spec.model_copy(update={'python_feature_artifact': artifact})
    frozen._base_dir = run_log

    result = ResearchFunnel(run_log=run_log, isolate=True).run(frozen, development_only=True)

    assert result['stages']['1']['status'] == 'PASS'
    assert set(result['stages']['1']['feature_columns']) >= {
        'lgb_signal', 'baseline_mom', 'atr_24h', 'in_pit_universe'}
    assert result['stages']['1']['pit_membership_rows'] > 0
    # Stage 1 loaded train+validation development rows; only the train prefix was uploaded.
    assert result['stages']['1']['panel_rows'] > training_rows
    # Demand a genuine native IC/HAC evaluation, not merely an inconclusive
    # Stage 2 invocation. The deliberate IC=1 gate falsifies this test model.
    assert result['stages']['2']['status'] == 'FALSIFIED_STAGE_2'
    assert result['stages']['2']['observations'] >= spec.gates.minimum_ic_observations
    assert set(result['stages']['2']['diagnostics']) == {'lgb_signal', 'baseline_mom'}
    assert set(result['stages']['2']['checks']) == {
        'candidate_mean_ic', 'candidate_hac_t', 'baseline_increment'}
    assert result['status'] == 'FALSIFIED_STAGE_2'
    assert result['holdout_access'] is False


# 4. Artifact bytes are immutable once referenced by an exported spec.
def test_tampered_exported_model_artifact_is_rejected(tmp_path: Path):
    run_log = tmp_path / 'logs'
    folder = run_log / 'python_features'
    folder.mkdir(parents=True)
    blob = b'not a real model, only immutable bytes'
    sha = hashlib.sha256(blob).hexdigest()
    path = folder / f'{sha}.pkl'
    path.write_bytes(blob)
    spec = _spec(tmp_path / 'unused')
    trainer = ColabTrainer(spec, run_log=run_log)
    sidecar = trainer.write_model_contract(sha)
    path.write_bytes(blob + b' tampered')
    frozen = spec.model_copy(update={
        'python_feature_artifact': PythonFeatureArtifact(
            path=f'python_features/{sha}.pkl', sha256=sha,
            contract_sha256=file_hash(sidecar))})
    frozen._base_dir = run_log
    with pytest.raises(QuantError, match='changed'):
        feature_function(frozen)

    # Restoring the model cannot bypass a modified contract sidecar.
    path.write_bytes(blob)
    sidecar.write_bytes(sidecar.read_bytes() + b' ')
    with pytest.raises(QuantError, match='contract sidecar is missing or changed'):
        feature_function(frozen)


# 5. Deterministic training identity and strict no-validation training input.
def test_training_is_reproducible_and_never_uses_validation_rows(tmp_path: Path):
    panel_root, panel = _publish_vault(tmp_path)
    spec = _spec(panel_root)
    trainer = ColabTrainer(spec, run_log=tmp_path / 'logs')
    first, first_meta = _train_default(tmp_path, trainer, name='first')
    second, second_meta = _train_default(tmp_path, trainer, name='second')

    assert first_meta == second_meta
    # The closure serialization is stable on the pinned local environment;
    # the content address matches across separate fits with the same seed/data.
    assert file_hash(first) == file_hash(second)
    first_predictor = cloudpickle.loads(first.read_bytes())
    second_predictor = cloudpickle.loads(second.read_bytes())
    frame = make_panel(hours=120)
    compiled = FeatureCompiler(spec)(frame)
    one = first_predictor(compiled)['lgb_signal'].to_numpy()
    two = second_predictor(compiled)['lgb_signal'].to_numpy()
    assert np.array_equal(one, two)

    train_arrow = tmp_path / 'boundary.arrow'
    trainer.prepare_training_data(train_arrow)
    uploaded = pl.read_ipc(train_arrow)
    assert uploaded['timestamp'].max() < spec.windows.train.end
    validation = panel.filter(pl.col('timestamp') >= spec.windows.validation.start)
    assert validation.height > 0
    assert uploaded.filter(pl.col('timestamp') >= spec.windows.validation.start).is_empty()


# 6. Contract rejects wrong names, changed rows, and rogue canonical values.
def test_model_output_contract_rejects_wrong_name_and_row_identity(tmp_path: Path):
    spec = _spec(tmp_path / 'unused')
    compiled = FeatureCompiler(spec)(make_panel(hours=60))
    payload = {
        'schema': 'model_feature_contract_v1',
        'model_sha256': '0' * 64,
        'signal': 'lgb_signal',
        'baseline': 'baseline_mom',
        'atr_feature': 'atr_24h',
        'row_keys': ['timestamp', 'symbol'],
        'canonical_columns': list(compiled.columns[:12]),
        'predictor_output': 'lgb_signal',
        'legacy_output_aliases': {'lgb_return_pred': 'lgb_signal'},
    }
    contract = ModelFeatureContract.from_payload(payload, spec, '0' * 64)
    keys = compiled.select('timestamp', 'symbol')
    valid = keys.with_columns(pl.lit(0.0).alias('lgb_signal'))
    assert compose_model_output(compiled, valid, contract).columns == compiled.columns

    with pytest.raises(QuantError, match='unexpected predictor output'):
        compose_model_output(compiled, keys.with_columns(pl.lit(0.0).alias('wrong_name')), contract)
    with pytest.raises(QuantError, match='row identity'):
        compose_model_output(compiled, valid.head(-1), contract)
    tampered_close = keys.with_columns(
        pl.lit(0.0).alias('lgb_signal'), pl.lit(0.0).alias('close'))
    with pytest.raises(QuantError, match='canonical column close'):
        compose_model_output(
            compiled.with_columns(pl.lit(1.0).alias('close')), tampered_close, contract)
    # Documented legacy output is normalized explicitly, never by guessing.
    legacy = keys.with_columns(pl.lit(0.0).alias('lgb_return_pred'))
    normalized = compose_model_output(compiled, legacy, contract)
    assert 'lgb_signal' in normalized.columns and 'lgb_return_pred' not in normalized.columns


def test_composed_model_owns_signal_without_compiling_placeholder(tmp_path: Path):
    spec = _spec(tmp_path / 'unused')
    payload = spec.model_dump(mode='json')
    # A remote model output is not a native feature and must not require one.
    payload['features'][0] = {'name': 'lgb_signal', 'native': 'nonexistent_model_primitive'}
    spec = CandidateSpec.model_validate(payload)
    trainer = ColabTrainer(spec, run_log=tmp_path / 'logs')
    model_hash = '3' * 64
    contract = trainer.model_contract(model_hash)
    predictor = lambda frame: frame.select('timestamp', 'symbol').with_columns(
        pl.lit(0.02).alias('lgb_signal'))
    composed = composed_model_pipeline(spec, cloudpickle.dumps(predictor), contract, model_hash)
    result = composed(make_panel(hours=120))
    assert result.height == 120 * 4
    assert set(result.columns) >= {
        'timestamp', 'symbol', 'lgb_signal', 'baseline_mom', 'atr_24h',
        'in_pit_universe', 'open', 'close', 'is_tradable'}
    assert result['lgb_signal'].eq(0.02).all()
    assert result['in_pit_universe'].sum() > 0


def test_workbench_colab_binding_resolves_artifact_from_run_log(tmp_path: Path, monkeypatch):
    panel_root, _ = _publish_vault(tmp_path)
    spec = _spec(panel_root)
    run_log = tmp_path / 'logs'
    trainer = ColabTrainer(spec, run_log=run_log)
    source = run_log / 'python_features' / 'fixture.pkl'
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b'fixture bytes - never unpickled by host')
    sha = file_hash(source)
    artifact_file = source.with_name(f'{sha}.pkl')
    artifact_file.write_bytes(source.read_bytes())
    sidecar = trainer.write_model_contract(sha)
    artifact = PythonFeatureArtifact(path=f'python_features/{sha}.pkl', sha256=sha,
                                     contract_sha256=file_hash(sidecar))

    def fake_train(self, *args, **kwargs):
        return artifact, self.spec.model_copy(update={'python_feature_artifact': artifact})

    monkeypatch.setattr(ColabTrainer, 'train', fake_train)
    workbench = Workbench(spec, run_log=run_log)
    workbench.train_colab()
    assert workbench.spec._base_dir == run_log.resolve()
    assert feature_function(workbench.spec) is not None
    exported = workbench.export_yaml(tmp_path / 'exported' / 'workbench_colab.yaml')
    replay = parse_spec(exported)
    assert replay.python_feature_artifact.contract_sha256 == file_hash(
        exported.parent / replay.python_feature_artifact.path.replace('.pkl', '.json'))


def test_legacy_python_artifact_hash_serialization_is_unchanged():
    legacy = PythonFeatureArtifact(path='old/features.pkl', sha256='0' * 64)
    assert legacy.model_dump(mode='json') == {
        'path': 'old/features.pkl', 'sha256': '0' * 64}
