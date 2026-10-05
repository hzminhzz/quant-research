from __future__ import annotations

from pathlib import Path
import pytest
from src.catalog import (
    CatalogResolutionError,
    ResolvedDataset,
    is_research_ready,
    load_dataset_catalog,
    load_readiness_audit,
    resolve_data_store,
    resolve_dataset,
)

STORE_ROOT = Path("/home/quant/dev/quant/ml4t-data/.data/store")


def test_load_dataset_catalog():
    catalog = load_dataset_catalog(STORE_ROOT)
    assert "catalog_identity" in catalog
    assert "resolutions" in catalog
    assert "entries" in catalog
    assert len(catalog["entries"]) > 0


def test_resolve_accepted_indices():
    for alias, expected_key in [
        ("DE30", "index_minute_DAX"),
        ("DAX", "index_minute_DAX"),
        ("DE30/EUR", "index_minute_DAX"),
        ("JP225", "index_minute_NIKKEI225"),
        ("NIKKEI225", "index_minute_NIKKEI225"),
        ("JP225/USD", "index_minute_NIKKEI225"),
    ]:
        resolved = resolve_dataset(alias, store_root=STORE_ROOT)
        assert isinstance(resolved, ResolvedDataset)
        assert resolved.dataset_key == expected_key
        assert resolved.authority == "canonical"
        assert resolved.qualification == "accepted_with_exclusions"
        assert resolved.store_path == STORE_ROOT / expected_key
        assert resolved.catalog_identity != ""
        assert resolved.consumer_identity != ""


def test_unqualified_canonical_indices_fail_closed_without_override():
    for alias in ["NAS100", "SPX500", "US30"]:
        with pytest.raises(CatalogResolutionError, match="is unqualified"):
            resolve_dataset(alias, store_root=STORE_ROOT)

        resolved = resolve_dataset(
            alias, store_root=STORE_ROOT, allow_unqualified=True
        )
        assert resolved.authority == "canonical"
        assert resolved.qualification == "unqualified"
        assert any(
            "dataset qualification: unqualified" in w for w in resolved.warnings
        )


def test_resolve_canonical_forex():
    for pair in ["EURUSD", "USDJPY", "GBPUSD", "AUDUSD", "USDCAD"]:
        resolved = resolve_dataset(pair, store_root=STORE_ROOT)
        assert resolved.dataset_key == f"forex_minute_{pair}"
        assert resolved.authority == "canonical"
        assert resolved.qualification == "accepted"


def test_resolve_legacy_secondary_requires_explicit_override():
    with pytest.raises(CatalogResolutionError, match="non-canonical authority"):
        resolve_dataset("NQ", store_root=STORE_ROOT)

    with pytest.raises(CatalogResolutionError, match="non-canonical authority"):
        resolve_dataset("ES", store_root=STORE_ROOT)

    resolved_nq = resolve_dataset(
        "NQ",
        store_root=STORE_ROOT,
        allow_noncanonical=True,
        allow_unqualified=True,
    )
    assert resolved_nq.dataset_key == "lse_futures_minute_NQ"
    assert resolved_nq.authority == "secondary"
    assert any("non-canonical authority" in w for w in resolved_nq.warnings)


def test_contract_level_futures_fails_closed_on_cfd_and_continuous():
    with pytest.raises(CatalogResolutionError, match="contract_level_futures=false"):
        resolve_dataset("DE30", store_root=STORE_ROOT, require_contract_level=True)

    with pytest.raises(CatalogResolutionError, match="contract_level_futures=false"):
        resolve_dataset(
            "NQ",
            store_root=STORE_ROOT,
            allow_noncanonical=True,
            allow_unqualified=True,
            require_contract_level=True,
        )

    with pytest.raises(CatalogResolutionError, match="contract_level_futures=false"):
        resolve_dataset(
            "ES",
            store_root=STORE_ROOT,
            allow_noncanonical=True,
            allow_unqualified=True,
            require_contract_level=True,
        )


def test_resolve_data_store_returns_provenance_audit():
    store_path, sym, audit = resolve_data_store("DE30", store_root=STORE_ROOT)
    assert store_path == STORE_ROOT / "index_minute_DAX"
    assert sym == "DE30/EUR"
    assert audit["dataset_key"] == "index_minute_DAX"
    assert audit["authority"] == "canonical"
    assert audit["qualification"] == "accepted_with_exclusions"
    assert "catalog_identity" in audit
    assert "consumer_identity" in audit


def test_missing_catalog_fails_closed(tmp_path: Path):
    with pytest.raises(CatalogResolutionError, match="research dataset catalog missing"):
        resolve_dataset("DE30", store_root=tmp_path)


def test_readiness_audit_consumer_interface():
    audit = load_readiness_audit(STORE_ROOT)
    assert audit["schema_version"] == "research-readiness-audit-v1"
    assert audit["high_level_research_ready"] is True
    assert is_research_ready("crypto", store_root=STORE_ROOT) is True
    assert is_research_ready("fx", store_root=STORE_ROOT) is True
    assert is_research_ready("index", store_root=STORE_ROOT) is True
    assert is_research_ready("cme_futures", store_root=STORE_ROOT) is False
    assert is_research_ready(None, store_root=STORE_ROOT) is True
