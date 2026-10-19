"""Development-only execution of one declared sleeve/class pair.

The pipeline is: load only certified development rows, bind financing (modeled
for price-only classes, observed for perp funding), compile features with the
causal proof, allocate target weights, run the qualified native simulation at
base and doubled costs, evaluate the seven gates against the class's aligned
trial returns, then write a casefile and one ledger entry per attempt.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from .carry_model import CarryConfig, CarryProduct, build_carry_sidecar, load_rate_curve
from .common import QuantError, digest, file_hash, read_json
from .cost_qualification import qualify_costs, run_qualified_ts
from .holdout import guard_development_read
from .profit_concentration import diagnose_sleeve, write_profit_concentration
from .sleeve_matrix import load_frozen, require_declaration, require_symbols
from .ts_allocator import allocate_ts
from .ts_casefile import build_casefile, read_trials, record_attempt, write_casefile
from .ts_features import compile_ts_and_verify
from .ts_gates import class_dsr, evaluate_class, forecast_return_hac
from .ts_spec import MarketClass, TimeSeriesSpec, parse_ts_spec

REPO = Path(__file__).resolve().parents[2]
MATRIX_DIR = REPO / 'config/sleeves/advanced_futures_30'
STORE = Path('/home/quant/dev/quant/ml4t-data/.data/store')
EVIDENCE_ROOT = 'sleeves_advanced_futures_30'


LoadPanel = Callable[[MarketClass, datetime, datetime], pl.DataFrame]
LoadFunding = Callable[[MarketClass, datetime, datetime], pl.DataFrame]
LoadCurve = Callable[[str, datetime, datetime], pl.DataFrame]
LoadManifest = Callable[[MarketClass], dict]


@dataclass
class SleeveLoaders:
    panel: LoadPanel | None = None
    funding: LoadFunding | None = None
    curve: LoadCurve | None = None
    manifest: LoadManifest | None = None
    products: dict[str, CarryProduct] | None = None


def _default_panel(market_class: MarketClass, start: datetime, end: datetime) -> pl.DataFrame:
    from src.data_vault import DataVault
    return DataVault(market_class.panel_root).load(start=start, end=end)


def _default_funding(market_class: MarketClass, start: datetime, end: datetime) -> pl.DataFrame:
    from src.data_vault import DataVault
    return DataVault(market_class.panel_root).load_funding(start, end)


def _default_manifest(market_class: MarketClass) -> dict:
    path = Path(market_class.panel_root) / 'manifest.json'
    if not path.exists():
        raise QuantError('BLOCKED_DATA', f'No vault manifest at {path}')
    return read_json(path)


def load_products(path: str | Path = MATRIX_DIR / 'carry_products.yaml') -> dict[str, CarryProduct]:
    try:
        payload = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    except (OSError, yaml.YAMLError) as exc:
        raise QuantError('BLOCKED_DATA', f'Carry product assumptions unreadable: {exc}') from exc
    products = {}
    for symbol, values in (payload or {}).get('products', {}).items():
        products[symbol] = CarryProduct(symbol=symbol, **values)
    return products


def _lookback(features) -> int:
    """Longest declared window, shift or EMA period, used as warm-up."""
    longest = 1

    def walk(node: Any) -> None:
        nonlocal longest
        if isinstance(node, dict):
            if isinstance(node.get('window'), int):
                longest = max(longest, node['window'])
            if isinstance(node.get('periods'), int):
                longest = max(longest, node['periods'])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for feature in features:
        if feature.native == 'ema' or feature.native == 'atr':
            longest = max(longest, int(feature.params.get('period', 1)))
        walk(feature.expr)
    return longest


def inject_modeled_carry(panel: pl.DataFrame, sidecar, bar_seconds: int) -> pl.DataFrame:
    """Spread each daily settlement rate across that day's bars for features."""
    bars_per_day = max(1, 86400 // bar_seconds)
    rates = (sidecar.events.select('timestamp', 'symbol', 'funding_rate')
             .with_columns((pl.col('funding_rate') / bars_per_day).alias('bar_rate'))
             .sort('symbol', 'timestamp'))
    return (panel.sort('symbol', 'timestamp')
            .join_asof(rates, on='timestamp', by='symbol', strategy='backward',
                       check_sortedness=False)
            .with_columns(pl.col('bar_rate').fill_null(0.0).alias('carry_rate'))
            .drop('bar_rate', 'funding_rate')
            .sort('symbol', 'timestamp'))


def _split_returns(daily: pl.DataFrame, spec: TimeSeriesSpec) -> tuple[pl.Series, pl.Series]:
    frame = daily.with_columns(pl.col('date').cast(pl.Date))
    train = frame.filter((pl.col('date') >= spec.windows.train.start.date())
                         & (pl.col('date') < spec.windows.train.end.date()))
    validation = frame.filter((pl.col('date') >= spec.windows.validation.start.date())
                              & (pl.col('date') < spec.windows.validation.end.date()))
    return train['return'].drop_nulls(), validation['return'].drop_nulls()


def _trial_returns(run_log: Path, market_class: MarketClass) -> tuple[pl.DataFrame, list[str]]:
    """Aligned return matrix for this class, from hashed ledger artifacts only."""
    entries = [r for r in read_trials(run_log)
               if r.get('event') == 'trial_returns' and r.get('market_class') == market_class.name]
    frames, used = [], []
    for entry in entries:
        path = Path(run_log) / entry['artifacts']['returns']
        if not path.is_file() or file_hash(path) != entry['artifacts']['sha256']:
            raise QuantError('INVALID_EVIDENCE', f'Returns artifact changed: {path}')
        column = entry['sleeve_id']
        series = (pl.read_parquet(path).select(pl.col('date').alias('timestamp'),
                                               pl.col('return').alias(column))
                  .drop_nulls().sort('timestamp'))
        frames.append(series)
        used.append(column)
    if not frames:
        return pl.DataFrame(), []
    aligned = frames[0]
    for frame in frames[1:]:
        aligned = aligned.join(frame, on='timestamp', how='inner')
    return aligned.sort('timestamp'), used


def run_sleeve(spec_path: str | Path, market_class_name: str, *,
               run_log: str | Path = REPO / 'run_log',
               loaders: SleeveLoaders | None = None,
               stress: bool = True) -> dict[str, Any]:
    """Execute one declared pair; every attempt appends exactly one ledger entry."""
    loaders = loaders or SleeveLoaders()
    panel_loader = loaders.panel or _default_panel
    funding_loader = loaders.funding or _default_funding
    manifest_loader = loaders.manifest or _default_manifest
    curve_loader = loaders.curve or (lambda name, start, end: load_rate_curve(STORE, name, start=start, end=end))
    products = loaders.products if loaders.products is not None else load_products()
    log = Path(run_log)
    spec = parse_ts_spec(spec_path)
    market_class = next((c for c in spec.market_classes if c.name == market_class_name), None)
    if market_class is None:
        raise QuantError('INVALID_SPEC', f'{spec.sleeve_id} does not declare {market_class_name}')
    matrix, matrix_sha = load_frozen(MATRIX_DIR)
    declaration = require_declaration(matrix, spec, market_class,
                                      matrix_sha=matrix_sha, expected_sha=matrix_sha)
    warmup = _lookback(spec.features) * market_class.bar_seconds
    start = spec.windows.train.start - timedelta(seconds=warmup)
    end = spec.windows.validation.end
    guard_development_read(end, spec.windows.protected.start)
    try:
        panel = panel_loader(market_class, start, end)
        require_symbols(market_class, set(panel['symbol'].unique().to_list()))
        qualification_manifest = manifest_loader(market_class)
        if market_class.carry.mode == 'modeled':
            if not (market_class.carry.curve and market_class.carry.tenor):
                raise QuantError('INVALID_SPEC', 'Modeled carry requires a curve and tenor')
            curve = curve_loader(market_class.carry.curve, start, end)
            selected = [products[s] for s in market_class.symbols if s in products]
            if len(selected) != len(market_class.symbols):
                missing = sorted(set(market_class.symbols) - set(products))
                raise QuantError('BLOCKED_DATA', f'No carry product assumptions for {missing}')
            panel_start = panel['timestamp'].min()
            panel_end = panel['timestamp'].max() + timedelta(seconds=market_class.bar_seconds)
            sidecar = build_carry_sidecar(panel, curve, selected,
                                          CarryConfig(curve_name=market_class.carry.curve,
                                                      tenor=market_class.carry.tenor),
                                          start=panel_start, end=panel_end)
            panel = inject_modeled_carry(panel, sidecar, market_class.bar_seconds)
            events, carry_metadata = sidecar.events, sidecar.metadata
        elif market_class.carry.mode == 'observed':
            events = funding_loader(market_class, start, end)
            carry_metadata = {'status': 'OBSERVED', 'sign_convention': 'positive_rate_charges_longs'}
        else:
            raise QuantError('BLOCKED_DATA', f'{market_class.name} financing is not declared')

        features, proof = compile_ts_and_verify(
            panel, spec, market_class, isolate=spec.python_feature_artifact is not None)
        targets = allocate_ts(features, spec, market_class)
        result = run_qualified_ts(panel, targets, spec, market_class,
                                  vault_manifest=qualification_manifest,
                                  carry_events=events, carry_metadata=carry_metadata)
        train_returns, validation_returns = _split_returns(result.daily, spec)
        if stress:
            doubled = spec.costs.model_copy(update={
                'commission_bps_one_way': spec.costs.commission_bps_one_way * 2,
                'slippage_bps_one_way': spec.costs.slippage_bps_one_way * 2})
            from .ts_runner import run_native_ts
            stress_result = run_native_ts(panel, targets, spec.model_copy(update={'costs': doubled}),
                                          market_class, carry_events=events,
                                          carry_metadata=carry_metadata)
            _, stress_returns = _split_returns(stress_result.daily, spec)
        else:
            stress_returns = validation_returns

        folder = (log / EVIDENCE_ROOT / market_class.name / spec.sleeve_id)
        folder.mkdir(parents=True, exist_ok=True)
        returns_path = folder / 'daily.parquet'
        result.daily.write_parquet(returns_path)
        record_attempt(log, spec=spec, market_class=market_class, event='trial_returns',
                       status='RETURNS', artifacts={
                           'returns': str(returns_path.relative_to(log)),
                           'sha256': file_hash(returns_path)})
        # Explanatory only. A diagnostic failure is recorded as BLOCKED and never
        # feeds the seven gates, the disposition, the trial ledger or selection.
        diagnostic = diagnose_sleeve(
            daily=result.daily, periods_per_year=market_class.periods_per_year,
            initial_cash=spec.initial_cash, panel=panel, fills=result.fills,
            funding=result.funding,
            identity={'sleeve_id': spec.sleeve_id, 'spec_hash': spec.spec_hash,
                      'market_class': market_class.name,
                      'selection_family_id': spec.selection_family_id},
            provenance={'engine': 'ml4t-backtest==0.1.7 native fills/equity',
                        'development_window_only': True,
                        'daily_source': str(returns_path.relative_to(log))},
            strict=False)
        diagnostic_written = write_profit_concentration(diagnostic, folder)
        diagnostic_summary = {
            **diagnostic_written['summary'],
            'artifact': str(diagnostic_written['path'].relative_to(log)),
        }
        matrix_frame, trials = _trial_returns(log, market_class)
        dsr_result = class_dsr(matrix_frame, market_class.periods_per_year)
        dsr_path = folder / 'dsr_inputs.parquet'
        matrix_frame.write_parquet(dsr_path)
        forecast_check = forecast_return_hac(features, spec)
        report = evaluate_class(spec, market_class, train_returns=train_returns,
                                validation_returns=validation_returns,
                                stress_returns=stress_returns,
                                forecast_check=forecast_check,
                                class_dsr_result=dsr_result)
        report['dsr_input_sha256'] = file_hash(dsr_path)
        report['dsr_trials'] = trials
        disposition = {'status': report['status']}
        if report['status'] == 'INCONCLUSIVE':
            disposition['reason'] = report.get('reason', 'Insufficient evidence')
        qualification = qualify_costs(spec, market_class,
                                      vault_manifest=qualification_manifest,
                                      carry_metadata=carry_metadata)
        attempts = [{'sleeve_id': r.get('sleeve_id'), 'event': r.get('event'),
                     'status': r.get('status'), 'hash': r.get('record_hash')}
                    for r in read_trials(log)
                    if r.get('sleeve_id') == spec.sleeve_id
                    and r.get('market_class') == market_class.name]
        last_hash = read_trials(log)[-1]['record_hash']
        casefile = build_casefile(
            spec=spec, market_class=market_class,
            feature_proof={'status': proof.status,
                           'input_sha256': digest({'source': market_class.panel_root,
                                                   'rows': panel.height,
                                                   'symbols': sorted(market_class.symbols),
                                                   'first': panel['timestamp'].min().isoformat(),
                                                   'last': panel['timestamp'].max().isoformat()}),
                           'output_sha256': digest({'rows': features.height,
                                                    'columns': list(features.columns)}),
                           'checks': list(proof.cutoffs)},
            qualification=qualification.to_dict(), carry_metadata=carry_metadata,
            gate_report=report, disposition=disposition,
            code_hash=_code_hash(), panel_hash=qualification_manifest.get('manifest_hash', digest(market_class.panel_root)),
            vault_root=market_class.panel_root, attempts=attempts, last_hash=last_hash,
            profit_concentration=diagnostic_summary)
        write_casefile(casefile, folder)
        record_attempt(log, spec=spec, market_class=market_class, event='outcome',
                       status=report['status'], artifacts={
                           'casefile': str((folder / 'casefile.json').relative_to(log)),
                           'sha256': casefile['casefile_sha256']})
        return {'sleeve_id': spec.sleeve_id, 'market_class': market_class.name,
                'status': report['status'], 'declaration': declaration,
                'casefile_sha256': casefile['casefile_sha256'], 'report': report,
                'profit_concentration': diagnostic_summary}
    except QuantError as exc:
        record_attempt(log, spec=spec, market_class=market_class, event='outcome',
                       status=exc.status, reason=exc.reason)
        return {'sleeve_id': spec.sleeve_id, 'market_class': market_class.name,
                'status': exc.status, 'reason': exc.reason}


def _code_hash() -> str:
    from .common import runtime_identity
    return runtime_identity()


def run_spec(spec_path: str | Path, *, run_log: str | Path = REPO / 'run_log',
             loaders: SleeveLoaders | None = None,
             market_classes: list[str] | None = None) -> dict[str, Any]:
    spec = parse_ts_spec(spec_path)
    names = market_classes or [c.name for c in spec.market_classes]
    results = [run_sleeve(spec_path, name, run_log=run_log, loaders=loaders) for name in names]
    return {'sleeve_id': spec.sleeve_id, 'results': results, 'status': 'COMPLETED'}
