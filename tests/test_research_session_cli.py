from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_research_session import prepare, write_spec

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/research_session.py"


def cli(root: Path, *args: str):
    """Run the real entry point, never main() or an argparse mock."""
    process = subprocess.run(
        [sys.executable, str(SCRIPT), *args, "--root", str(root)],
        cwd=root, capture_output=True, text=True, timeout=30, check=False,
    )
    assert not process.stderr
    return process.returncode, json.loads(process.stdout)


def test_cli_full_session_records_failures_and_never_promotes(tmp_path):
    path, _ = prepare(tmp_path)
    artifact = tmp_path / "failed-run.txt"
    artifact.write_text("Runner failure")

    init_code, frozen = cli(tmp_path, "init", "--spec", str(path))
    check_code, audit = cli(tmp_path, "check", "--session", "thesis-01")
    record_code, record = cli(
        tmp_path, "record", "--session", "thesis-01", "--trial", "fixed-rule",
        "--status", "failed", "--artifact", str(artifact),
    )
    report_code, report = cli(tmp_path, "report", "--session", "thesis-01")

    assert [init_code, check_code, record_code, report_code] == [0, 0, 0, 0]
    assert frozen["status"] == "FROZEN"
    assert audit["status"] == "PASS"
    assert record["status"] == "failed"
    assert report["trials"][0]["status"] == "failed"
    assert report["approval_status"] == "NOT_APPROVED"


@pytest.mark.parametrize("bad_yaml", ["[]", "thesis: [", "session_id: x\nsession_id: y\n"])
def test_cli_malformed_yaml_is_json_error_without_writes(tmp_path, bad_yaml):
    path = tmp_path / "spec.yaml"
    path.write_text(bad_yaml)

    code, result = cli(tmp_path, "init", "--spec", str(path))

    assert code == 2
    assert result["status"] == "ERROR"
    assert not (tmp_path / "run_log").exists()


@pytest.mark.parametrize("target", ["session", "trial", "data"])
def test_cli_duplicate_and_traversal_ids_reject(tmp_path, target):
    path, spec = prepare(tmp_path)
    if target == "session":
        spec["session_id"] = "../escape"
    elif target == "trial":
        spec["trials"].append(spec["trials"][0].copy())
    else:
        spec["data"][0]["id"] = "../escape"
    write_spec(path, spec)

    code, result = cli(tmp_path, "init", "--spec", str(path))

    assert code == 2
    assert result["status"] == "ERROR"


def test_cli_missing_data_blocks_check_and_registers_failed_diagnostic(tmp_path):
    path, _ = prepare(tmp_path)
    (tmp_path / "data/prices.parquet").unlink()
    assert cli(tmp_path, "init", "--spec", str(path))[0] == 0

    check_code, check = cli(tmp_path, "check", "--session", "thesis-01")
    code, result = cli(tmp_path, "diagnose", "--session", "thesis-01", "--trial", "coverage")
    report_code, report = cli(tmp_path, "report", "--session", "thesis-01")

    assert check_code == code == 2
    assert check["status"] == "BLOCKED"
    assert result["status"] == "failed"
    assert report_code == 0
    assert report["trials"][1]["status"] == "failed"


def test_cli_diagnostic_executes_and_reruns_preserve_artifacts(tmp_path):
    path, _ = prepare(tmp_path)
    assert cli(tmp_path, "init", "--spec", str(path))[0] == 0

    code, result = cli(tmp_path, "diagnose", "--session", "thesis-01", "--trial", "coverage")
    artifact = tmp_path / result["artifact"]["path"]
    before = artifact.read_bytes()
    rerun_code, rerun = cli(tmp_path, "diagnose", "--session", "thesis-01", "--trial", "coverage")
    init_code, init_rerun = cli(tmp_path, "init", "--spec", str(path))

    assert code == 0
    assert result["diagnostic"]["summaries"][0]["rows"] == 3
    assert result["diagnostic"]["strategy_evidence"] is False
    assert rerun_code == init_code == 2
    assert rerun["status"] == init_rerun["status"] == "ERROR"
    assert artifact.read_bytes() == before


def test_cli_terminal_duplicate_preserves_failed_record(tmp_path):
    path, _ = prepare(tmp_path)
    assert cli(tmp_path, "init", "--spec", str(path))[0] == 0
    artifact = tmp_path / "failure.log"
    artifact.write_text("Failure")
    assert cli(
        tmp_path, "record", "--session", "thesis-01", "--trial", "fixed-rule",
        "--status", "failed", "--artifact", str(artifact),
    )[0] == 0

    code, result = cli(
        tmp_path, "record", "--session", "thesis-01", "--trial", "fixed-rule",
        "--status", "completed", "--artifact", str(artifact),
    )
    _, report = cli(tmp_path, "report", "--session", "thesis-01")

    assert code == 2
    assert result["status"] == "ERROR"
    assert report["trials"][0]["status"] == "failed"


@pytest.mark.parametrize("trial", ["unknown", "../escape"])
def test_cli_rejects_undeclared_or_traversal_trial(tmp_path, trial):
    path, _ = prepare(tmp_path)
    assert cli(tmp_path, "init", "--spec", str(path))[0] == 0
    artifact = tmp_path / "result.json"
    artifact.write_text("{}")

    code, result = cli(
        tmp_path, "record", "--session", "thesis-01", "--trial", trial,
        "--status", "completed", "--artifact", str(artifact),
    )

    assert code == 2
    assert result["status"] == "ERROR"
