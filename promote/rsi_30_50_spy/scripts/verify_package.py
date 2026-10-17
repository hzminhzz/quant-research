"""Read-only content and provenance verifier for frozen research packages.

Run from checkout root with:
    uv run python promote/<candidate>/scripts/verify_package.py

No execution, portfolio selection, backtest, promotion or Git writes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
REPO = PACKAGE.parents[1]
MANIFEST = PACKAGE / "provenance/manifest.json"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    manifest = json.loads(MANIFEST.read_text())
    errors: list[str] = []
    if manifest.get("approval_status") != "NOT_APPROVED":
        errors.append("APPROVAL_NOT_FAIL_CLOSED")
    if manifest.get("workflow_status") != "PROMOTED_FOR_FURTHER_RESEARCH":
        errors.append("WRONG_PROMOTION_INTENT")
    if manifest.get("independent_of_shannon") is not True:
        errors.append("SHANNON_SEPARATION_UNDECLARED")
    for item in manifest.get("files", []):
        relative = item["path"]
        target = PACKAGE / relative
        if not target.is_file():
            errors.append(f"MISSING {relative}")
            continue
        if sha(target) != item["sha256"]:
            errors.append(f"SHA256_MISMATCH {relative}")
        if target.stat().st_size != item["size_bytes"]:
            errors.append(f"SIZE_MISMATCH {relative}")
        if item.get("source_path"):
            origin = REPO / item["source_path"]
            if not origin.is_file():
                errors.append(f"MISSING_ROOT_SOURCE {item['source_path']}")
            elif sha(origin) != item.get("source_sha256"):
                errors.append(f"ROOT_SOURCE_CHANGED {item['source_path']}")
    import yaml

    strategy = yaml.safe_load((PACKAGE / "strategy.yaml").read_text())
    if strategy.get("classification") != "EXPLORATORY":
        errors.append("CLASS_NOT_EXPLORATORY")
    if strategy.get("approval_status") != "NOT_APPROVED":
        errors.append("STRATEGY_APPROVAL_MISMATCH")
    if strategy.get("live_trading_enabled") is not False:
        errors.append("LIVE_NOT_DISABLED")
    if strategy.get("strategy_id") != manifest["strategy_id"]:
        errors.append("STRATEGY_ID_MISMATCH")
    summary = json.loads((PACKAGE / "reports/native_summary.json").read_text())
    cost = json.loads((PACKAGE / "reports/cost_stress.json").read_text())
    if summary["strategy"] != manifest["original_strategy_name"]:
        errors.append("SUMMARY_STRATEGY_MISMATCH")
    if cost["case"] != summary["strategy"] or len(cost["trials"]) != 2:
        errors.append("COST_TRIAL_SET_MISMATCH")
    if summary.get("protected_after_utc") != "2026-10-12T00:00:00+00:00":
        errors.append("HOLDOUT_CUTOFF_MISMATCH")
    native = REPO / "run_log/independent_five_full_history_20261014" / summary["strategy"]
    for file, expected in summary.get("artifact_sha256", {}).items():
        artifact = native / file
        if not artifact.is_file():
            errors.append(f"MISSING_NATIVE_ARTIFACT {file}")
        elif sha(artifact) != expected:
            errors.append(f"NATIVE_HASH_MISMATCH {file}")
    audit = REPO / "run_log/independent_five_full_history_20261014/audit.json"
    if not audit.exists() or json.loads(audit.read_text()).get("status") != "PASS":
        errors.append("NATIVE_AUDIT_NOT_PASSED")
    print(json.dumps({
        "package": str(PACKAGE.relative_to(REPO)),
        "strategy_id": manifest["strategy_id"],
        "verified_package_files": len(manifest.get("files", [])),
        "native_artifact_hashes": len(summary.get("artifact_sha256", {})),
        "status": "VERIFIED" if not errors else "FAILED",
        "scientific_approval": "NOT_APPROVED",
        "errors": errors,
    }, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
