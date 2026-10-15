"""Phase 3 evidence is an explicit agent policy, not an invented runtime gate.

Prove the documented recording example works with unchanged SessionSpecV1.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest
import yaml

from src.research_session import (
    ResearchSessionError,
    init_session,
    record_trial,
    report_session,
)

ROOT = Path(__file__).resolve().parents[1]


def test_operating_contract_requires_prebacktest_signal_evidence() -> None:
    guide = (ROOT / "docs/research_operations.md").read_text(encoding="utf-8")
    sessions = (ROOT / "docs/research_sessions.md").read_text(encoding="utf-8")
    agent = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    template = (ROOT / "docs/phase3_signal_evaluation_template.md").read_text(
        encoding="utf-8"
    )

    assert "Required ResearchPhase 3 decision before a full backtest" in guide
    assert "Pre-backtest signal/economic evaluation: ResearchPhase 3" in sessions
    assert (
        "research_operations.md#required-researchphase-3-decision-before-a-full-backtest"
        in agent
    )
    for outcome in ("PASS", "FAIL", "INCONCLUSIVE", "NOT_APPLICABLE"):
        assert f"**{outcome}**" in guide
        assert f"**{outcome}**" in template
    assert "signal/economic" in sessions
    assert "phase3_signal_evaluation_template.md" in guide
    assert "phase3_signal_evaluation_template.md" in sessions
    assert "does **not** add a new runtime" in guide.lower()
    assert "no" in template.lower() and "runpermit" in template.lower().replace("`", "")
    assert "retrospective" in sessions.lower()
    assert "2025" not in template  # No embedded outcome or reused example holdout.


def test_existing_session_v1_registers_phase3_evidence_outside_control_dir(
    tmp_path: Path,
) -> None:
    (tmp_path / "data").mkdir()
    times = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(4)]
    pl.DataFrame(
        {
            "timestamp": times,
            "open": [1.0, 2.0, 3.0, 4.0],
            "high": [1.0, 2.0, 3.0, 4.0],
            "low": [1.0, 2.0, 3.0, 4.0],
            "close": [1.0, 2.0, 3.0, 4.0],
        }
    ).write_parquet(tmp_path / "data/prices.parquet")

    session_id = "phase3-policy-test"
    spec = {
        "session_id": session_id,
        "thesis": "Conditional next-open returns carry the tested pattern.",
        "mechanism": "Persistent order imbalance.",
        "falsifier": "No positive baseline-adjusted conditional return.",
        "market": "crypto",
        "instruments": [{"symbol": "BTCUSDT", "kind": "spot"}],
        "data": [{"id": "prices", "path": "data/prices.parquet", "role": "prices"}],
        "evaluation": {
            "development_start": "2024-01-01T00:00:00Z",
            "development_end": "2024-01-04T00:00:00Z",
            "holdout_start": "2024-01-04T00:00:00Z",
        },
        "baseline": "Unconditional next-day move.",
        "costs": {"commission_bps": 2, "slippage_bps": 1},
        "trials": [
            {
                "id": "phase3-signal-screen",
                "kind": "diagnostic",
                "description": "Predeclared signed next-open event evidence.",
            },
        ],
    }
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(spec), encoding="utf-8")
    frozen = init_session(path, tmp_path)
    assert frozen["status"] == "FROZEN"

    artifact = tmp_path / "run_log" / "diagnostics" / session_id
    artifact.mkdir(parents=True)
    report = artifact / "phase3_signal_evaluation.md"
    report.write_text(
        "# Phase 3\n\nINCONCLUSIVE — insufficient independence.\n", encoding="utf-8"
    )

    result = record_trial(
        session_id,
        "phase3-signal-screen",
        "completed",
        report.relative_to(tmp_path).as_posix(),
        tmp_path,
    )
    assert result["kind"] == "diagnostic"
    assert result["status"] == "completed"
    assert result["artifact_generation_verified"] is False
    assert result["artifact"]["exists"] is True

    full_report = report_session(session_id, tmp_path)
    assert full_report["approval_status"] == "NOT_APPROVED"

    control = tmp_path / "run_log/research_sessions" / session_id
    invalid = control / "arbitrary.md"
    invalid.write_text("not an accepted result location", encoding="utf-8")
    with pytest.raises(ResearchSessionError, match="session control file"):
        record_trial(
            session_id,
            "phase3-signal-screen",
            "completed",
            invalid.relative_to(tmp_path).as_posix(),
            tmp_path,
        )
