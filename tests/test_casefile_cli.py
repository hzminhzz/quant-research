"""CLI-level Casefile/explain/resume validation, no external market data."""
import json
import subprocess
import sys
from pathlib import Path

from tests.test_run_permit import setup_trial

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts/research.py"


def invoke(*args):
    return subprocess.run(
        [sys.executable, str(CLI), *args], cwd=ROOT,
        capture_output=True, text=True, check=False, timeout=30,
    )


def test_cli_casefile_cold_start_and_idempotent_invalid_resume(tmp_path):
    setup_trial(tmp_path)
    before = (tmp_path / "run_log/research_sessions/permit-synthetic/frozen_spec.json").read_bytes()
    a = invoke("casefile", "--session", "permit-synthetic", "--root", str(tmp_path))
    b = invoke("casefile", "--session", "permit-synthetic", "--root", str(tmp_path))
    assert a.returncode in (0, 2), a.stderr
    assert b.returncode in (0, 2), b.stderr
    left, right = json.loads(a.stdout), json.loads(b.stdout)
    assert left == right and left["scope"] == "research_casefile"
    assert left["exposure"]["approval_status"] == "NOT_APPROVED"
    assert left["effects"] == ["READ_ONLY"]
    assert left["trial_status"]["declared"] == 1
    assert (tmp_path / "run_log/research_sessions/permit-synthetic/frozen_spec.json").read_bytes() == before
    blocked = invoke("resume", "--session", "permit-synthetic", "--attempt", "a" * 32,
                     "--root", str(tmp_path))
    assert blocked.returncode == 2
    assert json.loads(blocked.stdout)["reason_code"] == "ATTEMPT_UNKNOWN"


def test_cli_explain_verifiable_record_and_reject_external_file(tmp_path):
    record = {
        "status": "BLOCKED", "reason_code": "ENGINE_EXECUTION_INVALID",
        "expected": "stop-first", "observed": "target-first",
        "where_found": "native/fills.parquet",
        "next_safe_action": "Correct bracket ordering"
    }
    (tmp_path / "gate.json").write_text(json.dumps(record))
    response = invoke("explain", "--root", str(tmp_path), "--gate-file", "gate.json")
    assert response.returncode == 2
    result = json.loads(response.stdout)
    for field in ("reason_code", "expected", "observed", "where_found", "next_safe_action"):
        assert result[field] == record[field]
    outside = invoke("explain", "--root", str(tmp_path), "--gate-file", "/etc/passwd")
    assert outside.returncode == 2
    assert json.loads(outside.stdout)["reason_code"] == "INSPECTION_ERROR"
    assert invoke("explain", "--root", str(tmp_path)).returncode == 2
