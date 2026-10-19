"""Sleeve casefile and append-only trial semantics.

A casefile is a validated, hashed record of one sleeve run: identity, feature
proof, cost qualification, carry provenance, the per-class gate table, the
terminal disposition and runtime identities. Validation happens before the file
is written, and nothing else is written by this module except one ledger entry
per attempt -- a rejected attempt leaves no casefile behind.

The ledger distinguishes a variation declared before an outcome from a change
made after one: the latter is recorded as a new trial and explicitly invalidates
the prior verdict.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .common import QuantError, append_trial, digest, safe_name, write_json
from .ts_spec import MarketClass, TimeSeriesSpec

DISPOSITIONS = {
    'QUALIFIED', 'FALSIFIED', 'BLOCKED', 'INCONCLUSIVE',
    'DIAGNOSTIC', 'PORTFOLIO_MODE', 'BLOCKED_MULTILEG', 'BLOCKED_NO_CONTRACT_CURVE',
}
REQUIRED_SECTIONS = ('identity', 'feature_proof', 'costs', 'carry',
                     'gates', 'disposition', 'runtime', 'ledger')
CARRY_STATUSES = {'MODELED', 'OBSERVED', 'NOT_APPLIED', 'UNKNOWN_NOT_MODELLED'}
COST_STATUSES = {'EXECUTION_QUALIFIED', 'DECLARED_ASSUMPTIONS'}
GATE_STATUSES = {'QUALIFIED', 'FALSIFIED', 'INCONCLUSIVE'}
PROFIT_STATUSES = {'AVAILABLE', 'UNAVAILABLE', 'INCONCLUSIVE', 'BLOCKED'}


def _hex64(value: Any, name: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise QuantError('INVALID_EVIDENCE', f'{name} must be a lowercase sha256 hex digest')


def validate_casefile(casefile: dict[str, Any]) -> None:
    if not isinstance(casefile, dict):
        raise QuantError('INVALID_EVIDENCE', 'Casefile must be a mapping')
    missing = [name for name in REQUIRED_SECTIONS if name not in casefile]
    if missing:
        raise QuantError('INVALID_EVIDENCE', f'Casefile is missing sections: {missing}')
    identity = casefile['identity']
    for key in ('sleeve_id', 'spec_hash', 'market_class', 'book_strategy'):
        if key not in identity:
            raise QuantError('INVALID_EVIDENCE', f'identity is missing {key}')
    safe_name(identity['sleeve_id'])
    _hex64(identity['spec_hash'], 'identity.spec_hash')
    if identity['market_class'] not in ('indices', 'metals', 'crypto'):
        raise QuantError('INVALID_EVIDENCE', 'identity.market_class is not a declared class')

    proof = casefile['feature_proof']
    if proof.get('status') != 'PASS':
        raise QuantError('INVALID_EVIDENCE', 'feature_proof must record a PASS')
    for key in ('input_sha256', 'output_sha256'):
        _hex64(proof.get(key), f'feature_proof.{key}')
    if not proof.get('checks'):
        raise QuantError('INVALID_EVIDENCE', 'feature_proof must record its cutoff checks')

    costs = casefile['costs']
    if costs.get('status') not in COST_STATUSES:
        raise QuantError('INVALID_EVIDENCE', 'costs.status is not a qualification state')
    _hex64(costs.get('sha256'), 'costs.sha256')

    carry = casefile['carry']
    if carry.get('status') not in CARRY_STATUSES:
        raise QuantError('INVALID_EVIDENCE', 'carry.status is not a declared financing state')
    if carry['status'] == 'MODELED' and not carry.get('curve'):
        raise QuantError('INVALID_EVIDENCE', 'modeled carry must name its curve')

    gates = casefile['gates']
    if gates.get('status') not in GATE_STATUSES:
        raise QuantError('INVALID_EVIDENCE', 'gates.status is not a gate outcome')
    if not isinstance(gates.get('checks'), dict) or not gates['checks']:
        raise QuantError('INVALID_EVIDENCE', 'gates.checks must record every gate')

    disposition = casefile['disposition']
    if disposition.get('status') not in DISPOSITIONS:
        raise QuantError('INVALID_EVIDENCE', f'disposition {disposition.get("status")} is not terminal')
    if disposition['status'] == 'BLOCKED' and not disposition.get('reason'):
        raise QuantError('INVALID_EVIDENCE', 'a BLOCKED disposition needs a reason')

    runtime = casefile['runtime']
    for key in ('code_hash', 'panel_hash'):
        _hex64(runtime.get(key), f'runtime.{key}')
    if not runtime.get('vault_root'):
        raise QuantError('INVALID_EVIDENCE', 'runtime.vault_root is required')

    ledger = casefile['ledger']
    if not isinstance(ledger.get('attempts'), list) or not ledger.get('last_hash'):
        raise QuantError('INVALID_EVIDENCE', 'ledger must record attempts and the last hash')
    _hex64(ledger['last_hash'], 'ledger.last_hash')

    # Optional, explicitly non-gating explanatory evidence. It is validated here
    # so a casefile cannot smuggle a diagnostic into the gate/disposition surface.
    diagnostic = casefile.get('profit_concentration')
    if diagnostic is not None:
        if not isinstance(diagnostic, dict):
            raise QuantError('INVALID_EVIDENCE', 'profit_concentration must be a mapping')
        if diagnostic.get('status') not in PROFIT_STATUSES:
            raise QuantError('INVALID_EVIDENCE', 'profit_concentration.status is not terminal')
        if diagnostic.get('gating') is not False:
            raise QuantError('INVALID_EVIDENCE', 'profit_concentration must be non-gating')
        _hex64(diagnostic.get('artifact_sha256'), 'profit_concentration.artifact_sha256')
        hashes = diagnostic.get('source_hashes')
        if not isinstance(hashes, dict) or not hashes:
            raise QuantError('INVALID_EVIDENCE', 'profit_concentration needs source hashes')
        for key, value in hashes.items():
            _hex64(value, f'profit_concentration.source_hashes.{key}')
        if diagnostic['status'] in ('BLOCKED', 'INCONCLUSIVE') and not diagnostic.get('reason'):
            raise QuantError('INVALID_EVIDENCE',
                             'A blocked/inconclusive profit diagnostic needs a reason')


def build_casefile(*, spec: TimeSeriesSpec, market_class: MarketClass,
                   feature_proof: dict[str, Any], qualification: dict[str, Any],
                   carry_metadata: dict[str, Any] | None, gate_report: dict[str, Any],
                   disposition: dict[str, Any], code_hash: str, panel_hash: str,
                   vault_root: str, attempts: list[dict[str, Any]],
                   last_hash: str,
                   profit_concentration: dict[str, Any] | None = None) -> dict[str, Any]:
    carry = (carry_metadata or {}).get('status', 'NOT_APPLIED')
    casefile = {
        'schema_version': 1,
        'scope': 'time_series_sleeve',
        'identity': {
            'sleeve_id': spec.sleeve_id,
            'spec_hash': spec.spec_hash,
            'selection_family_id': spec.selection_family_id,
            'book_strategy': spec.book_strategy,
            'market_class': market_class.name,
            'symbols': list(market_class.symbols),
        },
        'feature_proof': feature_proof,
        'costs': {'status': qualification['status'],
                  'values': qualification['costs'],
                  'assumptions': qualification['assumptions'],
                  'sha256': qualification['sha256']},
        'carry': {'status': carry,
                  'curve': (carry_metadata or {}).get('curve'),
                  'sign_convention': (carry_metadata or {}).get('sign_convention'),
                  'sha256': (carry_metadata or {}).get('sha256')},
        'gates': gate_report,
        'disposition': disposition,
        'runtime': {'code_hash': code_hash, 'panel_hash': panel_hash,
                    'vault_root': vault_root, 'holdout_access': False},
        'ledger': {'attempts': attempts, 'last_hash': last_hash},
    }
    if profit_concentration is not None:
        casefile['profit_concentration'] = profit_concentration
    validate_casefile(casefile)
    casefile['casefile_sha256'] = digest({k: v for k, v in casefile.items()
                                          if k != 'casefile_sha256'})
    return casefile


def write_casefile(casefile: dict[str, Any], directory: str | Path) -> dict[str, str]:
    """Validate before touching the filesystem; write one hashed casefile."""
    validate_casefile(casefile)
    expected = digest({k: v for k, v in casefile.items() if k != 'casefile_sha256'})
    if casefile.get('casefile_sha256') != expected:
        raise QuantError('INVALID_EVIDENCE', 'Casefile hash does not match its contents')
    target = Path(directory) / 'casefile.json'
    write_json(target, casefile)
    return {'path': str(target), 'sha256': casefile['casefile_sha256']}


def read_trials(root: str | Path) -> list[dict[str, Any]]:
    """Read and verify the append-only ledger chain."""
    path = Path(root) / 'trial_ledger.jsonl'
    if not path.exists():
        return []
    records, previous = [], '0' * 64
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        stored = record.pop('record_hash', None)
        if record.get('previous_hash') != previous or digest(record) != stored:
            raise QuantError('INVALID_EVIDENCE', f'Trial ledger chain is broken at line {number}')
        previous = stored
        records.append({**record, 'record_hash': stored})
    return records


def record_attempt(root: str | Path, *, spec: TimeSeriesSpec, market_class: MarketClass,
                   event: str, status: str, reason: str | None = None,
                   artifacts: dict[str, Any] | None = None) -> dict[str, Any]:
    """Append exactly one ledger entry; never write a casefile or artifact."""
    record = append_trial(Path(root), {
        'casefile': 'ts_sleeve',
        'event': event,
        'status': status,
        'sleeve_id': spec.sleeve_id,
        'selection_family_id': spec.selection_family_id,
        'spec_hash': spec.spec_hash,
        'market_class': market_class.name,
        'holdout_access': False,
        'reason': reason,
        'artifacts': artifacts or {},
    })
    return record


def classify_gate_change(root: str | Path, *, selection_family_id: str,
                         spec_hash: str, change: dict[str, Any]) -> dict[str, Any]:
    """A change before an outcome is a variation; after one it is a new trial."""
    records = read_trials(root)
    outcomes = [r for r in records
                if r.get('event') == 'outcome'
                and r.get('selection_family_id') == selection_family_id
                and r.get('record_hash') not in
                {voided for prior in records for voided in prior.get('invalidates', [])}]
    kind = 'new_trial' if outcomes else 'predeclared_variation'
    record = append_trial(Path(root), {
        'casefile': 'ts_sleeve',
        'event': kind,
        'status': 'RECLASSIFIED' if outcomes else 'DECLARED',
        'selection_family_id': selection_family_id,
        'spec_hash': spec_hash,
        'change': change,
        'invalidates': [r['record_hash'] for r in outcomes],
        'holdout_access': False,
    })
    return record


def active_outcomes(root: str | Path, selection_family_id: str) -> list[dict[str, Any]]:
    """Outcomes that no later new-trial record has invalidated."""
    records = read_trials(root)
    voided = {h for r in records for h in r.get('invalidates', [])}
    return [r for r in records
            if r.get('event') == 'outcome'
            and r.get('selection_family_id') == selection_family_id
            and r.get('record_hash') not in voided]
