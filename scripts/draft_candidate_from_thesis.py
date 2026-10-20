"""Draft an executable CandidateSpec skeleton from a descriptive inbox thesis.

This tool never invents a formula, gate, window or cost. It maps only fields
that are already explicit and unambiguous in the source document, then reports
every remaining gap by exact dotted path so an author or agent can fill it.

Exit codes follow the factory convention:
  0  draft written; every required field was already present
  3  draft written with declared gaps (``GAPS``); not yet executable
  2  the source could not be read or is not a mapping
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.engine.spec_parser as spec_parser

# The required-spec vocabulary lives in the ingest module, which is the
# authoritative statement of what an executable CandidateSpec needs.
from src.engine.thesis_ingest import _REQUIRED_SPEC_FIELDS

# Canonical executable field -> ordered candidate source paths. The first
# path that yields a value wins; a later path is never merged into an earlier
# one, so a partially-populated dialect cannot half-fill a field.
_FIELD_SOURCES: dict[str, tuple[str, ...]] = {
    'candidate_id': ('candidate_id', 'identity.candidate_id'),
    'selection_family_id': ('selection_family_id', 'identity.selection_family_id'),
    'thesis': ('thesis', 'economic_thesis.statement', 'economic_thesis.hypothesis'),
    'panel_root': ('panel_root', 'data_requirements.panel_root'),
    'windows': ('windows', 'development_evaluation.windows'),
    'features': ('features', 'feature_contracts'),
    'signal': ('signal',),
    'baseline': ('baseline',),
    'universe': ('universe',),
    'allocation': ('allocation',),
    'costs': ('costs', 'cost_assumptions'),
    'gates': ('gates',),
    'benchmark': ('benchmark', 'market', 'markets_and_data.market_benchmark'),
    'bar_seconds': ('bar_seconds',),
}

# Nested-only paths that carry a machine-readable value under a different name.
_NESTED_SOURCES: dict[str, tuple[str, ...]] = {
    'windows': ('research_evaluation.proposed_periods',),
    'universe': ('markets_and_data.instruments',),
    'costs': ('research_evaluation.cost_model_requirements',),
}

# Fields whose absence is expected for a descriptive thesis. They are reported,
# never guessed: each could be written several defensible ways.
_AUTHOR_REQUIRED = ('features', 'signal', 'baseline', 'universe', 'allocation',
                    'gates', 'bar_seconds', 'panel_root')


def _at(document: Any, path: str) -> Any:
    value: Any = document
    for part in path.split('.'):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _first(document: dict, paths: tuple[str, ...]) -> tuple[Any, str | None]:
    for path in paths:
        value = _at(document, path)
        if value is not None:
            return value, path
    return None, None


def _costs_flat(raw: Any) -> dict | None:
    """Map cost vocabulary only when every required numeric is explicit.

    ``total_round_trip_bps_per_leg`` and the funding prose are dropped: the
    executable schema takes one-way commission and slippage separately, and
    deriving one from the other would invent an assumption.
    """
    if not isinstance(raw, dict):
        return None
    commission = raw.get('commission_bps_one_way', raw.get('taker_fee_bps'))
    slippage = raw.get('slippage_bps_one_way', raw.get('slippage_bps'))
    spread = raw.get('spread_bps', 0.0)
    if commission is None or slippage is None:
        return None
    if any(isinstance(v, bool) or not isinstance(v, (int, float))
           for v in (commission, slippage, spread)):
        return None
    return {
        'commission_bps_one_way': float(commission),
        'slippage_bps_one_way': float(slippage),
        'spread_bps': float(spread),
        'spread_included_in_slippage': bool(raw.get('spread_included_in_slippage', True)),
    }


# Executable shapes accepted per field. A value that does not already have the
# executable shape is reported as a gap instead of being copied through: prose
# dicts and prose strings are never passed off as a specification.
_STR_FIELDS = frozenset({'candidate_id', 'selection_family_id', 'thesis', 'panel_root',
                         'signal', 'baseline', 'benchmark'})
_NUM_FIELDS = frozenset({'bar_seconds'})


def _executable(field: str, value: Any) -> Any:
    """Return ``value`` when it already has the executable shape, else ``None``."""
    if value is None:
        return None
    if field in _STR_FIELDS:
        return value if isinstance(value, str) and value.strip() else None
    if field in _NUM_FIELDS:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return value
    if field == 'features':
        if not isinstance(value, list) or not value:
            return None
        # Each entry must already name a feature and carry native or expr.
        for entry in value:
            if not isinstance(entry, dict):
                return None
            if not isinstance(entry.get('name'), str) or not entry['name'].strip():
                return None
            if (entry.get('native') is None) == (entry.get('expr') is None):
                return None
        return value
    if field in {'windows', 'universe', 'allocation', 'costs', 'gates'}:
        return value if isinstance(value, dict) and value else None
    return value


def _windows_nested(raw: Any) -> dict | None:
    """Map the nested period vocabulary when all three windows are explicit."""
    if not isinstance(raw, dict):
        return None
    mapping = {'train': 'train_window', 'validation': 'validation_window',
               'protected': 'protected_test_window'}
    out = {}
    for target, source in mapping.items():
        span = raw.get(source)
        if not (isinstance(span, (list, tuple)) and len(span) == 2):
            return None
        out[target] = {'start': str(span[0]), 'end': str(span[1])}
    return out


def draft(document: dict) -> tuple[dict, dict[str, str]]:
    """Return ``(draft_spec, provenance)`` for every field safe to map."""
    spec: dict[str, Any] = {}
    provenance: dict[str, str] = {}
    for field, paths in _FIELD_SOURCES.items():
        value, used = _first(document, paths)
        if value is None and field in _NESTED_SOURCES:
            value, used = _first(document, _NESTED_SOURCES[field])
            if field == 'windows':
                value = _windows_nested(value)
                if value is None:
                    used = None
            elif field == 'costs':
                value = _costs_flat(value)
                if value is None:
                    used = None
        if field == 'costs' and value is not None:
            normalized = _costs_flat(value)
            value = normalized if normalized is not None else None
        value = _executable(field, value)
        if value is None:
            continue
        spec[field] = value
        if used:
            provenance[field] = used
    return spec, provenance


def gaps(spec: dict) -> list[str]:
    """Name every executable field that is still absent, in schema order."""
    missing = []
    for field in sorted(_REQUIRED_SPEC_FIELDS):
        if spec.get(field) is None:
            note = ' (author choice required)' if field in _AUTHOR_REQUIRED else ''
            missing.append(field + note)
    return missing


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        print('usage: draft_candidate_from_thesis.py <thesis.yaml>', file=sys.stderr)
        return 2
    source = Path(args[0])
    try:
        document = yaml.safe_load(source.read_text(encoding='utf-8'))
    except (OSError, yaml.YAMLError) as exc:
        print(json.dumps({'status': 'UNREADABLE', 'reason': str(exc)}))
        return 2
    if not isinstance(document, dict):
        print(json.dumps({'status': 'INVALID_SOURCE',
                          'reason': 'thesis YAML root must be a mapping'}))
        return 2

    spec, provenance = draft(document)
    missing = gaps(spec)
    result = {
        'status': 'COMPLETE_SKELETON' if not missing else 'GAPS',
        'source': str(source),
        'mapped': provenance,
        'missing': missing,
        'draft': spec,
        'authority': 'NO_EXECUTION_OR_TRADING_APPROVAL',
    }
    print(json.dumps(result, indent=1, default=str, sort_keys=True))
    return 0 if not missing else 3


if __name__ == '__main__':
    raise SystemExit(main())
