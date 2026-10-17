"""Reproducible ATS-6 process, failure and independent-evidence acceptance program."""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import sqlite3
import subprocess
import sys
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from scripts.ats6_fixtures import (
    START,
    admitted,
    amended_account,
    create_fixture,
    fill,
    intent,
    observe,
    opening_unknown,
    publish,
    signed,
)
from src.research_control.action_authorization import TrustPolicyV1, canonical_json
from src.shadow_contracts import AccountSnapshot, DomainPolicy, data
from src.shadow_router import ShadowRouter, runtime_identity


def save(path, value):
    with Path(path).open("x", encoding="utf-8") as f:
        json.dump(value, f, sort_keys=True, indent=2)
        f.flush()
        os.fsync(f.fileno())


def worker(path, op, args, output, barrier=None, fault=None):
    if barrier is not None:
        barrier.wait(15)
    r = ShadowRouter(path)
    result = getattr(r, op)(*args, now=START, fault=fault)
    save(output, result)


def join_processes(processes, expected=0):
    for p in processes:
        p.join(25)
        if p.is_alive():
            p.kill()
            p.join(5)
            raise AssertionError("PROCESS_TIMEOUT")
        assert p.exitcode == expected, (p.pid, p.exitcode, expected)


def concurrent(folder, both_fit=False):
    r, key, epoch = create_fixture(folder / "router.db", shared=1000, caps=(700, 700))
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(2)
    lots = 5 if both_fit else 7
    inputs = [signed(r, key, intent("parallel-" + str(i), lots)) for i in range(2)]
    jobs = [ctx.Process(target=worker, args=(str(r.path), "admit", (a, g, epoch),
                                            folder / f"worker-{i}.json", barrier))
            for i, (a, g) in enumerate(inputs)]
    for p in jobs:
        p.start()
    join_processes(jobs)
    return r, {"reserved": 1000 if both_fit else 700, "recognized": 0}


def crashed(folder, point):
    r, key, epoch = create_fixture(folder / "router.db")
    action, grant = signed(r, key, intent("crash"))
    operation = point.split(":")[0]
    args = (action, grant, epoch)
    if operation == "publish":
        assert r.admit(*args, now=START)["status"] == "ADMITTED"
        args = ("crash", 1, epoch)
    ctx = mp.get_context("spawn")
    p = ctx.Process(target=worker, args=(str(r.path), operation, args,
                                         folder / "worker-result.json", None, point))
    p.start()
    code = 91 if point.endswith("before_commit") else 92
    join_processes([p], code)
    save(folder / "crash_evidence.json", {"fault": point, "observed_exitcode": p.exitcode})
    restarted = ShadowRouter(r.path)
    before = restarted.recover()
    save(folder / "recovery_before_retry.json", before)
    retry = restarted.admit(action, grant, epoch, now=START)
    assert retry["reason"] in ("ADMISSION_COMMITTED", "EXISTING_DECISION")
    revision = restarted.snapshot()["routes"]["crash"]["revision"]
    restarted.publish("crash", revision, epoch, now=START)
    restarted.publish("crash", revision, epoch, now=START)  # Local outbox delivery retry.
    restarted.confirm_publication("crash", epoch, now=START)
    return restarted, {"reserved": 600, "recognized": 0}


def clean(folder):
    r, key, epoch = create_fixture(folder / "router.db")
    admitted(r, key, epoch, intent("crash"))
    publish(r, "crash", epoch)
    r.confirm_publication("crash", epoch, now=START)
    return r, {"reserved": 600, "recognized": 0}


def partial(folder):
    r, key, epoch = create_fixture(folder / "router.db", shared=1200, caps=(1200,))
    admitted(r, key, epoch, intent("partial", 10))
    publish(r, "partial", epoch)
    one, two, close_fill = fill("one", 4), fill("two", 2), fill("close", 3, role="close")
    observe(r, "partial", epoch, 1, "ack")
    observe(r, "partial", epoch, 2, "fill", executions=(one,))
    observe(r, "partial", epoch, 3, "cancel")
    assert r.snapshot()["usage"]["shared"]["reserved"] == 600
    observe(r, "partial", epoch, 4, "fill", executions=(two,))
    observe(r, "partial", epoch, 5, "reconcile", executions=(one, two),
            terminal="canceled", complete=True)
    observe(r, "partial", epoch, 6, "fill", executions=(close_fill,))
    assert r.snapshot()["usage"]["shared"]["recognized"] == 600
    observe(r, "partial", epoch, 7, "reconcile", executions=(one, two, close_fill),
            terminal="canceled", complete=True)
    return r, {"reserved": 0, "recognized": 300}


def lost_ack(folder):
    r, key, epoch = create_fixture(folder / "router.db")
    a, g = admitted(r, key, epoch, intent("lost"))
    publish(r, "lost", epoch)
    observe(r, "lost", epoch, 1, "unknown")
    r = ShadowRouter(r.path)
    r.recover()
    assert r.admit(a, g, epoch, now=START + timedelta(seconds=2))["reason"] == "EXISTING_DECISION"
    observe(r, "lost", epoch, 3, "ack")
    observe(r, "lost", epoch, 3, "ack", now=START + timedelta(seconds=4),
            at=START + timedelta(seconds=3))
    observe(r, "lost", epoch, 5, "unknown")
    return r, {"reserved": 600, "recognized": 0, "unknown": 600}


def stale_control_and_clocks(folder):
    r, key, epoch = create_fixture(folder / "router.db")
    admitted(r, key, epoch, intent("event-clocks"))
    publish(r, "event-clocks", epoch, now=START + timedelta(seconds=1))
    observe(r, "event-clocks", epoch, 2, "ack", now=START + timedelta(seconds=3),
            at=START + timedelta(seconds=2))
    observe(r, "event-clocks", epoch, 5, "unknown")
    result = observe(r, "event-clocks", epoch, 3, "ack", now=START + timedelta(seconds=6),
                     at=START + timedelta(seconds=3))
    assert result["reason"] == "STALE_EXECUTION_CONTROL_EVENT"
    observe(r, "event-clocks", epoch, 4, "fill", executions=(fill("delayed-fill", 2),),
            now=START + timedelta(seconds=7), at=START + timedelta(seconds=4))
    events = r.audit_events("event-clocks")
    save(folder / "ats3_events.json", data(events))
    by_kind = {e.kind: e for e in events}
    assert by_kind["order"].event_at == START + timedelta(seconds=1)
    assert by_kind["ack"].event_at == START + timedelta(seconds=2)
    assert by_kind["ack"].available_at == START + timedelta(seconds=3)
    assert by_kind["fill"].event_at == START + timedelta(seconds=4)
    assert by_kind["fill"].available_at == START + timedelta(seconds=7)
    return r, {"reserved": 400, "recognized": 200, "unknown": 400}


def rejected(folder):
    r, key, epoch = create_fixture(folder / "router.db")
    admitted(r, key, epoch, intent("rejected"))
    publish(r, "rejected", epoch)
    observe(r, "rejected", epoch, 1, "reject")
    assert r.snapshot()["usage"]["shared"]["reserved"] == 600
    observe(r, "rejected", epoch, 2, "reconcile", terminal="rejected", complete=True)
    return r, {"reserved": 0, "recognized": 0}


def stale_source(folder, kind):
    r, key, epoch = create_fixture(folder / "router.db", caps=(800,))
    snapshot = AccountSnapshot.model_validate(r.snapshot()["accounts"]["shadow:a"])
    changes = {"revision": 2}
    if kind == "mark":
        changes["valid_until"] = START + timedelta(seconds=1)
    elif kind == "coverage":
        binding = data(snapshot.binding)
        binding["coverage"] = []
        changes["binding"] = binding
    else:
        changes["margin_capacity_units"] = None
    assert r.update_account(snapshot.model_copy(update=changes), epoch, now=START)["status"] == "UPDATED"
    a, g = signed(r, key, intent("stale"))
    assert r.admit(a, g, epoch, now=START + timedelta(seconds=2))["status"] == "SKIPPED"
    return r, {"reserved": 0, "recognized": 0}


def changed(folder, kind):
    r, key, epoch = create_fixture(folder / "router.db")
    a, g = signed(r, key, intent("changed"))
    if kind != "prepared_account":
        assert r.admit(a, g, epoch, now=START)["status"] == "ADMITTED"
    now = START + timedelta(seconds=2)
    if kind == "revoke":
        p = TrustPolicyV1.model_validate_json(canonical_json(r.snapshot()["authority"]))
        r.update_authority(p.model_copy(update={"revoked_grant_ids": (g["grant_id"],)}),
                           1, epoch, now=now)
    elif kind == "global_limit":
        p = DomainPolicy.model_validate(r.snapshot()["policy"])
        r.update_policy(p.model_copy(update={"revision": 2, "shared_limit_units": 300}), epoch, now=now)
    else:
        raw = r.snapshot()["accounts"]["shadow:a"]
        snapshot = amended_account(raw, at=now, unknown=kind == "rule",
                                   risk_limit=300 if kind == "account_limit" else None)
        assert r.update_account(snapshot, epoch, now=now)["status"] == "UPDATED"
    if kind == "prepared_account":
        assert r.admit(a, g, epoch, now=now)["reason"] == "STALE_OR_ALTERED_BINDINGS"
        return r, {"reserved": 0, "recognized": 0}
    assert r.publish("changed", 1, epoch, now=now)["status"] == "DISPATCH_BLOCKED"
    return r, {"reserved": 600, "recognized": 0}


def fenced(folder):
    r, key, old = create_fixture(folder / "router.db")
    a, g = admitted(r, key, old, intent("owner"))
    publish(r, "owner", old)
    observe(r, "owner", old, 1, "unknown")
    new = r.claim("replacement", old, now=START + timedelta(seconds=2))["epoch"]
    assert new == old + 1
    assert r.admit(a, g, old, now=START + timedelta(seconds=3))["reason"] == "STALE_OWNER_FENCE"
    assert r.confirm_publication("owner", old, now=START + timedelta(seconds=3))["reason"] == "STALE_OWNER_FENCE"
    return r, {"reserved": 600, "recognized": 0, "unknown": 600}


def multileg(folder):
    from scripts.ats6_fixtures import SECOND, SYMBOL
    r, key, epoch = create_fixture(folder / "router.db", shared=2000, caps=(500, 500))
    for item in (intent("together", 3, symbols=(SYMBOL, SECOND)),
                 intent("cross", 1, symbols=(SYMBOL, "other:perpetual:BETAUSD"))):
        a, g = signed(r, key, item)
        assert r.admit(a, g, epoch, now=START)["status"] == "SKIPPED"
    return r, {"reserved": 0, "recognized": 0}


def reordered(folder, conflict=False):
    r, key, epoch = create_fixture(folder / "router.db", shared=2000, caps=(2000,))
    admitted(r, key, epoch, intent("events"))
    publish(r, "events", epoch)
    one, two = fill("one", 2), fill("two", 1)
    if conflict:
        observe(r, "events", epoch, 1, "fill", executions=(one,))
        observe(r, "events", epoch, 2, "fill", executions=(fill("one", 3),))
        a, g = signed(r, key, intent("blocked", 1))
        assert r.admit(a, g, epoch, now=START + timedelta(seconds=3))["status"] == "SKIPPED"
        return r, {"reserved": 700, "recognized": 200, "unknown": 700}
    observe(r, "events", epoch, 3, "fill", executions=(two,))
    observe(r, "events", epoch, 2, "fill", executions=(one,),
            now=START + timedelta(seconds=4), at=START + timedelta(seconds=2))
    observe(r, "events", epoch, 4, "fill", executions=(one,), now=START + timedelta(seconds=5))
    observe(r, "events", epoch, 5, "reconcile", executions=(one, two),
            terminal="canceled", complete=True, now=START + timedelta(seconds=6))
    return r, {"reserved": 0, "recognized": 300}


def preexisting(folder):
    r, key, epoch = create_fixture(folder / "router.db", obligations=(opening_unknown(700),))
    r = ShadowRouter(r.path)
    r.recover()
    a, g = signed(r, key, intent("new", 4))
    assert r.admit(a, g, epoch, now=START)["status"] == "SKIPPED"
    return r, {"reserved": 700, "recognized": 0, "unknown": 700}


def incomplete(folder):
    r, key, epoch = create_fixture(folder / "router.db")
    admitted(r, key, epoch, intent("incomplete"))
    publish(r, "incomplete", epoch)
    observe(r, "incomplete", epoch, 1, "fill", executions=(fill("one", 2),))
    observe(r, "incomplete", epoch, 2, "reconcile", terminal="canceled", complete=True)
    return r, {"reserved": 400, "recognized": 200, "unknown": 400}


def late_after_terminal(folder):
    r, key, epoch = create_fixture(folder / "router.db", caps=(1000, 1000))
    admitted(r, key, epoch, intent("first"))
    publish(r, "first", epoch)
    f = fill("first-fill", 2)
    observe(r, "first", epoch, 1, "fill", executions=(f,))
    observe(r, "first", epoch, 2, "reconcile", executions=(f,), terminal="canceled", complete=True)
    admitted(r, key, epoch, intent("second", 8), now=START + timedelta(seconds=3))
    observe(r, "first", epoch, 3, "fill", executions=(fill("unexpected-late", 1),),
            now=START + timedelta(seconds=4))
    a, g = signed(r, key, intent("must-block", 1))
    assert r.admit(a, g, epoch, now=START + timedelta(seconds=5))["status"] == "SKIPPED"
    return r, {"reserved": 1100, "recognized": 300, "unknown": 300}


def projection_repair(folder):
    r, key, epoch = create_fixture(folder / "router.db")
    admitted(r, key, epoch, intent("repair"))
    with sqlite3.connect(r.path) as con:
        con.execute("UPDATE projection SET body='{}',sha256='broken' WHERE id=1")
    try:
        r.recover()
    except ValueError as exc:
        save(folder / "detected_projection_failure.json", {"error": str(exc)})
    else:
        raise AssertionError("CORRUPTION_NOT_DETECTED")
    r.recover(repair_projection=True)
    return r, {"reserved": 600, "recognized": 0}


def isolated(folder):
    from scripts.ats6_shadow_worker import isolated_command
    state_dir = folder / "isolated-state"
    state_dir.mkdir()
    r, key, epoch = create_fixture(state_dir / "router.db")
    a, g = signed(r, key, intent("isolated"))
    canary = folder / "unmounted-private-canary.txt"
    canary.write_text("synthetic canary, not a broker credential")
    save(state_dir / "request.json", {
        "action": a, "grant": g, "epoch": epoch, "now": START.isoformat(),
        "canary_path": str(canary.resolve()),
        "parent_net_namespace": os.readlink("/proc/self/ns/net"),
    })
    result = subprocess.run(isolated_command(state_dir), capture_output=True, text=True, timeout=30, check=False,
                            env={**os.environ, "ATS6_ORDER_SECRET_SENTINEL": "synthetic-env-canary"})
    save(folder / "sandbox_process.json", {"exitcode": result.returncode,
                                           "stdout": result.stdout, "stderr": result.stderr})
    assert result.returncode == 0, result.stderr
    return r, {"reserved": 600, "recognized": 0}


SCENARIOS = [
    ("simultaneous_shared_cushion", lambda p: concurrent(p, False)),
    ("simultaneous_multiple_accounts", lambda p: concurrent(p, True)),
    ("clean_control", clean),
    *[(point.replace(":", "_"), lambda p, point=point: crashed(p, point)) for point in (
        "admit:before_commit", "admit:after_commit", "publish:before_commit", "publish:after_commit")],
    ("partial_cancel_late_close", partial), ("lost_ack_restart_duplicates", lost_ack),
    ("stale_control_and_audit_clocks", stale_control_and_clocks),
    ("rejection_reconciliation", rejected),
    *[(kind + "_source", lambda p, kind=kind: stale_source(p, kind)) for kind in ("mark", "coverage", "margin")],
    *[(kind + "_change", lambda p, kind=kind: changed(p, kind)) for kind in (
        "revoke", "rule", "global_limit", "account_limit", "prepared_account")],
    ("superseded_owner", fenced), ("indivisible_multileg", multileg),
    ("reordered_duplicate_events", reordered),
    ("conflicting_events", lambda p: reordered(p, True)),
    ("preexisting_unknown_restart", preexisting), ("incomplete_reconciliation", incomplete),
    ("late_after_certified_terminal", late_after_terminal),
    ("projection_rebuild", projection_repair), ("credential_free_namespace", isolated),
]


def qualify_case(folder, operation):
    router, expected = operation(folder)
    recovered = router.recover()
    save(folder / "router_recovery.json", recovered)
    save(folder / "projection.json", router.snapshot())
    # SQLite backup captures one consistent committed database, not a live file copy.
    frozen = folder / "committed.sqlite"
    with sqlite3.connect(router.path) as source, sqlite3.connect(frozen) as target:
        source.backup(target)
    out = folder / "independent.json"
    process = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("ats6_outside_judge.py")), str(frozen), "--output", str(out)],
        capture_output=True, text=True, timeout=45, check=False,
    )
    save(folder / "independent_process.json", {"exitcode": process.returncode,
                                               "stdout": process.stdout, "stderr": process.stderr})
    report = json.loads(out.read_text())
    assert process.returncode == 0, report
    for key, value in expected.items():
        assert report["shared"][key] == value, (key, report["shared"][key], value)
    for key in ("reserved", "recognized", "margin", "unknown", "used"):
        assert report["shared"][key] == recovered["usage"]["shared"][key], key
    save(folder / "expectations.json", {"expected": expected, "status": "PASS"})
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=Path("run_log/ats6/acceptance"))
    parser.add_argument("--detach", action="store_true")
    args = parser.parse_args()
    if args.detach:
        logs = args.output_root.resolve() / "launches"
        logs.mkdir(parents=True, exist_ok=True)
        log = logs / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8] + ".log")
        with log.open("x") as output:
            process = subprocess.Popen(
                [sys.executable, "-m", "scripts.ats6_acceptance", "--output-root",
                 str(args.output_root.resolve())],
                cwd=Path(__file__).resolve().parents[1], stdout=output, stderr=subprocess.STDOUT,
                start_new_session=True,
                env={"PATH": "/usr/bin:/bin", "OPENBLAS_NUM_THREADS": "1",
                     "OMP_NUM_THREADS": "1", "POLARS_MAX_THREADS": "2"},
            )
        print(json.dumps({"pid": process.pid, "log": str(log)}, sort_keys=True))
        return 0
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
    root = args.output_root.resolve() / run_id
    root.mkdir(parents=True, exist_ok=False)
    save(root / "frozen_acceptance_plan.json", {
        "scope": "SYNTHETIC_SHADOW_ONLY", "runtime": runtime_identity(),
        "scenarios": [name for name, _ in SCENARIOS],
        "oracle": "separate Python process; no router imports",
        "fault_exitcodes": {"before_commit": 91, "after_commit": 92},
        "policy_comparisons": ["cushion", "first_fit", "least_used"],
        "real_orders": False, "protected_outcomes": False,
    })
    results, reports = {}, {}
    for name, operation in SCENARIOS:
        folder = root / name
        folder.mkdir()
        try:
            reports[name] = qualify_case(folder, operation)
            results[name] = "PASS"
        except Exception as exc:  # noqa: BLE001 - retain every failed acceptance attempt.
            save(folder / "failure.json", {"exception": type(exc).__name__, "message": str(exc),
                                            "traceback": traceback.format_exc()})
            results[name] = "FAIL"
        print(name + ": " + results[name], flush=True)
    controls = [name for name in results if name.endswith("_commit")] + ["clean_control"]
    if all(name in reports for name in controls):
        assert len({json.dumps(reports[name]["shared"], sort_keys=True) for name in controls}) == 1
        results["clean_interrupted_economic_equivalence"] = "PASS"
    else:
        results["clean_interrupted_economic_equivalence"] = "FAIL"
    from scripts.ats6_policy_comparison import compare
    try:
        policy_report = compare(root / "policy_comparison", qualify_case, save)
        save(root / "policy_comparison.json", policy_report)
        results["frozen_policy_comparison"] = "PASS"
    except Exception as exc:  # noqa: BLE001 - preserve partial policy runs.
        save(root / "policy_comparison_failure.json", {"exception": type(exc).__name__,
              "message": str(exc), "traceback": traceback.format_exc()})
        results["frozen_policy_comparison"] = "FAIL"
    status = "QUALIFIED_SYNTHETIC_SHADOW" if all(v == "PASS" for v in results.values()) else "PARTIALLY_QUALIFIED"
    summary = {"status": status, "runtime": runtime_identity(), "run_id": run_id,
               "requirements": results, "scope": "SYNTHETIC_SHADOW_ONLY", "deployment_permission": False}
    save(root / "acceptance.json", summary)
    manifest = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.name.endswith(("-wal", "-shm", ".db")):
            manifest[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    save(root / "artifact_hashes.json", manifest)
    print(json.dumps({"status": status, "evidence": str(root)}, sort_keys=True), flush=True)
    return 0 if status == "QUALIFIED_SYNTHETIC_SHADOW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
