"""Headless validation of the marimo notebook DAGs.

The runbook in ``AGENTS.md`` (Verification Runbook, Step 2) requires
``marimo check`` to report zero warnings and zero errors before changes are
committed. This file enforces that rule.

``--strict`` is not used: in marimo 0.24.2 it raises
``UnboundLocalError: cannot access local variable 'fixed'`` even when there are
no issues, so the non-zero exit code cannot be trusted. The JSON summary is the
gate instead.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS = sorted((REPO_ROOT / "notebooks").glob("*.py"))

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


@pytest.mark.parametrize("notebook", NOTEBOOKS, ids=lambda path: path.name)
def test_marimo_check_reports_no_issues(notebook: Path) -> None:
    process = subprocess.run(
        [sys.executable, "-m", "marimo", "check", "--format", "json", str(notebook)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=300,
    )

    output = process.stdout.strip()
    assert output, f"marimo check produced no output; stderr:\n{process.stderr}"

    payload = json.loads(output.splitlines()[-1])
    summary = payload["summary"]

    assert summary["errored"] is False, f"{notebook.name} errored:\n{output}"
    assert summary["total_issues"] == 0, (
        f"{notebook.name} reports {summary['total_issues']} issues:\n"
        f"{json.dumps(payload['issues'], indent=2)}"
    )
    assert process.returncode == 0, (
        f"marimo check exited {process.returncode}; stderr:\n{process.stderr}"
    )
