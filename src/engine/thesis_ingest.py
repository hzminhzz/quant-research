"""Convert explicit machine-readable thesis clauses to strict executable YAML."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .common import QuantError
from .spec_parser import CandidateSpec, export_spec

_ROOT_FIELDS = {
    'format', 'candidate_id', 'selection_family_id', 'status', 'research_mode', 'created_on',
    'timezone_for_report', 'not_a_frozen_session', 'not_execution_approved', 'source_references',
    'economic_thesis', 'thesis', 'mechanism', 'instruments', 'market', 'data_requirements',
    'feature_contracts', 'strategy_rules', 'entry_and_basket_construction_rules',
    'signal_and_execution_clock', 'bar_seconds', 'sizing', 'cost_assumptions', 'baseline',
    'signal', 'development_evaluation', 'primary_falsifier', 'acceptance_and_stop_rules',
    'parity_and_causality_tests', 'known_adaptations', 'verified_facts', 'assumptions',
    'unresolved_blockers', 'candidate_spec',
}
_REQUIRED_SPEC_FIELDS = {
    'candidate_id', 'selection_family_id', 'thesis', 'panel_root', 'windows', 'features',
    'signal', 'baseline', 'universe', 'allocation', 'costs', 'gates', 'benchmark', 'bar_seconds',
}
_GATE_FIELDS = {
    'minimum_ic', 'minimum_hac_t', 'minimum_ic_observations', 'require_baseline_ic_improvement',
    'dsr_probability', 'maximum_abs_beta', 'maximum_short_stop_fraction', 'minimum_completed_trades',
    'require_baseline_sharpe_improvement', 'minimum_daily_observations',
}


def _fail(message: str) -> None:
    raise QuantError('INVALID_THESIS', message)


def _mapping(value: Any, field: str) -> dict:
    if not isinstance(value, dict):
        _fail(f'{field} must be a structured mapping')
    return value


def _unknown(mapping: dict, allowed: set[str], field: str) -> None:
    fields = sorted(set(mapping) - allowed)
    if fields:
        _fail(f'Unmapped fields in {field}: ' + ', '.join(fields))


def _number(value: Any, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f'{field} must be an explicit numeric value')


def _from_raw(document: dict) -> dict:
    unknown = sorted(set(document) - _ROOT_FIELDS)
    if unknown:
        _fail('Unmapped thesis fields: ' + ', '.join(unknown))

    required_top = ('candidate_id', 'selection_family_id', 'economic_thesis', 'data_requirements',
                    'feature_contracts', 'entry_and_basket_construction_rules', 'development_evaluation',
                    'cost_assumptions', 'primary_falsifier', 'acceptance_and_stop_rules', 'signal',
                    'baseline', 'market', 'bar_seconds')
    missing = [name for name in required_top if name not in document]
    if missing:
        _fail('Raw thesis is missing explicit fields: ' + ', '.join(missing))

    thesis = _mapping(document['economic_thesis'], 'economic_thesis')
    _unknown(thesis, {'statement', 'economic_null', 'direction', 'horizon',
                      'independent_portfolio_alpha'}, 'economic_thesis')
    if not isinstance(thesis.get('statement'), str) or not thesis['statement'].strip():
        _fail('economic_thesis.statement must contain the explicit thesis text')
    data = _mapping(document['data_requirements'], 'data_requirements')
    _unknown(data, {'panel_root', 'required', 'forbidden_shortcuts', 'source_audit_gate'}, 'data_requirements')
    if not isinstance(data.get('panel_root'), str) or not data['panel_root']:
        _fail('data_requirements.panel_root must explicitly identify the local panel')

    features_raw = document['feature_contracts']
    if not isinstance(features_raw, list) or not features_raw:
        _fail('feature_contracts must be a nonempty list of explicit feature definitions')
    features = []
    for index, raw in enumerate(features_raw):
        field = f'feature_contracts[{index}]'
        feature = _mapping(raw, field)
        _unknown(feature, {'name', 'native', 'params', 'expr', 'calculation', 'native_status'}, field)
        if 'calculation' in feature:
            if 'expr' in feature:
                _fail(f'{field} cannot specify both calculation and expr')
            feature['expr'] = feature.pop('calculation')
        native_defined = feature.get('native') is not None
        expr_defined = feature.get('expr') is not None
        if 'name' not in feature or not (native_defined ^ expr_defined):
            _fail(f'{field} needs name and exactly one explicit native or calculation/expr definition')
        if isinstance(feature.get('expr'), str):
            _fail(f'{field}.calculation must be a structured operation tree, not prose')
        features.append(feature)

    rules = _mapping(document['entry_and_basket_construction_rules'], 'entry_and_basket_construction_rules')
    _unknown(rules, {'universe', 'allocation'}, 'entry_and_basket_construction_rules')
    if not {'universe', 'allocation'} <= set(rules):
        _fail('entry_and_basket_construction_rules must explicitly provide universe and allocation mappings')

    development = _mapping(document['development_evaluation'], 'development_evaluation')
    _unknown(development, {'windows', 'interval'}, 'development_evaluation')
    if development.get('interval') != '[start,end)':
        _fail("development_evaluation.interval must explicitly be '[start,end)'")
    windows = _mapping(development.get('windows'), 'development_evaluation.windows')
    if set(windows) != {'train', 'validation', 'protected'}:
        _fail('development_evaluation.windows must explicitly define train, validation and protected')
    for name, window_value in windows.items():
        window = _mapping(window_value, f'development_evaluation.windows.{name}')
        _unknown(window, {'start', 'end'}, f'development_evaluation.windows.{name}')
        if set(window) != {'start', 'end'}:
            _fail(f'development_evaluation.windows.{name} requires explicit start and end')

    cost_source = _mapping(document['cost_assumptions'], 'cost_assumptions')
    cost_keys = {'commission_bps_one_way', 'slippage_bps_one_way', 'spread_bps', 'spread_included_in_slippage'}
    _unknown(cost_source, cost_keys | {'status', 'buy_fill_model', 'sell_fill_model', 'commission',
                                       'financing', 'spread', 'spread_double_counting', 'financing_roll',
                                       'currency_conversion', 'slippage', 'market_impact', 'source_authority'},
             'cost_assumptions')
    if not {'commission_bps_one_way', 'slippage_bps_one_way', 'spread_bps'} <= set(cost_source):
        _fail('cost_assumptions must explicitly provide numeric one-way commission, slippage and spread')
    for name in ('commission_bps_one_way', 'slippage_bps_one_way', 'spread_bps'):
        _number(cost_source[name], f'cost_assumptions.{name}')
    if 'spread_included_in_slippage' not in cost_source:
        _fail('cost_assumptions.spread_included_in_slippage must explicitly state spread treatment')

    primary = _mapping(document['primary_falsifier'], 'primary_falsifier')
    acceptance = _mapping(document['acceptance_and_stop_rules'], 'acceptance_and_stop_rules')
    _unknown(primary, {'gates'}, 'primary_falsifier')
    _unknown(acceptance, {'gates'}, 'acceptance_and_stop_rules')
    primary_gates = _mapping(primary.get('gates'), 'primary_falsifier.gates')
    acceptance_gates = _mapping(acceptance.get('gates'), 'acceptance_and_stop_rules.gates')
    _unknown(primary_gates, _GATE_FIELDS, 'primary_falsifier.gates')
    _unknown(acceptance_gates, _GATE_FIELDS, 'acceptance_and_stop_rules.gates')
    gates = dict(primary_gates)
    overlap = set(gates) & set(acceptance_gates)
    if overlap:
        _fail('Duplicate gate declarations in primary_falsifier and acceptance_and_stop_rules: ' +
              ', '.join(sorted(overlap)))
    gates.update(acceptance_gates)
    if not gates:
        _fail('Provide explicit numeric gates under primary_falsifier.gates or acceptance_and_stop_rules.gates')

    market = document['market']
    if not isinstance(market, str) or not market.strip():
        _fail('market must explicitly name the executable benchmark/instrument')
    raw = {
        'candidate_id': document['candidate_id'],
        'selection_family_id': document['selection_family_id'],
        'source_spec_status': 'exact',
        'thesis': thesis['statement'],
        'panel_root': data['panel_root'],
        'windows': windows,
        'features': features,
        'signal': document['signal'],
        'baseline': document['baseline'],
        'universe': rules['universe'],
        'allocation': rules['allocation'],
        'costs': cost_source,
        'gates': gates,
        'benchmark': market,
        'bar_seconds': document['bar_seconds'],
    }
    missing = sorted(_REQUIRED_SPEC_FIELDS - set(raw))
    if missing:
        _fail('Raw thesis cannot construct CandidateSpec; missing: ' + ', '.join(missing))
    return raw


def convert_thesis(source: str | Path, output: str | Path) -> CandidateSpec:
    """Convert raw explicit clauses or validate a complete ``candidate_spec``.

    Narrative clauses are never interpreted. All required raw semantic choices
    must be represented by typed fields before any output is written.
    """
    try:
        with Path(source).open(encoding='utf-8') as handle:
            document = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise QuantError('INVALID_THESIS', f'Cannot read thesis YAML: {exc}') from exc
    if not isinstance(document, dict):
        _fail('Thesis YAML root must be a mapping')

    if 'candidate_spec' in document:
        extras = set(document) - _ROOT_FIELDS
        if extras:
            _fail('Unmapped thesis fields: ' + ', '.join(sorted(extras)))
        mapping = document['candidate_spec']
        if not isinstance(mapping, dict):
            _fail('candidate_spec must be a structured mapping')
        missing = sorted(_REQUIRED_SPEC_FIELDS - set(mapping))
        if missing:
            _fail('candidate_spec must explicitly declare: ' + ', '.join(missing))
        costs = _mapping(mapping.get('costs'), 'candidate_spec.costs')
        required_costs = {'commission_bps_one_way', 'slippage_bps_one_way', 'spread_bps',
                          'spread_included_in_slippage'}
        missing_costs = sorted(required_costs - set(costs))
        if missing_costs:
            _fail('candidate_spec.costs must explicitly declare: ' + ', '.join(missing_costs))
        if document.get('candidate_id', mapping.get('candidate_id')) != mapping.get('candidate_id'):
            _fail('Top-level candidate_id must match candidate_spec.candidate_id')
    else:
        mapping = _from_raw(document)

    try:
        spec = CandidateSpec.model_validate(mapping)
    except (ValueError, TypeError) as exc:
        raise QuantError('INVALID_THESIS', f'Executable thesis mapping is invalid: {exc}') from exc
    export_spec(spec, output)
    return spec
