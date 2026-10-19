from __future__ import annotations

from pathlib import Path

import pytest

from src.engine.common import QuantError
from src.engine.non_sleeve import (
    CONTRACT_FIELDS,
    REQUIRED,
    disposition_for,
    load_dispositions,
    validate_dispositions,
)
from src.engine.sleeve_matrix import load_matrix

SPEC_DIR = Path(__file__).parents[1] / 'config/sleeves/advanced_futures_30'
ARTIFACT = SPEC_DIR / 'non_sleeve_dispositions.yaml'


def records() -> list[dict]:
    return load_dispositions(ARTIFACT)


def test_all_five_records_exist_with_their_required_disposition():
    data = records()
    assert {r['book_strategy'] for r in data} == set(REQUIRED)
    for record in data:
        assert record['disposition'] == REQUIRED[record['book_strategy']]
        assert record['disposition'] in {
            'DIAGNOSTIC', 'PORTFOLIO_MODE', 'BLOCKED_MULTILEG', 'BLOCKED_NO_CONTRACT_CURVE'}
        assert record['reason'].strip()
        assert record['evidence']
    validate_dispositions(data, spec_dir=SPEC_DIR)


def test_every_cited_marker_exists_in_the_implementation():
    for record in records():
        for item in record['evidence']:
            if item['kind'] == 'code_marker':
                text = (Path(__file__).parents[1] / item['path']).read_text(encoding='utf-8')
                assert item['marker'] in text
            if item['kind'] == 'schema_absence':
                from src.data_vault.panel_builder import CANONICAL_COLUMNS
                assert not (set(CANONICAL_COLUMNS) & set(item['absent_fields']))


def test_no_contract_curve_exists_in_the_canonical_schema_or_vault():
    from src.data_vault.panel_builder import CANONICAL_COLUMNS
    assert not (set(CANONICAL_COLUMNS) & set(CONTRACT_FIELDS))
    record = disposition_for(30, records())
    vault = next(i for i in record['evidence'] if i['kind'] == 'vault_single_series')
    import json
    path = Path(__file__).parents[1] / vault['vault_root'] / 'manifest.json'
    if not path.is_file():
        pytest.skip('external vault is not mounted in this checkout')
    manifest = json.loads(path.read_text())
    assert manifest['entries']
    for entry in manifest['entries']:
        keys = set(entry) | set(entry.get('provenance', {}))
        assert not (keys & set(CONTRACT_FIELDS))


def test_none_of_the_five_is_represented_as_a_sleeve():
    matrix = load_matrix(SPEC_DIR / 'compatibility.yaml')
    declared = {variant['book_strategy'] for variant in matrix['variants']}
    assert declared.isdisjoint(REQUIRED)
    for book in REQUIRED:
        assert list(SPEC_DIR.glob(f'af30_s{book:02d}_*.yaml')) == []


def test_a_record_without_evidence_is_rejected():
    data = records()
    data[0] = {**data[0], 'evidence': []}
    with pytest.raises(QuantError) as exc:
        validate_dispositions(data, spec_dir=SPEC_DIR)
    assert exc.value.status == 'INVALID_EVIDENCE'


def test_a_generic_blocked_disposition_is_not_accepted():
    data = records()
    target = next(r for r in data if r['book_strategy'] == 28)
    target['disposition'] = 'BLOCKED'
    with pytest.raises(QuantError) as exc:
        validate_dispositions(data, spec_dir=SPEC_DIR)
    assert exc.value.status == 'INVALID_SPEC'
    assert 'BLOCKED_MULTILEG' in exc.value.reason


def test_a_stale_marker_is_rejected():
    data = records()
    evidence = data[1]['evidence'][0]
    evidence['marker'] = 'this symbol does not exist('
    with pytest.raises(QuantError) as exc:
        validate_dispositions(data, spec_dir=SPEC_DIR)
    assert exc.value.status == 'INVALID_EVIDENCE'


def test_a_sleeve_spec_for_a_non_sleeve_item_is_rejected(tmp_path: Path):
    data = records()
    (tmp_path / 'af30_s24_fake.yaml').write_text('spec_kind: time_series\n', encoding='utf-8')
    with pytest.raises(QuantError) as exc:
        validate_dispositions(data, spec_dir=tmp_path)
    assert 'sleeve spec' in exc.value.reason
