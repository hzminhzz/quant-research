"""Fail-closed status handling for published research artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_STATUS: dict[str, Any] = {
    "strategy": "multi_asset_eow_orb_meta_gate",
    "status": "NOT_APPROVED",
    "validated_commit": None,
    "blocking_gates": ["validation_status_missing"],
    "legacy_artifacts_reproducible": False,
    "corrected_run_id": None,
}


def load_validation_status(path: str | Path = "run_log/validation_status.json") -> dict[str, Any]:
    """Load a status record and force ``NOT_APPROVED`` while gates remain."""
    candidate = Path(path)
    if not candidate.exists():
        return dict(DEFAULT_STATUS)

    with candidate.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        return dict(DEFAULT_STATUS)

    result = dict(DEFAULT_STATUS)
    result.update(payload)
    gates = result.get("blocking_gates")
    if not isinstance(gates, list) or gates:
        result["status"] = "NOT_APPROVED"
    elif result.get("status") != "APPROVED":
        result["status"] = "NOT_APPROVED"
    return result


def approval_status(path: str | Path = "run_log/validation_status.json") -> str:
    """Return the fail-closed status used by reports and runners."""
    return str(load_validation_status(path).get("status", "NOT_APPROVED"))
