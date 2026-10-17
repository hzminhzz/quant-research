"""ATS-7 immutable identities and external authorization, separate from ATS-2 grants.

There is deliberately no production signing function. Local simulation permission
cannot authorize a provider call. Hashes establish identity, never scientific truth.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import platform
import re
import sqlite3
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.research_control.action_authorization import canonical_json, sha256_json


class ReleaseBlocked(PermissionError):
    """No new economic effect is permitted."""


class Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SourceBinding(Frozen):
    role: str
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Product(Frozen):
    asset: str
    venue_symbol: str
    kind: Literal["linear_perpetual", "synthetic"]
    quantity_step: str
    price_tick: str
    minimum_quantity: str
    minimum_notional: str
    position_mode: Literal["one_way"]
    margin_mode: str
    specification_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("quantity_step", "price_tick", "minimum_quantity", "minimum_notional")
    @classmethod
    def positive_decimal(cls, value: str) -> str:
        from decimal import Decimal
        n = Decimal(value)
        if not n.is_finite() or n <= 0:
            raise ValueError("positive finite decimal required")
        return value


class RiskEnvelope(Frozen):
    capital: float = Field(gt=0)
    max_order_shares: float = Field(gt=0)
    max_order_value: float = Field(gt=0)
    max_position_shares: float = Field(gt=0)
    max_position_value: float = Field(gt=0)
    max_total_exposure: float = Field(gt=0)
    max_positions: int = Field(gt=0)
    max_orders_per_minute: int = Field(gt=0)
    max_daily_loss: float = Field(gt=0)
    max_drawdown_pct: float = Field(gt=0, le=1)
    max_price_deviation_pct: float = Field(gt=0, le=1)
    max_data_staleness_seconds: float = Field(gt=0)
    dedup_window_seconds: float = Field(gt=0)

    @model_validator(mode="after")
    def consistent(self):
        values = self.model_dump()
        if not all(math.isfinite(v) for v in values.values()):
            raise ValueError("non-finite risk")
        if not self.max_order_value <= self.max_position_value <= self.max_total_exposure:
            raise ValueError("inconsistent value caps")
        if self.max_order_shares > self.max_position_shares:
            raise ValueError("inconsistent quantity caps")
        return self


class OperationPolicy(Frozen):
    bar_seconds: int = Field(gt=0)
    max_clock_skew_seconds: float = Field(gt=0)
    max_account_age_seconds: float = Field(gt=0)
    feed_silence_seconds: float = Field(gt=0)
    observation_days: int = Field(ge=28)
    minimum_cycles: int = Field(ge=1)
    minimum_bar_coverage: float = Field(gt=0, le=1)
    owner: str
    rollback_procedure: str
    monitoring_requirements: tuple[str, ...]
    halt_policy: Literal["latch_no_new_risk"]
    recovery_policy: Literal["reconcile_then_separate_resume"]
    expiry_policy: Literal["block_open_preserve_obligations"]

    @model_validator(mode="after")
    def cadence(self):
        if self.feed_silence_seconds <= self.bar_seconds:
            raise ValueError("watchdog must allow a complete bar")
        if not self.owner or not self.rollback_procedure or not self.monitoring_requirements:
            raise ValueError("operational ownership required")
        return self


class StrategyBinding(Frozen):
    module: str
    class_name: str
    parameters_json: str
    signal_timing: str
    scientific_status: Literal["SYNTHETIC_ENGINEERING", "QUALIFIED"]
    research_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("parameters_json")
    @classmethod
    def parameters(cls, value: str) -> str:
        decoded = json.loads(value)
        if not isinstance(decoded, dict) or canonical_json(decoded).decode() != value:
            raise ValueError("parameters must be canonical JSON object")
        return value


class ReleaseManifest(Frozen):
    kind: Literal["ats7_release_v1"] = "ats7_release_v1"
    name: str
    environment: Literal["LOCAL_PAPER", "PROVIDER_DEMO", "LIVE"]
    account_ref: str
    risk_domain: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,60}$")
    provider: str
    endpoint: str
    strategy: StrategyBinding
    portfolio_json: str
    products: tuple[Product, ...]
    risk: RiskEnvelope
    operations: OperationPolicy
    account_terms_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    account_terms_source: str
    account_terms_effective_at: datetime
    data_cost_calendar_execution_json: str
    native_versions_json: str
    sources: tuple[SourceBinding, ...]
    qualification_evidence: tuple[SourceBinding, ...]
    not_before: datetime
    expires_at: datetime

    @field_validator("not_before", "expires_at", "account_terms_effective_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timezone required")
        return value.astimezone(UTC)

    @field_validator("portfolio_json", "data_cost_calendar_execution_json", "native_versions_json")
    @classmethod
    def canonical_object(cls, value: str) -> str:
        decoded = json.loads(value)
        if not isinstance(decoded, dict) or canonical_json(decoded).decode() != value:
            raise ValueError("canonical JSON object required")
        return value

    @model_validator(mode="after")
    def boundaries(self):
        if self.expires_at <= self.not_before:
            raise ValueError("invalid release window")
        if not self.products or len({p.asset for p in self.products}) != len(self.products):
            raise ValueError("unique products required")
        if len({s.path for s in self.sources}) != len(self.sources):
            raise ValueError("duplicate source")
        roles = {s.role for s in self.sources}
        if not {"strategy", "dependencies", "native_live", "connector"} <= roles:
            raise ValueError("critical implementation bindings missing")
        endpoints = {
            "LOCAL_PAPER": "local://ml4t-virtual-portfolio",
            "PROVIDER_DEMO": "https://api-demo.bybit.com",
            "LIVE": "https://api.bybit.com",
        }
        if self.endpoint != endpoints[self.environment]:
            raise ValueError("environment/endpoint mismatch")
        if self.environment == "LOCAL_PAPER":
            if not self.account_ref.startswith("local:"):
                raise ValueError("local account namespace required")
        elif re.fullmatch(r"sha256:[0-9a-f]{64}", self.account_ref) is None:
            raise ValueError("private authenticated account fingerprint required")
        if not any(s.role == "terms" and s.sha256 == self.account_terms_sha256
                   for s in (*self.sources, *self.qualification_evidence)):
            raise ValueError("account terms content must be bound to source evidence")
        if self.environment == "LIVE" and self.strategy.scientific_status != "QUALIFIED":
            raise ValueError("synthetic strategy cannot be live")
        return self

    @property
    def identity(self) -> str:
        return sha256_json(self.model_dump(mode="json"))

    def verify_sources(self) -> None:
        deployment = json.loads(self.data_cost_calendar_execution_json).get("deployment")
        if deployment != {"python": platform.python_version(), "machine": platform.machine(),
                          "sqlite": sqlite3.sqlite_version}:
            raise ReleaseBlocked("DEPLOYMENT_ENVIRONMENT_DRIFT")
        for source in (*self.sources, *self.qualification_evidence):
            path = Path(source.path)
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != source.sha256:
                raise ReleaseBlocked("SOURCE_DRIFT:" + source.role)
        for package, expected in json.loads(self.native_versions_json).items():
            if version(package) != expected:
                raise ReleaseBlocked("DEPENDENCY_DRIFT:" + package)


class Attestation(Frozen):
    kind: Literal["ats7_attestation_v1"] = "ats7_attestation_v1"
    purpose: Literal["QUALIFICATION", "AUTHORIZATION"]
    issuer_id: str
    manifest_sha256: str
    environment: Literal["LOCAL_PAPER", "PROVIDER_DEMO", "LIVE"]
    account_ref: str
    risk_sha256: str
    actions: tuple[Literal["open", "reduce", "cancel", "resume"], ...]
    issued_at: datetime
    expires_at: datetime
    recovery_until: datetime
    evidence_sha256: str
    observation_started_at: datetime | None = None
    observation_finished_at: datetime | None = None
    observation_cycles: int = 0
    observation_bar_coverage: float = 0.0
    unresolved_anomalies: int = 0
    nonce: str
    signature_b64: str

    @field_validator("issued_at", "expires_at", "recovery_until",
                     "observation_started_at", "observation_finished_at")
    @classmethod
    def aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("timezone required")
        return value

    def signed_payload(self) -> bytes:
        return canonical_json(self.model_dump(mode="json", exclude={"signature_b64"}))


class TrustedSigner(Frozen):
    issuer_id: str
    public_key_b64: str
    role: Literal["QUALIFICATION", "AUTHORIZATION"]
    environments: tuple[Literal["PROVIDER_DEMO", "LIVE"], ...]


class ReleaseTrust(Frozen):
    kind: Literal["ats7_external_trust_v1"] = "ats7_external_trust_v1"
    revision: int = Field(gt=0)
    signers: tuple[TrustedSigner, ...]
    revoked_nonces: tuple[str, ...]
    expires_at: datetime

    @classmethod
    def load_external(cls, path: Path) -> ReleaseTrust:
        # Enforce an actual different-owner trust boundary. The operator must
        # provision this file; a research-owned approval directory is rejected.
        real = path.resolve(strict=True)
        for entry in (real, *real.parents):
            st = entry.stat()
            if st.st_uid == os.geteuid() or st.st_mode & 0o022:
                raise ReleaseBlocked("TRUST_WRITABLE_BY_WORKER")
        return cls.model_validate_json(real.read_bytes())


def verify_attestation(receipt: Attestation, trust: ReleaseTrust,
                       manifest: ReleaseManifest, *, purpose: str, action: str,
                       now: datetime) -> None:
    if now.tzinfo is None or trust.expires_at.tzinfo is None or now >= trust.expires_at:
        raise ReleaseBlocked("TRUST_EXPIRED")
    matches = [s for s in trust.signers if s.issuer_id == receipt.issuer_id
               and s.role == purpose and manifest.environment in s.environments]
    if len(matches) != 1 or receipt.purpose != purpose:
        raise ReleaseBlocked("UNTRUSTED_ISSUER_OR_ROLE")
    if receipt.nonce in trust.revoked_nonces:
        raise ReleaseBlocked("AUTHORIZATION_REVOKED")
    expected = (manifest.identity, manifest.environment, manifest.account_ref,
                sha256_json(manifest.risk.model_dump(mode="json")))
    observed = (receipt.manifest_sha256, receipt.environment, receipt.account_ref,
                receipt.risk_sha256)
    if observed != expected:
        raise ReleaseBlocked("ATTESTATION_SCOPE_MISMATCH")
    expiry = receipt.recovery_until if action in {"reduce", "cancel"} else receipt.expires_at
    if not receipt.issued_at <= now < expiry or action not in receipt.actions:
        raise ReleaseBlocked("ATTESTATION_EXPIRED_OR_ACTION_DENIED")
    if receipt.recovery_until < receipt.expires_at:
        raise ReleaseBlocked("INVALID_RECOVERY_WINDOW")
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(matches[0].public_key_b64, validate=True))
        key.verify(base64.b64decode(receipt.signature_b64, validate=True), receipt.signed_payload())
    except Exception as exc:
        raise ReleaseBlocked("INVALID_SIGNATURE") from exc


class ExternalAuthority:
    """Read fresh public authorization for every effect; never issue an approval."""

    def __init__(self, trust_path: Path, approval_path: Path, qualification_path: Path):
        self.trust_path = trust_path
        self.approval_path = approval_path
        self.qualification_path = qualification_path

    def require(self, manifest: ReleaseManifest, action: str, now: datetime) -> None:
        trust = ReleaseTrust.load_external(self.trust_path)
        approval = Attestation.model_validate_json(self.approval_path.read_bytes())
        qualification = Attestation.model_validate_json(self.qualification_path.read_bytes())
        verify_attestation(approval, trust, manifest, purpose="AUTHORIZATION", action=action, now=now)
        verify_attestation(qualification, trust, manifest, purpose="QUALIFICATION", action=action, now=now)
        if approval.issuer_id == qualification.issuer_id:
            raise ReleaseBlocked("INDEPENDENT_QUALIFIER_REQUIRED")
        by_id = {s.issuer_id: s.public_key_b64 for s in trust.signers}
        if by_id[approval.issuer_id] == by_id[qualification.issuer_id]:
            raise ReleaseBlocked("INDEPENDENT_QUALIFIER_KEY_REQUIRED")
        evidence = sha256_json([s.model_dump(mode="json") for s in manifest.qualification_evidence])
        if not manifest.qualification_evidence or qualification.evidence_sha256 != evidence:
            raise ReleaseBlocked("QUALIFICATION_EVIDENCE_MISMATCH")
        if approval.evidence_sha256 != sha256_json(qualification.model_dump(mode="json")):
            raise ReleaseBlocked("APPROVAL_NOT_BOUND_TO_QUALIFICATION")
        if manifest.environment == "LIVE":
            start, end = qualification.observation_started_at, qualification.observation_finished_at
            if (start is None or end is None or end > now or end < start
                    or (end - start).total_seconds() < manifest.operations.observation_days * 86400
                    or qualification.observation_cycles < manifest.operations.minimum_cycles
                    or qualification.observation_bar_coverage < manifest.operations.minimum_bar_coverage
                    or qualification.unresolved_anomalies != 0):
                raise ReleaseBlocked("PAPER_OBSERVATION_INCOMPLETE")
