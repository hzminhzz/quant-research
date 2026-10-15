"""Interactive research using the same vault/compiler/oracles as the factory."""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import cloudpickle
import polars as pl

from src.data_vault import DataVault
from src.engine.backtest_runner import run_native
from src.engine.common import (
    QuantError,
    append_trial,
    beneath,
    file_hash,
    runtime_identity,
)
from src.engine.feature_compiler import compile_and_verify
from src.engine.signal_allocator import allocate
from src.engine.spec_parser import (
    CandidateSpec,
    PythonFeatureArtifact,
    export_spec,
    parse_spec,
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
        self.spec = spec if isinstance(spec, CandidateSpec) else parse_spec(spec)
        self.run_log, self.isolate = Path(run_log).resolve(), isolate
        self._vault = DataVault(self.spec.panel_root, run_log=self.run_log)  # no unlock receipts
        self.panel: pl.DataFrame | None = None
        self.feature_panel: pl.DataFrame | None = None
        self._custom_python = False

    def _record(self, action: str, status: str, **metadata):
        append_trial(self.run_log, {'candidate_id': self.spec.candidate_id,
                                   'selection_family_id': self.spec.selection_family_id,
                                   'spec_hash': self.spec.spec_hash, 'code_hash': runtime_identity(),
                                   'event': f'workbench_{action}', 'status': status,
                                   'panel_hash': self._vault.manifest_hash,
                                   'holdout_access': False, **metadata})

    def load(self, start=None, end=None) -> pl.DataFrame:
        self.panel = self._vault.load(start=start, end=end)
        self.feature_panel = None
        self._record('load', 'COMPLETED', rows=self.panel.height)
        return self.panel

    def features(self, definitions: list[dict] | Callable | None = None) -> pl.DataFrame:
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
