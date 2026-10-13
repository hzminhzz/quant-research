"""Casefile, explain and read-only recovery contracts, independent of market data."""
from src.research_control.attempts import AttemptLedger
from src.research_control.casefile import (
    build_casefile,
    explain_blocker,
    inspect_resume,
)
from tests.test_run_permit import gate, setup_trial


def seeded(tmp_path, visibility):
    data, contract, comp, evidence = setup_trial(tmp_path)
    permit = gate(tmp_path, data, contract, comp, evidence)
    assert permit.status == "PASS"
    ledger = AttemptLedger(
        tmp_path, permit.permit.session_id,
        list_jobs=lambda: visibility[0]
    )
    return ledger, permit


def test_cold_start_casefile_frozen_scope_and_no_provider_scan(tmp_path):
    visibility = [set()]
    ledger, permit = seeded(tmp_path, visibility)
    case = build_casefile(tmp_path, permit.permit.session_id,
                          list_jobs=lambda: visibility[0])
    assert case["scope"] == "research_casefile"
    assert case["status"] == "IN_PROGRESS"
    assert case["hypothesis"]
    assert case["falsifier"]
    assert case["source"]["spec_sha256"]
    assert case["plan"]["evaluation"]["development_start"]
    assert case["trial_status"]["declared"] == 1
    assert case["trial_status"]["pending"] == 1
    assert case["runtime"]["visibility"] == "available"
    assert case["exposure"]["approval_status"] == "NOT_APPROVED"
    assert case["exposure"]["holdout_verified_unseen"] is False
    assert case["effects"] == ["READ_ONLY"]
    assert ledger.events() == []
    assert build_casefile(tmp_path, permit.permit.session_id,
                          list_jobs=lambda: visibility[0]) == case


def test_casefile_running_is_not_pass_and_resume_is_idempotent(tmp_path):
    visibility = [set()]
    ledger, permit = seeded(tmp_path, visibility)
    claim = ledger.claim(permit, job_name="ml4t-casefile", command="native synthetic")
    assert claim.status == "LAUNCH"
    assert ledger.transition(claim.attempt_id, "RUNNING").status == "RESUME"
    visibility[0] = {"ml4t-casefile", "other-untouched"}
    case = build_casefile(tmp_path, permit.permit.session_id,
                          list_jobs=lambda: visibility[0])
    assert case["status"] == "RUNNING"
    assert case["runtime"]["matching_live_jobs"] == ["ml4t-casefile"]
    before = len(ledger.events())
    one = inspect_resume(tmp_path, permit.permit.session_id, claim.attempt_id,
                         list_jobs=lambda: visibility[0])
    two = inspect_resume(tmp_path, permit.permit.session_id, claim.attempt_id,
                         list_jobs=lambda: visibility[0])
    assert one == two and one["status"] == "RUNNING"
    assert len(ledger.events()) == before
    assert visibility[0] == {"ml4t-casefile", "other-untouched"}


def test_unknown_tmux_blocks_and_terminal_is_review_not_pass(tmp_path):
    visibility = [set()]
    ledger, permit = seeded(tmp_path, visibility)
    claim = ledger.claim(permit, job_name="ml4t-casefile", command="native synthetic")
    visibility[0] = None
    case = build_casefile(tmp_path, permit.permit.session_id,
                          list_jobs=lambda: visibility[0])
    assert case["status"] == "BLOCKED"
    assert case["reason_code"] == "JOB_VISIBILITY_UNKNOWN"
    assert inspect_resume(tmp_path, permit.permit.session_id, claim.attempt_id,
                          list_jobs=lambda: visibility[0])["status"] == "BLOCKED"
    visibility[0] = set()
    assert ledger.transition(claim.attempt_id, "FAILED").reason_code == "ATTEMPT_STATE_RECORDED"
    assert inspect_resume(tmp_path, permit.permit.session_id, claim.attempt_id,
                          list_jobs=lambda: visibility[0])["status"] == "REVIEW"
    assert build_casefile(tmp_path, permit.permit.session_id,
                          list_jobs=lambda: visibility[0])["status"] == "BLOCKED"


def test_structured_failure_expected_observed_remedy_and_missing_attempt(tmp_path):
    visibility = [set()]
    ledger, permit = seeded(tmp_path, visibility)
    bad = explain_blocker({
        "status": "BLOCKED", "reason_code": "ENGINE_EXECUTION_INVALID",
        "expected": "stop-first OCO", "observed": "take-profit-first",
        "where_found": "native/fills.parquet",
        "next_safe_action": "Review native order sequencing",
    })
    assert bad["expected"] == "stop-first OCO"
    assert bad["observed"] == "take-profit-first"
    assert bad["where_found"] == "native/fills.parquet"
    assert bad["next_safe_action"] == "Review native order sequencing"
    assert inspect_resume(tmp_path, permit.permit.session_id, "a" * 32,
                          list_jobs=lambda: visibility[0])["reason_code"] == "ATTEMPT_UNKNOWN"
    assert ledger.events() == []
    forged_done = explain_blocker({"status": "PASS", "reason_code": "WORKER_DONE"})
    assert forged_done["status"] == "BLOCKED"
    assert forged_done["reason_code"] == "ASSERTED_SUCCESS_NOT_EVIDENCE"


def test_held_lease_missing_process_never_becomes_pass(tmp_path):
    visibility = [set()]
    ledger, permit = seeded(tmp_path, visibility)
    claim = ledger.claim(permit, job_name="ml4t-casefile", command="native synthetic")
    result = inspect_resume(tmp_path, permit.permit.session_id, claim.attempt_id,
                            list_jobs=lambda: visibility[0])
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "LEASE_UNCERTAIN"
