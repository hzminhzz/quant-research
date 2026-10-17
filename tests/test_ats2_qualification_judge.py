"""Independent ATS-2 qualification judge must reject altered raw fixture records."""
from __future__ import annotations

import json

import pytest
from cryptography.exceptions import InvalidSignature

from scripts.ats2_acceptance import _synthetic_protected_case
from scripts.ats2_qualification_judge import check_authorization


def _fixture(tmp_path):
    folder = tmp_path / "synthetic_protected"
    result = _synthetic_protected_case(folder)
    return folder, {"synthetic_protected_authorization": result}


def test_independent_protected_authority_judge_accepts_valid_raw_evidence(tmp_path):
    _, manifest = _fixture(tmp_path)
    checks = []
    check_authorization(tmp_path, manifest, checks)
    assert len(checks) == 3


def test_independent_protected_authority_judge_rejects_forged_signature(tmp_path):
    folder, manifest = _fixture(tmp_path)
    path = folder / manifest["synthetic_protected_authorization"]["grant_path"]
    doc = json.loads(path.read_text())
    original = doc["signature_b64"]
    doc["signature_b64"] = ("A" if original[0] != "A" else "B") + original[1:]
    path.write_text(json.dumps(doc, sort_keys=True), encoding="utf-8")
    with pytest.raises((InvalidSignature, AssertionError)):
        check_authorization(tmp_path, manifest, [])


def test_independent_protected_authority_judge_rejects_tampered_claim(tmp_path):
    folder, manifest = _fixture(tmp_path)
    path = folder / manifest["synthetic_protected_authorization"]["claim_path"]
    doc = json.loads(path.read_text())
    doc["attempts"] = 2
    path.write_text(json.dumps(doc, sort_keys=True), encoding="utf-8")
    with pytest.raises(AssertionError, match="CLAIM_DRIFT|GRANT_NOT_ONE_SHOT"):
        check_authorization(tmp_path, manifest, [])


def test_independent_protected_authority_judge_rejects_proof_drift(tmp_path):
    folder, manifest = _fixture(tmp_path)
    path = folder / manifest["synthetic_protected_authorization"]["proof_path"]
    doc = json.loads(path.read_text())
    doc["live_order_authority"] = True
    path.write_text(json.dumps(doc, sort_keys=True), encoding="utf-8")
    with pytest.raises(AssertionError, match="PROOF_DRIFT|PROTECTED_WORKER_BOUNDARY_UNVERIFIED"):
        check_authorization(tmp_path, manifest, [])
