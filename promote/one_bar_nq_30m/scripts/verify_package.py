#!/usr/bin/env python3
"""Verify package structure, YAML syntax, and content hashes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
REQUIRED = [
    "README.md", "STATUS.md", "strategy.yaml", "config/backtest.yaml",
    "config/research_status.yaml", "data/data_manifest.json", "src",
    "tests", "backtests/lse_2026", "backtests/dukascopy_long_history",
    "backtests/phase567", "backtests/remediation", "backtests/practical_yearly",
    "audits", "provenance/manifest.json",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    missing = [entry for entry in REQUIRED if not (PACKAGE / entry).exists()]
    if missing:
        raise SystemExit(f"Missing required package entries: {missing}")
    try:
        import yaml
    except ImportError as error:
        raise SystemExit("PyYAML is required to validate package YAML") from error
    for name in ("strategy.yaml", "config/backtest.yaml", "config/research_status.yaml"):
        with (PACKAGE / name).open() as stream:
            if yaml.safe_load(stream) is None:
                raise SystemExit(f"Empty YAML: {name}")
    manifest = json.loads((PACKAGE / "provenance/manifest.json").read_text())
    failures = []
    for relative, record in manifest["files"].items():
        path = PACKAGE / relative
        if not path.is_file() or sha256(path) != record["sha256"]:
            failures.append(relative)
    if failures:
        raise SystemExit(f"SHA256 verification failed: {failures}")
    if len(manifest["files"]) != manifest["file_count_excluding_manifest"]:
        raise SystemExit("Manifest file count mismatch")
    print(f"Verified {len(manifest['files'])} package files and 3 YAML files.")


if __name__ == "__main__":
    main()
