"""One development-only, identity-bound ATS-4 event protocol: frozen M8 N8."""
from __future__ import annotations

import hashlib
import inspect
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import polars as pl
import pyarrow.parquet as pq
import yaml
from pydantic import BaseModel, ConfigDict

from src.data_vault.panel_builder import parquet_bounds
from src.engine.common import QuantError, digest, file_hash, runtime_identity
from src.oracle.research_protocols import ProtocolDescriptor, gates_for_protocol
from src.research_control.contracts import ResearchContractV1
from src.research_control.feature_gateway import FeatureContractError, FeatureGateway
from src.research_control.m8_cash_calendar import cash_session_signal_eligible

BAR = timedelta(minutes=30)
INITIAL_CASH = 100_000.0
UNIT_MULTIPLIER = 1.0
COST_MULTIPLIERS = (1, 2, 3)

REPOSITORY = Path(__file__).resolve().parents[2]
SOURCE = Path('/home/quant/dev/quant/research_artifacts/ats4/20261016/source/prices_30m.parquet')
SOURCE_SHA256 = '36e6a5dd5e16feb21ba5828ed306dc32c703d74143692dce1019322a52d159c8'
CONFIG = REPOSITORY / 'config/research_contract_m8_n8_cash_v7.yaml'
CONFIG_SHA256 = '3f595848a8dd1b02ff7293ce3ee72fe848548f1ff80a66c73445b3c5d10ccb53'
SESSION = REPOSITORY / 'run_log/research_sessions/m8_n8_dukascopy_us_cash_30m_v7/frozen_spec.json'
FROZEN_SESSION_SHA256 = '5e9689cddcc10ae6f6978d192f0a403642eba9536b335825389c234e6d867ebb'
FROZEN_ENVELOPE_SHA256 = 'b3e756e944b5bd232775017c6c05d64dd598d8f95cba8d60ed6f55a5d72a71dd'
COSTS = REPOSITORY / 'run_log/m8/n8/cash_session_cost_evidence.json'
COSTS_SHA256 = '89a08d8c5e22fc71e852e1d865e0900b976be2d857bb1346a93294d6dfdccd00'
CALENDAR = REPOSITORY / 'run_log/m8/n8/cash_session_calendar_evidence.json'
CALENDAR_SHA256 = 'c3313673441294070a0ac1ce57c4ad3d24ab61841fb2828a670651b804848882'
INTENT = REPOSITORY / 'run_log/m8/n8/cash_session_run_intent_v7.json'
INTENT_SHA256 = 'f899c65545daa54810cb0b6b4330a4201650287c0d8f68563a2435cc6fa2dc19'
AUDIT_RECIPE = REPOSITORY / 'run_log/m8/n8/cash_session_audit_recipe_v7.json'
AUDIT_RECIPE_SHA256 = 'ce624dfc1f1c89a0c4592fdc0426f465fc694a8f1af2cd16d6783bf9b1f34b39'
TRIAL = REPOSITORY / 'run_log/research_sessions/m8_n8_dukascopy_us_cash_30m_v7/trials/N8_cash_session_primary_3cost_stress.json'
TRIAL_SHA256 = '2ee2d04477e39ca6453584aae7ea5bbdc8b105d8346f053c5fcc47bab6d38f75'
RULE_TEXT = REPOSITORY / 'run_log/m8/original_rulebook_extracted_pages.txt'
RULE_TEXT_SHA256 = 'a0ece8b0aad23b28d5041b308a8ed7aa00a75a255338d6c03b6b8c0d0dd6661a'
SOURCE_FINGERPRINT = REPOSITORY / 'run_log/m8/n8/source_fingerprints_recovery.json'
SOURCE_FINGERPRINT_SHA256 = 'ca6677352cad81f630447d6a399b8be98df08e22b6b1c3a812795b89cef42e61'
HISTORICAL_RESULT = REPOSITORY / 'run_log/m8/n8/cash_session/results/e908ef2f-0d1d-44f4-a484-0203b616cbb4'
HISTORICAL_MANIFEST_SHA256 = 'f26957ca91b16ad80a203bae2c06e8d6001a1d948b6e980e5ece6fe017d663a7'
START = datetime(2020, 1, 1, tzinfo=UTC)
END = datetime(2025, 1, 1, tzinfo=UTC)


class M8N8EventSpec(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    protocol: Literal['event']
    strategy_id: Literal['m8_n8_cash_session_v7']

    @property
    def spec_hash(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class BtaNqMondayEventSpec(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    protocol: Literal['event']
    strategy_id: Literal['bta_nq_monday_bb10_atr5_cfd_v1']

    @property
    def spec_hash(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


def validate_event_spec(spec: M8N8EventSpec | BtaNqMondayEventSpec) -> M8N8EventSpec | BtaNqMondayEventSpec:
    try:
        if not isinstance(spec, (M8N8EventSpec, BtaNqMondayEventSpec)) or getattr(spec, '__pydantic_extra__', None):
            raise ValueError('expected a strict event spec without extra fields')
        if set(vars(spec)) != {'protocol', 'strategy_id'}:
            raise ValueError('event spec contains forged fields')
        payload = spec.model_dump(mode='python')
        if isinstance(spec, M8N8EventSpec):
            validated = M8N8EventSpec.model_validate(payload)
        elif isinstance(spec, BtaNqMondayEventSpec):
            validated = BtaNqMondayEventSpec.model_validate(payload)
        else:
            raise TypeError(f'unsupported event spec type: {type(spec).__name__}')
        if set(payload) != {'protocol', 'strategy_id'} or validated != spec:
            raise ValueError('event spec contains altered or unsupported fields')
        return validated
    except (ValueError, TypeError) as exc:
        raise QuantError('INVALID_SPEC', str(exc)) from exc


def parse_event_spec(source: str | Path | M8N8EventSpec | BtaNqMondayEventSpec) -> M8N8EventSpec | BtaNqMondayEventSpec:
    if isinstance(source, (M8N8EventSpec, BtaNqMondayEventSpec)):
        return validate_event_spec(source)
    try:
        payload = yaml.safe_load(Path(source).read_text(encoding='utf-8'))
        if not isinstance(payload, dict) or 'protocol' not in payload:
            raise ValueError('missing explicit protocol discriminator')
        strategy_id = payload.get('strategy_id')
        if strategy_id == 'm8_n8_cash_session_v7':
            return validate_event_spec(M8N8EventSpec.model_validate(payload))
        if strategy_id == 'bta_nq_monday_bb10_atr5_cfd_v1':
            return validate_event_spec(BtaNqMondayEventSpec.model_validate(payload))
        raise ValueError(f'unsupported event strategy_id: {strategy_id}')
    except (OSError, yaml.YAMLError, ValueError, TypeError) as exc:
        if isinstance(exc, QuantError):
            raise
        raise QuantError('INVALID_SPEC', str(exc)) from exc


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


def _authority(path: Path, expected: str) -> str:
    if not path.is_file():
        status = 'BLOCKED_DATA' if path == SOURCE else 'BLOCKED_HISTORY'
        raise QuantError(status, f'frozen authority is missing: {path}')
    if _sha256(path) != expected:
        raise QuantError('INVALID_EVIDENCE', f'frozen authority changed: {path}')
    return expected


def _factory_lineage(root: Path) -> list[dict[str, Any]]:
    path = root / 'trial_ledger.jsonl'
    if not path.is_file():
        return []
    previous = '0' * 64
    records = []
    try:
        for line in path.read_text(encoding='utf-8').splitlines():
            row = json.loads(line)
            record_hash = row.pop('record_hash')
            if row.get('previous_hash') != previous or digest(row) != record_hash:
                raise QuantError('INVALID_EVIDENCE', 'ATS-4 trial lineage hash chain is broken')
            previous = record_hash
            if (row.get('protocol_family') == 'event'
                    and row.get('candidate_id') == 'm8_n8_cash_session_v7'
                    and row.get('event') in {'registered', 'completed'}):
                records.append({**row, 'record_hash': record_hash})
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise QuantError('INVALID_EVIDENCE', f'ATS-4 trial lineage is unreadable: {exc}') from exc
    return records


def _development_data() -> tuple[pl.DataFrame, Any, ResearchContractV1, dict[str, str]]:
    for path, expected in ((CONFIG, CONFIG_SHA256), (SESSION, FROZEN_SESSION_SHA256),
                           (COSTS, COSTS_SHA256), (CALENDAR, CALENDAR_SHA256),
                           (INTENT, INTENT_SHA256), (AUDIT_RECIPE, AUDIT_RECIPE_SHA256),
                           (TRIAL, TRIAL_SHA256), (RULE_TEXT, RULE_TEXT_SHA256),
                           (SOURCE_FINGERPRINT, SOURCE_FINGERPRINT_SHA256)):
        _authority(path, expected)
    if not SOURCE.is_file():
        raise QuantError('BLOCKED_DATA', 'frozen M8 development source is unavailable')
    if SOURCE.is_symlink() or SOURCE.stat().st_size != 1_404_224:
        raise QuantError('INVALID_EVIDENCE', 'frozen M8 development source identity changed')
    lower, upper = parquet_bounds(SOURCE)  # inspect footer before decoding rows
    metadata = pq.ParquetFile(SOURCE).metadata
    if upper >= END or lower < datetime(2019, 12, 1, tzinfo=UTC) or metadata.num_rows != 57_504:
        raise QuantError('INVALID_EVIDENCE', 'frozen source bounds or row count changed')
    source_hash = _authority(SOURCE, SOURCE_SHA256)
    data = pl.read_parquet(SOURCE)
    if data.height != metadata.num_rows or not {'timestamp', 'symbol', 'open', 'high', 'low', 'close', 'volume'} <= set(data.columns):
        raise QuantError('BLOCKED_DATA', 'source schema or row count differs from frozen M8')
    if data['timestamp'].null_count() or data['symbol'].null_count() or data['symbol'].n_unique() != 1:
        raise QuantError('BLOCKED_DATA', 'invalid timestamps or symbol cardinality')
    if data.select(pl.struct('symbol', 'timestamp').n_unique()).item() != data.height:
        raise QuantError('BLOCKED_DATA', 'duplicate source bars')
    if data['timestamp'].min() < datetime(2019, 12, 1, tzinfo=UTC) or data['timestamp'].max() >= END:
        raise QuantError('INVALID_EVIDENCE', 'decoded rows cross frozen development bounds')
    frozen = json.loads(SESSION.read_text(encoding='utf-8'))
    if (frozen.get('session_id') != 'm8_n8_dukascopy_us_cash_30m_v7'
            or frozen.get('frozen_sha256') != FROZEN_ENVELOPE_SHA256
            or frozen.get('spec_sha256') != '8dd1d431176e4e04a47142609fad02b71e993fe5cbeccc6978ceb57faae98f55'
            or frozen['spec']['evaluation']['holdout_accessed'] is not False
            or frozen['identity']['data'][0]['sha256'] != SOURCE_SHA256):
        raise QuantError('INVALID_EVIDENCE', 'frozen session identity differs')
    contract = ResearchContractV1.model_validate(yaml.safe_load(CONFIG.read_text(encoding='utf-8')))
    computation = FeatureGateway().compute(data, contract)
    authority = {'source_sha256': source_hash,
                 'feature_contract_sha256': CONFIG_SHA256,
                 'frozen_session_sha256': FROZEN_SESSION_SHA256,
                 'cost_assumptions_sha256': COSTS_SHA256,
                 'calendar_sha256': CALENDAR_SHA256,
                 'run_intent_sha256': INTENT_SHA256,
                 'audit_recipe_sha256': AUDIT_RECIPE_SHA256,
                 'trial_record_sha256': TRIAL_SHA256,
                 'extracted_rule_text_sha256': RULE_TEXT_SHA256,
                 'source_fingerprint_sha256': SOURCE_FINGERPRINT_SHA256}
    return data, computation, contract, authority


def independent_signal_oracle(data: pl.DataFrame) -> list[datetime]:
    """Calculate strict prior-high signals from source bars, independently of features."""
    if data['timestamp'].n_unique() != data.height:
        raise ValueError('BLOCKED_DATA: duplicate M8 bars')
    signals: list[datetime] = []
    highs: list[float] = []
    for row in data.sort('timestamp').iter_rows(named=True):
        stamp = row['timestamp'].astimezone(UTC)
        if (len(highs) >= 50 and stamp >= START and stamp + 2 * BAR < END
                and float(row['close']) > max(highs[-50:])
                and cash_session_signal_eligible(stamp, evaluation_end=END)):
            signals.append(stamp)
        highs.append(float(row['high']))
    return signals


def independent_execution_oracle(signals: list[datetime]) -> list[datetime]:
    """Apply the frozen one-position/two-open lifecycle to the full signal set."""
    executed: list[datetime] = []
    for signal in signals:
        if not executed or signal >= executed[-1] + 2 * BAR:
            executed.append(signal)
    return executed


def _assert_historical_parity(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    manifest_path = HISTORICAL_RESULT / 'manifest.json'
    report_path = HISTORICAL_RESULT / 'report.json'
    if not manifest_path.is_file() or not report_path.is_file():
        raise QuantError('BLOCKED_HISTORY', 'frozen historical M8 result authority is missing')
    if _sha256(manifest_path) != HISTORICAL_MANIFEST_SHA256:
        raise QuantError('INVALID_EVIDENCE', 'historical artifact manifest changed')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if (report.get('data_sha256') != SOURCE_SHA256
            or report.get('source_fingerprint_sha256') != SOURCE_FINGERPRINT_SHA256
            or manifest.get('identity', {}).get('config_sha256') != CONFIG_SHA256
            or manifest.get('identity', {}).get('source_sha256') != '4efc88df16cf743d7a0b3634bd649981fdeab0951ec7068595ea50e37bec2298'
            or manifest.get('identity', {}).get('frozen_session_sha256') != FROZEN_ENVELOPE_SHA256
            or manifest.get('identity', {}).get('spec_sha256') != '8dd1d431176e4e04a47142609fad02b71e993fe5cbeccc6978ceb57faae98f55'
            or manifest.get('identity', {}).get('engine_version') != '0.1.7'
            or manifest.get('scenarios') != ['1x', '2x', '3x']
            or manifest.get('files', {}).get('report.json') != _sha256(report_path)):
        raise QuantError('INVALID_EVIDENCE', 'historical artifact identity differs')
    comparisons = []
    for scenario in scenarios:
        name, result = scenario['scenario'], scenario['native']
        for kind, frame in (('fills', result.to_fills_dataframe()), ('equity', result.to_equity_dataframe())):
            path = HISTORICAL_RESULT / f'{kind}_{name}.parquet'
            if not path.is_file():
                raise QuantError('BLOCKED_HISTORY', f'frozen historical artifact is missing: {path.name}')
            if _sha256(path) != manifest['files'][path.name]:
                raise QuantError('INVALID_EVIDENCE', f'historical {path.name} hash mismatch')
            old = pl.read_parquet(path).sort('timestamp')
            new = frame.sort('timestamp')
            if not old.equals(new):
                raise ValueError(f'PARITY_FAIL: native {kind} differs from frozen historical {name}')
            comparisons.append({'scenario': name, 'table': kind, 'rows': old.height, 'exact': True})
        old_scenario = next((item for item in report['cost_scenarios'] if item['scenario'] == name), None)
        if old_scenario is None or old_scenario['audit']['status'] != 'PASS':
            raise QuantError('INVALID_EVIDENCE', f'persisted {name} audit is missing or failed')
        if old_scenario['audit'] != scenario['audit']:
            raise ValueError(f'PARITY_FAIL: independent {name} event/cash audit differs from frozen record')
        if old_scenario['metrics'] != scenario['metrics']:
            raise ValueError(f'PARITY_FAIL: {name} daily risk/trade metrics differ from frozen record')
    return {'status': 'PASS', 'comparisons': comparisons,
            'historical_attempt_id': manifest['attempt_id'],
            'historical_report_sha256': manifest['files']['report.json'],
            'historical_runtime_code_sha256': manifest['identity']['code_sha256'],
            'historical_source_fingerprint_sha256': manifest['identity']['source_sha256'],
            'historical_feature_proof_sha256': manifest['identity']['feature_proof_sha256']}


def run_m8_n8_event(spec: M8N8EventSpec, *, output_dir: str | Path | None = None) -> dict[str, Any]:
    """Run the frozen M8 rule through native execution, history, and state reconciliation."""
    spec = validate_event_spec(spec)
    folder = Path(output_dir) if output_dir is not None else None
    if folder is not None:
        folder.mkdir(parents=True, exist_ok=True)
    from src.engine.ats4_authority import event_runtime_identity, verified_known_history
    from src.engine.ats4_reconciliation import reconcile_m8_n8
    from src.engine.ats4_sleeves import NativeScenario, demonstration
    from src.portfolio_evidence import SleeveIdentity, TrialDisclosure
    from src.research_control.m8_n8 import (
        _assert_scheduled_fills_present,
        _run_one,
        audit_n8_result,
        classify_n8_economics,
        expected_signals,
        summarize_n8_scenario,
    )

    runtime_before = event_runtime_identity()
    import importlib.metadata
    ledger_root = Path(output_dir).resolve().parents[2] if output_dir is not None else REPOSITORY
    lineage = _factory_lineage(ledger_root)
    history = verified_known_history(current_attempts=tuple(lineage))
    current_registration = next((row for row in reversed(lineage)
                                 if row.get('event') == 'registered'
                                 and output_dir is not None
                                 and row.get('attempt_id') == Path(output_dir).name), None)
    previous_lineage = [row for row in lineage if current_registration is None
                        or row.get('attempt_id') != current_registration.get('attempt_id')]
    data, computation, contract, authorities = _development_data()
    from ml4t.backtest import BacktestConfig, DataFeed, Engine, Strategy
    from ml4t.diagnostic.api import PortfolioAnalysis
    from ml4t.engineer import compute_features

    independent = independent_signal_oracle(data)
    expected_executions = independent_execution_oracle(independent)
    adapter_signals = expected_signals(data, computation.data, START, END, cash_session_only=True)
    if independent != adapter_signals:
        raise ValueError('CAUSAL_ORACLE_MISMATCH: independent signals differ from managed feature adapter')
    try:
        _assert_scheduled_fills_present(data, independent)
    except FeatureContractError as exc:
        if exc.reason_code == 'EXECUTION_EXCEPTION':
            raise QuantError('BLOCKED_DATA', str(exc)) from exc
        raise
    scenarios = []
    for multiple in COST_MULTIPLIERS:
        native, strategy, expected = _run_one(data, computation, contract, START, END, multiple,
                                              cash_session_only=True)
        name = f'{multiple}x'
        if folder is not None:
            native.to_fills_dataframe().write_parquet(folder / f'fills_{name}.parquet')
            native.to_equity_dataframe().write_parquet(folder / f'equity_{name}.parquet')
            native.to_portfolio_state_dataframe().write_parquet(folder / f'portfolio_state_{name}.parquet')
        if expected != independent or strategy.executed_signals != expected_executions:
            raise ValueError('EVENT_SEQUENCE_MISMATCH: actual signals/orders omitted or added events')
        reconciliation = reconcile_m8_n8(native, strategy, data, expected_executions, multiple)
        if reconciliation['status'] != 'PASS':
            raise ValueError(f"NATIVE_RECONCILIATION_FAILED: {reconciliation['status']}")
        if folder is not None:
            pl.DataFrame(reconciliation['orders']).write_parquet(folder / f'orders_{name}.parquet')
            pl.DataFrame(reconciliation['ledger']).write_parquet(folder / f'accounting_{name}.parquet')
        audit = audit_n8_result(native, strategy, data, independent, cost_multiple=multiple)
        if audit.status != 'PASS':
            raise ValueError(f'ACCOUNTING_AUDIT_FAILED: {audit.reason_code}')
        metrics = summarize_n8_scenario(native, audit.to_record(), START, END, cash_session_only=True)
        scenarios.append({'scenario': f'{multiple}x', 'audit': audit.to_record(),
                          'metrics': metrics, 'native': native, 'strategy': strategy,
                          'reconciliation': reconciliation})
    parity = _assert_historical_parity(scenarios)
    economics = classify_n8_economics(scenarios)
    event_gates = gates_for_protocol(ProtocolDescriptor(protocol='event'),
                                     cost_status='assumed', mark_status='daily_only')
    current_attempts = history['trial_disclosure']
    trial_disclosure = TrialDisclosure(
        tuple(current_attempts['known_trial_ids']), tuple(current_attempts['outcomes']),
        current_attempts['unknown_count'], tuple(current_attempts['missing_outcome_ids']))
    m8_identity = SleeveIdentity(
        spec.strategy_id, 'v7', spec.spec_hash, runtime_before['identity_digest'],
        authorities['source_sha256'], authorities['cost_assumptions_sha256'],
        authorities['calendar_sha256'], spec.strategy_id)
    cash_identity = SleeveIdentity(
        'cash_no_trade_baseline', 'v1', spec.spec_hash, runtime_before['identity_digest'],
        authorities['source_sha256'], 'zero_yield_zero_fee_assumption',
        authorities['calendar_sha256'], spec.strategy_id)
    sleeve_scenarios = [NativeScenario(item['scenario'], item['native'], item['reconciliation'])
                        for item in scenarios]
    try:
        sleeve_result = demonstration(
            data,
            sleeve_scenarios,
            identity=m8_identity, cash_identity=cash_identity,
            authorities={'source_sha256': authorities['source_sha256'],
                         'cost_authority_sha256': authorities['cost_assumptions_sha256'],
                         'calendar_authority_sha256': authorities['calendar_sha256']},
            trial_disclosure=trial_disclosure, periods_per_year=252, include_sleeves=True)
    except ValueError as exc:
        if not str(exc).startswith('missing native equity mark on scheduled open date '):
            raise
        sleeve_result = {'report': {
            'status': 'BLOCKED_DATA',
            'reason': str(exc),
            'api': 'src.engine.ats4_sleeves.demonstration(data, three NativeScenario values, identity, cash_identity, authorities, trial_disclosure, periods_per_year)',
            'missing_requirement': 'an actual reconciled native equity mark on every scheduled UTC evaluation date',
        }}
    runtime_after = event_runtime_identity()
    if runtime_before['identity_digest'] != runtime_after['identity_digest']:
        raise QuantError('INVALID_EVIDENCE', 'ATS-4 event runtime identity changed during native replay')
    compact_reconciliations = {
        item['scenario']: {key: value for key, value in item['reconciliation'].items()
                           if key not in {'orders', 'ledger'}}
        for item in scenarios
    }
    report = {
        'status': 'PARTIALLY_QUALIFIED',
        'protocol': {'family': 'event', 'strategy_id': spec.strategy_id,
                     'protocol_status': 'EXACT_FROZEN_RULE_AND_CLOCKS',
                     'protocol_hash': spec.spec_hash,
                     'frozen_rule': 'strict close[t] > max(high[t-50:t]); enter t+1 open; exit t+2 open; one long unit; no stop, target, overnight hold, or overlapping position'},
        'parity': parity,
        'science_status': 'RETROSPECTIVE_OBSERVED_2020_2024; NO_OOS_OR_DSR_CLAIM',
        'sample_design': {'development_window': ['2020-01-01T00:00:00Z', '2025-01-01T00:00:00Z'],
                          'train_validation_split': 'not declared by frozen authority; one observed development interval',
                          'protected_window_read': False, 'oos_claim': False, 'dsr_status': 'UNAVAILABLE_INCOMPLETE_TRIAL_HISTORY'},
        'economics_status': economics,
        'cost_status': 'ASSUMED_NOT_QUALIFIED',
        'mark_status': '30M_SOURCE_CLOSE_MARKS_RECONCILED; INTRADAY_ACCOUNT_BARRIER_UNQUALIFIED',
        'clock_evidence': {'status': 'LITERAL_UTC_DST_AND_EARLY_CLOSE_REGRESSIONS',
                           'test_authority': 'tests/test_m8_cash_calendar.py',
                           'calendar_predicate_shared_with_signal_adapter': True},
        'gates': event_gates.__dict__,
        'source_bridge': {'mode': 'HASH_VERIFIED_DEVELOPMENT_ONLY_DIRECT_PARQUET',
                          'source_path': str(SOURCE), 'rows': data.height,
                          'source_sha256': authorities['source_sha256'],
                          'bounds_checked_before_decode': True,
                          'protected_read': False, 'source_exposure': 'already observed'},
        'authorities': authorities,
        'event_runtime_identity': {'before': runtime_before, 'after': runtime_after,
                                   'identity_digest': runtime_before['identity_digest']},
        'historical_runtime_code_sha256': parity['historical_runtime_code_sha256'],
        'runtime_code_sha256': runtime_identity(),
        'native_versions': {name: importlib.metadata.version(name) for name in
                            ('ml4t-backtest', 'ml4t-diagnostic', 'ml4t-engineer')},
        'native_api_signatures': {
            f'{function.__module__}.{function.__name__}': str(inspect.signature(function))
            for function in (Engine, Strategy, BacktestConfig, DataFeed, PortfolioAnalysis, compute_features)
        },
        'feature_proof': {'provider_versions': computation.proof.provider_versions,
                          'feature_set_sha256': computation.proof.feature_set_sha256,
                          'input_sha256': computation.proof.input_sha256,
                          'output_sha256': computation.proof.output_sha256,
                          'checks': computation.proof.checks},
        'calendar_authority': {'version': '4.13.2', 'requested': 'XNAS', 'resolved': 'XNYS',
                               'range': ['2020-01-01', '2025-01-01'],
                               'source_sha256': authorities['calendar_sha256'],
                               'limitation': 'calendar schedule is not independent proof of historical Dukascopy execution hours'},
        'cost_model': {'status': 'ASSUMED_NOT_QUALIFIED', 'slippage_bps_per_fill': 3.0,
                       'commission_bps_per_fill': 0.6, 'multipliers': [1, 2, 3],
                       'source_sha256': authorities['cost_assumptions_sha256'],
                       'meaning': 'adverse price impact and commission assumptions, not observed spreads or fills'},
        'known_trial_history': history,
        'ats4_previous_attempt_lineage': {'source': 'hashed append-only factory trial ledger',
                                          'records': previous_lineage,
                                          'current_registration': current_registration},
        'native_reconciliation': compact_reconciliations,
        'sleeve_evidence': sleeve_result['report'],
        'cost_scenarios': [{'scenario': item['scenario'],
                            'audit': {key: value for key, value in item['audit'].items() if key != 'trades'},
                            'metrics': item['metrics']} for item in scenarios],
        'candidate_count': 1,
        'baseline': {'type': 'cash_no_trade', 'initial_equity': INITIAL_CASH,
                     'final_equity': INITIAL_CASH, 'net_pnl': 0.0, 'daily_return': 0.0},
        'eligible_signal_count': len(independent),
        'executed_signal_count': len(expected_executions),
        'execution_count': [item['audit']['executed_trade_count'] for item in scenarios],
        'trade_count': len(expected_executions),
    }
    if folder is not None:
        native_artifacts = {}
        for item in scenarios:
            name = item['scenario']
            for kind in ('fills', 'equity', 'orders', 'accounting', 'portfolio_state'):
                artifact = folder / f'{kind}_{name}.parquet'
                frame = pl.read_parquet(artifact)
                native_artifacts[artifact.name] = {'sha256': file_hash(artifact), 'rows': frame.height}
        if 'sleeves' in sleeve_result:
            from dataclasses import asdict

            sleeve_path = folder / 'portfolio_sleeves.json'
            sleeve_path.write_text(json.dumps([asdict(sleeve) for sleeve in sleeve_result['sleeves']],
                                              sort_keys=True, allow_nan=False), encoding='utf-8')
            native_artifacts[sleeve_path.name] = {'sha256': file_hash(sleeve_path),
                                                'sleeves': len(sleeve_result['sleeves'])}
        event_oracle = {
            'protocol_hash': spec.spec_hash,
            'candidate_signals': [stamp.isoformat() for stamp in independent],
            'executed_signals': [stamp.isoformat() for stamp in expected_executions],
            'orders_artifacts': {item['scenario']: f"orders_{item['scenario']}.parquet" for item in scenarios},
        }
        oracle_path = folder / 'event_oracle.json'
        oracle_path.write_text(
            json.dumps(event_oracle, sort_keys=True, separators=(',', ':'),
                       default=lambda value: value.isoformat() if isinstance(value, datetime) else str(value)),
            encoding='utf-8')
        native_artifacts[oracle_path.name] = {'sha256': file_hash(oracle_path),
                                              'candidate_signals': len(independent),
                                              'executions': len(expected_executions)}
        report['native_artifacts'] = native_artifacts
        (folder / 'event_evidence.json').write_text(
            json.dumps(report, sort_keys=True, indent=2, default=str), encoding='utf-8')
    return report


def run_bta_nq_event(spec: BtaNqMondayEventSpec, *, output_dir: str | Path | None = None) -> dict[str, Any]:
    """Audit BTA NQ Monday Bollinger ATR breakout prerequisites on Dukascopy index CFD data."""
    from src.data_vault import DataVault

    folder = Path(output_dir).resolve() if output_dir is not None else None
    vault_path = REPOSITORY / 'data/vault/markets_20261015/index_1h'
    if not vault_path.exists():
        from src.data_vault.market_materializer import materialize_price_markets
        materialize_price_markets(
            Path('/home/quant/dev/quant/ml4t-data/.data/store'), vault_path,
            category='index', granularity='1h',
            start='2012-01-01T00:00:00Z', end='2025-01-01T00:00:00Z',
            protected_test_start='2025-01-01T00:00:00Z',
            trusted_partitioning=False,
        )
    if not vault_path.exists():
        raise QuantError('BLOCKED_DATA', f'canonical index_1h vault missing: {vault_path}')
    vault = DataVault(vault_path)
    dev_start = datetime(2012, 1, 1, tzinfo=UTC)
    dev_end = datetime(2025, 1, 1, tzinfo=UTC)
    df = vault.load(end=dev_end).filter(
        (pl.col('symbol') == 'NQ') & (pl.col('timestamp') >= dev_start) & (pl.col('timestamp') < dev_end)
    ).sort('timestamp')
    if df.is_empty():
        raise QuantError('BLOCKED_DATA', 'No development NQ rows found in vault')

    report = {
        'status': 'BLOCKED_EXECUTION',
        'strategy_id': spec.strategy_id,
        'spec_hash': spec.spec_hash,
        'protocol': 'event',
        'market_scope': 'indices:usatechidxusd:60m',
        'instrument': 'Dukascopy US Tech 100 CFD proxy (usatechidxusd)',
        'development_window': ['2012-01-01T00:00:00Z', '2025-01-01T00:00:00Z'],
        'holdout_access': False,
        'development_rows': df.height,
        'reason': (
            'BLOCKED_EXECUTION: Native ml4t.backtest.Engine stop-order execution adapter is not qualified for '
            'hourly Dukascopy CFD bars. Hand-rolled Python simulation loops are prohibited by AGENTS.md; '
            'high-crossing approximations on 60m OHLC fabricate stop fills without verified intrabar quote depth, '
            'adverse gap execution, or independent cash/equity reconciliation. Also, Monday 23:00 America/New_York '
            'exit requires verified broker session calendar mapping rather than arbitrary end-of-day bar indexing.'
        ),
        'missing_requirements': [
            'Native ml4t.backtest.Engine stop-order execution adapter with intrabar queue priority and gap accounting.',
            'Verified America/New_York Monday session calendar with exact 23:00 exit and pause handling.',
            'Contemporaneous broker bid/ask spreads and financing evidence to replace placeholder assumptions.',
        ],
        'artifacts': {},
    }

    if folder is not None:
        evidence_path = folder / 'stage3_evidence.json'
        evidence_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding='utf-8')
        report['artifacts'] = {
            evidence_path.name: file_hash(evidence_path),
        }
        (folder / 'event_evidence.json').write_text(json.dumps(report, indent=2, sort_keys=True), encoding='utf-8')
    return report
