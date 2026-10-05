"""ml4t-data research dataset catalog resolution for quant-research.

Resolves research datasets through ml4t-data's authority and qualification catalog,
enforcing canonical authority by default and failing closed for non-canonical,
unqualified, or false contract-level futures claims.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_STORE_ROOT = Path("/home/quant/dev/quant/ml4t-data/.data/store")
CATALOG_RELATIVE_PATH = Path(".catalog/research-dataset-catalog.json")
READINESS_AUDIT_RELATIVE_PATH = Path(".catalog/research-readiness.json")


class CatalogError(RuntimeError):
    """Base error for dataset catalog operations."""


class CatalogResolutionError(CatalogError):
    """Raised when a research dataset cannot be resolved safely."""


@dataclass(frozen=True)
class ResolvedDataset:
    """Resolved research dataset with authority, qualification, and provenance evidence."""

    dataset_key: str
    store_path: Path
    authority: str
    qualification: str
    asset_class: str
    source_symbol: str | None
    catalog_identity: str
    consumer_identity: str
    capabilities: dict[str, bool]
    contract_level: dict[str, Any] | None
    warnings: list[str]

    def to_audit_dict(self) -> dict[str, Any]:
        """Return a structured audit dictionary for research session provenance."""
        return {
            "dataset_key": self.dataset_key,
            "store_path": str(self.store_path),
            "authority": self.authority,
            "qualification": self.qualification,
            "asset_class": self.asset_class,
            "source_symbol": self.source_symbol,
            "catalog_identity": self.catalog_identity,
            "consumer_identity": self.consumer_identity,
            "capabilities": dict(self.capabilities),
            "warnings": list(self.warnings),
        }


def _normalize_alias(value: str) -> str:
    """Normalize alias to uppercase alphanumeric for index lookup."""
    return re.sub(r"[^A-Z0-9]+", "", value.strip().upper())


def load_dataset_catalog(
    store_root: Path | str | None = None,
) -> dict[str, Any]:
    """Load the live research dataset catalog from the ml4t-data store.

    Fails closed if the catalog does not exist or is malformed.
    """
    root = Path(store_root or os.environ.get("ML4T_STORE_ROOT") or DEFAULT_STORE_ROOT)
    catalog_path = root / CATALOG_RELATIVE_PATH
    if not catalog_path.is_file():
        raise CatalogResolutionError(
            f"research dataset catalog missing at {catalog_path}; "
            "build it via 'scripts/research_dataset_catalog.py build' in ml4t-data"
        )
    try:
        with catalog_path.open("r", encoding="utf-8") as stream:
            catalog = json.load(stream)
    except (json.JSONDecodeError, OSError) as exc:
        raise CatalogResolutionError(
            f"failed to read catalog at {catalog_path}: {exc}"
        ) from exc

    if not isinstance(catalog, dict) or "catalog_identity" not in catalog:
        raise CatalogResolutionError(
            f"malformed catalog at {catalog_path}: missing 'catalog_identity'"
        )
    return catalog


def resolve_dataset(
    name: str,
    *,
    store_root: Path | str | None = None,
    allow_noncanonical: bool = False,
    allow_unqualified: bool = False,
    require_contract_level: bool = False,
    catalog: dict[str, Any] | None = None,
) -> ResolvedDataset:
    """Resolve an instrument name or alias to an authoritative dataset.

    Parameters
    ----------
    name : str
        Instrument symbol, alias, or dataset key (e.g. 'DE30', 'JP225', 'EURUSD', 'BTCUSDT').
    store_root : Path | str | None
        Path to ml4t-data/.data/store root. Defaults to ML4T_STORE_ROOT or DEFAULT_STORE_ROOT.
    allow_noncanonical : bool
        If False (default), only canonical datasets resolve. Non-canonical (secondary/
        experimental/retired) datasets raise CatalogResolutionError.
    allow_unqualified : bool
        If False (default), only accepted or accepted_with_exclusions datasets resolve.
    require_contract_level : bool
        If True, requires contract_level_futures=True. Fails closed for continuous futures,
        CFDs, and provider-defined index series.
    catalog : dict | None
        Pre-loaded catalog dictionary. If None, loads from store_root.
    """
    root = Path(store_root or os.environ.get("ML4T_STORE_ROOT") or DEFAULT_STORE_ROOT)
    cat = catalog or load_dataset_catalog(root)
    catalog_identity = str(cat.get("catalog_identity", ""))

    entries_by_key = {
        entry["dataset_key"]: entry for entry in cat.get("entries", [])
    }
    resolutions = cat.get("resolutions", {})

    normalized = _normalize_alias(name)
    chosen_key: str | None = None
    warnings: list[str] = []

    # 1. Exact dataset_key match
    if name in entries_by_key:
        chosen_key = name
    # 2. Look up in catalog resolution index
    elif normalized in resolutions:
        resolution = resolutions[normalized]
        if not allow_noncanonical:
            chosen_key = resolution.get("default_dataset_key")
            if chosen_key is None:
                candidates = resolution.get("candidate_dataset_keys", [])
                pref = resolution.get("preferred_noncanonical_dataset_key")
                raise CatalogResolutionError(
                    f"cannot resolve {name!r}: non-canonical authority requires "
                    f"explicit allow_noncanonical=True (candidates: {candidates}, preferred non-canonical: {pref})"
                )
        else:
            chosen_key = (
                resolution.get("default_dataset_key")
                or resolution.get("preferred_noncanonical_dataset_key")
            )
            if chosen_key is None:
                candidates = resolution.get("candidate_dataset_keys", [])
                if candidates:
                    chosen_key = candidates[0]
    # 3. Direct symbol mapping for broad 1h crypto perpetual archive
    elif normalized in ("BTCUSDT", "ETHUSDT", "SOLUSDT") or normalized.startswith("CRYPTOFUTURESFUNDING"):
        if "crypto_futures_ohlcv_1h_BINANCE_UM_PERP" in entries_by_key:
            chosen_key = "crypto_futures_ohlcv_1h_BINANCE_UM_PERP"

    if chosen_key is None or chosen_key not in entries_by_key:
        raise CatalogResolutionError(f"no policy dataset or alias matches {name!r}")

    entry = entries_by_key[chosen_key]
    authority = str(entry.get("authority", "unknown"))
    qualification = str(entry.get("qualification", "unknown"))
    capabilities = dict(entry.get("capabilities", {}))
    contract_level = entry.get("contract_level")

    # Authority validation
    if not allow_noncanonical and authority != "canonical":
        raise CatalogResolutionError(
            f"cannot resolve {name!r}: authority={authority} requires explicit allow_noncanonical=True"
        )
    if authority != "canonical":
        warnings.append(f"non-canonical authority: {authority}")

    # Qualification validation
    if not allow_unqualified and qualification not in ("accepted", "accepted_with_exclusions"):
        raise CatalogResolutionError(
            f"cannot resolve {name!r}: dataset {chosen_key} is unqualified (qualification={qualification})"
        )
    if qualification not in ("accepted", "accepted_with_exclusions"):
        warnings.append(f"dataset qualification: {qualification}")

    # Contract-level futures validation (fail closed)
    if require_contract_level:
        if not capabilities.get("contract_level_futures"):
            raise CatalogResolutionError(
                f"cannot resolve {name!r} ({chosen_key}): contract_level_futures=false; "
                "continuous futures and index CFDs cannot satisfy contract-level requests"
            )
        if not contract_level or not contract_level.get("individual_contract_identity"):
            raise CatalogResolutionError(
                f"cannot resolve {name!r} ({chosen_key}): missing individual contract identity"
            )

    store_path = root / chosen_key
    if not store_path.exists():
        raise CatalogResolutionError(
            f"resolved dataset store {chosen_key} absent at {store_path}"
        )

    return ResolvedDataset(
        dataset_key=chosen_key,
        store_path=store_path,
        authority=authority,
        qualification=qualification,
        asset_class=str(entry.get("asset_class", "unknown")),
        source_symbol=entry.get("source_symbol"),
        catalog_identity=catalog_identity,
        consumer_identity=str(entry.get("consumer_identity", "")),
        capabilities=capabilities,
        contract_level=contract_level,
        warnings=warnings,
    )


def resolve_data_store(
    instrument: str,
    *,
    store_root: Path | str | None = None,
    allow_noncanonical: bool = False,
    allow_unqualified: bool = False,
    require_contract_level: bool = False,
    catalog: dict[str, Any] | None = None,
) -> tuple[Path, str, dict[str, Any]]:
    """Resolve an instrument to a store path, canonical symbol, and audit metadata.

    Returns
    -------
    tuple[Path, str, dict[str, Any]]
        (store_path, canonical_source_symbol, audit_metadata)
    """
    resolved = resolve_dataset(
        instrument,
        store_root=store_root,
        allow_noncanonical=allow_noncanonical,
        allow_unqualified=allow_unqualified,
        require_contract_level=require_contract_level,
        catalog=catalog,
    )
    canonical_symbol = resolved.source_symbol or instrument
    return resolved.store_path, canonical_symbol, resolved.to_audit_dict()


def load_readiness_audit(
    store_root: Path | str | None = None,
) -> dict[str, Any]:
    """Load the machine-readable cross-asset research-readiness audit.

    Fails closed if the audit artifact is missing or invalid.
    """
    root = Path(store_root or os.environ.get("ML4T_STORE_ROOT") or DEFAULT_STORE_ROOT)
    audit_path = root / READINESS_AUDIT_RELATIVE_PATH
    if not audit_path.is_file():
        raise CatalogResolutionError(
            f"readiness audit missing at {audit_path}; "
            "run 'scripts/audit_research_readiness.py' in ml4t-data"
        )
    try:
        with audit_path.open("r", encoding="utf-8") as stream:
            audit = json.load(stream)
    except (json.JSONDecodeError, OSError) as exc:
        raise CatalogResolutionError(
            f"failed to read readiness audit at {audit_path}: {exc}"
        ) from exc
    return audit


def is_research_ready(
    asset_class: str | None = None,
    *,
    store_root: Path | str | None = None,
) -> bool:
    """Return True if the lake is verified research-ready for the asset class.

    Parameters
    ----------
    asset_class : str | None
        'crypto', 'fx', 'index', 'cme_futures', or None (overall).
    """
    audit = load_readiness_audit(store_root)
    if asset_class is None:
        return bool(audit.get("high_level_research_ready", False))
    norm = asset_class.lower()
    if norm in ("crypto", "crypto_perp"):
        return bool(audit.get("high_level_crypto_ready", False))
    if norm in ("fx", "forex"):
        return bool(audit.get("fx_ready", False))
    if norm in ("index", "indices"):
        return bool(audit.get("index_ready", False))
    if norm in ("cme_futures", "contract_level_futures"):
        return bool(audit.get("contract_level_cme_ready", False))
    raise ValueError(f"unknown asset class: {asset_class!r}")
