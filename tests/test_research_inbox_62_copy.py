"""Verify the 62-source copy without interpreting or executing trading rules."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from src.engine.research_capture import capture_source

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "research_inbox"
MANIFEST = ROOT / "docs/audit/ats62_inbox_copy_20261018.json"


def test_source_copy_is_complete_byte_identical_and_non_executable(tmp_path: Path) -> None:
    document = json.loads(MANIFEST.read_text(encoding="utf-8"))
    members = document["files"]
    assert document["thesis_folders"] == 62
    assert document["files_total"] == 124
    assert len(members) == 124

    archive_dirs = {Path(name).parent.name for name in members}
    assert len(archive_dirs) == 62
    all_folders = {p.name for p in INBOX.iterdir() if p.is_dir()}
    assert len(all_folders) == 69
    assert archive_dirs <= all_folders
    assert len(all_folders - archive_dirs) == 7

    for folder in sorted(archive_dirs):
        assert {name for name in members if name.startswith(folder + "/")} == {
            folder + "/thesis.yaml", folder + "/brief.md",
        }
        for filename in ("thesis.yaml", "brief.md"):
            name = f"{folder}/{filename}"
            payload = (INBOX / name).read_bytes()
            assert hashlib.sha256(payload).hexdigest() == members[name]
        assert isinstance(yaml.safe_load((INBOX / folder / "thesis.yaml").read_text(encoding="utf-8")), dict)
        result = capture_source(INBOX / folder, tmp_path / "capture")
        assert result.status == "THESIS_CAPTURED"
        assert result.executable is False
        assert result.source_bytes_ref

    legacy_dirs = all_folders - archive_dirs
    for folder in legacy_dirs:
        assert (INBOX / folder / "thesis.yaml").is_file()
        assert (INBOX / folder / "brief.md").is_file()
