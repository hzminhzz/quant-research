"""M8 recovery qualification; no market-data scan or worker launch occurs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.research_control.attempts import AttemptLedger
from src.research_control.casefile import inspect_resume
from tests.test_run_permit import gate, setup_trial


def test_m8_absent_running_job_blocks_then_records_new_attempt_after_lease(tmp_path):
    data, contract, computation, evidence = setup_trial(tmp_path)
    permit = gate(tmp_path, data, contract, computation, evidence)
    now = [datetime(2026, 10, 13, tzinfo=UTC)]
    jobs = [set()]
    ledger = AttemptLedger(
        tmp_path,
        contract.session_id,
        list_jobs=lambda: jobs[0],
        clock=lambda: now[0],
    )

    first = ledger.claim(
        permit, job_name="ml4t-m8-recovery", command="native", lease_seconds=30
    )
    assert first.status == "LAUNCH"
    assert (
        ledger.transition(first.attempt_id, "RUNNING").reason_code
        == "ATTEMPT_STATE_RECORDED"
    )

    # An active attempt absent from tmux is uncertain. It cannot be replayed.
    inspection = inspect_resume(
        tmp_path,
        contract.session_id,
        first.attempt_id,
        list_jobs=lambda: jobs[0],
    )
    assert (inspection["status"], inspection["reason_code"]) == (
        "BLOCKED",
        "LEASE_UNCERTAIN",
    )
    assert ledger.latest()[first.attempt_id]["status"] == "RUNNING"

    # After lease expiration and confirmed process absence, the aborted
    # attempt remains terminal and any retry has a new accountable identity.
    now[0] += timedelta(seconds=31)
    retry = ledger.claim(
        permit, job_name="ml4t-m8-recovery", command="native", lease_seconds=30
    )
    assert retry.status == "LAUNCH"
    assert retry.attempt_id != first.attempt_id
    assert ledger.latest()[first.attempt_id]["status"] == "ABORTED"
    assert ledger.latest()[retry.attempt_id]["status"] == "PLANNED"
    assert (
        ledger.transition(first.attempt_id, "COMPLETED").reason_code
        == "ATTEMPT_ALREADY_TERMINAL"
    )
