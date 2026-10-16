"""Kill a real public ATS-2 launcher and recover the same signed native action."""
from __future__ import annotations

import multiprocessing
import signal
import time

import pytest

from src.research_control.ats2 import observe_run, start_action, verify_result
from src.research_control.attempts import AttemptLedger
from tests.test_ats2 import _start_in_process, authorization, prepared


def test_public_native_crash_recovery_preserves_grant_and_replays(tmp_path):
    crash_root = tmp_path / "crashed"
    crash_root.mkdir()
    action, request, data, contract, computation = prepared(crash_root)
    grant, policy = authorization(crash_root, action, request)
    original = (str(crash_root), action, request, computation, data, contract,
                grant, str(policy))
    ctx = multiprocessing.get_context("spawn")
    launcher = ctx.Process(target=_start_in_process, args=(original,))
    launcher.start()
    ledger = AttemptLedger(crash_root, action.session_id, list_jobs=lambda: set())
    first = None
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        candidates = list(ledger.latest().values())
        if candidates and candidates[-1]["status"] == "RUNNING" and candidates[-1].get("checkpoint_path"):
            first = candidates[-1]
            break
        if not launcher.is_alive():
            break
        time.sleep(0.015)
    if first is None:
        if launcher.is_alive():
            launcher.kill()
        launcher.join(timeout=5)
        pytest.fail("PUBLIC_NATIVE_CRASH_POINT_NOT_OBSERVED")
    launcher.kill()
    launcher.join(timeout=5)
    assert launcher.exitcode == -signal.SIGKILL
    uncertain = start_action(crash_root, action, request, computation, data, contract,
                             grant=grant, trusted_policy_path=policy,
                             list_jobs=lambda: set())
    assert uncertain["status"] == "BLOCKED" and uncertain["reason_code"] in (
        "LEASE_UNCERTAIN", "WORKER_LOCK_HELD")
    time.sleep(3.2)
    recovered = start_action(crash_root, action, request, computation, data, contract,
                             grant=grant, trusted_policy_path=policy,
                             list_jobs=lambda: set())
    assert recovered["status"] == "OUTPUT_READY", recovered
    assert recovered["attempt_id"] != first["attempt_id"]
    latest = ledger.latest()
    old = latest[first["attempt_id"]]
    successor = latest[recovered["attempt_id"]]
    assert old["status"] == "ABORTED"
    assert successor["parent_attempt_id"] == old["attempt_id"]
    assert successor["fencing_token"] > old["fencing_token"]
    assert successor["metadata"]["authorization"]["grant_id"] == first["metadata"]["authorization"]["grant_id"] == grant.grant_id
    assert successor["metadata"]["ats2_action"] == first["metadata"]["ats2_action"]
    assert observe_run(crash_root, action.session_id, recovered["attempt_id"])["completion"] == "OUTPUT_READY"
    assert verify_result(crash_root, action.session_id, recovered["attempt_id"])["state"] == "VERIFIED"

    clean_root = tmp_path / "clean"
    clean_root.mkdir()
    control_action, control_request, control_data, control_contract, control_compute = prepared(clean_root)
    control_grant, control_policy = authorization(clean_root, control_action, control_request)
    clean = start_action(clean_root, control_action, control_request, control_compute,
                         control_data, control_contract, grant=control_grant,
                         trusted_policy_path=control_policy, list_jobs=lambda: set())
    assert clean["status"] == "OUTPUT_READY", clean
    assert verify_result(clean_root, control_action.session_id, clean["attempt_id"])["state"] == "VERIFIED"
    recovered_native = crash_root / recovered["artifact_path"] / "native"
    clean_native = clean_root / clean["artifact_path"] / "native"
    for filename in ("fills.parquet", "trades.parquet", "equity.parquet",
                     "portfolio_state.parquet", "daily_pnl.parquet"):
        import polars as pl
        assert pl.read_parquet(recovered_native / filename).equals(
            pl.read_parquet(clean_native / filename)), filename
