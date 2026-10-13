"""Standing CFD/perpetual scope keeps native source-identity gates intact."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from src.research_control.contracts import ResearchContractV1

ROOT = Path(__file__).resolve().parents[1]


def _cfd_adaptation() -> dict:
    data = yaml.safe_load(
        (ROOT / "config/research_contract_v1_example.yaml").read_text(encoding="utf-8")
    )
    data["session_id"] = "future-cfd-breakout"
    data["dataset"].update(
        requested_product="Dukascopy USATECH.IDX/USD CFD breakout adaptation",
        authority="canonical",
        catalog_dataset_key="index_minute_NQ",
        external_exception_id=None,
    )
    return data


def test_new_session_accepts_explicit_cfd_adaptation_without_cme_data() -> None:
    # A CME-inspired price rule can be researched as an actual Dukascopy CFD.
    contract = ResearchContractV1.model_validate(_cfd_adaptation())
    assert contract.dataset.product_class == "cfd"
    assert contract.dataset.source_symbol == "USATECH.IDX/USD"
    assert contract.dataset.volume_semantics == "broker_tick_or_quote_proxy"
    assert contract.dataset.catalog_dataset_key == "index_minute_NQ"


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        (
            {"requested_product": "CME NQ futures breakout"},
            "CME traded-volume claims",
        ),
        (
            {"product_class": "dated_future"},
            "Dukascopy USATECH data is a CFD proxy",
        ),
        (
            {"volume_semantics": "genuine_exchange_traded"},
            "CFD volume cannot be claimed",
        ),
        (
            {"source_symbol": "NQ.F", "requested_product": "Dukascopy NQ CFD"},
            "LSE NQ.F is not Dukascopy",
        ),
    ],
)
def test_cfd_scope_does_not_weaken_futures_source_gate(
    changes: dict[str, str], reason: str
) -> None:
    data = _cfd_adaptation()
    data["dataset"].update(changes)
    with pytest.raises(ValidationError, match=reason):
        ResearchContractV1.model_validate(data)


def test_every_new_research_session_has_standing_policy_pointer() -> None:
    assert "docs/architecture/market_scope_policy.md" in (ROOT / "AGENTS.md").read_text(
        encoding="utf-8"
    )
    assert "architecture/market_scope_policy.md" in (
        ROOT / "docs/research_sessions.md"
    ).read_text(encoding="utf-8")
