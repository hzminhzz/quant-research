"""Scoped, signed ATS-2 synthetic development grants.

This module validates authority only. It does not issue grants automatically,
launch workers, read protected data, or replace the AttemptLedger. The only
trust domain implemented here is SYNTHETIC_ONLY.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import Field, StrictBool, StrictStr, ValidationError, field_validator

from .contracts import StrictModel

_HEX = re.compile(r"^[0-9a-f]{64}$")
_MAX_POLICY_BYTES = 64 * 1024


class ScopeV1(StrictModel):
    """Canonical immutable scope covered by both the signature and scope hash."""

    schema_version: Literal[1]
    action_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    session_id: StrictStr = Field(min_length=1, max_length=100)
    trial_id: StrictStr = Field(min_length=1, max_length=160)
    operation: Literal["development_native_bracket", "synthetic_protected_fixture_read", "shadow_route"]
    source_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    data_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    spec_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    config_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    window_start: datetime
    window_end: datetime
    selection_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("window_start", "window_end")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone_required")
        return value.astimezone(UTC)

    @field_validator("window_end")
    @classmethod
    def window_ordered(cls, value: datetime, info):
        start = info.data.get("window_start")
        if start is not None and value <= start:
            raise ValueError("window_end_must_follow_start")
        return value


class SignedGrantV1(StrictModel):
    schema_version: Literal[1]
    grant_id: StrictStr
    issuer_id: StrictStr = Field(min_length=1, max_length=120)
    issued_at: datetime
    expires_at: datetime
    allowed_effect: StrictStr
    protected_data: StrictBool
    trading: StrictBool
    scope: ScopeV1
    scope_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    signature_b64: StrictStr = Field(min_length=80, max_length=100)

    @field_validator("grant_id")
    @classmethod
    def uuid_grant_id(cls, value: str) -> str:
        try:
            parsed = UUID(value)
        except ValueError as exc:
            raise ValueError("grant_id_must_be_uuid") from exc
        if str(parsed) != value:
            raise ValueError("grant_id_must_be_canonical_uuid")
        return value

    @field_validator("issued_at", "expires_at")
    @classmethod
    def grant_time_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone_required")
        return value.astimezone(UTC)


class TrustedIssuerV1(StrictModel):
    issuer_id: StrictStr = Field(min_length=1, max_length=120)
    public_key_b64: StrictStr = Field(min_length=40, max_length=60)
    enabled: StrictBool


class TrustPolicyV1(StrictModel):
    schema_version: Literal[1]
    trust_domain: StrictStr
    max_grant_seconds: int = Field(ge=1, le=86_400)
    issuers: tuple[TrustedIssuerV1, ...] = Field(min_length=1)
    revoked_grant_ids: tuple[StrictStr, ...] = ()

    @field_validator("issuers")
    @classmethod
    def unique_issuers(cls, value: tuple[TrustedIssuerV1, ...]):
        ids = [issuer.issuer_id for issuer in value]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_issuer_id")
        return value


@dataclass(frozen=True)
class AuthorizationDecision:
    status: Literal["AUTHORIZED", "DENIED"]
    reason_code: str
    grant_id: str | None = None
    scope_sha256: str | None = None
    admission: Literal["NEW_ADMISSION", "RETRY_SAME_ADMISSION"] | None = None


def canonical_json(value: Any) -> bytes:
    """Stable JSON bytes; reject non-data values and non-finite numbers."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _action_data(action: Any) -> dict[str, Any]:
    if hasattr(action, "model_dump"):
        action = action.model_dump(mode="json")
    if not isinstance(action, Mapping):
        raise TypeError("ACTION_SCHEMA_INVALID")
    raw = dict(action)
    # Prove the action's own digest before using it as a grant scope identity.
    contract_sha = raw.get("contract_sha256")
    if not isinstance(contract_sha, str) or not _HEX.fullmatch(contract_sha):
        raise ValueError("ACTION_DIGEST_MISSING")
    unsigned = dict(raw)
    unsigned.pop("contract_sha256")
    if sha256_json(unsigned) != contract_sha:
        raise ValueError("ACTION_DIGEST_INVALID")
    return raw


def build_scope(action: Any, *, window_start: datetime, window_end: datetime,
                selection_sha256: str) -> ScopeV1:
    """Build the complete allowed-effect scope from one frozen action."""
    raw = _action_data(action)
    identity = raw.get("identity")
    if not isinstance(identity, Mapping):
        raise TypeError("ACTION_IDENTITY_MISSING")
    required = ("source_sha256", "data_sha256", "spec_sha256", "config_sha256")
    if any(not isinstance(identity.get(key), str) or not _HEX.fullmatch(identity[key])
           for key in required):
        raise ValueError("ACTION_IDENTITY_INVALID")
    return ScopeV1.model_validate({
        "schema_version": 1,
        "action_sha256": sha256_json(raw),
        "session_id": raw.get("session_id"),
        "trial_id": raw.get("trial_id"),
        "operation": raw.get("operation"),
        "source_sha256": identity["source_sha256"],
        "data_sha256": identity["data_sha256"],
        "spec_sha256": identity["spec_sha256"],
        "config_sha256": identity["config_sha256"],
        "window_start": window_start,
        "window_end": window_end,
        "selection_sha256": selection_sha256,
    })


def scope_sha256(scope: ScopeV1 | Mapping[str, Any]) -> str:
    if isinstance(scope, ScopeV1):
        payload = scope.model_dump(mode="json")
    else:
        payload = ScopeV1.model_validate(scope).model_dump(mode="json")
    return sha256_json(payload)


def _signed_payload(grant: SignedGrantV1 | Mapping[str, Any]) -> dict[str, Any]:
    payload = (grant.model_dump(mode="json") if isinstance(grant, SignedGrantV1)
               else dict(grant))
    payload.pop("signature_b64", None)
    return payload


def issue_synthetic_grant(scope: ScopeV1, *, issuer_id: str,
                          private_key: Ed25519PrivateKey, issued_at: datetime,
                          expires_at: datetime, grant_id: str | None = None,
                          protected_fixture: bool = False, shadow: bool = False) -> SignedGrantV1:
    """Explicit fixture/test issuer. No policy lookup or automatic issuance occurs."""
    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError("private_key must be Ed25519PrivateKey")
    if issued_at.tzinfo is None or expires_at.tzinfo is None or expires_at <= issued_at:
        raise ValueError("GRANT_TIME_INVALID")
    if protected_fixture and shadow:
        raise ValueError("EFFECTS_MUST_BE_EXCLUSIVE")
    required_operation = ("shadow_route" if shadow else
                          "synthetic_protected_fixture_read" if protected_fixture
                          else "development_native_bracket")
    if scope.operation != required_operation:
        raise ValueError("SYNTHETIC_GRANT_OPERATION_INVALID")
    payload = {
        "schema_version": 1,
        "grant_id": grant_id or str(uuid4()),
        "issuer_id": issuer_id,
        "issued_at": issued_at.astimezone(UTC).isoformat(),
        "expires_at": expires_at.astimezone(UTC).isoformat(),
        "allowed_effect": ("shadow_only" if shadow else
                           "synthetic_protected_fixture_read" if protected_fixture
                           else "development_only"),
        "protected_data": protected_fixture,
        "trading": False,
        "scope": scope.model_dump(mode="json"),
        "scope_sha256": scope_sha256(scope),
    }
    unsigned_grant = SignedGrantV1.model_validate_json(canonical_json({
        **payload, "signature_b64": base64.b64encode(bytes(64)).decode("ascii")
    }))
    signature = private_key.sign(canonical_json(_signed_payload(unsigned_grant)))
    payload["signature_b64"] = base64.b64encode(signature).decode("ascii")
    return SignedGrantV1.model_validate_json(canonical_json(payload))


def _policy(path: str | Path | None) -> TrustPolicyV1:
    if path is None:
        raise ValueError("TRUST_POLICY_MISSING")
    source = Path(path)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > _MAX_POLICY_BYTES:
        raise ValueError("TRUST_POLICY_UNAVAILABLE")
    return TrustPolicyV1.model_validate_json(source.read_text(encoding="utf-8"))


def _admission_disposition(grant: SignedGrantV1, action_digest: str,
                           scope_digest: str,
                           admission_records: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]]) -> str:
    matches = []
    for record in admission_records:
        metadata = record.get("metadata")
        authorization = metadata.get("authorization") if isinstance(metadata, Mapping) else None
        if isinstance(authorization, Mapping) and authorization.get("grant_id") == grant.grant_id:
            matches.append((record, authorization))
    if not matches:
        return "NEW_ADMISSION"
    attempt_ids = {record.get("attempt_id") for record, _ in matches}
    run_ids = {record.get("run_id") for record, _ in matches}
    if len(attempt_ids) != 1 or len(run_ids) != 1 or None in attempt_ids or None in run_ids:
        raise ValueError("GRANT_REPLAY")
    for record, authorization in matches:
        if (authorization.get("action_sha256") != action_digest
            or authorization.get("scope_sha256") != scope_digest
            or record.get("trial_id") != grant.scope.trial_id):
            raise ValueError("GRANT_REPLAY_SCOPE_DRIFT")
    return "RETRY_SAME_ADMISSION"


def validate_grant(grant: SignedGrantV1 | Mapping[str, Any], action: Any, *,
                   window_start: datetime, window_end: datetime,
                   selection_sha256: str,
                   trusted_policy_path: str | Path | None = None,
                   admission_records: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]] = (),
                   now: datetime | None = None,
                   protected_fixture: bool = False, shadow: bool = False,
                   trusted_policy: TrustPolicyV1 | None = None) -> AuthorizationDecision:
    """Verify signature, trust, expiry, scope, revocation, and durable replay evidence."""
    grant_id = grant.grant_id if isinstance(grant, SignedGrantV1) else (
        grant.get("grant_id") if isinstance(grant, Mapping) else None)
    if protected_fixture and shadow:
        return AuthorizationDecision("DENIED", "EFFECTS_MUST_BE_EXCLUSIVE", grant_id)
    if trusted_policy is not None and (not shadow or trusted_policy_path is not None):
        return AuthorizationDecision("DENIED", "POLICY_SOURCE_AMBIGUOUS", grant_id)
    try:
        # ATS-6 pins this public policy in the same transaction as risk admission.
        # Only the explicit shadow path accepts a transaction-owned policy.
        policy = (TrustPolicyV1.model_validate(trusted_policy.model_dump())
                  if trusted_policy is not None else _policy(trusted_policy_path))
    except FileNotFoundError:
        return AuthorizationDecision("DENIED", "TRUST_POLICY_UNAVAILABLE", grant_id)
    except ValidationError:
        return AuthorizationDecision("DENIED", "TRUST_POLICY_INVALID", grant_id)
    except ValueError as exc:
        return AuthorizationDecision("DENIED", str(exc).split(":", 1)[0], grant_id)
    if policy.trust_domain != "SYNTHETIC_ONLY":
        return AuthorizationDecision("DENIED", "TRUST_DOMAIN_UNSUPPORTED", grant_id)
    try:
        parsed = (grant if isinstance(grant, SignedGrantV1)
                  else SignedGrantV1.model_validate_json(canonical_json(grant)))
    except (ValidationError, TypeError, ValueError):
        return AuthorizationDecision("DENIED", "GRANT_SCHEMA_INVALID", grant_id)
    required_effect = ("shadow_only" if shadow else
                       "synthetic_protected_fixture_read" if protected_fixture
                       else "development_only")
    if parsed.allowed_effect != required_effect:
        return AuthorizationDecision("DENIED", "EFFECT_DENIED", parsed.grant_id)
    if parsed.protected_data != protected_fixture:
        return AuthorizationDecision("DENIED", "PROTECTED_DATA_DENIED", parsed.grant_id)
    if protected_fixture and parsed.scope.operation != "synthetic_protected_fixture_read":
        return AuthorizationDecision("DENIED", "FIXTURE_OPERATION_REQUIRED", parsed.grant_id)
    if shadow and parsed.scope.operation != "shadow_route":
        return AuthorizationDecision("DENIED", "OPERATION_DENIED", parsed.grant_id)
    if not protected_fixture and not shadow and parsed.scope.operation != "development_native_bracket":
        return AuthorizationDecision("DENIED", "OPERATION_DENIED", parsed.grant_id)
    if parsed.trading:
        return AuthorizationDecision("DENIED", "TRADING_DENIED", parsed.grant_id)
    issuers = {issuer.issuer_id: issuer for issuer in policy.issuers}
    issuer = issuers.get(parsed.issuer_id)
    if issuer is None or not issuer.enabled:
        return AuthorizationDecision("DENIED", "UNKNOWN_ISSUER", parsed.grant_id)
    if parsed.grant_id in policy.revoked_grant_ids:
        return AuthorizationDecision("DENIED", "GRANT_REVOKED", parsed.grant_id)
    observed = now or datetime.now(UTC)
    if observed.tzinfo is None or observed.utcoffset() is None:
        return AuthorizationDecision("DENIED", "VALIDATION_CLOCK_INVALID", parsed.grant_id)
    observed = observed.astimezone(UTC)
    issued, expires = parsed.issued_at.astimezone(UTC), parsed.expires_at.astimezone(UTC)
    if expires <= issued or (expires - issued).total_seconds() > policy.max_grant_seconds:
        return AuthorizationDecision("DENIED", "GRANT_DURATION_INVALID", parsed.grant_id)
    if issued > observed:
        return AuthorizationDecision("DENIED", "GRANT_NOT_YET_VALID", parsed.grant_id)
    if observed >= expires:
        return AuthorizationDecision("DENIED", "GRANT_EXPIRED", parsed.grant_id)
    try:
        public_bytes = base64.b64decode(issuer.public_key_b64, validate=True)
        signature = base64.b64decode(parsed.signature_b64, validate=True)
        public_key = Ed25519PublicKey.from_public_bytes(public_bytes)
        public_key.verify(signature, canonical_json(_signed_payload(parsed)))
    except (ValueError, binascii.Error, InvalidSignature):
        return AuthorizationDecision("DENIED", "SIGNATURE_INVALID", parsed.grant_id)
    try:
        declared_scope_digest = scope_sha256(parsed.scope)
    except (ValidationError, TypeError, ValueError):
        return AuthorizationDecision("DENIED", "GRANT_SCOPE_INVALID", parsed.grant_id)
    if declared_scope_digest != parsed.scope_sha256:
        return AuthorizationDecision("DENIED", "GRANT_SCOPE_HASH_MISMATCH", parsed.grant_id)
    try:
        expected_scope = build_scope(action, window_start=window_start,
                                     window_end=window_end,
                                     selection_sha256=selection_sha256)
    except (ValidationError, ValueError):
        return AuthorizationDecision("DENIED", "ACTION_SCOPE_INVALID", parsed.grant_id)
    if parsed.scope != expected_scope:
        return AuthorizationDecision("DENIED", "ACTION_SCOPE_MISMATCH", parsed.grant_id,
                                     declared_scope_digest)
    try:
        admission = _admission_disposition(parsed, expected_scope.action_sha256,
                                           declared_scope_digest, admission_records)
    except ValueError as exc:
        return AuthorizationDecision("DENIED", str(exc).split(":", 1)[0], parsed.grant_id,
                                     declared_scope_digest)
    reason = "GRANT_VALID_RETRY_SAME_ADMISSION" if admission == "RETRY_SAME_ADMISSION" else "GRANT_VALID_NEW_ADMISSION"
    return AuthorizationDecision("AUTHORIZED", reason, parsed.grant_id,
                                 declared_scope_digest, admission)  # type: ignore[arg-type]


def public_key_b64(private_key: Ed25519PrivateKey) -> str:
    """Serialize a fixture issuer public key; callers must protect the private key."""
    raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")
