"""G9 — the provenance gate.

An `exact` provenance claim on an inbox-derived candidate must be earned by a
convert_thesis receipt, not asserted by a hand-written YAML. This is the defect
that let five locally-invented specifications run under `exact` in this session.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.engine.common import QuantError
from src.engine.funnel import ResearchFunnel, verify_provenance
from src.engine.spec_parser import CandidateSpec, export_spec

CANDIDATE = "inbox_probe_v1"


def _spec(tmp_path: Path, *, candidate_id: str = CANDIDATE,
          status: str = "exact") -> CandidateSpec:
    panel = tmp_path / "panel"
    panel.mkdir(parents=True, exist_ok=True)
    (panel / "manifest.json").write_text("{}", encoding="utf-8")
    return CandidateSpec.model_validate({
        "candidate_id": candidate_id,
        "selection_family_id": candidate_id,
        "source_spec_status": status,
        "thesis": "provenance gate probe",
        "panel_root": str(panel),
        "windows": {
            "train": {"start": "2023-01-01T00:00:00Z", "end": "2023-07-01T00:00:00Z"},
            "validation": {"start": "2023-07-01T00:00:00Z", "end": "2024-01-01T00:00:00Z"},
            "protected": {"start": "2026-01-01T00:00:00Z", "end": "2026-10-01T00:00:00Z"},
        },
        "features": [
            {"name": "sig", "native": "roc", "params": {"period": 24}},
            {"name": "base", "native": "roc", "params": {"period": 48}},
            {"name": "atr_24h", "native": "atr", "params": {"period": 24}},
        ],
        "signal": "sig",
        "baseline": "base",
        "allocation": {"long_count": 2, "short_count": 2, "atr_feature": "atr_24h"},
        "universe": {"minimum_assets": 5, "top_n": 10},
    })


def _inbox(tmp_path: Path, *names: str) -> Path:
    root = tmp_path / "research_inbox"
    root.mkdir(parents=True, exist_ok=True)
    for name in names:
        (root / name).mkdir(exist_ok=True)
    return root


def _receipt(run_log: Path, candidate_id: str, spec: CandidateSpec) -> Path:
    path = run_log / "inbox_factory" / "candidates" / candidate_id / "frozen_candidate.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    export_spec(spec, path)
    return path


def test_exact_claim_without_receipt_is_rejected(tmp_path: Path) -> None:
    inbox = _inbox(tmp_path, CANDIDATE)
    with pytest.raises(QuantError, match="no convert_thesis receipt exists"):
        verify_provenance(_spec(tmp_path), run_log=tmp_path / "run_log", inbox=inbox)


def test_non_exact_status_passes_without_receipt(tmp_path: Path) -> None:
    inbox = _inbox(tmp_path, CANDIDATE)
    verify_provenance(_spec(tmp_path, status="prompt_derived_example"),
                      run_log=tmp_path / "run_log", inbox=inbox)


@pytest.mark.parametrize("status", ["prompt_derived_example", "synthetic_test"])
def test_non_exact_statuses_are_allowed(tmp_path: Path, status: str) -> None:
    inbox = _inbox(tmp_path, CANDIDATE)
    verify_provenance(_spec(tmp_path, status=status), run_log=tmp_path / "run_log", inbox=inbox)


def test_exact_claim_with_matching_receipt_passes(tmp_path: Path) -> None:
    inbox = _inbox(tmp_path, CANDIDATE)
    spec = _spec(tmp_path)
    run_log = tmp_path / "run_log"
    _receipt(run_log, CANDIDATE, spec)
    verify_provenance(spec, run_log=run_log, inbox=inbox)


def test_receipt_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    inbox = _inbox(tmp_path, CANDIDATE)
    run_log = tmp_path / "run_log"
    # receipt produced from a *different* specification
    _receipt(run_log, CANDIDATE, _spec(tmp_path, status="prompt_derived_example"))
    with pytest.raises(QuantError, match="does not match the frozen spec_hash"):
        verify_provenance(_spec(tmp_path), run_log=run_log, inbox=inbox)


def test_candidate_absent_from_inbox_is_not_gated(tmp_path: Path) -> None:
    inbox = _inbox(tmp_path, "some_other_thesis_v1")
    verify_provenance(_spec(tmp_path), run_log=tmp_path / "run_log", inbox=inbox)


def test_gate_fires_before_any_market_data_access(tmp_path: Path) -> None:
    inbox = _inbox(tmp_path, CANDIDATE)
    spec = _spec(tmp_path)
    # panel_root has no canonical manifest: if the funnel reached the vault this
    # would raise BLOCKED_DATA, so INVALID_PROVENANCE proves the gate is upstream.
    funnel = ResearchFunnel(run_log=tmp_path / "run_log", isolate=False)
    import src.engine.funnel as funnel_module
    original = funnel_module.INBOX
    funnel_module.INBOX = inbox
    try:
        with pytest.raises(QuantError) as excinfo:
            funnel.run(spec)
        assert excinfo.value.status == "INVALID_PROVENANCE"
    finally:
        funnel_module.INBOX = original
