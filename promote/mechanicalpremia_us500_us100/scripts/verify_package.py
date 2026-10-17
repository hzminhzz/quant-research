"""Read-only integrity check for the promoted Mechanical Premia research package.

Invoke from repository root:
  uv run python promote/mechanicalpremia_us500_us100/scripts/verify_package.py
This validates frozen copied file hashes. It does not rerun market data or modify
any package/source files. Approval status is deliberately NOT_APPROVED.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
MANIFEST = PACKAGE / "provenance/manifest.json"


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["approval_status"] == "NOT_APPROVED"
    assert manifest["promotion_intent"] == "FURTHER_RESEARCH_ONLY"
    assert manifest["native_c3_cells_verified"] == 84
    errors: list[str] = []
    for record in manifest["files"]:
        target = PACKAGE / record["path"]
        if not target.is_file():
            errors.append(f"MISSING {record['path']}")
            continue
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != record["sha256"]:
            errors.append(f"CHECKSUM_MISMATCH {record['path']}")
        if target.stat().st_size != record["size_bytes"]:
            errors.append(f"SIZE_MISMATCH {record['path']}")
    html = PACKAGE / "reports/C3_US500_US100_Strategy_and_Portfolio_Tearsheet_2013_2026.html"
    if html.exists():
        text = html.read_text(encoding="utf-8")
        for title in ("H1 volatility breakout", "D1 mean reversion", "Combined portfolio"):
            if title.lower() not in text.lower():
                errors.append(f"TEARSHEET_SECTION_MISSING {title}")
    print(json.dumps({
        "package": str(PACKAGE), "checked_files": len(manifest["files"]),
        "status": "VERIFIED" if not errors else "FAILED", "errors": errors,
        "scientific_approval": "NOT_APPROVED",
    }, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
