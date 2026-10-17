from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.research_control.action_authorization import (
    TrustPolicyV1,
    build_scope,
    issue_synthetic_grant,
    public_key_b64,
    validate_grant,
)

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
ISSUER_ID = "synthetic-test-issuer"


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()).hexdigest()


def make_action(**changes):
    action = {
        "schema_version": 1,
        "revision": 1,
        "operation": "development_native_bracket",
        "session_id": "synthetic-session",
        "trial_id": "synthetic-trial",
        "permit_sha256": "1" * 64,
        "identity": {
            "source_sha256": "2" * 64,
            "data_sha256": "3" * 64,
            "spec_sha256": "4" * 64,
            "config_sha256": "5" * 64,
            "code_sha256": "6" * 64,
        },
        "parameters": {"signal_at": "2026-10-16T10:00:00+00:00", "quantity": 1},
        "read_scope": "frozen_development_inputs",
        "write_scope": "run_log/ats2/synthetic-session/synthetic-trial",
        "expected_outputs": ["execution_audit.json", "native/"],
    }
    action.update(changes)
    action["contract_sha256"] = digest({k: v for k, v in action.items()
                                         if k != "contract_sha256"})
    return action


def write_policy(path: Path, public_key: str, *, revoked=(), issuer_id=ISSUER_ID):
    policy = TrustPolicyV1(
        schema_version=1,
        trust_domain="SYNTHETIC_ONLY",
        max_grant_seconds=3600,
        issuers=({"issuer_id": issuer_id, "public_key_b64": public_key, "enabled": True},),
        revoked_grant_ids=tuple(revoked),
    )
    path.write_text(policy.model_dump_json(), encoding="utf-8")
    path.chmod(0o600)
    return path


@pytest.fixture
def authority(tmp_path):
    action = make_action()
    key = Ed25519PrivateKey.generate()
    policy_path = write_policy(tmp_path / "trusted-policy.json", public_key_b64(key))
    scope = build_scope(
        action,
        window_start=datetime(2026, 10, 16, 9, 0, tzinfo=UTC),
        window_end=datetime(2026, 10, 16, 16, 0, tzinfo=UTC),
        selection_sha256="7" * 64,
    )
    grant = issue_synthetic_grant(
        scope, issuer_id=ISSUER_ID, private_key=key,
        issued_at=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=30),
        grant_id="9f5c0d5d-032f-48e1-9ea1-b7f1d6bb4868",
    )
    return action, key, policy_path, scope, grant


def validate(authority, grant=None, *, action=None, window_start=None, window_end=None,
             selection_sha256="7" * 64, policy_path=None, records=(), now=NOW):
    original_action, _, original_policy, scope, original_grant = authority
    return validate_grant(
        grant or original_grant,
        action or original_action,
        window_start=window_start or scope.window_start,
        window_end=window_end or scope.window_end,
        selection_sha256=selection_sha256,
        trusted_policy_path=policy_path or original_policy,
        admission_records=records,
        now=now,
    )


def test_explicit_synthetic_grant_validates_with_complete_scope(authority):
    result = validate(authority)
    assert (result.status, result.reason_code, result.admission) == (
        "AUTHORIZED", "GRANT_VALID_NEW_ADMISSION", "NEW_ADMISSION"
    )
    assert result.scope_sha256 == authority[4].scope_sha256


def test_missing_trusted_policy_fails_closed(authority):
    # Default path is deliberately absent; callers cannot supply an in-memory root.
    denied = validate_grant(
        authority[4], authority[0], window_start=authority[3].window_start,
        window_end=authority[3].window_end, selection_sha256="7" * 64,
        trusted_policy_path=None, now=NOW,
    )
    assert (denied.status, denied.reason_code) == ("DENIED", "TRUST_POLICY_MISSING")


def test_forged_signature_and_unknown_issuer_are_denied(authority):
    grant = authority[4].model_dump(mode="json")
    signature = grant["signature_b64"]
    grant["signature_b64"] = ("A" if signature[0] != "A" else "B") + signature[1:]
    assert validate(authority, grant=grant).reason_code == "SIGNATURE_INVALID"

    unknown = issue_synthetic_grant(
        authority[3], issuer_id="unknown-issuer", private_key=Ed25519PrivateKey.generate(),
        issued_at=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=10),
    )
    assert validate(authority, grant=unknown).reason_code == "UNKNOWN_ISSUER"


def test_expired_and_revoked_grants_are_denied(authority, tmp_path):
    expired = issue_synthetic_grant(
        authority[3], issuer_id=ISSUER_ID, private_key=authority[1],
        issued_at=NOW - timedelta(hours=2), expires_at=NOW - timedelta(hours=1),
    )
    assert validate(authority, grant=expired).reason_code == "GRANT_EXPIRED"
    revoked_policy = write_policy(tmp_path / "revoked-policy.json", public_key_b64(authority[1]),
                                  revoked=(authority[4].grant_id,))
    assert validate(authority, policy_path=revoked_policy).reason_code == "GRANT_REVOKED"


def test_scope_changes_to_action_window_data_spec_or_selection_are_denied(authority):
    action = authority[0]
    changed_action = make_action(parameters={"signal_at": "2026-10-16T10:00:00+00:00",
                                             "quantity": 2})
    assert validate(authority, action=changed_action).reason_code == "ACTION_SCOPE_MISMATCH"
    assert validate(authority, window_start=datetime(2026, 10, 16, 9, 1, tzinfo=UTC)).reason_code == "ACTION_SCOPE_MISMATCH"
    assert validate(authority, selection_sha256="8" * 64).reason_code == "ACTION_SCOPE_MISMATCH"
    for key in ("source_sha256", "data_sha256", "spec_sha256", "config_sha256"):
        identity = dict(action["identity"])
        identity[key] = "a" * 64
        assert validate(authority, action=make_action(identity=identity)).reason_code == "ACTION_SCOPE_MISMATCH"


def test_protected_or_trading_effects_are_denied_even_with_a_valid_signature(authority):
    for key, value, expected in (
        ("allowed_effect", "protected_history", "EFFECT_DENIED"),
        ("protected_data", True, "PROTECTED_DATA_DENIED"),
        ("trading", True, "TRADING_DENIED"),
    ):
        payload = authority[4].model_dump(mode="json")
        payload[key] = value
        result = validate(authority, grant=payload)
        assert result.reason_code == expected


def _admission(grant, attempt_id="attempt-1", run_id="run-1"):
    return {
        "attempt_id": attempt_id,
        "run_id": run_id,
        "trial_id": grant.scope.trial_id,
        "metadata": {"authorization": {
            "grant_id": grant.grant_id,
            "action_sha256": grant.scope.action_sha256,
            "scope_sha256": grant.scope_sha256,
        }},
    }


def test_replay_denied_but_same_original_admission_retry_is_distinct(authority):
    grant = authority[4]
    retry = validate(authority, records=(_admission(grant),))
    assert (retry.status, retry.reason_code, retry.admission) == (
        "AUTHORIZED", "GRANT_VALID_RETRY_SAME_ADMISSION", "RETRY_SAME_ADMISSION"
    )
    replay = validate(authority, records=(_admission(grant), _admission(
        grant, attempt_id="attempt-2", run_id="run-2")))
    assert (replay.status, replay.reason_code) == ("DENIED", "GRANT_REPLAY")


def test_attempt_record_scope_drift_denies_retry(authority):
    row = _admission(authority[4])
    row["metadata"]["authorization"]["action_sha256"] = "0" * 64
    result = validate(authority, records=(row,))
    assert (result.status, result.reason_code) == ("DENIED", "GRANT_REPLAY_SCOPE_DRIFT")


def test_unexpected_errors_are_not_authorization_denials(authority, monkeypatch):
    # Unexpected implementation errors must propagate; only documented
    # authorization failures may be represented as DENIED decisions.
    import src.research_control.action_authorization as auth

    def unexpected(*_args, **_kwargs):
        raise TypeError("injected unexpected error")

    monkeypatch.setattr(auth, "build_scope", unexpected)
    with pytest.raises(TypeError, match="injected unexpected error"):
        validate(authority)


def test_bubblewrap_worker_cannot_read_or_change_host_authority(tmp_path, authority):
    bwrap = shutil.which("bwrap")
    if not bwrap:
        pytest.skip("bubblewrap executable unavailable")
    authority_dir = tmp_path / "host-authority"
    authority_dir.mkdir()
    key_path = authority_dir / "issuer-private.pem"
    key_path.write_bytes(authority[1].private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    key_path.chmod(0o600)
    trust_path = authority[2]
    ledger_path = authority_dir / "attempt-ledger.json"
    ledger_path.write_text('{"events":[]}', encoding="utf-8")
    ledger_path.chmod(0o600)
    accepted = authority_dir / "accepted-output"
    accepted.mkdir()
    accepted_file = accepted / "result.json"
    accepted_file.write_text('{"accepted":true}', encoding="utf-8")
    accepted_file.chmod(0o600)
    staging = tmp_path / "staging"
    staging.mkdir()
    staging.chmod(0o777)
    paths = json.dumps([str(key_path), str(trust_path), str(ledger_path), str(accepted)])
    child = """
import json
import pathlib
import sys
paths = json.loads(sys.argv[1])
forbidden = []
for p in paths:
    q = pathlib.Path(p)
    target = q / "worker-write" if q.suffix == "" else q
    try:
        q.read_bytes() if q.is_file() else next(q.iterdir())
        forbidden.append("read:" + p)
    except (FileNotFoundError, PermissionError, NotADirectoryError, StopIteration):
        pass
    try:
        target.write_text("tampered")
        forbidden.append("write:" + p)
    except (FileNotFoundError, PermissionError, NotADirectoryError, IsADirectoryError):
        pass
pathlib.Path("/work/staging/worker-output.json").write_text(json.dumps({"forbidden": forbidden}))
print(json.dumps({"forbidden": forbidden}))
"""
    command = [bwrap, "--die-with-parent", "--unshare-user", "--uid", "65534", "--gid", "65534",
               "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib",
               "--ro-bind", "/lib64", "/lib64", "--dir", "/etc",
               "--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache", "--proc", "/proc",
               "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/work",
               "--bind", str(staging), "/work/staging", "--chdir", "/work",
               "/usr/bin/python3", "-c", child, paths]
    result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
    if result.returncode and "No permissions to create a new namespace" in result.stderr:
        pytest.skip("nested Codex sandbox blocks Bubblewrap user namespaces")
    assert result.returncode == 0, result.stderr
    report = json.loads((staging / "worker-output.json").read_text())
    assert report["forbidden"] == []
    assert "tampered" not in key_path.read_text(errors="replace")
    assert trust_path.stat().st_mode & 0o777 == 0o600
    assert ledger_path.read_text() == '{"events":[]}'
    assert accepted_file.read_text() == '{"accepted":true}'
