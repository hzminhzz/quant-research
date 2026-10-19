from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "research_source_publication.py"
SOURCE_ID = "oil_to_cad_daily_delayed_adjustment_20261015_v1"
TARGET_ID = "synthetic_source_candidate_v1"


def git(path: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, check=True)
    return p.stdout.strip()


@pytest.fixture
def environment(tmp_path: Path):
    upstream = tmp_path / "upstream"
    bare = tmp_path / "origin.git"
    repo = tmp_path / "checkout"
    upstream.mkdir()
    git(upstream, "init", "-b", "main")
    git(upstream, "config", "user.email", "tests@example.org")
    git(upstream, "config", "user.name", "Tests")
    (upstream / "README.md").write_text("synthetic publication fixture\n")
    git(upstream, "add", ".")
    git(upstream, "commit", "-m", "baseline")
    subprocess.run(["git", "clone", "--bare", str(upstream), str(bare)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(bare), str(repo)], check=True, capture_output=True)
    git(repo, "config", "user.email", "tests@example.org")
    git(repo, "config", "user.name", "Tests")
    git(repo, "switch", "-c", "research/synthetic-publication")
    dest = repo / "research_inbox" / TARGET_ID
    shutil.copytree(REPO / "research_inbox" / SOURCE_ID, dest)
    thesis = dest / "thesis.yaml"
    brief = dest / "brief.md"
    thesis.write_text(thesis.read_text().replace(SOURCE_ID, TARGET_ID))
    brief.write_text(brief.read_text().replace(SOURCE_ID, TARGET_ID))
    git(repo, "add", "research_inbox")
    git(repo, "commit", "-m", "synthetic source pair")
    return repo, bare, tmp_path / "receipts"


def run_cli(environment, action: str, factory: str, run_id: str, *extra: str):
    """Invoke the CLI as a bare script: no PYTHONPATH and no repo-root cwd."""
    repo, _, receipts = environment
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    assert "PYTHONPATH" not in env
    cwd = receipts.parent
    assert cwd != repo and repo not in cwd.parents
    command = [sys.executable, str(SCRIPT), action, "--repo", str(repo),
               "--receipt-root", str(receipts), "--factory", factory,
               "--run-id", run_id, *extra]
    return subprocess.run(command, capture_output=True, text=True, env=env,
                          cwd=str(cwd), check=False)


def invoke(environment, *extra: str):
    p = run_cli(environment, "publish", "ml", "fixture-run", *extra)
    return p, json.loads(p.stdout)


def test_publish_remote_verified_and_retry_is_idempotent(environment):
    repo, bare, _ = environment
    first, record = invoke(environment)
    assert first.returncode == 0, first.stderr + first.stdout
    assert record["status"] == "REMOTE_PUBLICATION_VERIFIED"
    assert record["remote_sha"] == git(repo, "rev-parse", "HEAD")
    assert git(bare, "rev-parse", "refs/heads/research/synthetic-publication") == record["remote_sha"]
    second, r2 = invoke(environment)
    assert second.returncode == 0
    assert r2["remote_sha"] == record["remote_sha"]
    assert r2["transport_attempts"] == 1
    assert len(list((environment[2] / "ml").glob("*.json"))) == 2


def test_remote_ref_collision_blocks_without_overwrite(environment):
    _, bare, _ = environment
    git(bare, "branch", "research/synthetic-publication", "main")
    p, result = invoke(environment)
    assert p.returncode == 2
    assert result["status"] == "NOT_PUBLISHED"
    assert "different SHA" in result["reason"]
    assert git(bare, "rev-parse", "refs/heads/research/synthetic-publication") == git(bare, "rev-parse", "main")


def test_incomplete_candidate_blocks_and_writes_receipt(environment):
    repo, _, receipts = environment
    (repo / "research_inbox" / TARGET_ID / "brief.md").unlink()
    p, record = invoke(environment)
    assert p.returncode == 2
    assert record["status"] == "NOT_PUBLISHED"
    assert list((receipts / "ml").glob("*.json"))


def test_no_op_durable_receipt(environment):
    _, _, receipts = environment
    p = run_cli(environment, "no-op", "crypto", "empty-run",
                "--reason", "screened candidates all duplicate")
    assert p.returncode == 0, p.stderr + p.stdout
    assert "ModuleNotFoundError" not in p.stderr
    result = json.loads(p.stdout)
    assert result["status"] == "NO_NOVEL_SOURCE"
    assert result["reason"] == "screened candidates all duplicate"
    assert result["scope"] == {"scientific_trials": 0, "protected_reads": 0, "orders": 0}
    written = list((receipts / "crypto").glob("*.json"))
    assert len(written) == 1
    assert json.loads(written[0].read_text()) == {
        key: value for key, value in result.items() if key != "receipt_path"
    }
