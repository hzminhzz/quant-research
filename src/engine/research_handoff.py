"""Strict admission checks for descriptive, non-executable research handoffs."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import yaml

from .common import QuantError
from .thesis_ingest import (
    _ROOT_FIELDS,  # Shared ATS root vocabulary; executable ingest stays separate.
)

_MAX_FILE_BYTES = 512_000
_REQUIRED = {
    'economic_thesis', 'mechanism', 'strategy_rules', 'feature_contracts',
    'signal_and_execution_clock', 'cost_assumptions', 'baseline', 'primary_falsifier',
    'data_requirements', 'instruments', 'development_evaluation', 'source_references',
    'sizing', 'acceptance_and_stop_rules', 'parity_and_causality_tests',
}
_PLACEHOLDER = re.compile(r'^(?:todo|tbd|placeholder|fill[_ -]?me|n/?a|<[^>]+>)$', re.IGNORECASE)


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            _fail(f'duplicate YAML key: {key}')
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def _fail(message: str) -> None:
    raise QuantError('INVALID_HANDOFF', message)


def _substantive(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip()) and not _PLACEHOLDER.fullmatch(value.strip())
    if isinstance(value, dict):
        return any(_substantive(v) for v in value.values())
    if isinstance(value, list):
        return any(_substantive(v) for v in value)
    return value is not None


def _has_placeholder(value: object) -> bool:
    if isinstance(value, str):
        return bool(_PLACEHOLDER.fullmatch(value.strip()))
    if isinstance(value, dict):
        return any(_has_placeholder(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_placeholder(v) for v in value)
    return False


def _confirmed_local_paths(reference: dict) -> bool:
    paths = reference.get('local_path', reference.get('paths', reference.get('files_read')))
    if isinstance(paths, str):
        paths = [paths]
    if not isinstance(paths, list) or not paths:
        return False
    root = Path(__file__).resolve().parents[2]
    for item in paths:
        if not isinstance(item, str):
            return False
        path = Path(item)
        if path.is_absolute() or '..' in path.parts or not (root / path).is_file() or (root / path).is_symlink():
            return False
    return True


def _declared_external_store(reference: dict) -> bool:
    """Recognize a non-portable VPS source claim without pretending CI verified its contents."""
    if reference.get('type') != 'read_only_metadata_and_directory_inspection':
        return False
    root = reference.get('root')
    keys = reference.get('checked_keys')
    return (root == '/home/quant/dev/quant/ml4t-data/.data/store'
            and isinstance(keys, list) and bool(keys)
            and all(isinstance(key, str) and re.fullmatch(r'[A-Za-z0-9_]+', key) for key in keys))


def validate_handoff(candidate_dir: str | Path) -> dict[str, str | int]:
    """Validate a two-file handoff envelope; this grants no research execution authority."""
    directory = Path(candidate_dir)
    if directory.is_symlink() or not directory.is_dir():
        _fail('candidate path must be a real directory')
    candidate_id = directory.name
    if not re.fullmatch(r'[a-z0-9]+(?:_[a-z0-9]+)*', candidate_id):
        _fail('candidate directory must use stable snake_case candidate_id')
    entries = list(directory.iterdir())
    if {p.name for p in entries} != {'thesis.yaml', 'brief.md'} or any(p.is_symlink() or not p.is_file() for p in entries):
        _fail('candidate directory must contain exactly thesis.yaml and brief.md, with no symlinks')
    if any(p.stat().st_size > _MAX_FILE_BYTES for p in entries):
        _fail('handoff text file exceeds the bounded admission size')
    try:
        yaml_text = (directory / 'thesis.yaml').read_text(encoding='utf-8')
        brief = (directory / 'brief.md').read_text(encoding='utf-8')
    except (OSError, UnicodeError) as exc:
        _fail(f'handoff files must be readable UTF-8: {exc}')
    try:
        document = yaml.load(yaml_text, Loader=_UniqueKeyLoader)
    except (yaml.YAMLError, TypeError, RecursionError) as exc:
        _fail(f'thesis YAML is invalid: {exc}')
    if not isinstance(document, dict):
        _fail('thesis YAML root must be a mapping')
    if _has_placeholder(document):
        _fail('thesis YAML contains a placeholder value')
    unknown = sorted(set(document) - _ROOT_FIELDS)
    if unknown:
        _fail('unmapped thesis fields: ' + ', '.join(unknown))
    if document.get('candidate_id') != candidate_id:
        _fail('candidate_id must exactly match its containing directory')
    if document.get('status') != 'THESIS_READY_UNVERIFIED' or document.get('not_execution_approved') is not True or document.get('not_a_frozen_session') is not True:
        _fail('status must be THESIS_READY_UNVERIFIED; not_execution_approved and not_a_frozen_session must be true')
    if 'candidate_spec' in document:
        _fail('candidate_spec is executable scope: qualify it separately with quant.py ingest')
    if not isinstance(document.get('research_mode'), str) or not document['research_mode'].strip():
        _fail('research_mode must explicitly identify design-only research')
    family = document.get('selection_family_id')
    if not isinstance(family, str) or not re.fullmatch(r'[a-z0-9]+(?:_[a-z0-9]+)*', family):
        _fail('selection_family_id must be a nonempty stable snake_case identifier')
    missing = sorted(key for key in _REQUIRED if not _substantive(document.get(key)))
    if missing:
        _fail('required handoff sections are absent or empty: ' + ', '.join(missing))
    if not brief.strip() or _PLACEHOLDER.fullmatch(brief.strip()):
        _fail('brief.md must contain non-placeholder UTF-8 text')
    if candidate_id not in brief:
        _fail('brief.md must identify the same candidate_id')

    references = document['source_references']
    if not isinstance(references, list) or not references:
        _fail('source_references must be a nonempty list')
    ids: set[str] = set()
    external = False
    external_local_claims = 0
    for index, ref in enumerate(references):
        if not isinstance(ref, dict) or not isinstance(ref.get('id'), str) or not ref['id'].strip():
            _fail(f'source_references[{index}] needs a source ID')
        if ref['id'] in ids:
            _fail(f'duplicate source ID: {ref["id"]}')
        ids.add(ref['id'])
        url = ref.get('url')
        if url:
            parsed = urlparse(url) if isinstance(url, str) else None
            if (parsed is None or parsed.scheme != 'https' or not parsed.hostname
                    or parsed.username or parsed.password or parsed.hostname in {'localhost', 'example.com', 'example.org', 'example.net'}
                    or parsed.hostname.endswith(('.localhost', '.local', '.invalid'))):
                _fail(f'source_references[{index}].url must be a non-placeholder HTTPS URL')
            external = True
        elif _confirmed_local_paths(ref):
            continue
        elif _declared_external_store(ref):
            external_local_claims += 1
        else:
            _fail(f'source_references[{index}] must have HTTPS, confirmed repo paths, or explicit unverified VPS source identity')
    if not external:
        _fail('at least one external HTTPS source reference is required')
    return {'status': 'HANDOFF_VALID_UNVERIFIED', 'candidate_id': candidate_id,
            'validation': 'STRUCTURE_AND_DECLARED_PROVENANCE_ONLY',
            'external_local_claims_unverified': external_local_claims,
            'authority': 'NO_EXECUTION_OR_TRADING_APPROVAL'}
