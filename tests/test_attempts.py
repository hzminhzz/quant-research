"""Append-only attempts and safe tmux recovery without spawning OS processes."""
from datetime import UTC, datetime, timedelta

from src.research_control.attempts import AttemptLedger
from tests.test_run_permit import gate, setup_trial


def prepared(tmp_path, *, visibility=None, clock=None):
    data, contract, comp, evidence = setup_trial(tmp_path)
    report = gate(tmp_path, data, contract, comp, evidence)
    assert report.status == "PASS"
    ledger = AttemptLedger(
        tmp_path, report.permit.session_id, list_jobs=lambda: visibility[0],
        clock=clock
    )
    return ledger, report


def test_visibility_unknown_blocks_before_create(tmp_path):
    visibility = [None]
    ledger, permit = prepared(tmp_path, visibility=visibility)
    result = ledger.claim(permit, job_name="ml4t-m4c", command="python native_test.py")
    assert (result.status, result.reason_code) == ("BLOCKED", "JOB_VISIBILITY_UNKNOWN")
    assert ledger.events() == []


def test_duplicate_running_resumes_exact_attempt_then_reuses_completed(tmp_path):
    visibility = [set()]
    ledger, permit = prepared(tmp_path, visibility=visibility)
    first = ledger.claim(permit, job_name="ml4t-m4c", command="python native_test.py")
    assert first.status == "LAUNCH"
    assert ledger.claim(permit, job_name="ml4t-m4c", command="python native_test.py").reason_code == "LEASE_UNCERTAIN"
    assert ledger.transition(first.attempt_id, "RUNNING").reason_code == "ATTEMPT_STATE_RECORDED"
    visibility[0] = {"ml4t-m4c", "unrelated-other-task"}
    resumed = ledger.claim(permit, job_name="ml4t-m4c", command="python native_test.py")
    assert resumed.status == "RESUME" and resumed.attempt_id == first.attempt_id
    assert ledger.transition(first.attempt_id, "COMPLETED", detail="artifact hash checked").reason_code == "ATTEMPT_STATE_RECORDED"
    reused = ledger.claim(permit, job_name="ml4t-m4c", command="python native_test.py")
    assert reused.status == "REUSE" and reused.attempt_id == first.attempt_id
    assert [e["status"] for e in ledger.events()] == ["PLANNED", "RUNNING", "COMPLETED"]
    assert len({e["run_id"] for e in ledger.events()}) == 1
    assert len({e["revision"] for e in ledger.events()}) == 3
    assert visibility[0] == {"ml4t-m4c", "unrelated-other-task"}


def test_disappeared_running_job_is_not_reattached_or_duplicated(tmp_path):
    visibility = [set()]
    ledger, permit = prepared(tmp_path, visibility=visibility)
    first = ledger.claim(permit, job_name="ml4t-m4c", command="python native_test.py")
    assert first.status == "LAUNCH"
    assert ledger.transition(first.attempt_id, "RUNNING").reason_code == "ATTEMPT_STATE_RECORDED"
    # A process that vanished before its lease expires has an uncertain outcome.
    decision = ledger.claim(permit, job_name="ml4t-m4c", command="python native_test.py")
    assert decision.status == "BLOCKED"
    assert decision.reason_code == "LEASE_UNCERTAIN"
    assert decision.attempt_id == first.attempt_id
    assert ledger.latest()[first.attempt_id]["status"] == "RUNNING"


def test_expired_lease_preserves_aborted_and_new_attempt(tmp_path):
    time = [datetime(2026, 1, 5, tzinfo=UTC)]
    visibility = [set()]
    ledger, permit = prepared(tmp_path, visibility=visibility, clock=lambda: time[0])
    first = ledger.claim(permit, job_name="ml4t-m4c", command="native", lease_seconds=30)
    assert first.status == "LAUNCH"
    time[0] += timedelta(seconds=31)
    second = ledger.claim(permit, job_name="ml4t-m4c", command="native", lease_seconds=30)
    assert second.status == "LAUNCH" and second.attempt_id != first.attempt_id
    assert ledger.latest()[first.attempt_id]["status"] == "ABORTED"
    assert ledger.latest()[second.attempt_id]["status"] == "PLANNED"
    assert ledger.transition(first.attempt_id, "COMPLETED").reason_code == "ATTEMPT_ALREADY_TERMINAL"


def test_job_name_conflict_and_state_machine_reject_invalid_transition(tmp_path):
    visibility = [set()]
    ledger, permit = prepared(tmp_path, visibility=visibility)
    first = ledger.claim(permit, job_name="ml4t-m4c", command="native")
    assert ledger.claim(permit, job_name="ml4t-m4c", command="modified native").reason_code == "ACTIVE_RUN_EXISTS"
    assert ledger.transition(first.attempt_id, "COMPLETED").reason_code == "ATTEMPT_STATE_INVALID"
    assert ledger.transition(first.attempt_id, "BROKEN").reason_code == "ATTEMPT_STATE_INVALID"
    assert ledger.transition("unknown", "RUNNING").reason_code == "ATTEMPT_UNKNOWN"


def test_stale_head_permit_and_unowned_tmux_fail_closed(tmp_path):
    visibility = [{"ml4t-m4c"}]
    ledger, permit = prepared(tmp_path, visibility=visibility)
    assert ledger.claim(permit, job_name="ml4t-m4c", command="native").reason_code == "ACTIVE_UNOWNED_JOB"
    (tmp_path / "src/strategy.py").write_text("changed", encoding="utf-8")
    from src.research_control.run_permit import GateReport

    stale = GateReport.model_validate(
        {**permit.model_dump(mode="json"), "status": "BLOCKED",
         "reason_code": "IDENTITY_DRIFT", "permit": None}
    )
    assert ledger.claim(stale, job_name="ml4t-m4c", command="native").reason_code == "PERMIT_REQUIRED"
    assert ledger.claim(permit, job_name="ml4t-m4c", command="native").reason_code == "IDENTITY_DRIFT"
