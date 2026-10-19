import json
from pathlib import Path

import pytest

from src.promoted_evidence import load_registration, verify_registration

ROOT = Path(__file__).resolve().parents[1] / "promote" / "mechanicalpremia_us500_us100"
REGISTRATION = Path(
    "config/promoted_qualification/mechanicalpremia_us500_us100.json"
)


def test_fixed_decision_rule_yields_restructure_without_retrospective_optimization():
    registration = load_registration(REGISTRATION)
    assert registration["verdict"] == "RESTRUCTURE"
    assert set(registration["decision_rule"]) == {"KEEP", "RESTRUCTURE", "SHELVE"}
    assert registration["frozen_comparison"]["sleeves"] == [
        "H1_STANDALONE", "D1_STANDALONE", "C3_JOINT_SOURCE_WEIGHTED",
    ]
    assert registration["frozen_comparison"]["weights"] == {
        "H1": "0.2336", "D1": "0.7664",
    }
    assert registration["frozen_comparison"]["cost_multiples"] == ["1.0", "1.5"]


def test_archival_native_cells_and_attribution_are_preserved_not_compounded():
    registration = load_registration(REGISTRATION)
    comparison = registration["frozen_comparison"]
    attribution = registration["archival_attribution"]
    assert comparison["annual_native_cells_c3"] == "84/84"
    assert comparison["three_candidate_native_cells"] == "252/252"
    assert attribution["H1"]["closed_trades"] == 1347
    assert attribution["D1"]["closed_trades"] == 58
    assert attribution["C3"]["closed_trades"] == 1405
    assert attribution["classification"].endswith("NOT_CONTINUOUS_ROI")


def test_unavailable_impact_carry_and_spread_make_edge_inconclusive():
    registration = load_registration(REGISTRATION)
    friction = registration["friction_attribution"]
    assert registration["economic_edge"].startswith("INCONCLUSIVE")
    assert friction["spread"] == "UNAVAILABLE"
    assert friction["carry_financing"] == "UNAVAILABLE"
    assert friction["market_impact"].startswith("UNAVAILABLE_NO_TRUE_ADV")
    assert registration["frozen_comparison"]["same_continuous_time_grid_available"] is False


@pytest.mark.skipif(not ROOT.is_dir(), reason="external frozen source not present")
def test_external_frozen_package_and_modeled_cost_rows():
    registration = load_registration(REGISTRATION)
    assert verify_registration(registration, ROOT)["source_identity"] == "VERIFIED"
    summary = json.loads((ROOT / "reports/three_candidate_summary.json").read_text())
    assert summary["completed"] == summary["expected"] == 252
    c3 = summary["comparative_summary"]["C3_US_ONLY"]
    assert c3["source_1"]["mean_annual_return_pct"] == pytest.approx(2.9881403515274534)
    assert c3["cost_1.5"]["mean_annual_return_pct"] == pytest.approx(2.0738828190283)
