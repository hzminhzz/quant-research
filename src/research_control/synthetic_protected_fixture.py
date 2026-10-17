"""Synthetic-only protected-read proof for ATS-2 authorization qualification.

This is a test fixture, not a general protected-data reader. It creates its own
recognizably synthetic bytes, accepts only its fixed action shape, and has no
production, credential, broker, or arbitrary-path API.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .action_authorization import (
    SignedGrantV1,
    build_scope,
    canonical_json,
    sha256_json,
    validate_grant,
)

MAGIC = b"ATS2_SYNTHETIC_PROTECTED_V1:"
PAYLOAD_SIZE = len(MAGIC) + 32
ACTION = "synthetic_protected_fixture_read"
_SOURCE = hashlib.sha256(b"ats2-fixture-only-source").hexdigest()
_SPEC = hashlib.sha256(b"ats2-fixture-only-spec").hexdigest()
_CONFIG = hashlib.sha256(b"ats2-fixture-only-config").hexdigest()
_SELECTION = hashlib.sha256(b"ats2-fixture-only-selection").hexdigest()
_START = datetime(2026, 1, 5, tzinfo=UTC)
_END = _START + timedelta(hours=1)


def _write_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(payload)
        out.flush()
        os.fsync(out.fileno())
    dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def prepare_fixture(root: str | Path) -> dict[str, Any]:
    """Create only new synthetic bytes and a frozen, signed-grant-ready action."""
    base = Path(root).resolve()
    if base.is_symlink():
        raise ValueError("FIXTURE_ROOT_UNSAFE")
    base.mkdir(parents=True, exist_ok=True)
    payload = MAGIC + os.urandom(32)
    fixture = base / "synthetic_protected_fixture.bin"
    _write_once(fixture, payload)
    action = {
        "schema_version": 1,
        "revision": 1,
        "operation": ACTION,
        "session_id": "ats2-fixture-only",
        "trial_id": "synthetic-protected-read",
        "read_scope": "synthetic_fixture_bytes_only",
        "write_scope": "receipt_hash_only",
        "identity": {
            "source_sha256": _SOURCE,
            "data_sha256": hashlib.sha256(payload).hexdigest(),
            "spec_sha256": _SPEC,
            "config_sha256": _CONFIG,
            "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        "selection_sha256": _SELECTION,
        "max_read_bytes": PAYLOAD_SIZE,
        "trading": False,
        "protected_fixture_only": True,
    }
    action["contract_sha256"] = sha256_json(action)
    _write_once(base / "fixture_action.json", canonical_json(action) + b"\n")
    return action


def fixture_scope(action: dict[str, Any]):
    return build_scope(action, window_start=_START, window_end=_END,
                       selection_sha256=_SELECTION)


def _validate_action(root: Path, action: dict[str, Any]) -> bool:
    source = root / "fixture_action.json"
    if source.is_symlink() or not source.is_file():
        return False
    try:
        on_disk = json.loads(source.read_text())
        required = {"schema_version", "revision", "operation", "session_id",
                    "trial_id", "read_scope", "write_scope", "identity",
                    "selection_sha256", "max_read_bytes", "trading",
                    "protected_fixture_only", "contract_sha256"}
        return bool(
            set(action) == required and on_disk == action
            and action["schema_version"] == 1 and action["revision"] == 1
            and action["operation"] == ACTION
            and action["read_scope"] == "synthetic_fixture_bytes_only"
            and action["write_scope"] == "receipt_hash_only"
            and action["session_id"] == "ats2-fixture-only"
            and action["trial_id"] == "synthetic-protected-read"
            and action["selection_sha256"] == _SELECTION
            and action["max_read_bytes"] == PAYLOAD_SIZE
            and action["trading"] is False
            and action["protected_fixture_only"] is True
            and action["identity"]["source_sha256"] == _SOURCE
            and action["identity"]["spec_sha256"] == _SPEC
            and action["identity"]["config_sha256"] == _CONFIG
            and action["identity"]["code_sha256"] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            and sha256_json({k: v for k, v in action.items() if k != "contract_sha256"})
            == action["contract_sha256"]
        )
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return False


def _sandbox_command(fixture: Path, output_dir: Path, data_digest: str,
                     issuer_private_path: Path, policy_path: Path) -> list[str]:
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        raise RuntimeError("ISOLATION_UNAVAILABLE")
    executable = Path(sys.executable).resolve()
    prefix = Path(sys.prefix).resolve()
    stdlib = Path(sysconfig.get_paths()["stdlib"]).resolve()
    worker = Path(__file__).with_name("synthetic_protected_fixture_worker.py").resolve()
    command = [bwrap, "--unshare-all", "--die-with-parent", "--new-session",
               "--clearenv", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for system in ("/usr", "/lib", "/lib64"):
        if Path(system).exists():
            command.extend(("--ro-bind", system, system))
    for path in {executable.parent, stdlib, prefix}:
        if path.exists() and str(path) not in ("/usr", "/lib", "/lib64"):
            command.extend(("--ro-bind", str(path), str(path)))
    command.extend((
        "--ro-bind", str(worker), "/worker.py",
        "--dir", "/work", "--ro-bind", str(fixture), "/work/fixture.bin",
        "--bind", str(output_dir), "/work/out",
        "--setenv", "HOME", "/tmp", "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        "--chdir", "/work", str(executable), "-B", "/worker.py",
        "/work/fixture.bin", "/work/out/digest.json", data_digest,
        str(issuer_private_path), str(policy_path),
    ))
    return command


def read_synthetic_protected_fixture(root: str | Path, action: dict[str, Any],
                                     grant: SignedGrantV1 | dict[str, Any], *,
                                     trusted_policy_path: str | Path,
                                     issuer_private_path: str | Path) -> dict[str, Any]:
    """One-shot signed and fenced fixture read; never accepts arbitrary sources.

    A denied authorization cannot read the fixture. The issuer key and policy
    are not mounted in the Bubblewrap worker; only the synthetic input is.
    """
    base = Path(root).resolve()
    if not _validate_action(base, action):
        return {"status": "BLOCKED", "reason_code": "FIXTURE_ACTION_INVALID"}
    source = base / "synthetic_protected_fixture.bin"
    if source.is_symlink() or not source.is_file():
        return {"status": "BLOCKED", "reason_code": "FIXTURE_SOURCE_UNAVAILABLE"}
    if not Path(trusted_policy_path).is_file() or not Path(issuer_private_path).is_file():
        return {"status": "BLOCKED", "reason_code": "EXTERNAL_AUTHORITY_UNAVAILABLE"}
    # Keep authorization and one-shot claim insertion atomic even if two
    # independent processes invoke the same signed protected claim.
    receipts_parent = base / "protected_receipts"
    if receipts_parent.is_symlink():
        return {"status": "BLOCKED", "reason_code": "FIXTURE_RECEIPT_PATH_UNSAFE"}
    claims = base / "consumed_claims"
    claims.mkdir(exist_ok=True)
    if claims.is_symlink():
        return {"status": "BLOCKED", "reason_code": "CLAIM_LEDGER_UNSAFE"}
    lock = claims / ".lock"
    if lock.is_symlink():
        return {"status": "BLOCKED", "reason_code": "CLAIM_LEDGER_UNSAFE"}
    with lock.open("a+") as file:
        fcntl.flock(file.fileno(), fcntl.LOCK_EX)
        try:
            decision = validate_grant(
                grant, action, window_start=_START, window_end=_END,
                selection_sha256=_SELECTION,
                trusted_policy_path=trusted_policy_path,
                protected_fixture=True,
            )
            if decision.status != "AUTHORIZED":
                return {"status": "BLOCKED", "reason_code": decision.reason_code}
            grant_id = decision.grant_id
            if not isinstance(grant_id, str) or not re.fullmatch(r"[0-9a-f-]{36}", grant_id):
                return {"status": "BLOCKED", "reason_code": "GRANT_ID_INVALID"}
            receipt = claims / (grant_id + ".json")
            if receipt.exists() or receipt.is_symlink():
                return {"status": "BLOCKED", "reason_code": "PROTECTED_GRANT_CONSUMED"}
            _write_once(receipt, canonical_json({
                "schema_version": 1, "grant_id": grant_id, "status": "CONSUMED",
                "action_sha256": action["contract_sha256"],
                "scope_sha256": decision.scope_sha256,
                "bound_input_sha256": action["identity"]["data_sha256"],
                "attempts": 1, "retry_policy": "NO_AUTOMATIC_RETRY",
                "consumed_at": datetime.now(UTC).isoformat(),
            }) + b"\n")
        finally:
            fcntl.flock(file.fileno(), fcntl.LOCK_UN)

    out = base / "protected_receipts" / grant_id
    out.mkdir(parents=True, exist_ok=False)
    try:
        command = _sandbox_command(source, out, action["identity"]["data_sha256"],
                                   Path(issuer_private_path).resolve(),
                                   Path(trusted_policy_path).resolve())
        process = subprocess.run(command, capture_output=True, text=True,
                                 timeout=20, check=False)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        _write_once(out / "failure.json", canonical_json({
            "status": "FAILED", "reason_code": "PROTECTED_FIXTURE_WORKER_UNAVAILABLE",
            "exception_type": type(exc).__name__,
        }) + b"\n")
        return {"status": "FAILED", "reason_code": "PROTECTED_FIXTURE_WORKER_UNAVAILABLE",
                "grant_id": grant_id}
    if process.returncode != 0:
        _write_once(out / "failure.json", canonical_json({
            "status": "FAILED", "reason_code": "PROTECTED_FIXTURE_WORKER_FAILED",
            "returncode": process.returncode,
        }) + b"\n")
        return {"status": "FAILED", "reason_code": "PROTECTED_FIXTURE_WORKER_FAILED",
                "grant_id": grant_id}
    result_path = out / "digest.json"
    if result_path.is_symlink() or not result_path.is_file():
        return {"status": "FAILED", "reason_code": "PROTECTED_FIXTURE_OUTPUT_MISSING"}
    result = json.loads(result_path.read_text())
    if (result.get("schema_version") != 1 or result.get("operation") != ACTION
        or result.get("sha256") != action["identity"]["data_sha256"]
        or result.get("bytes_read") != PAYLOAD_SIZE
        or result.get("issuer_key_visible") is not False
        or result.get("trust_policy_visible") is not False):
        return {"status": "FAILED", "reason_code": "PROTECTED_FIXTURE_OUTPUT_INVALID"}
    proof = {
        "schema_version": 1, "status": "VERIFIED_SYNTHETIC_PROTECTED_READ",
        "grant_id": grant_id, "action_sha256": action["contract_sha256"],
        "scope_sha256": decision.scope_sha256,
        "input_sha256": result["sha256"], "bytes_read": result["bytes_read"],
        "output_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
        "external_issuer_private_key_not_mounted": True,
        "trusted_policy_not_mounted": True,
        "network_namespace_unshared": True,
        "synthetic_only": True, "live_order_authority": False,
        "verified_at": datetime.now(UTC).isoformat(),
    }
    _write_once(out / "accepted.json", canonical_json(proof) + b"\n")
    return {"status": proof["status"], "grant_id": grant_id,
            "proof": str((out / "accepted.json").relative_to(base))}
