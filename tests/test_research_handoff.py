from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from src.engine.common import QuantError
from src.engine.research_handoff import validate_handoff

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / 'research_inbox'


def test_all_published_handoffs_validate() -> None:
    candidates = sorted(p for p in INBOX.iterdir() if p.is_dir() and not p.name.startswith('.'))
    assert candidates, 'at least one published handoff must be present'
    assert all(validate_handoff(path)['status'] == 'HANDOFF_VALID_UNVERIFIED' for path in candidates)


@pytest.fixture
def handoff(tmp_path: Path) -> Path:
    original_id = 'oil_to_cad_daily_delayed_adjustment_20261015_v1'
    path = tmp_path / 'sample_candidate_v1'
    shutil.copytree(INBOX / original_id, path)
    document = yaml.safe_load((path / 'thesis.yaml').read_text(encoding='utf-8'))
    document['candidate_id'] = path.name
    (path / 'thesis.yaml').write_text(yaml.safe_dump(document), encoding='utf-8')
    brief = (path / 'brief.md').read_text(encoding='utf-8')
    (path / 'brief.md').write_text(brief.replace(original_id, path.name), encoding='utf-8')
    return path


def _write(path: Path, document: dict) -> None:
    (path / 'thesis.yaml').write_text(yaml.safe_dump(document), encoding='utf-8')


def test_rejects_folder_id_mismatch(handoff: Path) -> None:
    document = yaml.safe_load((handoff / 'thesis.yaml').read_text(encoding='utf-8'))
    document['candidate_id'] = 'different_candidate_v1'
    _write(handoff, document)
    with pytest.raises(QuantError, match='match its containing directory'):
        validate_handoff(handoff)


def test_rejects_duplicate_source_ids(handoff: Path) -> None:
    doc = yaml.safe_load((handoff / 'thesis.yaml').read_text())
    doc['candidate_id'] = handoff.name
    doc['source_references'][1]['id'] = doc['source_references'][0]['id']
    _write(handoff, doc)
    with pytest.raises(QuantError, match='duplicate source ID'):
        validate_handoff(handoff)


def test_rejects_duplicate_yaml_keys(handoff: Path) -> None:
    source = (handoff / 'thesis.yaml').read_text(encoding='utf-8')
    source += '\ncandidate_id: duplicate\n'
    (handoff / 'thesis.yaml').write_text(source, encoding='utf-8')
    with pytest.raises(QuantError, match='duplicate YAML key'):
        validate_handoff(handoff)


def test_rejects_placeholder_values(handoff: Path) -> None:
    doc = yaml.safe_load((handoff / 'thesis.yaml').read_text())
    doc['candidate_id'] = handoff.name
    doc['assumptions'] = ['TODO']
    _write(handoff, doc)
    with pytest.raises(QuantError, match='placeholder value'):
        validate_handoff(handoff)


@pytest.mark.parametrize('url', ['http://example.org/source', 'https:///missing-host', 'javascript:alert(1)'])
def test_rejects_non_https_or_malformed_source_url(handoff: Path, url: str) -> None:
    doc = yaml.safe_load((handoff / 'thesis.yaml').read_text())
    doc['candidate_id'] = handoff.name
    doc['source_references'][0]['url'] = url
    _write(handoff, doc)
    with pytest.raises(QuantError, match='HTTPS URL'):
        validate_handoff(handoff)


def test_rejects_extra_files_and_symlinked_payload(handoff: Path) -> None:
    (handoff / 'extra.txt').write_text('unexpected', encoding='utf-8')
    with pytest.raises(QuantError, match='exactly thesis.yaml and brief.md'):
        validate_handoff(handoff)


def test_rejects_symlinked_handoff_file(handoff: Path, tmp_path: Path) -> None:
    target = tmp_path / 'brief-target.md'
    target.write_text('brief', encoding='utf-8')
    (handoff / 'brief.md').unlink()
    (handoff / 'brief.md').symlink_to(target)
    with pytest.raises(QuantError, match='no symlinks'):
        validate_handoff(handoff)


def test_preserves_unverified_external_store_provenance(handoff: Path) -> None:
    result = validate_handoff(handoff)
    assert result['status'] == 'HANDOFF_VALID_UNVERIFIED'
    assert result['external_local_claims_unverified'] == 1
    assert result['validation'] == 'STRUCTURE_AND_DECLARED_PROVENANCE_ONLY'


def test_rejects_placeholder_domain(handoff: Path) -> None:
    document = yaml.safe_load((handoff / 'thesis.yaml').read_text(encoding='utf-8'))
    document['source_references'][0]['url'] = 'https://example.com/fake'
    _write(handoff, document)
    with pytest.raises(QuantError, match='non-placeholder HTTPS URL'):
        validate_handoff(handoff)


def test_rejects_missing_design_sections_and_executable_claim(handoff: Path) -> None:
    document = yaml.safe_load((handoff / 'thesis.yaml').read_text(encoding='utf-8'))
    document['acceptance_and_stop_rules'] = {}
    _write(handoff, document)
    with pytest.raises(QuantError, match='acceptance_and_stop_rules'):
        validate_handoff(handoff)
    document['acceptance_and_stop_rules'] = {'stopping': 'reject if null not falsified'}
    document['candidate_spec'] = {'schema_version': 1}
    _write(handoff, document)
    with pytest.raises(QuantError, match='candidate_spec is executable scope'):
        validate_handoff(handoff)


def test_rejects_broken_brief_identity(handoff: Path) -> None:
    (handoff / 'brief.md').write_text('A description without candidate identity.', encoding='utf-8')
    with pytest.raises(QuantError, match='brief.md must identify the same candidate_id'):
        validate_handoff(handoff)


def test_rejects_unapproved_status_and_missing_falsifier(handoff: Path) -> None:
    doc = yaml.safe_load((handoff / 'thesis.yaml').read_text())
    doc['candidate_id'] = handoff.name
    doc['not_execution_approved'] = False
    _write(handoff, doc)
    with pytest.raises(QuantError, match='not_execution_approved'):
        validate_handoff(handoff)
    doc['not_execution_approved'] = True
    doc['primary_falsifier'] = None
    _write(handoff, doc)
    with pytest.raises(QuantError, match='primary_falsifier'):
        validate_handoff(handoff)
