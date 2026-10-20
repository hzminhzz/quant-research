"""The draft tool maps only explicit, executable-shaped fields and names the rest."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "draft_candidate_from_thesis.py"
sys.path.insert(0, str(ROOT))

from src.engine.thesis_ingest import _REQUIRED_SPEC_FIELDS  # noqa: E402


def run_tool(path: Path) -> tuple[int, dict]:
    result = subprocess.run([sys.executable, str(TOOL), str(path)],
                            capture_output=True, text=True, check=False)
    return result.returncode, json.loads(result.stdout)


def write(path: Path, document: dict) -> Path:
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def test_nested_thesis_maps_only_executable_shapes_and_reports_every_gap(tmp_path):
    """A descriptive nested thesis yields a skeleton, never an invented formula."""
    source = write(tmp_path / "thesis.yaml", {
        "identity": {"candidate_id": "synthetic_nested", "selection_family_id": "family"},
        "economic_thesis": {"hypothesis": "Persistent structural premium."},
        "markets_and_data": {"market_benchmark": "BTCUSDT_PERP"},
        "deterministic_strategy_specification": {
            "mathematical_feature_definitions": {"entry": "buy the dip"}},
        "research_evaluation": {
            "proposed_periods": {"train_window": ["2020-01-01", "2022-12-31"],
                                 "validation_window": ["2023-01-01", "2024-12-31"],
                                 "protected_test_window": ["2025-01-01", "2025-06-30"]},
            "cost_model_requirements": {"taker_fee_bps": 5.0, "slippage_bps": 4.0}},
        "scientific_integrity": {},
    })

    code, result = run_tool(source)

    assert code == 3, "declared gaps must not report success"
    assert result["status"] == "GAPS"
    assert result["draft"]["candidate_id"] == "synthetic_nested"
    assert result["draft"]["benchmark"] == "BTCUSDT_PERP"
    assert result["draft"]["windows"]["train"] == {"start": "2020-01-01", "end": "2022-12-31"}
    assert result["draft"]["costs"] == {
        "commission_bps_one_way": 5.0, "slippage_bps_one_way": 4.0,
        "spread_bps": 0.0, "spread_included_in_slippage": True}
    # Prose feature definitions must never be copied through as executable features.
    assert "features" not in result["draft"]
    assert any(gap.startswith("features") for gap in result["missing"])


def test_every_missing_executable_field_is_named_exactly_once(tmp_path):
    source = write(tmp_path / "thesis.yaml", {"candidate_id": "only_an_id"})

    code, result = run_tool(source)

    assert code == 3
    named = [gap.split(" (")[0] for gap in result["missing"]]
    assert len(named) == len(set(named)), "a gap must not be reported twice"
    assert set(named) == set(_REQUIRED_SPEC_FIELDS) - {"candidate_id"}
    assert result["mapped"] == {"candidate_id": "candidate_id"}


def test_unreadable_source_fails_without_writing_a_draft(tmp_path):
    broken = tmp_path / "thesis.yaml"
    broken.write_text("candidate_id: [unclosed\n", encoding="utf-8")

    code, result = run_tool(broken)

    assert code == 2
    assert result["status"] == "UNREADABLE"
    assert "draft" not in result
