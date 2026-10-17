import json
from pathlib import Path

import pytest

from src.promoted_evidence import load_registration, verify_registration

ROOT = Path("/home/quant/dev/quant/quant-research/promote/rsi_30_50_spy")
REGISTRATION = Path("config/promoted_qualification/rsi_30_50_spy.json")


def test_mapping_is_cfd_proxy_not_spy_or_futures_and_preserves_author_variant():
    registration = load_registration(REGISTRATION)
    mapping = registration["mapping"]
    assert mapping == {
        "source_symbol_name": "SPY",
        "tested_symbol": "ES",
        "tested_product_class": "cfd_price_proxy",
        "cme_translation_registered": False,
        "continuous_adjusted_series_priced_as_contract": False,
        "rising_ma_filter_present": False,
    }
    assert registration["verdict"] == "BLOCKED_EXTERNAL_DATA"


def test_archival_native_result_is_preserved_not_recomputed_or_promoted():
    evidence = load_registration(REGISTRATION)["archival_native_evidence"]
    assert evidence["status"] == "VERIFIED_ARCHIVE_NOT_NEW_RESULT"
    assert evidence["closed_trades"] == 101
    assert evidence["sharpe_252"] == "0.7835938000318212"
    assert evidence["selection_family_known_trials"] == 7
    assert evidence["author_trial_count"] == "UNKNOWN"


def test_missing_futures_and_broker_contract_evidence_blocks_execution_claim():
    barriers = set(load_registration(REGISTRATION)["barriers"])
    assert "NO_DIRECTIONAL_CFD_FINANCING_OR_SWAP_SCHEDULE" in barriers
    assert "NO_CME_DATED_CONTRACT_ROLL_SESSION_MARGIN_COMMISSION_OR_BASIS_DATA" in barriers
    assert "NO_SPY_ADJUSTED_PRICE_DIVIDEND_PARITY" in barriers


@pytest.mark.skipif(not ROOT.is_dir(), reason="external frozen source not present")
def test_external_frozen_package_identity_and_native_summary():
    registration = load_registration(REGISTRATION)
    assert verify_registration(registration, ROOT)["source_identity"] == "VERIFIED"
    summary = json.loads((ROOT / "reports/native_summary.json").read_text())
    assert summary["source_asset"] == "ES"
    assert summary["metrics"]["num_trades"] == 101
    assert summary["metrics"]["sharpe"] == float(
        registration["archival_native_evidence"]["sharpe_252"]
    )
    assert summary["metrics"]["execution_policy"]["impact_bps"] == 0
