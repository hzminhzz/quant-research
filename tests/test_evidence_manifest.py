from __future__ import annotations

import json
from pathlib import Path

from src.engine.combined_portfolio import load_rule, rule_digest
from src.engine.common import file_hash
from src.engine.spec_parser import CandidateSpec
from src.engine.ts_spec import TimeSeriesSpec
from src.oracle.research_protocols import parse_research_spec

SPEC_DIR = Path(__file__).parents[1] / 'specs/advanced_futures_30'
MANIFEST = SPEC_DIR / 'evidence_manifest.json'


def manifest() -> dict:
    return json.loads(MANIFEST.read_text())


def test_every_artifact_hash_matches_the_manifest():
    data = manifest()
    assert data['artifacts']
    for path, expected in data['artifacts'].items():
        assert Path(path).is_file(), path
        assert file_hash(path) == expected, f'{path} drifted from the evidence manifest'


def test_matrix_and_rule_hashes_match():
    data = manifest()
    freeze = json.loads((Path('config/sleeves/advanced_futures_30/compatibility.freeze.json')).read_text())
    assert data['matrix_freeze_sha256'] == freeze['sha256']
    assert data['portfolio_rule_sha256'] == rule_digest(load_rule())


def test_all_twenty_five_sleeves_are_inventoried():
    data = manifest()
    sleeves = [path for path in data['artifacts'] if '/af30_s' in path]
    assert len(sleeves) == data['sleeve_count'] == 25


def test_every_candidate_still_parses_to_its_recorded_hash():
    for path, expected in manifest()['candidates'].items():
        spec = parse_research_spec(path)
        if isinstance(spec, CandidateSpec):
            assert expected['protocol'] == 'cross_sectional'
        elif isinstance(spec, TimeSeriesSpec):
            assert expected['protocol'] == 'time_series'
        else:
            assert expected['protocol'] == getattr(spec, 'protocol', 'event')
        assert spec.spec_hash == expected['spec_hash'], f'{path} changed its spec hash'


def test_verification_summary_covers_every_criterion():
    text = (SPEC_DIR / 'verification.md').read_text(encoding='utf-8')
    for number in range(1, 15):
        assert f'| AC{number} |' in text, f'AC{number} is not named in the summary'
    assert 'NOT_APPROVED' in text
    assert 'TODO' not in text and 'UNVERIFIED' not in text.upper()
    assert manifest()['deployment_status'] == 'NOT_APPROVED'


def test_manifest_cannot_claim_deployment_approval():
    data = manifest()
    assert data['deployment_status'] == 'NOT_APPROVED'
    assert 'approval' not in data or 'deployment_approval' not in data
