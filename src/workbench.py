"""Interactive research using the same vault/compiler/oracles as the factory."""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import cloudpickle
import polars as pl
import yaml

from src.data_vault import DataVault
from src.engine.backtest_runner import run_native
from src.engine.common import (
    QuantError,
    append_trial,
    beneath,
    file_hash,
    runtime_identity,
    write_json,
)
from src.engine.feature_compiler import compile_and_verify
from src.engine.signal_allocator import allocate
from src.engine.spec_parser import (
    CandidateSpec,
    PythonFeatureArtifact,
    export_spec,
)
from src.oracle.research_protocols import (
    describe_research_protocol,
    parse_research_spec,
)
from src.oracle.stage2_diagnostic import stage2


class Workbench:
    """Load a typed candidate or exported YAML; development data requires no permits.

    Calls are recorded as exploratory evidence, not promotion. Custom Python
    callables run in a restricted subprocess by default. The host notebook is
    still trusted and can access its owner's files outside this API.
    """
    def __init__(self, spec: CandidateSpec | str | Path, *, run_log: str | Path = 'run_log',
                 isolate: bool = True):
        self.spec = parse_research_spec(spec)
        self._event = describe_research_protocol(self.spec).protocol == 'event'
        self.run_log, self.isolate = Path(run_log).resolve(), isolate
        self._vault = (None if self._event
                       else DataVault(self.spec.panel_root, run_log=self.run_log))  # no unlock receipts
        self.panel: pl.DataFrame | None = None
        self.feature_panel: pl.DataFrame | None = None
        self._event_feature_proof: dict | None = None
        self._custom_python = False

    def _record(self, action: str, status: str, **metadata):
        event = self._event
        record = {'candidate_id': self.spec.strategy_id if event else self.spec.candidate_id,
                  'selection_family_id': self.spec.strategy_id if event else self.spec.selection_family_id,
                  'spec_hash': self.spec.spec_hash, 'code_hash': runtime_identity(),
                  'event': f'workbench_{action}', 'status': status,
                  'panel_hash': self._vault.manifest_hash if self._vault else None,
                  'holdout_access': False, **metadata}
        if event:
            record['protocol'] = 'event'
        append_trial(self.run_log, record)

    def load(self, start=None, end=None) -> pl.DataFrame:
        if self._event:
            if start is not None or end is not None:
                self._record('load', 'REJECTED', reason='event protocol has one frozen development window')
                raise QuantError('INVALID_SPEC', 'M8 event protocol uses its frozen development window')
            from src.engine.event_protocol import _development_data
            try:
                self.panel, computation, _contract, authority = _development_data()
            except Exception as exc:
                status = exc.status if isinstance(exc, QuantError) else 'ENGINEERING_ERROR'
                self._record('load', status, reason=f'{type(exc).__name__}: {exc}')
                raise
            self.feature_panel = computation.data
            self._event_feature_proof = {
                'feature_set_sha256': computation.proof.feature_set_sha256,
                'input_sha256': computation.proof.input_sha256,
                'output_sha256': computation.proof.output_sha256,
                'provider_versions': computation.proof.provider_versions,
                'checks': computation.proof.checks,
            }
            self._record('load', 'COMPLETED', rows=self.panel.height, authorities=authority,
                         scope='development_only; protected_read=false')
            return self.panel
        self.panel = self._vault.load(start=start, end=end)
        self.feature_panel = None
        self._record('load', 'COMPLETED', rows=self.panel.height)
        return self.panel

    def features(self, definitions: list[dict] | Callable | None = None) -> pl.DataFrame:
        if self._event:
            if definitions is not None:
                self._record('features', 'REJECTED', reason='frozen event features cannot be overridden')
                raise QuantError('INVALID_SPEC', 'M8 event features are frozen')
            if self.panel is None:
                self.load()
            self._record('features', 'PASS', **(self._event_feature_proof or {}))
            return self.feature_panel
        if self.panel is None:
            self.load()
        if isinstance(definitions, list):
            payload = self.spec.model_dump(mode='json')
            payload['features'] = definitions
            payload['python_feature_artifact'] = None
            self.spec = CandidateSpec.model_validate(payload)
            definitions = None
        if callable(definitions):
            blob = cloudpickle.dumps(definitions)
            checksum = hashlib.sha256(blob).hexdigest()
            folder = self.run_log / 'python_features'
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / (checksum + '.pkl')
            if not path.exists():
                with path.open('xb') as handle:
                    handle.write(blob)
            if file_hash(path) != checksum:
                raise QuantError('INVALID_EVIDENCE', 'Archived Python feature bytes changed')
            self.spec = self.spec.model_copy(update={'python_feature_artifact': PythonFeatureArtifact(path=path.name, sha256=checksum)})
            self.spec._base_dir = folder
        self._custom_python = self.spec.python_feature_artifact is not None
        if self._custom_python and not self.isolate:
            raise QuantError('ISOLATION_UNAVAILABLE', 'Serialized Python features require isolation')
        self._record('features', 'STARTED', custom_python=self._custom_python)
        try:
            self.feature_panel, evidence = compile_and_verify(self.panel, self.spec, isolate=self.isolate)
            self._record('features', 'PASS', causal_evidence=evidence.to_dict())
            return self.feature_panel
        except Exception as exc:
            self._record('features', 'FAILED', reason=str(exc))
            raise

    def ic(self) -> dict:
        if self._event:
            self._record('ic', 'REJECTED', reason='IC is not applicable to event protocol')
            raise QuantError('PROTOCOL_NOT_APPLICABLE', 'Cross-sectional IC is not an M8 event gate')
        if self.feature_panel is None:
            self.features()
        self._record('ic', 'STARTED')
        try:
            report, series = stage2(self.feature_panel, self.spec)
            self._record('ic', report['status'], diagnostic=report)
            return {'report': report, 'series': series}
        except Exception as exc:
            self._record('ic', 'FAILED', reason=str(exc))
            raise

    def backtest(self):
        """Exploratory native backtest; does not claim factory-stage qualification."""
        if self._event:
            from src.engine.event_protocol import run_m8_n8_event

            folder = self.run_log / 'workbench' / self.spec.spec_hash / uuid4().hex
            self._record('backtest', 'STARTED', qualification='development historical parity only')
            try:
                result = run_m8_n8_event(self.spec, output_dir=folder)
                self._record('backtest', result['status'], evidence_path=str(folder.relative_to(self.run_log)),
                             evidence_sha256=file_hash(folder / 'event_evidence.json'),
                             artifacts=result.get('native_artifacts', {}),
                             qualification='PARTIALLY_QUALIFIED; historical costs assumed')
                return result
            except Exception as exc:
                status = exc.status if isinstance(exc, QuantError) else 'ENGINEERING_ERROR'
                folder.mkdir(parents=True, exist_ok=True)
                partial_artifacts = {str(path.relative_to(folder)): file_hash(path)
                                     for path in sorted(folder.rglob('*')) if path.is_file()
                                     and path.name != 'failure_evidence.json'}
                failure_path = folder / 'failure_evidence.json'
                write_json(failure_path, {'status': status, 'reason': f'{type(exc).__name__}: {exc}',
                                          'artifacts': partial_artifacts, 'holdout_access': False})
                self._record('backtest', status, evidence_path=str(folder.relative_to(self.run_log)),
                             evidence_sha256=file_hash(failure_path), artifacts=partial_artifacts,
                             reason=f'{type(exc).__name__}: {exc}')
                raise
        if self._vault.manifest.get('quality_summary', {}).get('execution_qualified') is False:
            raise QuantError('INCONCLUSIVE_STAGE_3',
                             'This is a price-only source with unknown spread and directional swap. '
                             'Use Workbench features()/ic(); native PnL needs a qualified cost/carry adapter.')
        if self.feature_panel is None:
            self.features()
        self._record('backtest', 'STARTED')
        try:
            funding = self._vault.load_funding(self.feature_panel['timestamp'].min(),
                                               self.spec.windows.protected.start)
            funding = funding.filter(pl.col('timestamp') <= self.feature_panel['timestamp'].max()) if funding.height else funding
            result = run_native(self.feature_panel, allocate(self.feature_panel, self.spec), self.spec, funding=funding)
            folder = self.run_log / 'workbench' / self.spec.spec_hash / uuid4().hex
            folder.mkdir(parents=True, exist_ok=False)
            artifacts = {}
            for name, window in [('train', self.spec.windows.train), ('validation', self.spec.windows.validation)]:
                daily = result.daily.filter((pl.col('date') >= window.start.date()) & (pl.col('date') < window.end.date()))
                path = folder / (name + '.parquet')
                daily.write_parquet(path)
                artifacts[name] = {'path': str(path.relative_to(self.run_log)), 'sha256': file_hash(path)}
            self._record('backtest', 'COMPLETED', metrics=result.metrics, daily_returns=artifacts,
                         qualification='EXPLORATORY_ONLY; selection exposure retained in the family cohort')
            return result
        except Exception as exc:
            self._record('backtest', 'FAILED', reason=str(exc))
            raise

    def export_yaml(self, path: str | Path = 'thesis_candidate.yaml') -> Path:
        if self._event:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(yaml.safe_dump(self.spec.model_dump(mode='json'), sort_keys=False), encoding='utf-8')
            if parse_research_spec(target).spec_hash != self.spec.spec_hash:
                raise QuantError('INVALID_SPEC', 'Export/reimport changed the event specification')
            self._record('export', 'COMPLETED', exported_path=str(target))
            return target
        if self.spec.python_feature_artifact is not None:
            target = Path(path).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            artifact = self.spec.python_feature_artifact
            source = beneath(self.spec._base_dir, artifact.path, must_exist=True)
            blob = source.read_bytes()
            if hashlib.sha256(blob).hexdigest() != artifact.sha256:
                raise QuantError('INVALID_EVIDENCE', 'Python feature artifact was modified')
            filename = target.stem + '.features-' + artifact.sha256[:16] + '.pkl'
            destination = target.parent / filename
            if not destination.exists():
                with destination.open('xb') as handle:
                    handle.write(blob)
            if file_hash(destination) != artifact.sha256:
                raise QuantError('INVALID_EVIDENCE', 'Export would replace a different feature artifact')
            self.spec = self.spec.model_copy(update={'python_feature_artifact': PythonFeatureArtifact(path=filename, sha256=artifact.sha256)})
            self.spec._base_dir = target.parent
        exported = export_spec(self.spec, path)
        self._record('export', 'COMPLETED', exported_path=str(exported))
        return exported
