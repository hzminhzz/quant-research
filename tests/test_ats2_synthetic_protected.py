"""Synthetic-only protected fixture ATS-2 positive and adversarial authorization."""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.research_control.action_authorization import (
    TrustPolicyV1,
    issue_synthetic_grant,
    public_key_b64,
    validate_grant,
)
from src.research_control.synthetic_protected_fixture import (
    fixture_scope,
    prepare_fixture,
    read_synthetic_protected_fixture,
)


def protected_setup(tmp_path):
    root = tmp_path / "synthetic-root"
    action = prepare_fixture(root)
    issuer_root = tmp_path / "external-issuer"
    issuer_root.mkdir()
    private = Ed25519PrivateKey.generate()
    key_path = issuer_root / "issuer-key.pem"
    key_path.write_bytes(private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    policy_path = issuer_root / "trusted-policy.json"
    policy = TrustPolicyV1(
        schema_version=1, trust_domain="SYNTHETIC_ONLY", max_grant_seconds=3600,
        issuers=({"issuer_id": "external-fixture-issuer",
                  "public_key_b64": public_key_b64(private), "enabled": True},),
    )
    policy_path.write_text(policy.model_dump_json(), encoding="utf-8")
    now = datetime.now(UTC)
    grant = issue_synthetic_grant(
        fixture_scope(action), issuer_id="external-fixture-issuer",
        private_key=private, issued_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=10), protected_fixture=True,
    )
    return root, action, grant, key_path, policy_path, private


def run_fixture(args):
    root, action, grant, key_path, policy_path = args
    return read_synthetic_protected_fixture(
        root, action, grant,
        trusted_policy_path=policy_path, issuer_private_path=key_path,
    )


def test_real_synthetic_protected_read_with_external_issuer(tmp_path):
    root, action, grant, key_path, policy_path, _ = protected_setup(tmp_path)
    assert grant.protected_data is True and grant.trading is False
    assert grant.allowed_effect == "synthetic_protected_fixture_read"
    assert validate_grant(
        grant, action, window_start=grant.scope.window_start,
        window_end=grant.scope.window_end, selection_sha256=action["selection_sha256"],
        trusted_policy_path=policy_path,
    ).reason_code == "EFFECT_DENIED"
    original_key = hashlib.sha256(key_path.read_bytes()).hexdigest()
    original_policy = hashlib.sha256(policy_path.read_bytes()).hexdigest()
    result = run_fixture((str(root), action, grant, str(key_path), str(policy_path)))
    assert result["status"] == "VERIFIED_SYNTHETIC_PROTECTED_READ", result
    accepted = json.loads((root / result["proof"]).read_text())
    assert accepted["input_sha256"] == action["identity"]["data_sha256"]
    assert accepted["external_issuer_private_key_not_mounted"] is True
    assert accepted["trusted_policy_not_mounted"] is True
    assert accepted["live_order_authority"] is False
    assert hashlib.sha256(key_path.read_bytes()).hexdigest() == original_key
    assert hashlib.sha256(policy_path.read_bytes()).hexdigest() == original_policy
    assert "synthetic_protected_fixture.bin" not in result["proof"]
    assert run_fixture((str(root), action, grant, str(key_path), str(policy_path))) == {
        "status": "BLOCKED", "reason_code": "PROTECTED_GRANT_CONSUMED",
    }
    assert len(list((root / "consumed_claims").glob("*.json"))) == 1
    assert len(list((root / "protected_receipts").glob("*/accepted.json"))) == 1


def test_protected_fixture_denials_do_not_read_or_consume(tmp_path):
    root, action, grant, key_path, policy_path, key = protected_setup(tmp_path)
    base = (str(root), action, grant, str(key_path), str(policy_path))
    bad = grant.model_dump(mode="json")
    bad["signature_b64"] = ("A" if bad["signature_b64"][0] != "A" else "B") + bad["signature_b64"][1:]
    wrong_selection = dict(action)
    wrong_selection["selection_sha256"] = "0" * 64
    wrong_action = dict(action)
    wrong_action["identity"] = dict(action["identity"])
    wrong_action["identity"]["data_sha256"] = "1" * 64
    original_action_path = root / "fixture_action.json"
    original_action_raw = original_action_path.read_bytes()
    trials = [
        ("signature", (str(root), action, bad, str(key_path), str(policy_path)), "SIGNATURE_INVALID"),
        ("changed-selection", (str(root), wrong_selection, grant, str(key_path), str(policy_path)), "FIXTURE_ACTION_INVALID"),
        ("changed-data", (str(root), wrong_action, grant, str(key_path), str(policy_path)), "FIXTURE_ACTION_INVALID"),
        ("no-grant", (str(root), action, {}, str(key_path), str(policy_path)), "GRANT_SCHEMA_INVALID"),
    ]
    for name, args, reason in trials:
        rejected = run_fixture(args)
        assert rejected["reason_code"] == reason, (name, rejected)
        assert not (root / "protected_receipts").exists()
        assert not list((root / "consumed_claims").glob("*.json"))
    unknown = issue_synthetic_grant(
        fixture_scope(action), issuer_id="unknown-issuer",
        private_key=Ed25519PrivateKey.generate(),
        issued_at=datetime.now(UTC) - timedelta(minutes=1),
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        protected_fixture=True,
    )
    assert run_fixture((str(root), action, unknown, str(key_path), str(policy_path)))["reason_code"] == "UNKNOWN_ISSUER"
    expired = issue_synthetic_grant(
        fixture_scope(action), issuer_id="external-fixture-issuer",
        private_key=key,
        issued_at=datetime.now(UTC) - timedelta(minutes=4),
        expires_at=datetime.now(UTC) - timedelta(minutes=2),
        protected_fixture=True,
    )
    assert run_fixture((str(root), action, expired, str(key_path), str(policy_path)))["reason_code"] == "GRANT_EXPIRED"
    policy = TrustPolicyV1.model_validate_json(policy_path.read_text())
    revoked = policy.model_copy(update={"revoked_grant_ids": (grant.grant_id,)})
    policy_path.write_text(revoked.model_dump_json())
    assert run_fixture(base)["reason_code"] == "GRANT_REVOKED"
    assert original_action_path.read_bytes() == original_action_raw
    assert not list((root / "consumed_claims").glob("*.json"))


def test_same_protected_grant_is_consumed_once_across_processes(tmp_path):
    root, action, grant, key_path, policy_path, _ = protected_setup(tmp_path)
    params = (str(root), action, grant, str(key_path), str(policy_path))
    import multiprocessing
    with ProcessPoolExecutor(max_workers=2,
                             mp_context=multiprocessing.get_context("spawn")) as pool:
        result = list(pool.map(run_fixture, [params, params]))
    assert sum(item["status"] == "VERIFIED_SYNTHETIC_PROTECTED_READ" for item in result) == 1, result
    assert sum(item["reason_code"] == "PROTECTED_GRANT_CONSUMED" for item in result
               if item["status"] == "BLOCKED") == 1, result
    assert len(list((root / "consumed_claims").glob("*.json"))) == 1
    assert len(list((root / "protected_receipts").glob("*/accepted.json"))) == 1


def test_synthetic_protected_changed_input_fails_and_consumes_once(tmp_path):
    root, action, grant, key_path, policy_path, _ = protected_setup(tmp_path)
    source = root / "synthetic_protected_fixture.bin"
    raw = source.read_bytes()
    source.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    args = (str(root), action, grant, str(key_path), str(policy_path))
    first = run_fixture(args)
    assert first["status"] == "FAILED", first
    assert first["reason_code"] == "PROTECTED_FIXTURE_WORKER_FAILED"
    assert run_fixture(args) == {
        "status": "BLOCKED", "reason_code": "PROTECTED_GRANT_CONSUMED",
    }
    assert len(list((root / "consumed_claims").glob("*.json"))) == 1
    assert not list((root / "protected_receipts").glob("*/accepted.json"))


def test_synthetic_protected_grant_cannot_authorize_native_development(tmp_path):
    _, action, grant, _, policy_path, _ = protected_setup(tmp_path)
    assert validate_grant(
        grant, action, window_start=grant.scope.window_start,
        window_end=grant.scope.window_end,
        selection_sha256=action["selection_sha256"],
        trusted_policy_path=policy_path,
        protected_fixture=False,
    ).reason_code == "EFFECT_DENIED"
