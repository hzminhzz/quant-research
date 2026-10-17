"""Historic agent-context archive preserves every tracked byte and live entry point."""
from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs/architecture/dual_mode_20261015/archive_inventory.md"
ARCHIVE = ROOT / "archive/legacy_v1"
TARGET_GLOBS = (
    "scripts/run_*.py", "scripts/audit_*.py", "scripts/prepare_*.py",
    "scripts/verify_*.py", "scripts/finalize_*.py",
    "config/research_sessions/*.yaml",
)
ARCHIVED_SCRIPTS = {
    "scripts/audit_milkman_extended_2015_2024.py",
    "scripts/audit_milkman_native_cfd_20261014.py",
    "scripts/run_eow_rebuild.py",
    "scripts/run_ftmo_challenge_simulation.py",
    "scripts/run_full_10y_backtest.py",
    "scripts/run_orb_dual_session.py",
    "scripts/run_orb_filtered_matrix.py",
    "scripts/run_orb_final_benchmark.py",
    "scripts/run_orb_ml_research.py",
    "scripts/run_orb_multi_asset.py",
    "scripts/run_orb_parallel_matrix.py",
    "scripts/run_orb_raw_optimization.py",
    "scripts/run_pipeline.py",
    "scripts/run_validated_orb.py",
}


def test_archive_is_lossless_and_historical_entry_points_remain_compatible() -> None:
    text = INVENTORY.read_text(encoding="utf-8")
    listed = dict(re.findall(r"\| `([^`]+)` \| (?:tracked|untracked) \| `([0-9a-f]{64})` \|", text))
    assert len(listed) == 38
    expected_archived = ARCHIVED_SCRIPTS | {
        path for path in listed if path.startswith("config/research_sessions/")
        and not path.endswith("fomc_sp500_overnight_gross_phase3_20261015_v1.yaml")
    }
    assert len(expected_archived) == 29
    actual_archived = set()
    for relative, expected_sha in listed.items():
        original = ROOT / relative
        archived = ARCHIVE / relative
        if relative in expected_archived:
            assert archived.is_file() and not archived.is_symlink(), relative
            assert hashlib.sha256(archived.read_bytes()).hexdigest() == expected_sha, relative
            actual_archived.add(relative)
            # Original tracked CLI/configuration paths stay byte-identical until
            # their consumers have demonstrated native execution parity.
            assert original.is_file() and not original.is_symlink(), relative
            assert hashlib.sha256(original.read_bytes()).hexdigest() == expected_sha, relative
            if original.suffix == ".py":
                ast.parse(original.read_text(encoding="utf-8"), filename=relative)
        else:
            assert original.is_file() and not original.is_symlink(), relative
            assert not archived.exists(), relative
            assert hashlib.sha256(original.read_bytes()).hexdigest() == expected_sha, relative
    assert actual_archived == expected_archived
    active = {
        path.relative_to(ROOT).as_posix()
        for pattern in TARGET_GLOBS
        for path in ROOT.glob(pattern)
        if path.is_file()
    }
    assert active == set(listed)
    assert {
        path.relative_to(ARCHIVE).as_posix()
        for path in ARCHIVE.rglob("*")
        if path.suffix in {".py", ".yaml"} and path.is_file()
    } == expected_archived
