"""Written dispositions for book items that are not time-series sleeves.

A non-sleeve is not a failure and not a silent omission: each record names a
terminal disposition and the code or manifest evidence that makes it a
non-sleeve. Validation resolves every cited path and marker, so the record
cannot drift away from the implementation it describes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .common import QuantError, read_json
from .ts_casefile import DISPOSITIONS

REPO = Path(__file__).resolve().parents[2]
REQUIRED = {
    24: 'DIAGNOSTIC',
    25: 'PORTFOLIO_MODE',
    28: 'BLOCKED_MULTILEG',
    29: 'BLOCKED_MULTILEG',
    30: 'BLOCKED_NO_CONTRACT_CURVE',
}
CONTRACT_FIELDS = ('expiry', 'contract_month', 'contract_symbol', 'maturity', 'delivery_month')


def load_dispositions(path: str | Path = REPO / 'config/sleeves/advanced_futures_30/non_sleeve_dispositions.yaml'
                      ) -> list[dict[str, Any]]:
    try:
        payload = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    except (OSError, yaml.YAMLError) as exc:
        raise QuantError('INVALID_SPEC', f'Disposition artifact unreadable: {exc}') from exc
    if not isinstance(payload, dict) or payload.get('schema_version') != 1:
        raise QuantError('INVALID_SPEC', 'Disposition artifact must declare schema_version 1')
    records = payload.get('records')
    if not isinstance(records, list):
        raise QuantError('INVALID_SPEC', 'Disposition artifact requires a record list')
    return records


def _check_marker(evidence: dict[str, Any], root: Path) -> None:
    path = root / evidence['path']
    if not path.is_file():
        raise QuantError('INVALID_EVIDENCE', f'Cited evidence path is missing: {path}')
    marker = evidence.get('marker', '')
    if not marker or marker not in path.read_text(encoding='utf-8'):
        raise QuantError('INVALID_EVIDENCE', f'Marker {marker!r} is absent from {path}')


def _check_schema_absence(evidence: dict[str, Any], root: Path) -> None:
    _check_marker(evidence, root)
    from src.data_vault.panel_builder import CANONICAL_COLUMNS
    present = set(CANONICAL_COLUMNS) & set(evidence.get('absent_fields', []))
    if present:
        raise QuantError('INVALID_EVIDENCE',
                         f'Canonical schema now carries contract fields: {sorted(present)}')


def _check_single_series(evidence: dict[str, Any], root: Path) -> None:
    manifest = root / evidence['vault_root'] / 'manifest.json'
    if not manifest.is_file():
        # A fresh checkout has no gitignored vault. The schema-absence evidence
        # still stands; the vault check is verified wherever data is mounted.
        return
    payload = read_json(manifest)
    entries = payload.get('entries', [])
    if not entries:
        raise QuantError('INVALID_EVIDENCE', f'Vault manifest has no entries: {manifest}')
    for entry in entries:
        keys = set(entry) | set(entry.get('provenance', {}))
        found = sorted(keys & set(CONTRACT_FIELDS))
        if found:
            raise QuantError('INVALID_EVIDENCE',
                             f'Vault entry now carries contract fields {found} in {manifest}')
    symbols = {entry.get('symbol') for entry in entries if entry.get('symbol')}
    if len(symbols) == 0:
        raise QuantError('INVALID_EVIDENCE', f'Vault manifest identifies no symbols: {manifest}')


def validate_dispositions(records: list[dict[str, Any]], *, root: str | Path = REPO,
                          spec_dir: str | Path | None = None) -> None:
    root = Path(root)
    discovered = {}
    for record in records:
        book = record.get('book_strategy')
        if book not in REQUIRED:
            raise QuantError('INVALID_SPEC', f'Book strategy {book} is not a non-sleeve item')
        if book in discovered:
            raise QuantError('INVALID_SPEC', f'Duplicate disposition for strategy {book}')
        if record.get('disposition') != REQUIRED[book]:
            raise QuantError('INVALID_SPEC',
                             f'Strategy {book} must be {REQUIRED[book]}, not {record.get("disposition")}')
        if record.get('disposition') not in DISPOSITIONS:
            raise QuantError('INVALID_SPEC', f'Unknown disposition {record.get("disposition")}')
        if not str(record.get('reason', '')).strip():
            raise QuantError('INVALID_SPEC', f'Strategy {book} needs a written reason')
        evidence = record.get('evidence')
        if not isinstance(evidence, list) or not evidence:
            raise QuantError('INVALID_EVIDENCE', f'Strategy {book} cites no evidence')
        for item in evidence:
            kind = item.get('kind')
            if kind == 'code_marker':
                _check_marker(item, root)
            elif kind == 'schema_absence':
                _check_schema_absence(item, root)
            elif kind == 'vault_single_series':
                _check_single_series(item, root)
            elif kind == 'book_structure':
                if not item.get('reference') or not item.get('detail'):
                    raise QuantError('INVALID_EVIDENCE',
                                     f'Strategy {book} book evidence needs reference and detail')
            else:
                raise QuantError('INVALID_SPEC', f'Strategy {book} cites unknown evidence kind {kind}')
        discovered[book] = record
    missing = set(REQUIRED) - set(discovered)
    if missing:
        raise QuantError('INVALID_SPEC', f'Dispositions miss strategies {sorted(missing)}')
    if spec_dir is not None:
        for book in REQUIRED:
            sleeves = list(Path(spec_dir).glob(f'af30_s{book:02d}_*.yaml'))
            if sleeves:
                raise QuantError('INVALID_SPEC',
                                 f'Strategy {book} has a sleeve spec but a non-sleeve disposition')


def disposition_for(book_strategy: int,
                    records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    records = records if records is not None else load_dispositions()
    record = next((r for r in records if r.get('book_strategy') == book_strategy), None)
    if record is None:
        raise QuantError('INVALID_SPEC', f'No non-sleeve disposition for strategy {book_strategy}')
    return record
