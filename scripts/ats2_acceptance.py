"""Independent raw-record ATS-2 acceptance run using synthetic fixtures only."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import uuid
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.research_control.action_authorization import (
    TrustPolicyV1,
    build_scope,
    issue_synthetic_grant,
    public_key_b64,
)
from src.research_control.ats2 import (
    observe_run,
    prepare_action,
    start_action,
    verify_result,
)
from src.research_control.attempts import AttemptLedger
from tests.test_ats2 import _crashable_claimed_worker, _start_in_process
from tests.test_run_permit import gate, intent, setup_trial

_READ = (1 << 0) | (1 << 2) | (1 << 3)
_WRITE = _READ | (1 << 1) | (1 << 4) | (1 << 5) | (1 << 7) | (1 << 8) | (1 << 9) | (1 << 10) | (1 << 11) | (1 << 12) | (1 << 13) | (1 << 14) | (1 << 15)
_WORKER = r'''import base64, ctypes, json, os, sys, time
sys.path.insert(0, sys.argv[7])
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

class Ruleset(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]
class PathRule(ctypes.Structure):
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]

libc = ctypes.CDLL(None, use_errno=True)
handled = (1 << 16) - 1
ruleset = libc.syscall(444, ctypes.byref(Ruleset(handled)), ctypes.sizeof(Ruleset), 0)
if ruleset < 0: raise OSError(ctypes.get_errno(), "landlock_create_ruleset")
for path, rights in json.loads(sys.argv[1]):
    fd = os.open(path, getattr(os, "O_PATH", 0o10000000) | os.O_CLOEXEC)
    rule = PathRule(rights, fd)
    if libc.syscall(445, ruleset, 1, ctypes.byref(rule), 0) < 0:
        raise OSError(ctypes.get_errno(), "landlock_add_rule")
    os.close(fd)
if libc.prctl(38, 1, 0, 0, 0) < 0: raise OSError(ctypes.get_errno(), "no_new_privs")
if libc.syscall(446, ruleset, 0) < 0: raise OSError(ctypes.get_errno(), "landlock_restrict_self")
os.close(ruleset)
policy_path, grant_path, fixture_path, private_path, out_path = sys.argv[2:7]
result = {"boundary": "landlock-process-restriction", "private_key_denied": False,
          "policy_write_denied": False, "decision": "DENY", "reason": "MISSING_GRANT"}
try:
    with open(private_path, "rb") as f: f.read()
except OSError: result["private_key_denied"] = True
try:
    with open(policy_path, "ab") as f: f.write(b"x")
except OSError: result["policy_write_denied"] = True
with open(fixture_path, "rb") as f: fixture = json.load(f)
policy = json.load(open(policy_path, encoding="utf-8"))
try:
    grant = json.load(open(grant_path, encoding="utf-8"))
    claims, signature = grant["claims"], base64.b64decode(grant["signature"])
    issuer = claims.get("issuer")
    pub = policy["trusted_issuers"].get(issuer)
    if not pub: raise ValueError("UNKNOWN_ISSUER")
    Ed25519PublicKey.from_public_bytes(base64.b64decode(pub)).verify(
        signature, json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
    if claims.get("grant_id") in policy.get("consumed", []): raise ValueError("GRANT_REPLAY")
    if issuer in policy.get("revoked_issuers", []): raise ValueError("ISSUER_REVOKED")
    if claims.get("expires_at", 0) <= time.time(): raise ValueError("GRANT_EXPIRED")
    for key in ("action", "window", "data_sha256", "spec_sha256", "selection_decision", "scopes"):
        if claims.get(key) != fixture.get(key): raise ValueError("GRANT_SCOPE_MISMATCH:" + key)
    result.update(decision="ALLOW", reason="VALID_SYNTHETIC_GRANT")
except Exception as exc:
    result["reason"] = str(exc).split(":")[0]
if not result["private_key_denied"] or not result["policy_write_denied"]:
    raise RuntimeError("LANDLOCK_BOUNDARY_NOT_ENFORCED")
with open(out_path, "x", encoding="utf-8") as out:
    json.dump(result, out, sort_keys=True); out.write("\n")
'''


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _issue_synthetic_grant(workspace: Path, action, request) -> tuple:
    """Issue a signed synthetic grant for the action; return (grant, policy_path)."""
    key = Ed25519PrivateKey.generate()
    trust = workspace / "trust"
    trust.mkdir(exist_ok=True)
    policy_path = trust / "policy.json"
    policy = TrustPolicyV1.model_validate({
        "schema_version": 1, "trust_domain": "SYNTHETIC_ONLY",
        "max_grant_seconds": 3600,
        "issuers": ({"issuer_id": "ats2-acceptance-issuer",
                     "public_key_b64": public_key_b64(key), "enabled": True},),
        "revoked_grant_ids": (),
    })
    policy_path.write_text(policy.model_dump_json(), encoding="utf-8")
    start = request["evaluation_start"]
    end = request["evaluation_end"]
    if isinstance(start, str):
        from datetime import datetime
        start = datetime.fromisoformat(start)
        end = datetime.fromisoformat(end)
    scope = build_scope(action, window_start=start, window_end=end,
                        selection_sha256=action.selection_sha256)
    now = datetime.now(UTC)
    grant = issue_synthetic_grant(
        scope, issuer_id="ats2-acceptance-issuer", private_key=key,
        issued_at=now, expires_at=now + timedelta(minutes=10),
    )
    return grant, policy_path


def _raw_action_case(workspace: Path, *, concurrent: bool = False) -> dict:
    data, contract, computation, evidence = setup_trial(workspace)
    request = intent(data, evidence)
    action = prepare_action(
        workspace, request, computation, data, contract,
        signal_at=data["timestamp"][1], quantity=1, stop_price=99.0, limit_price=101.4,
    )
    grant, policy_path = _issue_synthetic_grant(workspace, action, request)
    if concurrent:
        payload = (str(workspace), action, request, computation, data, contract,
                   grant, str(policy_path))
        import multiprocessing
        with ProcessPoolExecutor(max_workers=2,
                                 mp_context=multiprocessing.get_context("spawn")) as pool:
            responses = list(pool.map(_start_in_process, [payload, payload]))
        output_ready = [row for row in responses if row["status"] == "OUTPUT_READY"]
        assert len(output_ready) == 1, responses
        attempt_id = output_ready[0]["attempt_id"]
    else:
        started = start_action(workspace, action, request, computation, data, contract,
                               grant=grant, trusted_policy_path=str(policy_path),
                               list_jobs=lambda: set())
        assert started["status"] == "OUTPUT_READY", started
        attempt_id = started["attempt_id"]
    ledger = AttemptLedger(workspace, action.session_id, list_jobs=lambda: set())
    raw = ledger.events()
    owned = [row for row in raw if row["attempt_id"] == attempt_id]
    states = [row["status"] for row in owned]
    assert states[0] == "PLANNED" and states[-1] == "COMPLETED", states
    assert [row["revision"] for row in owned] == sorted(row["revision"] for row in owned)
    assert len({row["fencing_token"] for row in owned}) == 1
    result = verify_result(workspace, action.session_id, attempt_id)
    observed = observe_run(workspace, action.session_id, attempt_id)
    accepted = workspace / result["attestation"]
    accepted_doc = json.loads(accepted.read_text())
    output = workspace / action.write_scope / attempt_id
    manifest = json.loads((output / "execution_audit.json").read_text())
    assert accepted_doc["verifier"] == "src.research_control.ats2.verify_result"
    assert manifest["live_order_authority"] is False
    assert manifest["audit"]["status"] == "PASS"
    assert observed["identity_freshness"] == "CURRENT"
    return {"attempt_id": attempt_id, "states": states,
            "fencing_token": owned[-1]["fencing_token"],
            "ledger_raw": raw, "manifest_sha256": _sha(output / "execution_audit.json"),
            "native_files": sorted(p.name for p in (output / "native").iterdir()),
            "verification": result, "response": observed,
            "development_input_sha256": hashlib.sha256((workspace / "bars.parquet").read_bytes()).hexdigest()}


def _raw_crash_case(workspace: Path) -> dict:
    import multiprocessing
    import signal

    data, contract, computation, evidence = setup_trial(workspace)
    permit = gate(workspace, data, contract, computation, evidence)
    now = [datetime.now(UTC)]
    ledger = AttemptLedger(workspace, contract.session_id, list_jobs=lambda: set(),
                           clock=lambda: now[0])
    first = ledger.claim(permit, job_name="ml4t-ats2-accept-crash",
                         command="ats2:acceptance-crash", lease_seconds=30,
                         managed_worker=True)
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    worker = context.Process(target=_crashable_claimed_worker,
                             args=(str(workspace), contract.session_id, first.attempt_id, ready))
    worker.start()
    if not ready.wait(15):
        worker.kill()
        worker.join(5)
        raise RuntimeError("CRASH_WORKER_CHECKPOINT_TIMEOUT")
    if ledger.worker_lock_status(first.attempt_id) != "WORKER_LOCK_HELD":
        raise AssertionError("LIVE_WORKER_LOCK_NOT_HELD")
    before = ledger.events()
    os.kill(worker.pid, signal.SIGKILL)
    worker.join(15)
    if worker.exitcode != -signal.SIGKILL:
        raise RuntimeError("CRASH_WORKER_NOT_KILLED")
    during_uncertainty = ledger.claim(
        permit, job_name="ml4t-ats2-accept-crash", command="ats2:acceptance-crash",
        lease_seconds=30, managed_worker=True,
    )
    if during_uncertainty.reason_code != "LEASE_UNCERTAIN":
        raise AssertionError(during_uncertainty)
    now[0] += timedelta(seconds=31)
    next_owner = ledger.claim(
        permit, job_name="ml4t-ats2-accept-crash", command="ats2:acceptance-crash",
        lease_seconds=10, managed_worker=True,
    )
    records = ledger.events()
    old, new = ledger.latest()[first.attempt_id], ledger.latest()[next_owner.attempt_id]
    if old["status"] != "ABORTED" or new["fencing_token"] <= old["fencing_token"]:
        raise AssertionError("FENCE_DID_NOT_ADVANCE")
    accepted_rel = f"run_log/ats2/accepted/{contract.session_id}/{first.run_id}/result.json"
    with ledger.worker_lease(next_owner.attempt_id):
        ledger.transition(next_owner.attempt_id, "RUNNING", detail="successor owns publication")
        ledger.publish_fenced(next_owner.attempt_id, new["fencing_token"],
                              relative_path=accepted_rel, payload=b"successor accepted")
        for attempt, token, kind in ((first.attempt_id, old["fencing_token"], "write"),):
            try:
                ledger.publish_fenced(attempt, token, relative_path=accepted_rel,
                                      payload=b"late old owner")
            except ValueError as exc:
                if "FENCED_WRITE_REJECTED" not in str(exc):
                    raise
            else:
                raise AssertionError("STALE_FENCED_WRITE_ACCEPTED")
        late = ledger.transition(first.attempt_id, "COMPLETED", detail="late old completion")
        if late.reason_code != "ATTEMPT_ALREADY_TERMINAL":
            raise AssertionError(late)
    accepted_path = workspace / accepted_rel
    rejected = sorted((ledger.path / "rejected_late").glob("*.json"))
    kinds = sorted(json.loads(path.read_text())["kind"] for path in rejected)
    if accepted_path.read_bytes() != b"successor accepted" or not {"write", "completion"}.issubset(kinds):
        raise AssertionError("LATE_OLD_OWNER_EVIDENCE_NOT_RETAINED")
    return {"old_attempt": first.attempt_id, "successor_attempt": next_owner.attempt_id,
            "pre_crash_records": before, "raw_records": records,
            "rejected_late": [json.loads(path.read_text()) for path in rejected],
            "accepted_sha256": _sha(accepted_path), "worker_exit": worker.exitcode,
            "uncertain_reason": during_uncertainty.reason_code}


def _authorization_case(folder: Path) -> dict:
    issuer = folder / "issuer"
    policy_dir, fixture_dir, grants_dir, output_dir = (
        folder / "policy", folder / "fixture", folder / "grants", folder / "output"
    )
    for path in (issuer, policy_dir, fixture_dir, grants_dir, output_dir):
        path.mkdir(parents=True)
    private = Ed25519PrivateKey.generate()
    private_path = issuer / "issuer_private.pem"
    _write(private_path, private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    fixture = {"action": "synthetic_protected_read", "window": "fixture-window-2030",
               "data_sha256": hashlib.sha256(b"synthetic protected outcomes").hexdigest(),
               "spec_sha256": hashlib.sha256(b"frozen synthetic spec").hexdigest(),
               "selection_decision": "frozen-select-1", "scopes": ["synthetic_fixture_read"]}
    fixture_path = fixture_dir / "request.json"
    _write(fixture_path, json.dumps(fixture, sort_keys=True).encode())
    pub_text = base64.b64encode(public).decode()
    trusted = {"trusted_issuers": {"fixture-issuer": pub_text},
               "revoked_issuers": [], "consumed": []}
    policy_path = policy_dir / "trust.json"
    _write(policy_path, json.dumps(trusted, sort_keys=True).encode())
    abi = ctypes_landlock_abi()
    if abi < 1:
        raise RuntimeError("LANDLOCK_UNAVAILABLE")
    executable = Path(sys.executable).resolve()
    python_root = executable.parent.parent
    package_root = Path(__file__).resolve().parents[1] / ".venv"
    roots = [
        ("/usr", _READ), ("/lib", _READ), ("/lib64", _READ), ("/dev", _READ),
        (str(python_root / "lib"), _READ),
        (str(python_root / "bin"), _READ),
        (str(package_root / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"), _READ),
        (str(policy_dir), _READ), (str(fixture_dir), _READ), (str(grants_dir), _READ),
        (str(output_dir), _WRITE),
    ]
    roots = [(p, rights) for p, rights in roots if Path(p).exists()]
    cases = {}
    grants = {
        "valid": (fixture.copy(), True, trusted.copy()),
        "unknown_issuer": ({**fixture, "issuer": "other"}, False, trusted.copy()),
        "expired": ({**fixture, "expires_at": 1}, False, trusted.copy()),
        "revoked": ({**fixture, "issuer": "fixture-issuer", "expires_at": time.time() + 60}, False,
                    {**trusted, "revoked_issuers": ["fixture-issuer"]}),
        "consumed_replay": ({**fixture, "issuer": "fixture-issuer", "grant_id": "consumed-1",
                              "expires_at": time.time() + 60}, False,
                             {**trusted, "consumed": ["consumed-1"]}),
        "forged_signature": ({**fixture, "issuer": "fixture-issuer",
                              "expires_at": time.time() + 60}, False, trusted.copy()),
        "wrong_action": ({**fixture, "issuer": "fixture-issuer", "expires_at": time.time() + 60,
                          "action": "other_action"}, False, trusted.copy()),
        "wrong_scope": ({**fixture, "issuer": "fixture-issuer", "expires_at": time.time() + 60,
                         "scopes": ["different_scope"]}, False, trusted.copy()),
        "wrong_window": ({**fixture, "issuer": "fixture-issuer", "expires_at": time.time() + 60,
                          "window": "other-window"}, False, trusted.copy()),
        "wrong_data": ({**fixture, "issuer": "fixture-issuer", "expires_at": time.time() + 60,
                        "data_sha256": "0" * 64}, False, trusted.copy()),
        "wrong_spec": ({**fixture, "issuer": "fixture-issuer", "expires_at": time.time() + 60,
                        "spec_sha256": "1" * 64}, False, trusted.copy()),
        "wrong_selection": ({**fixture, "issuer": "fixture-issuer", "expires_at": time.time() + 60,
                             "selection_decision": "retuned"}, False, trusted.copy()),
        "mutated_after_signing": ({**fixture, "issuer": "fixture-issuer", "expires_at": time.time() + 60,
                                   "scopes": ["mutated"]}, False, trusted.copy()),
    }
    for name, (claims, allowed, current_policy) in grants.items():
        claims.setdefault("grant_id", name)
        claims.setdefault("expires_at", time.time() + 60)
        claims.setdefault("issuer", "fixture-issuer")
        signature = private.sign(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
        if name == "forged_signature":
            signature = bytes([signature[0] ^ 1]) + signature[1:]
        if name == "mutated_after_signing":
            claims["scopes"] = ["synthetic_fixture_read"]
        if name == "unknown_issuer":
            claims["issuer"] = "untrusted"
            signature = private.sign(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
        policy_path.write_text(json.dumps(current_policy, sort_keys=True))
        grant_path = grants_dir / f"{name}.json"
        _write(grant_path, json.dumps({"claims": claims,
                                       "signature": base64.b64encode(signature).decode()},
                                      sort_keys=True).encode())
        output = output_dir / f"{name}.json"
        command = [sys.executable, "-S", "-c", _WORKER,
                   json.dumps(roots), str(policy_path), str(grant_path), str(fixture_path),
                   str(private_path), str(output),
                   str(package_root / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages")]
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        proc = subprocess.run(command, cwd="/", env=env, capture_output=True, text=True,
                              timeout=20, check=False)
        if proc.returncode != 0 or not output.exists():
            raise RuntimeError(f"LANDLOCK_WORKER_FAILED:{name}:{proc.returncode}:{proc.stderr}")
        observation = json.loads(output.read_text())
        cases[name] = observation
        if (observation["decision"] == "ALLOW") != allowed:
            raise AssertionError(f"authorization expectation mismatch: {name}:{observation}")
        if not observation["private_key_denied"] or not observation["policy_write_denied"]:
            raise AssertionError(f"worker crossed issuer boundary: {name}")
    output = output_dir / "stage_receipt_only.json"
    command = [sys.executable, "-S", "-c", _WORKER, json.dumps(roots),
               str(policy_path), str(grants_dir / "missing_grant.json"), str(fixture_path),
               str(private_path), str(output),
               str(package_root / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages")]
    proc = subprocess.run(command, cwd="/", capture_output=True, text=True,
                          timeout=20, check=False)
    if proc.returncode != 0 or not output.is_file():
        raise RuntimeError(f"STAGE_RECEIPT_ONLY_WORKER_FAILED:{proc.stderr}")
    cases["stage_receipt_only"] = json.loads(output.read_text())
    return {"landlock_abi": abi, "cases": cases,
            "trust_boundary": "Same-UID child restricted by Linux Landlock; private-key directory not granted; trust/fixture read-only; output directory writable.",
            "limitations": ["Synthetic Ed25519 issuer fixture only; not production issuer qualification",
                            "Landlock restricts filesystem access; this experiment does not qualify network isolation or owner-proof integrity"]}


def ctypes_landlock_abi() -> int:
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    return int(libc.syscall(444, None, 0, 1))


def main() -> int:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    root = (Path("run_log/ats2/acceptance") / stamp).resolve()
    root.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, "-m", "scripts.ats2_acceptance"]
    try:
        clean = _raw_action_case(root / "clean")
        concurrent = _raw_action_case(root / "concurrent", concurrent=True)
        crash = _raw_crash_case(root / "crash")
        authorization = _authorization_case(root / "authorization")
        raw_files = sorted(p for p in root.rglob("*") if p.is_file())
        manifest = {
            "schema_version": 1, "outcome": "PARTIALLY_QUALIFIED",
            "command": command, "head": subprocess.run(
                ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
            ).stdout.strip(),
            "code_identity": {str(p): _sha(p) for p in (
                Path("src/research_control/ats2.py"),
                Path("src/research_control/action_worker.py"),
                Path("src/research_control/attempts.py"),
                Path(__file__),
            )},
            "runtime": {"python": sys.version, "platform": platform.platform()},
            "clean_control": clean, "concurrent_control": concurrent,
            "crash_recovery": crash,
            "authorization_boundary": authorization,
            "raw_file_hashes": {str(p.relative_to(root)): _sha(p) for p in raw_files},
            "limitations": ["No protected market outcomes or production credentials used",
                            "Production trusted protected/deployment permission issuance remains closed and unqualified",
                            "No unrestricted factory run was started"],
        }
        manifest_path = root / "acceptance.json"
        _write(manifest_path, json.dumps(manifest, sort_keys=True, indent=2, default=str).encode() + b"\n")
        print(json.dumps({"outcome": manifest["outcome"], "acceptance_manifest": str(manifest_path),
                          "clean_attempt": clean["attempt_id"],
                          "concurrent_attempt": concurrent["attempt_id"],
                          "landlock_abi": authorization["landlock_abi"]}, sort_keys=True))
        return 0
    except (AssertionError, OSError, ValueError, RuntimeError,
            subprocess.SubprocessError, KeyError, TypeError) as exc:
        failure = {"outcome": "FAILED", "command": command,
                   "error": f"{type(exc).__name__}: {exc}", "observed_at": datetime.now(UTC).isoformat()}
        _write(root / "failure.json", json.dumps(failure, sort_keys=True, indent=2).encode() + b"\n")
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
