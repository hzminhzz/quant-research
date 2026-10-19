import json
from pathlib import Path

import numpy as np
import pytest
from ml4t.diagnostic.metrics.risk_adjusted import periodic_sharpe_ratio

from src.promoted_evidence import load_registration, verify_registration

ROOT = Path(__file__).resolve().parents[1]
REGISTRATION = Path("config/promoted_qualification/donchian_btc.json")


def test_signed_funding_overlay_semantics_and_scope_are_frozen():
    overlay = load_registration(REGISTRATION)["funding_overlay"]
    assert overlay["formula"].startswith("-signed_position_btc")
    assert overlay["position_clock"].startswith("strictly_before")
    assert overlay["events"] == 5819
    assert overlay["exact_settlement_marks"] == 1283
    assert overlay["total_cashflow_usdt"] == "-47096.83"
    assert overlay["exact_2025_2026"] is False
    assert "NOT_NATIVE_INTEGRATED" in overlay["status"]


def test_native_diagnostic_252_vs_365_annualization_is_explicit():
    returns = np.array([0.01, -0.004, 0.006, -0.002, 0.003], dtype=float)
    sharpe_252 = periodic_sharpe_ratio(returns, annualization_factor=252)
    sharpe_365 = periodic_sharpe_ratio(returns, annualization_factor=365)
    assert sharpe_365 / sharpe_252 == pytest.approx(np.sqrt(365 / 252))
    policy = load_registration(REGISTRATION)["annualization"]
    assert policy["native_archive_periods_per_year"] == 252
    assert policy["continuous_crypto_comparison_periods_per_year"] == 365


def test_reduced_risk_case_is_predeclared_but_not_claimed_executed():
    scenario = load_registration(REGISTRATION)["predeclared_reduced_risk_scenario"]
    assert scenario["volatility_target_annual"] == "0.125"
    assert scenario["max_target_leverage"] == "1.0"
    assert scenario["not_a_search"] is True
    assert scenario["status"].startswith("NOT_EXECUTED")


def test_missing_liquidation_and_exact_funding_keep_outcome_inconclusive():
    registration = load_registration(REGISTRATION)
    assert registration["verdict"] == "INCONCLUSIVE_MARGIN_LIQUIDATION_AND_EXACT_FUNDING"
    assert "NO_MAINTENANCE_MARGIN_OR_LIQUIDATION_MODEL" in registration["barriers"]
    assert "LINEAR_RISK_RESCALING_CANNOT_PROVE_ACCOUNT_SURVIVAL" in registration["barriers"]


@pytest.mark.skipif(not (ROOT / "promote/donchian_btc").is_dir(), reason="external frozen source not present")
def test_external_candidate_and_funding_overlay_identity():
    registration = load_registration(REGISTRATION)
    assert verify_registration(registration, ROOT)["source_identity"] == "VERIFIED"
    summary = json.loads(
        (ROOT / "promote/donchian_btc/reports/native_summary.json").read_text()
    )
    assert summary["metrics"]["num_fills"] == 2506
    assert summary["metrics"]["max_drawdown_pct"] == pytest.approx(25.06819822071595)
