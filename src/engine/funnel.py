"""One shared four-stage runner. Falsification is a normal terminal result."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any
from uuid import uuid4

import polars as pl

from src.data_vault import DataVault
from src.oracle.research_protocols import (
    describe_research_protocol,
    parse_research_spec,
)
from src.oracle.stage2_diagnostic import stage2
from src.oracle.stage3_falsifier import stage3

from .backtest_runner import NativeRun, run_native
from .common import (
    QuantError,
    append_trial,
    beneath,
    digest,
    file_hash,
    runtime_identity,
    write_json,
)
from .feature_compiler import compile_and_verify
from .isolation import feature_function, isolated_features
from .signal_allocator import allocate
from .spec_parser import CandidateSpec, parse_spec


def _save_run(run: NativeRun, root: Path, name: str) -> dict[str, str]:
    artifacts = {}
    for field in ('equity', 'daily', 'fills', 'trades', 'funding'):
        frame = getattr(run, field)
        if frame.width:
            path = root / f'{name}_{field}.parquet'
            frame.write_parquet(path)
            artifacts[path.name] = file_hash(path)
    path = root / f'{name}_metrics.json'
    write_json(path, {'metrics': run.metrics, 'timing': run.timing})
    artifacts[path.name] = file_hash(path)
    return artifacts


def _cohort(run_log: Path, spec: CandidateSpec) -> tuple[dict[str, dict[str, pl.DataFrame]], list[str]]:
    """Collect actual prior return artifacts in this declared selection family."""
    ledger = run_log / 'trial_ledger.jsonl'
    if not ledger.exists():
        return {}, list(spec.prior_trial_ids)
    records = []
    previous = '0' * 64
    for line in ledger.read_text().splitlines():
        record = json.loads(line)
        actual = record.pop('record_hash')
        if record.get('previous_hash') != previous or digest(record) != actual:
            raise QuantError('INVALID_EVIDENCE', 'Trial ledger hash chain is broken')
        previous = actual
        records.append(record)
    result, unresolved = {}, set(spec.prior_trial_ids)
    # Every distinct specification that reached Stage 3 must remain in the cohort.
    required = {r['spec_hash'] for r in records if (r.get('event') == 'stage3_started'
                or (r.get('event') == 'workbench_backtest' and r.get('status') == 'STARTED'))
                and r.get('selection_family_id') == spec.selection_family_id
                and r.get('market_scope', 'unspecified') == spec.market_scope
                and r.get('label_horizon_bars') == spec.label_horizon_bars
                and r.get('spec_hash') != spec.spec_hash}
    for record in records:
        if (record.get('selection_family_id') != spec.selection_family_id
            or record.get('market_scope', 'unspecified') != spec.market_scope
            or record.get('label_horizon_bars') != spec.label_horizon_bars):
            continue
        trial = record.get('spec_hash')
        if trial == spec.spec_hash or 'daily_returns' not in record:
            continue
        pieces = {}
        for window, artifact in record['daily_returns'].items():
            path = beneath(run_log, artifact['path'], must_exist=True)
            if file_hash(path) != artifact['sha256']:
                raise QuantError('INVALID_EVIDENCE', 'Prior trial returns changed')
            pieces[window] = pl.read_parquet(path)
        result[trial] = pieces
        unresolved.discard(record.get('candidate_id'))
        unresolved.discard(trial)
    unresolved |= required - set(result)
    return result, sorted(unresolved)


def _historical_trial_count(run_log: Path, spec: CandidateSpec, *, current_attempt: str | None = None) -> int:
    ledger = run_log / 'trial_ledger.jsonl'
    if not ledger.exists():
        return 0
    # The multiple-testing family is market scope + target horizon, NOT an
    # agent's self-selected name or selection_family_id. Count attempted
    # specifications from registration, including failed Stage 1/2 searches
    # and Workbench experiments, while deduplicating lifecycle events.
    attempts = set()
    previous = '0' * 64
    for line in ledger.read_text().splitlines():
        record = json.loads(line)
        actual = record.pop('record_hash', None)
        if record.get('previous_hash') != previous or digest(record) != actual:
            raise QuantError('INVALID_EVIDENCE', 'Trial ledger hash chain is broken')
        previous = actual
        if (record.get('event') in ('registered', 'workbench_backtest', 'stage3_started')
            and record.get('market_scope', 'unspecified') == spec.market_scope
            and record.get('label_horizon_bars') == spec.label_horizon_bars
            and record.get('attempt_id') != current_attempt):
            attempts.add(record.get('attempt_id') or record.get('spec_hash'))
    attempts.discard(None)
    return len(attempts)


INBOX = Path(__file__).resolve().parents[2] / 'research_inbox'


def verify_provenance(spec: CandidateSpec, *, run_log: str | Path,
                      inbox: str | Path | None = None) -> None:
    """Refuse an `exact` claim for an inbox-derived spec unless the converter made it.

    The inbox queue *earns* `source_spec_status == 'exact'` by running
    ``convert_thesis`` and comparing the produced specification. A hand-authored
    YAML can only *assert* it. This makes the assertion checkable for candidates
    whose identity matches an inbox directory; standalone and event-protocol
    candidates are unaffected, so no existing frozen spec changes meaning.
    """
    root = Path(inbox).resolve() if inbox is not None else INBOX
    if not root.is_dir():
        return
    ids = {path.name for path in root.iterdir() if path.is_dir() and not path.name.startswith('.')}
    if spec.candidate_id not in ids and spec.selection_family_id not in ids:
        return
    if spec.source_spec_status != 'exact':
        return
    receipt = (Path(run_log).resolve() / 'inbox_factory' / 'candidates'
               / spec.candidate_id / 'frozen_candidate.yaml')
    if not receipt.is_file():
        raise QuantError(
            'INVALID_PROVENANCE',
            f'{spec.candidate_id}: claims exact provenance from research_inbox/'
            f'{spec.candidate_id} but no convert_thesis receipt exists. Hand-authored or '
            'adapted specifications must declare a non-exact source_spec_status '
            '(prompt_derived_example, local_adaptation or synthetic_test).')
    produced = parse_spec(receipt)
    if produced.spec_hash != spec.spec_hash:
        raise QuantError(
            'INVALID_PROVENANCE',
            f'{spec.candidate_id}: conversion receipt spec_hash '
            f'{produced.spec_hash[:16]} does not match the frozen spec_hash '
            f'{spec.spec_hash[:16]}; the executable specification was modified after '
            'conversion and is no longer an exact transcription.')


class ResearchFunnel:
    def __init__(self, *, run_log: str | Path = 'run_log', isolate: bool = True):
        self.run_log = Path(run_log).resolve()
        self.isolate = isolate

    def run(self, specification: CandidateSpec | str | Path, *, development_only: bool = False) -> dict[str, Any]:
        if type(development_only) is not bool:
            raise QuantError('INVALID_SPEC', 'development_only must be an explicit boolean')
        spec = parse_research_spec(specification)
        protocol = describe_research_protocol(spec)
        # The frozen M8 event adapter has its own authority boundary. Do not
        # interpret a development-only request as permission to enter it.
        if (development_only and protocol.protocol != 'cross_sectional'
                and getattr(spec, 'strategy_id', None) == 'm8_n8_cash_session_v7'):
            raise QuantError('BLOCKED_PROTOCOL',
                             'Development-only mode currently supports only the native cross-sectional protocol')
        if protocol.protocol == 'event':
            return self._run_event(spec)
        if protocol.protocol != 'cross_sectional' or not isinstance(spec, CandidateSpec):
            raise QuantError('INVALID_SPEC', f'Unsupported research protocol: {protocol.protocol}')
        verify_provenance(spec, run_log=self.run_log)
        attempt = datetime.now(UTC).strftime('%Y%m%dT%H%M%S') + '-' + uuid4().hex[:10]
        output = self.run_log / 'dual_mode' / spec.candidate_id / attempt
        output.mkdir(parents=True, exist_ok=False)
        write_json(output / 'spec.json', spec.model_dump(mode='json'), exclusive=True)
        code = runtime_identity()
        identity = {'candidate_id': spec.candidate_id, 'selection_family_id': spec.selection_family_id,
                    'market_scope': spec.market_scope, 'label_horizon_bars': spec.label_horizon_bars,
                    'spec_hash': spec.spec_hash, 'code_hash': code, 'attempt_id': attempt,
                    'run_path': str(output.relative_to(self.run_log))}
        append_trial(self.run_log, {**identity, 'event': 'registered', 'status': 'RUNNING',
                                   'source_spec_status': spec.source_spec_status})
        case = {**identity, 'source_spec_status': spec.source_spec_status,
                'status': 'RUNNING', 'stages': {}, 'holdout_access': False,
                'development_only': development_only,
                'live_order_authority': False, 'assumptions': spec.assumptions,
                'worker_isolation': 'bubblewrap/no host data or network' if self.isolate else 'trusted in-process',
                'output_path': str(output)}
        daily_artifacts = {}
        try:
            vault = DataVault(spec.panel_root, run_log=self.run_log, receipt_dir=output)
            if spec.windows.protected.start != vault.protected_test_start:
                raise QuantError('INVALID_SPEC', 'Specification holdout differs from canonical vault cutoff')
            if spec.bar_seconds != vault.manifest['bar_seconds']:
                raise QuantError('INVALID_SPEC', 'Specification and canonical panel frequency differ')
            case['panel_hash'] = vault.manifest_hash
            models = {json.dumps({key: e.get('provenance', {}).get(key) for key in
                                  ('funding_mark_policy', 'funding_time_policy', 'volume_semantics',
                                   'spread_assumption', 'carry_status', 'execution_qualified', 'product')}, sort_keys=True)
                      for e in vault.manifest['entries'] if e['kind'] == 'development' and e['table'] == 'prices'}
            case['data_model_assumptions'] = [json.loads(model) for model in sorted(models)]
            case['source_exclusions'] = vault.manifest.get('excluded', [])
            frame = vault.load(end=spec.windows.validation.end)
            if frame.is_empty():
                raise QuantError('BLOCKED_DATA', 'No development panel rows')
            if spec.python_feature_artifact is not None and not self.isolate:
                raise QuantError('ISOLATION_UNAVAILABLE', 'Serialized Python features require the restricted worker')
            compiler = feature_function(spec)
            feature_fn = partial(isolated_features, feature_fn=compiler) if self.isolate else compiler
            features, proof = compile_and_verify(frame, spec, isolate=self.isolate)
            targets = allocate(features, spec)
            if targets.height:
                neutral = targets.group_by('timestamp').agg(pl.col('target_weight').sum())
                if neutral['target_weight'].abs().max() > 1e-12:
                    raise QuantError('INVALID_ALLOCATION', 'Portfolio target neutrality failed')
            report1 = {**proof.to_dict(), 'status': 'PASS',
                       'panel_rows': frame.height, 'symbols': frame['symbol'].n_unique(),
                       'pit_membership_rows': int(features['in_pit_universe'].sum()),
                       'source_coverage': 'All discovered historical sources considered; vendor delisting completeness not inferred',
                       'development_last_timestamp': frame['timestamp'].max().isoformat()}
            case['stages']['1'] = report1
            self._receipt(output, spec, vault.manifest_hash, code, 1, report1)
            report2, ic = stage2(features, spec)
            case['stages']['2'] = report2
            if ic.width:
                ic.write_parquet(output / 'stage2_ic.parquet')
            self._receipt(output, spec, vault.manifest_hash, code, 2, report2,
                          ['stage2_ic.parquet'] if ic.width else [])
            if report2['status'] != 'PASS':
                case['status'] = report2['status']
                return self._finish(output, case, daily_artifacts)
            # A source-only FX/index/metals panel is suitable for causal price
            # research, but its zero-shaped carry/spread placeholders are NOT
            # evidence of free financing or free execution. Never promote an
            # invalid cost model into a native economic simulation.
            if vault.manifest.get('quality_summary', {}).get('execution_qualified') is False:
                raise QuantError('INCONCLUSIVE_STAGE_3',
                                 'Price-only source has unknown spread and directional CFD swap. '
                                 'Register observed costs and an audited carry adapter before Stage 3.')
            funding = vault.load_funding(spec.windows.train.start, spec.windows.validation.end)
            prior, missing = _cohort(self.run_log, spec)
            if missing:
                raise QuantError('INCONCLUSIVE_STAGE_3', f'Prior selection evidence is missing: {missing}')
            append_trial(self.run_log, {**identity, 'event': 'stage3_started', 'status': 'RUNNING'})
            # prior_trial_ids was reconciled against ledger IDs above. stage3 receives
            # actual spec-hash keys, so use a copy with equivalent resolved cohort IDs.
            resolved_spec = spec.model_copy(update={'prior_trial_ids': list(prior)})
            report3, runs = stage3(features, resolved_spec, funding=funding, prior_cohort=prior,
                                   historical_trial_count=_historical_trial_count(
                                       self.run_log, spec, current_attempt=attempt))
            artifacts = {}
            for name, result in runs.items():
                artifacts.update(_save_run(result, output, name))
                if name.endswith('_candidate'):
                    split = name.removesuffix('_candidate')
                    path = output / f'{name}_daily.parquet'
                    daily_artifacts[split] = {'path': str(path.relative_to(self.run_log)), 'sha256': file_hash(path)}
            case['stages']['3'] = report3
            self._receipt(output, spec, vault.manifest_hash, code, 3, report3, list(artifacts))
            if report3['status'] != 'PASS':
                case['status'] = report3['status']
                return self._finish(output, case, daily_artifacts)
            if runtime_identity() != code:
                raise QuantError('INVALID_EVIDENCE', 'Runtime code changed during the frozen run')
            # Fail-closed batch boundary. Do not reserve a holdout claim, open a
            # protected partition, or run Stage 4 even when Stage 3 passes.
            if development_only:
                case['status'] = 'DEVELOPMENT_QUALIFIED'
                case['reason'] = 'Development-only run completed through Stage 3; Stage 4 is forbidden'
                case['holdout_access'] = False
                return self._finish(output, case, daily_artifacts)
            claim = vault.unlock_holdout(spec.candidate_id, spec.spec_hash)
            case['holdout_claim'] = claim['claim_id']
            try:
                protected, protected_funding = vault.load_holdout(claim)
            finally:
                case['holdout_access'] = any('/protected/' in path for path in vault.opened_files)
            # Development history supplies causal warmup; no fitting or retuning.
            joined = pl.concat([frame, protected], how='vertical_relaxed').sort('symbol', 'timestamp')
            holdout_features = feature_fn(joined).filter(
                (pl.col('timestamp') >= spec.windows.protected.start)
                & (pl.col('timestamp') < spec.windows.protected.end))
            holdout = run_native(holdout_features, allocate(holdout_features, spec), spec,
                                 funding=protected_funding)
            _save_run(holdout, output, 'holdout_candidate')
            report4 = {'status': 'EVALUATED_ONCE', 'metrics': holdout.metrics,
                       'prior_exposure': claim['prior_exposure'], 'retuning': False}
            case['stages']['4'] = report4
            case['status'] = 'HOLDOUT_EVALUATED'
            return self._finish(output, case, daily_artifacts)
        except QuantError as exc:
            case['status'], case['reason'] = exc.status, exc.reason
            return self._finish(output, case, daily_artifacts)
        except Exception as exc:
            case['status'], case['reason'] = 'ENGINEERING_ERROR', f'{type(exc).__name__}: {exc}'
            self._finish(output, case, daily_artifacts)
            raise

    def _run_event(self, spec) -> dict[str, Any]:
        """Run typed event protocols before entering any cross-sectional gates."""
        from .event_protocol import run_bta_nq_event, run_m8_n8_event

        attempt = datetime.now(UTC).strftime('%Y%m%dT%H%M%S') + '-' + uuid4().hex[:10]
        output = self.run_log / 'dual_mode' / spec.strategy_id / attempt
        output.mkdir(parents=True, exist_ok=False)
        write_json(output / 'spec.json', spec.model_dump(mode='json'), exclusive=True)
        code = runtime_identity()
        is_bta = getattr(spec, 'strategy_id', None) == 'bta_nq_monday_bb10_atr5_cfd_v1'
        market_scope = 'indices:usatechidxusd:60m' if is_bta else 'indices:usatechidxusd:30m'
        label_horizon = 1 if is_bta else 2
        identity = {'candidate_id': spec.strategy_id, 'selection_family_id': spec.strategy_id,
                    'market_scope': market_scope, 'label_horizon_bars': label_horizon,
                    'spec_hash': spec.spec_hash, 'protocol': spec.protocol,
                    'protocol_family': 'event', 'code_hash': code,
                    'attempt_id': attempt, 'run_path': str(output.relative_to(self.run_log))}
        append_trial(self.run_log, {**identity, 'event': 'registered', 'status': 'RUNNING'})
        case = {**identity, 'status': 'RUNNING', 'output_path': str(output), 'holdout_access': False,
                'live_order_authority': False, 'stages': {}}
        failure = None
        report = None
        try:
            if is_bta:
                report = run_bta_nq_event(spec, output_dir=output)
            else:
                report = run_m8_n8_event(spec, output_dir=output)
            case['stages']['event'] = report
            case['status'] = report['status']
            if 'reason' in report:
                case['reason'] = report['reason']
        except Exception as exc:  # noqa: BLE001 - append terminal trial evidence for every runner failure.
            failure = exc
            case['status'] = exc.status if isinstance(exc, QuantError) else 'ENGINEERING_ERROR'
            case['reason'] = f'{type(exc).__name__}: {exc}'
        case['finished_at'] = datetime.now(UTC).isoformat()
        if failure is not None:
            partial_artifacts = {str(path.relative_to(output)): file_hash(path)
                                 for path in sorted(output.rglob('*')) if path.is_file()
                                 and path.name not in {'casefile.json', 'failure_evidence.json'}}
            write_json(output / 'failure_evidence.json',
                       {'status': case['status'], 'reason': case['reason'],
                        'artifacts': partial_artifacts, 'holdout_access': False})
        elif not (output / 'event_evidence.json').is_file():
            write_json(output / 'event_evidence.json', report)
        write_json(output / 'casefile.json', case)
        evidence_path = output / ('event_evidence.json' if (output / 'event_evidence.json').is_file()
                                  else 'failure_evidence.json')
        append_trial(self.run_log, {**identity, 'event': 'completed', 'status': case['status'],
                                   'holdout_access': False,
                                   'evidence': {'path': str(evidence_path.relative_to(self.run_log)),
                                                'sha256': file_hash(evidence_path)},
                                   'casefile': {'path': str((output / 'casefile.json').relative_to(self.run_log)),
                                                'sha256': file_hash(output / 'casefile.json')}})
        if case['status'] == 'ENGINEERING_ERROR' and failure is not None:
            raise failure
        return case

    def _receipt(self, output, spec, panel_hash, code, stage, report, artifacts=()):
        path = output / f'stage{stage}_evidence.json'
        write_json(path, report, exclusive=True)
        evidence = {name: file_hash(beneath(output, name, must_exist=True))
                    for name in [path.name, *artifacts]}
        receipt = {'stage': stage, 'status': report['status'], 'candidate_id': spec.candidate_id,
                   'spec_hash': spec.spec_hash, 'code_hash': code, 'panel_hash': panel_hash,
                   'artifacts': evidence}
        receipt['receipt_hash'] = digest(receipt)
        write_json(output / f'stage{stage}.json', receipt, exclusive=True)

    def _finish(self, output, case, daily_artifacts):
        case['finished_at'] = datetime.now(UTC).isoformat()
        write_json(output / 'casefile.json', case)
        event = {k: case[k] for k in ('candidate_id', 'selection_family_id', 'market_scope',
                                      'label_horizon_bars', 'spec_hash', 'code_hash',
                                      'attempt_id', 'run_path', 'status')}
        event.update(event='completed', daily_returns=daily_artifacts,
                     casefile={'path': str((output / 'casefile.json').relative_to(self.run_log)),
                               'sha256': file_hash(output / 'casefile.json')},
                     holdout_access=case['holdout_access'])
        append_trial(self.run_log, event)
        # A leaderboard is a regenerable reference view, not a second authority.
        entries = []
        for line in (self.run_log / 'trial_ledger.jsonl').read_text().splitlines():
            row = json.loads(line)
            if row.get('event') == 'completed':
                entries.append({k: row.get(k) for k in ('candidate_id', 'spec_hash', 'attempt_id', 'status', 'casefile')})
        write_json(self.run_log / 'leaderboard.json', {'source': 'trial_ledger.jsonl', 'entries': entries})
        return case
