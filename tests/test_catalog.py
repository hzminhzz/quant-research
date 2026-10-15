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
from tests.conftest import require_path

# The catalog lives in the ml4t-data store, which is outside this repository.
STORE_ROOT = Path("/home/quant/dev/quant/ml4t-data/.data/store")

pytestmark = pytest.mark.data


@pytest.fixture(autouse=True)
def _store_root_must_exist():
    require_path(STORE_ROOT)


@pytest.mark.data
def test_load_dataset_catalog():
    catalog = load_dataset_catalog(STORE_ROOT)
    assert "catalog_identity" in catalog
    assert "resolutions" in catalog
    assert "entries" in catalog
    assert len(catalog["entries"]) > 0


@pytest.mark.data
def test_resolve_accepted_indices():
    for alias, expected_key, expected_qual in [
        ("DE30", "index_minute_DAX", "accepted"),
        ("DAX", "index_minute_DAX", "accepted"),
        ("DE30/EUR", "index_minute_DAX", "accepted"),
        ("JP225", "index_minute_NIKKEI225", "accepted"),
        ("NIKKEI225", "index_minute_NIKKEI225", "accepted"),
        ("JP225/USD", "index_minute_NIKKEI225", "accepted"),
        ("NQ", "index_minute_NQ", "accepted"),
        ("NAS100", "index_minute_NQ", "accepted"),
        ("ES", "index_minute_ES", "accepted"),
        ("SPX500", "index_minute_ES", "accepted"),
        ("EUSIDXEUR", "index_minute_EUSIDXEUR", "accepted"),
        ("ESTX50", "index_minute_EUSIDXEUR", "accepted"),
    ]:
        resolved = resolve_dataset(alias, store_root=STORE_ROOT)
        assert isinstance(resolved, ResolvedDataset)
        assert resolved.dataset_key == expected_key
        assert resolved.authority == "canonical"
        assert resolved.qualification == expected_qual
        assert resolved.store_path == STORE_ROOT / expected_key
        assert resolved.catalog_identity != ""
        assert resolved.consumer_identity != ""


@pytest.mark.data
def test_current_canonical_index_aliases_are_accepted_cfds():
    for alias, expected_key, expected_symbol in [
        ("NAS100", "index_minute_NQ", "usatechidxusd"),
        ("SPX500", "index_minute_ES", "usa500idxusd"),
    ]:
        resolved = resolve_dataset(alias, store_root=STORE_ROOT)
        assert resolved.dataset_key == expected_key
        assert resolved.authority == "canonical"
        assert resolved.qualification == "accepted"
        assert resolved.source_symbol == expected_symbol
        assert resolved.capabilities["contract_level_futures"] is False

    # US30 remains available only through a non-canonical, unqualified source.
    with pytest.raises(CatalogResolutionError, match="non-canonical authority"):
        resolve_dataset("US30", store_root=STORE_ROOT)
    with pytest.raises(CatalogResolutionError, match="is unqualified"):
        resolve_dataset("US30", store_root=STORE_ROOT, allow_noncanonical=True)
def test_deleted_lse_us_indices_and_futures_fail_closed():
    for removed in [
        "lse_futures_minute_NQ",
        "lse_futures_minute_ES",
        "index_minute_NAS100",
        "index_minute_SPX500",
        "index_minute_US30",
        "index_minute_USA30",
        "US30",
        "USA30",
        "DOW",
        "NQ.F",
        "ES.F",
    ]:
        with pytest.raises(CatalogResolutionError):
            resolve_dataset(
                removed,
                store_root=STORE_ROOT,
                allow_noncanonical=True,
                allow_unqualified=True,
            )


@pytest.mark.data
def test_resolve_canonical_forex():
    for pair in ["EURUSD", "USDJPY", "GBPUSD", "AUDUSD", "USDCAD", "GBPJPY", "CADJPY", "USDCHF"]:
        resolved = resolve_dataset(pair, store_root=STORE_ROOT)
        assert resolved.dataset_key == f"forex_minute_{pair}"
        assert resolved.authority == "canonical"
        assert resolved.qualification == "accepted"
    assert resolve_dataset("CHFUSD", store_root=STORE_ROOT).dataset_key == "forex_minute_USDCHF"


@pytest.mark.data
def test_futures_aliases_do_not_claim_contract_level_identity():
    for alias in ["NQ", "ES", "NAS100", "SPX500"]:
        with pytest.raises(
            CatalogResolutionError, match="contract_level_futures=false"
        ):
            resolve_dataset(alias, store_root=STORE_ROOT, require_contract_level=True)

@pytest.mark.data
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


@pytest.mark.data
def test_resolve_data_store_returns_provenance_audit():
    store_path, sym, audit = resolve_data_store("DE30", store_root=STORE_ROOT)
    assert store_path == STORE_ROOT / "index_minute_DAX"
    assert sym == "deuidxeur"
    assert audit["dataset_key"] == "index_minute_DAX"
    assert audit["authority"] == "canonical"
    assert audit["qualification"] == "accepted"
    assert "catalog_identity" in audit
    assert "consumer_identity" in audit


def test_missing_catalog_fails_closed(tmp_path: Path):
    with pytest.raises(
        CatalogResolutionError, match="research dataset catalog missing"
    ):
        resolve_dataset("DE30", store_root=tmp_path)


@pytest.mark.data
def test_readiness_audit_consumer_interface():
    with pytest.raises(CatalogResolutionError, match="readiness audit is stale"):
        load_readiness_audit(STORE_ROOT)
    with pytest.raises(CatalogResolutionError, match="readiness audit is stale"):
        is_research_ready("index", store_root=STORE_ROOT)


def test_noncanonical_unqualified_and_futures_gates_on_fixture(tmp_path: Path):
    dataset_key = "fixture_unqualified_index"
    (tmp_path / dataset_key).mkdir()
    catalog = {
        "catalog_identity": "fixture-catalog-v1",
        "resolutions": {
            "FIXTURE": {
                "candidate_dataset_keys": [dataset_key],
                "default_dataset_key": None,
                "preferred_noncanonical_dataset_key": dataset_key,
            }
        },
        "entries": [
            {
                "dataset_key": dataset_key,
                "authority": "secondary",
                "qualification": "unqualified",
                "source_symbol": "FIXTURE.CFD",
                "asset_class": "index",
                "capabilities": {"contract_level_futures": False},
                "contract_level": None,
            }
        ],
    }

    with pytest.raises(CatalogResolutionError, match="non-canonical authority"):
        resolve_dataset("FIXTURE", store_root=tmp_path, catalog=catalog)
    with pytest.raises(CatalogResolutionError, match="is unqualified"):
        resolve_dataset(
            "FIXTURE", store_root=tmp_path, catalog=catalog, allow_noncanonical=True
        )
    with pytest.raises(CatalogResolutionError, match="contract_level_futures=false"):
        resolve_dataset(
            "FIXTURE",
            store_root=tmp_path,
            catalog=catalog,
            allow_noncanonical=True,
            allow_unqualified=True,
            require_contract_level=True,
        )
    resolved = resolve_dataset(
        "FIXTURE",
        store_root=tmp_path,
        catalog=catalog,
        allow_noncanonical=True,
        allow_unqualified=True,
    )
    assert resolved.authority == "secondary"
    assert resolved.qualification == "unqualified"


def test_readiness_audit_must_match_catalog_identity(tmp_path: Path):
    catalog_dir = tmp_path / ".catalog"
    catalog_dir.mkdir()
    (catalog_dir / "research-dataset-catalog.json").write_text(
        '{"catalog_identity":"catalog-v1","entries":[],"resolutions":{}}',
        encoding="utf-8",
    )
    audit_path = catalog_dir / "research-readiness.json"
    audit_path.write_text('{"catalog_identity":"catalog-v1"}', encoding="utf-8")
    assert load_readiness_audit(tmp_path)["catalog_identity"] == "catalog-v1"

    audit_path.write_text('{"catalog_identity":"catalog-old"}', encoding="utf-8")
    with pytest.raises(CatalogResolutionError, match="readiness audit is stale"):
        load_readiness_audit(tmp_path)
