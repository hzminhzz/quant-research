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


class Environment:
    def __init__(self, tmp: Path, repo: Path, bare: Path, receipts: Path):
        self.tmp = tmp
        self.repo = repo
        self.bare = bare
        self.receipts = receipts
        # Simulates CI, whose PYTHONPATH contains only the pinned connector.
        self.pythonpath = tmp / "connector-only"
        self.pythonpath.mkdir(exist_ok=True)


@pytest.fixture
def environment(tmp_path: Path) -> Environment:
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
    subprocess.run(["git", "clone", "--bare", str(upstream), str(bare)], check=True,
                   capture_output=True)
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
    return Environment(tmp_path, repo, bare, tmp_path / "receipts")


def run_script(environment: Environment, *args: str, cwd: Path | None = None):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(environment.pythonpath)
    env.pop("PYTHONSTARTUP", None)
    p = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                       text=True, env=env, cwd=str(cwd or environment.tmp), check=False)
    return p


def invoke(environment: Environment, *extra: str):
    p = run_script(environment, "publish", "--repo", str(environment.repo),
                   "--receipt-root", str(environment.receipts), "--factory", "ml",
                   "--run-id", "fixture-run", *extra)
    assert "ModuleNotFoundError" not in p.stderr, p.stderr
    return p, json.loads(p.stdout)


def receipts_for(environment: Environment, factory: str = "ml") -> list[dict]:
    return [json.loads(path.read_text()) for path in
            sorted((environment.receipts / factory).glob("*.json"))]


def test_publish_remote_verified_and_retry_is_idempotent(environment):
    first, record = invoke(environment)
    assert first.returncode == 0, first.stderr + first.stdout
    assert record["status"] == "REMOTE_PUBLICATION_VERIFIED"
    assert record["remote_sha"] == git(environment.repo, "rev-parse", "HEAD")
    assert git(environment.bare, "rev-parse",
               "refs/heads/research/synthetic-publication") == record["remote_sha"]
    assert record["readback_verified"] is True
    assert all(value is False for value in record["authorization"].values())
    assert record["scope"] == {"scientific_trials": 0, "protected_reads": 0, "orders": 0}
    second, r2 = invoke(environment)
    assert second.returncode == 0
    assert r2["remote_sha"] == record["remote_sha"]
    assert r2["transport_attempts"] == 1
    stored = receipts_for(environment)
    assert len(stored) == 2
    assert {item["remote_sha"] for item in stored} == {record["remote_sha"]}
    assert all(item["receipt_path"].startswith(str(environment.receipts)) for item in stored)


def test_publish_runs_under_ci_direct_script_import_conditions(environment):
    # CI exports PYTHONPATH=.ci/trading-connector only and never exports the
    # checkout root; direct script execution must bootstrap itself.
    p, record = invoke(environment)
    assert p.returncode == 0, p.stderr + p.stdout
    assert record["status"] == "REMOTE_PUBLICATION_VERIFIED"


def test_remote_ref_collision_blocks_without_overwrite(environment):
    git(environment.bare, "branch", "research/synthetic-publication", "main")
    p, result = invoke(environment)
    assert p.returncode == 2
    assert result["status"] == "NOT_PUBLISHED"
    assert "different SHA" in result["reason"]
    assert git(environment.bare, "rev-parse",
               "refs/heads/research/synthetic-publication") == git(environment.bare,
                                                                  "rev-parse", "main")


def test_incomplete_candidate_blocks_and_writes_receipt(environment):
    repo = environment.repo
    git(repo, "reset", "--soft", "HEAD~1")
    git(repo, "rm", "--cached", "-q", f"research_inbox/{TARGET_ID}/brief.md")
    git(repo, "commit", "-m", "incomplete source pair")
    p, record = invoke(environment)
    assert p.returncode == 2
    assert record["status"] == "NOT_PUBLISHED"
    assert "complete source pairs" in record["reason"]
    assert record["error_type"] == "PublicationError"
    stored = receipts_for(environment)
    assert len(stored) == 1
    assert stored[0]["status"] == "NOT_PUBLISHED"
    assert stored[0]["reason"]


def test_out_of_scope_committed_path_blocks(environment):
    (environment.repo / "research_inbox" / TARGET_ID / "notes.md").write_text("staging notes\n")
    git(environment.repo, "add", "research_inbox")
    git(environment.repo, "commit", "-m", "out of scope file")
    p, record = invoke(environment)
    assert p.returncode == 2
    assert "out-of-scope committed path" in record["reason"]


def test_non_research_branch_blocks(environment):
    git(environment.repo, "switch", "-c", "topic/publication")
    p, record = invoke(environment)
    assert p.returncode == 2
    assert "research/* branch" in record["reason"]


def test_worktree_bytes_differing_from_committed_head_block(environment):
    path = f"research_inbox/{TARGET_ID}/thesis.yaml"
    thesis = environment.repo / path
    git(environment.repo, "update-index", "--skip-worktree", path)
    thesis.write_text(thesis.read_text() + "\n")
    p, record = invoke(environment)
    assert p.returncode == 2
    assert "differ from committed HEAD" in record["reason"]


def test_stale_origin_main_blocks(environment):
    other = environment.tmp / "main-advance"
    subprocess.run(["git", "clone", str(environment.bare), str(other)], check=True,
                   capture_output=True)
    git(other, "config", "user.email", "tests@example.org")
    git(other, "config", "user.name", "Tests")
    (other / "ADVANCE.md").write_text("main moved\n")
    git(other, "add", "ADVANCE.md")
    git(other, "commit", "-m", "advance main")
    git(other, "push", "origin", "main")
    p, record = invoke(environment)
    assert p.returncode == 2
    assert "origin/main is stale" in record["reason"]


def test_duplicate_candidate_on_other_remote_branch_blocks(environment):
    other = environment.tmp / "other-research"
    subprocess.run(["git", "clone", str(environment.bare), str(other)], check=True,
                   capture_output=True)
    git(other, "config", "user.email", "tests@example.org")
    git(other, "config", "user.name", "Tests")
    git(other, "switch", "-c", "research/other")
    dest = other / "research_inbox" / TARGET_ID
    shutil.copytree(REPO / "research_inbox" / SOURCE_ID, dest)
    thesis = dest / "thesis.yaml"
    brief = dest / "brief.md"
    thesis.write_text(thesis.read_text().replace(SOURCE_ID, TARGET_ID))
    brief.write_text(brief.read_text().replace(SOURCE_ID, TARGET_ID))
    git(other, "add", "research_inbox")
    git(other, "commit", "-m", "duplicate candidate")
    git(other, "push", "origin", "research/other")
    p, record = invoke(environment)
    assert p.returncode == 2
    assert "already exists on published branch" in record["reason"]


def test_no_op_durable_receipt_without_pythonpath(environment):
    p = run_script(environment, "no-op", "--repo", str(environment.repo),
                   "--receipt-root", str(environment.receipts), "--factory", "crypto",
                   "--run-id", "empty-run", "--reason", "screened candidates all duplicate")
    assert p.returncode == 0, p.stderr + p.stdout
    result = json.loads(p.stdout)
    assert result["status"] == "NO_NOVEL_SOURCE"
    assert result["transport_attempts"] == 0
    assert result["readback_verified"] is False
    stored = receipts_for(environment, "crypto")
    assert len(stored) == 1
    assert stored[0]["status"] == "NO_NOVEL_SOURCE"
    assert stored[0]["receipt_path"] == result["receipt_path"]


def test_no_op_does_not_require_clean_research_branch(environment):
    (environment.repo / "README.md").write_text("dirty tracked work\n")
    git(environment.repo, "switch", "-c", "topic/dirty")
    p = run_script(environment, "no-op", "--repo", str(environment.repo),
                   "--receipt-root", str(environment.receipts), "--factory", "general",
                   "--run-id", "empty-run", "--reason", "no novel sourced candidate")
    assert p.returncode == 0, p.stderr + p.stdout
    assert json.loads(p.stdout)["status"] == "NO_NOVEL_SOURCE"


def test_no_op_requires_reason_and_writes_blocked_receipt(environment):
    p = run_script(environment, "no-op", "--repo", str(environment.repo),
                   "--receipt-root", str(environment.receipts), "--factory", "ml",
                   "--run-id", "empty-run")
    assert p.returncode == 2
    assert json.loads(p.stdout)["status"] == "NOT_PUBLISHED"
    assert receipts_for(environment)[0]["status"] == "NOT_PUBLISHED"


def test_receipt_persistence_failure_exits_three(environment):
    blocker = environment.tmp / "not-a-directory"
    blocker.write_text("occupied\n")
    p = run_script(environment, "no-op", "--repo", str(environment.repo),
                   "--receipt-root", str(blocker), "--factory", "ml",
                   "--run-id", "empty-run", "--reason", "no novel source")
    assert p.returncode == 3
    assert p.stdout.strip() == ""
    assert "RECEIPT_FAILED" in p.stderr


def test_unexpected_admission_failure_still_writes_receipt(environment):
    # A cyclic YAML alias can exhaust recursion outside the narrow admission
    # error tuple; it must still block with a durable receipt, not a bare traceback.
    dest = environment.repo / "research_inbox" / "cyclic_nested_candidate_v1"
    dest.mkdir()
    (dest / "thesis.yaml").write_text(
        """identity:
  candidate_id: cyclic_nested_candidate_v1
  source_references:
    - &loop
      title: Cyclic Anchor
      id: loop-anchor
      children: [*loop]
economic_thesis: {}
markets_and_data: {}
deterministic_strategy_specification: {}
research_evaluation: {}
scientific_integrity: {}
"""
    )
    (dest / "brief.md").write_text("No candidate identity or source URL anchor.\n")
    git(environment.repo, "add", "research_inbox")
    git(environment.repo, "commit", "-m", "cyclic nested source pair")
    p, record = invoke(environment)
    assert p.returncode == 2, p.stderr + p.stdout
    assert record["status"] == "NOT_PUBLISHED"
    assert record["error_type"] == "RecursionError"
    assert "Traceback" not in p.stderr
    stored = receipts_for(environment)
    assert len(stored) == 1
    assert stored[0]["status"] == "NOT_PUBLISHED"
    assert stored[0]["error_type"] == "RecursionError"
