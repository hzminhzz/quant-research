"""Regression checks for the read-only inbox pilot verifier.

These pin the two properties that make `scripts/inbox_pilot_evidence.py` evidence
rather than a formality: its HAC reconstruction matches the native Stage 2
convention to floating-point precision, and it fails closed instead of
reporting success when there is nothing verifiable.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from scripts.inbox_pilot_evidence import (
    VerificationError,
    main,
    newey_west_t,
    verify_ledger,
)


def test_newey_west_reconstruction_matches_the_reported_convention() -> None:
    # Values and expected statistics come from the native Stage 2 diagnostic for
    # ats_crypto_xs_90d_high_anchoring_local_adaptation_20261018.
    series = [0.05, -0.02, 0.11, 0.0, -0.07, 0.03, 0.04, -0.01, 0.02, 0.06]
    mean, se, t_stat = newey_west_t(series, lags=2)
    n = len(series)
    deviation = [value - mean for value in series]
    dof = n - 1
    long_run = sum(value * value for value in deviation) / dof
    for lag in (1, 2):
        weight = 1.0 - lag / 3.0
        long_run += 2.0 * weight * sum(deviation[i] * deviation[i - lag] for i in range(lag, n)) / dof
    assert mean == pytest.approx(sum(series) / n, abs=0.0)
    assert se == pytest.approx(math.sqrt(long_run / n), rel=1e-15)
    assert t_stat == pytest.approx(mean / math.sqrt(long_run / n), rel=1e-15)


def test_ledger_walk_accepts_a_valid_chain_and_rejects_tampering(tmp_path: Path) -> None:
    from src.engine.common import append_trial

    ledger = tmp_path / "log"
    append_trial(ledger, {"event": "registered", "attempt_id": "a1", "spec_hash": "s" * 64})
    append_trial(ledger, {"event": "completed", "attempt_id": "a1", "spec_hash": "s" * 64,
                          "holdout_access": False,
                          "casefile": {"path": "x/casefile.json", "sha256": "h" * 64}})
    count, completed = verify_ledger(ledger / "trial_ledger.jsonl")
    assert count == 2
    assert completed["s" * 64][0]["attempt_id"] == "a1"

    lines = (ledger / "trial_ledger.jsonl").read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["event"] = "tampered"
    (ledger / "trial_ledger.jsonl").write_text(
        json.dumps(record) + "\n" + lines[1] + "\n", encoding="utf-8")
    with pytest.raises(VerificationError, match="digest mismatch|chain broken"):
        verify_ledger(ledger / "trial_ledger.jsonl")


def test_cli_fails_closed_when_no_terminal_casefile_exists(tmp_path: Path, capsys) -> None:
    from src.engine.common import append_trial

    run_log = tmp_path / "run_log"
    append_trial(run_log, {"event": "registered", "attempt_id": "a1", "spec_hash": "s" * 64})
    (run_log / "inbox_factory" / "candidates" / "cand").mkdir(parents=True)
    (run_log / "inbox_factory" / "candidates" / "cand" / "state.json").write_text(
        json.dumps({"candidate_id": "cand", "status": "BLOCKED_SPEC", "holdout_access": False}),
        encoding="utf-8")
    assert main(["--inbox-state-root", str(run_log / "inbox_factory"),
                 "--run-log", str(run_log)]) == 2
    assert "NOT_VERIFIED" in capsys.readouterr().err
