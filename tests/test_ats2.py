"""ATS-2 action contract regressions use only frozen synthetic research inputs."""
from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import signal
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from src.research_control.action_authorization import (
    TrustPolicyV1,
    build_scope,
    issue_synthetic_grant,
    public_key_b64,
)
from src.research_control.ats2 import (
    ActionContractV1,
    _hash,
    observe_run,
    prepare_action,
    start_action,
    verify_result,
)
from src.research_control.attempts import AttemptLedger
from tests.test_run_permit import gate, intent, setup_trial


def _start_in_process(args):
    root, action, request, computation, data, contract, grant, policy_path = args
    return start_action(root, action, request, computation, data, contract,
                        grant=grant, trusted_policy_path=policy_path,
                       list_jobs=lambda: set())


def _crashable_claimed_worker(root, session_id, attempt_id, ready):
    ledger = AttemptLedger(root, session_id, list_jobs=lambda: set())
    with ledger.worker_lease(attempt_id):
        ledger.transition(attempt_id, "RUNNING", detail="synthetic crash worker started")
        evidence = Path(root) / "run_log/ats2/staging" / attempt_id / "partial.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_bytes(b"old partial output")
        digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
        ledger.record_checkpoint(
            attempt_id, progress=1,
            artifacts={str(evidence.relative_to(root)): digest},
        )
        ready.set()
        while True:
            time.sleep(0.1)


def prepared(tmp_path, *, memory_mb: int | None = None):
    data, contract, computation, evidence = setup_trial(tmp_path)
    request = intent(data, evidence)
    if memory_mb is not None:
        request["budget"]["max_memory_mb"] = memory_mb
        request["requested_compute"]["max_memory_mb"] = memory_mb
    action = prepare_action(
        tmp_path, request, computation, data, contract,
        signal_at=data["timestamp"][1], quantity=1,
        stop_price=99.0, limit_price=101.4,
    )
    return action, request, data, contract, computation


def authorization(root, action, request):
    key = Ed25519PrivateKey.generate()
    trust = root / "trust"
    trust.mkdir(exist_ok=True)
    policy_path = trust / "policy.json"
    policy = TrustPolicyV1.model_validate({
        "schema_version": 1, "trust_domain": "SYNTHETIC_ONLY",
        "max_grant_seconds": 3600,
        "issuers": ({"issuer_id": "ats2-test-issuer",
                     "public_key_b64": public_key_b64(key), "enabled": True},),
        "revoked_grant_ids": (),
    })
    policy_path.write_text(policy.model_dump_json())
    start = datetime.fromisoformat(request["evaluation_start"])
    end = datetime.fromisoformat(request["evaluation_end"])
    scope = build_scope(action, window_start=start, window_end=end,
                        selection_sha256=action.selection_sha256)
    now = datetime.now().astimezone()
    grant = issue_synthetic_grant(
        scope, issuer_id="ats2-test-issuer", private_key=key,
        issued_at=now, expires_at=now + __import__("datetime").timedelta(minutes=10),
    )
    return grant, policy_path


def test_prepare_start_observe_verify_native_development_action(tmp_path):
    action, request, data, contract, computation = prepared(tmp_path)
    assert not (tmp_path / "run_log/ats2").exists()
    grant, policy_path = authorization(tmp_path, action, request)
    result = start_action(tmp_path, action, request, computation, data, contract,
                          grant=grant, trusted_policy_path=policy_path,
                          list_jobs=lambda: set())
    assert result["status"] == "OUTPUT_READY", result
    observed = observe_run(tmp_path, action.session_id, result["attempt_id"])
    assert observed["completion"] == "OUTPUT_READY"
    verified = verify_result(tmp_path, action.session_id, result["attempt_id"])
    assert verified["state"] == "VERIFIED"
    scope = verified["kernel_resource_enforcement"]
    assert scope["kernel_enforced"] is True
    assert scope["hard_limit_bytes"] == action.max_memory_mb * 1024**2
    assert scope["swap_limit_bytes"] == 0
    assert verify_result(tmp_path, action.session_id, result["attempt_id"])["sha256"] == verified["sha256"]
    manifest = json.loads((tmp_path / result["artifact_path"] / "execution_audit.json").read_text())
    assert manifest["live_order_authority"] is False
    assert verified["attestation"].endswith("/verification.json")


def test_action_is_strict_and_stale_inputs_do_not_start(tmp_path):
    action, request, data, contract, computation = prepared(tmp_path)
    grant, policy_path = authorization(tmp_path, action, request)
    with pytest.raises(ValidationError):
        ActionContractV1.model_validate(
            action.model_dump() | {"shell": "echo unsafe"}
        )
    changed = action.model_dump()
    changed["parameters"]["quantity"] = 99
    with pytest.raises(ValidationError, match="ACTION_CONTRACT_HASH_MISMATCH"):
        ActionContractV1.model_validate(changed)
    changed = action.model_dump(mode="json")
    changed["write_scope"] = "run_log/ats2/other-session"
    changed["contract_sha256"] = _hash(
        {key: value for key, value in changed.items() if key != "contract_sha256"}
    )
    changed["expected_outputs"] = tuple(changed["expected_outputs"])
    mutated_scope = ActionContractV1.model_validate(changed)
    with pytest.raises(ValueError, match="ACTION_SCOPE_MUTATED"):
        start_action(tmp_path, mutated_scope, request, computation, data, contract,
                     grant=grant, trusted_policy_path=policy_path,
                     list_jobs=lambda: set())
    (tmp_path / "src/strategy.py").write_text("RULE_VERSION = 9\n")
    with pytest.raises(ValueError, match="PREPARE_BLOCKED|ACTION_IDENTITY_STALE"):
        start_action(tmp_path, action, request, computation, data, contract,
                     grant=grant, trusted_policy_path=policy_path,
                     list_jobs=lambda: set())


def test_two_real_processes_admit_one_native_action(tmp_path):
    action, request, data, contract, computation = prepared(tmp_path)
    grant, policy_path = authorization(tmp_path, action, request)
    payload = (str(tmp_path), action, request, computation, data, contract,
               grant, str(policy_path))
    with ProcessPoolExecutor(max_workers=2,
                             mp_context=multiprocessing.get_context("spawn")) as pool:
        results = list(pool.map(_start_in_process, [payload, payload]))
    assert sum(item["status"] == "OUTPUT_READY" for item in results) == 1, results
    from src.research_control.attempts import AttemptLedger

    records = AttemptLedger(tmp_path, action.session_id, list_jobs=lambda: set()).events()
    reservations = [event for event in records if event["status"] == "PLANNED"]
    assert len(reservations) == 1
    assert len({event["attempt_id"] for event in records}) == 1


def test_sigkill_reclaim_fences_late_write_and_completion(tmp_path):
    data, contract, computation, evidence = setup_trial(tmp_path)
    permit = gate(tmp_path, data, contract, computation, evidence)
    assert permit.status == "PASS"
    ledger = AttemptLedger(tmp_path, contract.session_id, list_jobs=lambda: set())
    claim = ledger.claim(permit, job_name="ml4t-ats2-crash",
                         command="ats2:crash-fixture", lease_seconds=1,
                         managed_worker=True)
    assert claim.status == "LAUNCH"
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Event()
    worker = ctx.Process(target=_crashable_claimed_worker,
                         args=(str(tmp_path), contract.session_id, claim.attempt_id, ready))
    worker.start()
    assert ready.wait(15)
    assert ledger.worker_lock_status(claim.attempt_id) == "WORKER_LOCK_HELD"
    assert ledger.claim(permit, job_name="ml4t-ats2-crash",
                        command="ats2:crash-fixture", lease_seconds=1,
                        managed_worker=True).reason_code == "WORKER_LOCK_HELD"
    os.kill(worker.pid, signal.SIGKILL)
    worker.join(15)
    assert worker.exitcode == -signal.SIGKILL
    time.sleep(1.05)
    successor = ledger.claim(permit, job_name="ml4t-ats2-crash",
                             command="ats2:crash-fixture", lease_seconds=10,
                             managed_worker=True)
    assert successor.status == "LAUNCH"
    old = ledger.latest()[claim.attempt_id]
    new = ledger.latest()[successor.attempt_id]
    assert old["status"] == "ABORTED"
    assert new["fencing_token"] > old["fencing_token"]
    accepted = tmp_path / "run_log/ats2/accepted/synthetic/crash-result.json"
    with ledger.worker_lease(successor.attempt_id):
        assert ledger.transition(successor.attempt_id, "RUNNING").reason_code == "ATTEMPT_STATE_RECORDED"
        ledger.publish_fenced(
            successor.attempt_id, new["fencing_token"],
            relative_path="run_log/ats2/accepted/synthetic/crash-result.json",
            payload=b"new owner accepted result",
        )
        with pytest.raises(ValueError, match="FENCED_WRITE_REJECTED"):
            ledger.publish_fenced(
                claim.attempt_id, old["fencing_token"],
                relative_path="run_log/ats2/accepted/synthetic/crash-result.json",
                payload=b"late old owner output",
            )
        assert ledger.transition(claim.attempt_id, "COMPLETED",
                                 detail="late completion packet").reason_code == "ATTEMPT_ALREADY_TERMINAL"
    assert accepted.read_bytes() == b"new owner accepted result"
    rejected = list((ledger.path / "rejected_late").glob("*.json"))
    assert len(rejected) >= 2


def test_resource_budget_exhaustion_is_recorded_without_retry(tmp_path):
    # 128 MiB is intentionally insufficient for this real native fixture.
    # The kernel must terminate it in a cgroup rather than sampled-RSS polling.
    action, request, data, contract, computation = prepared(tmp_path, memory_mb=128)
    grant, policy_path = authorization(tmp_path, action, request)
    result = start_action(tmp_path, action, request, computation, data, contract,
                          grant=grant, trusted_policy_path=policy_path)
    assert result["status"] == "BUDGET_EXHAUSTED", result
    resource = json.loads((tmp_path / result["resource_evidence"]).read_text())
    assert resource["requested_memory_max_bytes"] == 128 * 1024**2
    assert resource["terminal_scope"]["result"] == "oom-kill"
    assert resource["last_verified_scope"]["memory_max_bytes"] == 128 * 1024**2
    assert resource["last_verified_scope"]["memory_swap_max_bytes"] == 0
    view = observe_run(tmp_path, action.session_id, result["attempt_id"])
    assert view["state"] == "FAILED"
    ledger = AttemptLedger(tmp_path, action.session_id)
    assert len([event for event in ledger.events()
                if event["attempt_id"] == result["attempt_id"] and event["status"] == "PLANNED"]) == 1
    second = start_action(tmp_path, action, request, computation, data, contract,
                          grant=grant, trusted_policy_path=policy_path)
    assert second["reason_code"] == "TERMINAL_ATTEMPT_RETAINED"
    assert len([event for event in ledger.events() if event["status"] == "PLANNED"]) == 1
