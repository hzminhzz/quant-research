"""Fail-closed identity-bound preflight permits; never grants order authority."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import polars as pl
from pydantic import (
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    ValidationError,
    model_validator,
)

from src.research_session import (
    ResearchSessionError,
    _hash,
    _identity,
    _load,
    _root,
)

from .contracts import ResearchContractV1, StrictModel
from .feature_gateway import (
    FeatureComputation,
    FeatureContractError,
    require_verified_feature_proof,
    verify_feature_proof,
)

Hash = Annotated[StrictStr, Field(pattern=r"^[a-f0-9]{64}$")]
Positive = Annotated[StrictInt | StrictFloat, Field(gt=0, allow_inf_nan=False)]


class CostDeclaration(StrictModel):
    commission_bps: Annotated[StrictInt | StrictFloat, Field(ge=0, allow_inf_nan=False)]
    slippage_bps: Annotated[StrictInt | StrictFloat, Field(ge=0, allow_inf_nan=False)]
    source: Annotated[StrictStr, Field(min_length=1)]
    evidence_path: Annotated[StrictStr, Field(min_length=1)]
    source_sha256: Hash


class MultiplierDeclaration(StrictModel):
    value: Positive
    unit: Annotated[StrictStr, Field(min_length=1)]
    instrument_symbol: Annotated[StrictStr, Field(min_length=1)]
    source: Annotated[StrictStr, Field(min_length=1)]
    evidence_path: Annotated[StrictStr, Field(min_length=1)]
    source_sha256: Hash


class ComputeBudget(StrictModel):
    max_wall_seconds: Annotated[StrictInt, Field(gt=0)]
    max_cpu_seconds: Annotated[StrictInt, Field(gt=0)]
    max_memory_mb: Annotated[StrictInt, Field(gt=0)]
    max_trials: Literal[1]


class IndependentAuditRecipe(StrictModel):
    method: Annotated[StrictStr, Field(min_length=1)]
    implementation: Annotated[StrictStr, Field(min_length=1)]
    version: Annotated[StrictStr, Field(min_length=1)]
    source_sha256: Hash
    evidence_path: Annotated[StrictStr, Field(min_length=1)]
    checks: Annotated[list[StrictStr], Field(min_length=1)]


class RunIntentV1(StrictModel):
    schema_version: Literal[1]
    session_id: Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")]
    trial_id: Annotated[StrictStr, Field(min_length=1)]
    evaluation_start: Annotated[datetime, Field(strict=False)]
    evaluation_end: Annotated[datetime, Field(strict=False)]
    decision_at: Annotated[datetime, Field(strict=False)]
    exit_at: Annotated[datetime, Field(strict=False)]
    required_exit_available_at: Annotated[datetime, Field(strict=False)]
    expected_source_vendor: Annotated[StrictStr, Field(min_length=1)]
    expected_source_symbol: Annotated[StrictStr, Field(min_length=1)]
    expected_catalog_dataset_key: StrictStr | None
    costs: CostDeclaration
    multiplier: MultiplierDeclaration
    effects: Annotated[
        list[Literal["READ_ONLY", "EVIDENCE_APPEND"]], Field(min_length=1)
    ]
    budget: ComputeBudget
    requested_compute: ComputeBudget
    independent_audit: IndependentAuditRecipe

    @model_validator(mode="after")
    def ordered_aware_times(self) -> RunIntentV1:
        times = (
            self.evaluation_start,
            self.evaluation_end,
            self.decision_at,
            self.exit_at,
            self.required_exit_available_at,
        )
        if any(value.tzinfo is None or value.utcoffset() is None for value in times):
            raise ValueError("all permit times must include a timezone")
        if not self.evaluation_start < self.evaluation_end:
            raise ValueError("evaluation_start must precede evaluation_end")
        if not self.evaluation_start <= self.decision_at <= self.evaluation_end:
            raise ValueError("decision_at must be inside the evaluation window")
        if not self.decision_at <= self.exit_at <= self.evaluation_end:
            raise ValueError(
                "exit_at must follow the decision and remain inside evaluation"
            )
        if self.required_exit_available_at != self.exit_at:
            raise ValueError(
                "required exit availability must equal the declared exit clock"
            )
        return self


class PermitIdentity(StrictModel):
    frozen_session_sha256: Hash
    spec_sha256: Hash
    config_sha256: Hash
    data_sha256: Hash
    source_sha256: Hash
    code_sha256: Hash
    feature_proof_sha256: Hash
    engine: Literal["ml4t.backtest"]
    engine_version: StrictStr
    intent_sha256: Hash


class RunPermitV1(StrictModel):
    schema_version: Literal[1]
    permit_sha256: Hash
    session_id: StrictStr
    trial_id: StrictStr
    identity: PermitIdentity
    evaluation_start: Annotated[datetime, Field(strict=False)]
    evaluation_end: Annotated[datetime, Field(strict=False)]
    available_at: Annotated[datetime, Field(strict=False)]
    costs: CostDeclaration
    multiplier: MultiplierDeclaration
    exit_at: Annotated[datetime, Field(strict=False)]
    effects: Annotated[
        list[Literal["READ_ONLY", "EVIDENCE_APPEND"]], Field(min_length=1)
    ]
    compute_budget: ComputeBudget
    independent_audit: IndependentAuditRecipe
    live_order_authority: Literal[False]

    @model_validator(mode="after")
    def verify_permit_identity(self) -> RunPermitV1:
        payload = self.model_dump(mode="json", exclude={"permit_sha256"})
        digest = _json_sha256(payload)
        if digest != self.permit_sha256:
            raise ValueError("permit_sha256 does not match the permit contents")
        return self


class GateReport(StrictModel):
    status: Literal["PASS", "BLOCKED"]
    reason_code: StrictStr
    summary: StrictStr
    expected: Any
    observed: Any
    where_found: StrictStr
    next_safe_action: StrictStr
    permit: RunPermitV1 | None = None


def _blocked(
    code: str, summary: str, expected: Any, observed: Any, where: str, action: str
) -> GateReport:
    return GateReport(
        status="BLOCKED",
        reason_code=code,
        summary=summary,
        expected=expected,
        observed=observed,
        where_found=where,
        next_safe_action=action,
    )


def _json_sha256(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _identity_hashes(
    root, frozen: dict[str, Any]
) -> tuple[str, str, str, str] | GateReport:
    identity = frozen["identity"]
    current_data = [_identity(root, item["path"]) for item in frozen["spec"]["data"]]
    if current_data != identity["data"]:
        return _blocked(
            "IDENTITY_DRIFT",
            "Frozen data identity changed.",
            identity["data"],
            current_data,
            "frozen session data identities",
            "Restore the frozen data or initialize a new session.",
        )
    current_config = (
        _identity(root, identity["config"]["path"]) if identity.get("config") else None
    )
    if current_config != identity.get("config"):
        return _blocked(
            "IDENTITY_DRIFT",
            "Frozen feature config identity changed.",
            identity.get("config"),
            current_config,
            "frozen session config",
            "Restore the frozen config or initialize a new session.",
        )
    current_source = []
    for folder in ("src", "scripts"):
        directory = root / folder
        if directory.exists():
            current_source.extend(
                _identity(root, path.relative_to(root))
                for path in sorted(directory.rglob("*.py"))
            )
    if current_source != identity["source"]:
        return _blocked(
            "IDENTITY_DRIFT",
            "Frozen source code identity changed.",
            identity["source"],
            current_source,
            "frozen session source identities",
            "Freeze a new session against the reviewed source tree.",
        )
    current_evidence = [_identity(root, item["path"]) for item in identity["evidence"]]
    if current_evidence != identity["evidence"]:
        return _blocked(
            "IDENTITY_DRIFT",
            "Frozen evidence identity changed.",
            identity["evidence"],
            current_evidence,
            "frozen session evidence",
            "Restore the frozen evidence or initialize a new session.",
        )
    return (
        _hash(current_data),
        identity["source_sha256"],
        identity["config"]["sha256"]
        if identity.get("config")
        else hashlib.sha256(b"").hexdigest(),
        _hash(current_source),
    )


def _verify_evidence(
    root, item: StrictModel, where: str, frozen_evidence: list[dict[str, Any]]
) -> GateReport | None:
    try:
        current = _identity(root, item.evidence_path)
    except (ResearchSessionError, OSError, ValueError) as exc:
        return _blocked(
            "IDENTITY_DRIFT",
            f"{where} evidence path is invalid.",
            item.evidence_path,
            str(exc),
            item.evidence_path,
            "Use an existing evidence file inside the workspace.",
        )
    if not current["exists"] or current["sha256"] != item.source_sha256:
        return _blocked(
            "IDENTITY_DRIFT",
            f"{where} evidence identity is missing or stale.",
            item.source_sha256,
            current,
            item.evidence_path,
            "Restore the frozen evidence file or initialize a new session.",
        )
    if not any(
        reference["path"] == current["path"]
        and reference["sha256"] == current["sha256"]
        for reference in frozen_evidence
    ):
        return _blocked(
            "IDENTITY_DRIFT",
            f"{where} evidence is not linked from the frozen session.",
            "a matching frozen evidence identity",
            current,
            "frozen session identity.evidence",
            "Link the evidence before freezing a new session.",
        )
    if where in ("Cost", "Multiplier"):
        code = "COSTS_UNKNOWN" if where == "Cost" else "MULTIPLIER_UNKNOWN"
        try:
            evidence = json.loads(
                (root / item.evidence_path).read_text(encoding="utf-8")
            )
            if where == "Cost":
                valid = (
                    evidence["commission_bps"] == item.commission_bps
                    and evidence["slippage_bps"] == item.slippage_bps
                )
            else:
                valid = (
                    math.isclose(
                        float(evidence["value"]),
                        float(item.value),
                        rel_tol=0,
                        abs_tol=0,
                    )
                    and evidence["unit"] == item.unit
                    and evidence["source_symbol"] == item.instrument_symbol
                )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            valid = False
        if not valid:
            return _blocked(
                code,
                f"{where} declaration does not match its evidence file.",
                item.model_dump(mode="json"),
                "missing or conflicting evidence fields",
                item.evidence_path,
                "Provide exact cost or instrument evidence before requesting a permit.",
            )
    return None


def preflight_run(
    root: str,
    intent: RunIntentV1 | dict[str, Any],
    computation: FeatureComputation,
    input_data: pl.DataFrame,
    contract: ResearchContractV1,
) -> GateReport:
    """Verify frozen identities and M3-B proof before issuing a research-only permit."""
    try:
        intent = RunIntentV1.model_validate(intent)
    except ValidationError as exc:
        fields = {".".join(map(str, error["loc"])) for error in exc.errors()}
        code = (
            "MULTIPLIER_UNKNOWN"
            if any(field.startswith("multiplier") for field in fields)
            else "AUDIT_RECIPE_MISSING"
            if any(field.startswith("independent_audit") for field in fields)
            else "COSTS_UNKNOWN"
            if any(field.startswith("costs") for field in fields)
            else "SOURCE_IDENTITY_CONFLICT"
            if any(field.startswith("expected_source") for field in fields)
            else "LIVE_ORDER_AUTHORITY_FORBIDDEN"
            if any(field.startswith("effects") for field in fields)
            else "BUDGET_EXCEEDED"
            if any(
                field.startswith(("budget", "requested_compute")) for field in fields
            )
            else "INVALID_PERMIT_REQUEST"
        )
        return _blocked(
            code,
            "Permit request failed strict validation.",
            "RunIntentV1",
            exc.errors(include_input=False),
            "permit request",
            "Correct the typed request before retrying.",
        )
    try:
        root_path = _root(root)
        _, frozen = _load(root_path, intent.session_id)
    except (ResearchSessionError, OSError, ValueError, TypeError, KeyError) as exc:
        return _blocked(
            "SESSION_IDENTITY_INVALID",
            "Frozen session could not be verified.",
            intent.session_id,
            str(exc),
            "run_log/research_sessions",
            "Repair or initialize the frozen session before requesting a permit.",
        )

    try:
        hashes = _identity_hashes(root_path, frozen)
    except (ResearchSessionError, OSError, ValueError, TypeError, KeyError) as exc:
        return _blocked(
            "IDENTITY_DRIFT",
            "A frozen identity could not be checked.",
            "all frozen file identities readable inside the workspace",
            str(exc),
            "frozen session identities",
            "Restore frozen inputs or initialize a new session.",
        )
    if isinstance(hashes, GateReport):
        return hashes

    if contract.session_id != intent.session_id:
        return _blocked(
            "SOURCE_IDENTITY_CONFLICT",
            "Feature contract belongs to another session.",
            intent.session_id,
            contract.session_id,
            "feature contract session_id",
            "Use the exact feature contract frozen by this session.",
        )
    try:
        verified = verify_feature_proof(computation, input_data, contract, root_path)
        verified = require_verified_feature_proof(verified)
    except FeatureContractError as exc:
        return _blocked(
            "FEATURE_PROOF_INVALID",
            "M3-B runtime feature verification failed.",
            "a runtime-issued proof for the frozen input and contract",
            exc.reason_code,
            "M3-B verify_feature_proof",
            "Recompute through FeatureGateway and verify against the frozen session.",
        )

    dataset = contract.dataset
    if (
        dataset.source_vendor != intent.expected_source_vendor
        or dataset.source_symbol != intent.expected_source_symbol
        or dataset.catalog_dataset_key != intent.expected_catalog_dataset_key
    ):
        return _blocked(
            "SOURCE_IDENTITY_CONFLICT",
            "Requested and frozen source identities differ.",
            {
                "vendor": intent.expected_source_vendor,
                "symbol": intent.expected_source_symbol,
                "catalog_key": intent.expected_catalog_dataset_key,
            },
            {
                "vendor": dataset.source_vendor,
                "symbol": dataset.source_symbol,
                "catalog_key": dataset.catalog_dataset_key,
            },
            "frozen ResearchContractV1.dataset",
            "Resolve the requested product in the catalog or register a separate explicit proxy.",
        )

    price_files = [item for item in frozen["spec"]["data"] if item["role"] == "prices"]
    if not price_files:
        return _blocked(
            "DATA_IDENTITY_MISSING",
            "Frozen session has no price data identity.",
            "one frozen prices dataset",
            [],
            "frozen session data",
            "Initialize a new session with its exact input data identity.",
        )
    try:
        frozen_data = pl.concat(
            [pl.read_parquet(_root(root_path) / item["path"]) for item in price_files],
            how="vertical",
        )
    except (OSError, pl.exceptions.PolarsError) as exc:
        return _blocked(
            "DATA_IDENTITY_DRIFT",
            "Frozen price data cannot be read.",
            [
                item
                for item in frozen["identity"]["data"]
                if item["path"] in {source["path"] for source in price_files}
            ],
            str(exc),
            price_files[0]["path"],
            "Restore a valid frozen dataset or initialize a new session.",
        )
    groups = contract.dataset.group_columns
    ordered_input = input_data.sort([*groups, "timestamp"])
    ordered_frozen = frozen_data.sort([*groups, "timestamp"])
    if not ordered_input.equals(ordered_frozen):
        return _blocked(
            "DATA_IDENTITY_DRIFT",
            "Feature proof input differs from frozen session data.",
            frozen["identity"]["data"][0]["sha256"],
            verified.proof.input_sha256,
            price_files[0]["path"],
            "Use the exact frozen data or initialize a new session.",
        )

    for item, label in (
        (intent.costs, "Cost"),
        (intent.multiplier, "Multiplier"),
        (intent.independent_audit, "Independent audit"),
    ):
        evidence_error = _verify_evidence(
            root_path, item, label, frozen["identity"]["evidence"]
        )
        if evidence_error:
            return evidence_error
    if intent.multiplier.instrument_symbol != intent.expected_source_symbol:
        return _blocked(
            "MULTIPLIER_UNKNOWN",
            "Multiplier evidence names another instrument.",
            intent.expected_source_symbol,
            intent.multiplier.instrument_symbol,
            "permit multiplier instrument_symbol",
            "Resolve the exact instrument multiplier.",
        )

    for name in ("max_wall_seconds", "max_cpu_seconds", "max_memory_mb", "max_trials"):
        if getattr(intent.requested_compute, name) > getattr(intent.budget, name):
            return _blocked(
                "BUDGET_EXCEEDED",
                "Requested compute exceeds the declared permit budget.",
                intent.budget.model_dump(mode="json"),
                intent.requested_compute.model_dump(mode="json"),
                "permit compute budget",
                "Reduce the requested compute or declare a bounded new trial.",
            )

    trial = next(
        (item for item in frozen["spec"]["trials"] if item["id"] == intent.trial_id),
        None,
    )
    if trial is None or trial["kind"] != "preregistered":
        return _blocked(
            "TRIAL_UNDECLARED",
            "Trial is not declared as preregistered.",
            "a preregistered trial in frozen spec",
            trial or "not declared",
            "frozen session trials",
            "Declare a new trial in a new frozen session before evaluation.",
        )

    evaluation = frozen["spec"]["evaluation"]
    try:
        dev_start = datetime.fromisoformat(evaluation["development_start"])
        dev_end = datetime.fromisoformat(evaluation["development_end"])
        holdout = (
            datetime.fromisoformat(evaluation["holdout_start"])
            if evaluation.get("holdout_start")
            else None
        )
    except (KeyError, TypeError, ValueError):
        dev_start = dev_end = holdout = None
    if holdout is not None and intent.evaluation_start >= holdout:
        return _blocked(
            "HOLDOUT_EXPOSED",
            "Evaluation overlaps the protected holdout.",
            f"end <= {holdout.isoformat()}",
            intent.evaluation_end.isoformat(),
            "frozen session evaluation.holdout_start",
            "Do not score this window; use development data or obtain separately authorized future data.",
        )
    if (
        dev_start is None
        or intent.evaluation_start < dev_start
        or intent.evaluation_end > dev_end
    ):
        return _blocked(
            "EVALUATION_WINDOW_INVALID",
            "Evaluation window is outside the frozen development interval.",
            [evaluation.get("development_start"), evaluation.get("development_end")],
            [intent.evaluation_start.isoformat(), intent.evaluation_end.isoformat()],
            "frozen session evaluation",
            "Use only the frozen development interval.",
        )

    costs = frozen["spec"]["costs"]
    if (
        intent.costs.commission_bps != costs["commission_bps"]
        or intent.costs.slippage_bps != costs["slippage_bps"]
    ):
        return _blocked(
            "COSTS_UNKNOWN",
            "Declared costs do not match the frozen session.",
            costs,
            intent.costs.model_dump(mode="json"),
            "frozen session costs",
            "Use the frozen costs or initialize a new session with sourced costs.",
        )

    frame = computation.data
    decision_utc = intent.decision_at.astimezone(UTC)
    available_values = (
        frame["available_at"].to_list() if "available_at" in frame.columns else []
    )
    eligible_availability = [
        value for value in available_values if value.astimezone(UTC) <= decision_utc
    ]
    available = max(eligible_availability) if eligible_availability else None
    if available is None:
        return _blocked(
            "FEATURE_CAUSALITY_FAIL",
            "Feature is unavailable at decision time.",
            f"available_at <= {intent.decision_at.isoformat()}",
            max(available_values).isoformat() if available_values else None,
            "M3-B output available_at",
            "Move the decision after feature availability.",
        )
    # A feature becoming available at the next clock is not proof of a real
    # executable bar at that clock. Require the frozen bar OPEN itself.
    timestamps = input_data["timestamp"].to_list()
    required_exit_utc = intent.required_exit_available_at.astimezone(UTC)
    if required_exit_utc not in [value.astimezone(UTC) for value in timestamps]:
        return _blocked(
            "DATA_SESSION_MISMATCH",
            "Required hard-flat bar is missing.",
            intent.required_exit_available_at.isoformat(),
            max(timestamps).isoformat() if timestamps else None,
            "frozen source bar open timestamps",
            "Provide the real executable exit bar or declare a new execution clock.",
        )

    versions = frozen["identity"].get("runner", [])
    repository_root = Path(__file__).resolve().parents[2]
    for identity in versions:
        if _identity(repository_root, identity["path"]) != identity:
            return _blocked(
                "IDENTITY_DRIFT",
                "Frozen session runner identity changed.",
                identity,
                _identity(repository_root, identity["path"]),
                "frozen runner source",
                "Freeze a new session against the reviewed runner.",
            )
    try:
        engine_version = importlib.metadata.version("ml4t-backtest")
    except importlib.metadata.PackageNotFoundError:
        return _blocked(
            "ENGINE_VERSION_UNKNOWN",
            "Native engine version is unavailable.",
            "installed ml4t-backtest version",
            None,
            "Python environment",
            "Install the locked project environment and retry.",
        )

    data_hash, frozen_source_hash, config_hash, current_source_hash = hashes
    proof_hash = hashlib.sha256(
        json.dumps(
            {
                "proof": verified.proof.__class__.__name__,
                "config": verified.proof.config_sha256,
                "contract": verified.proof.contract_sha256,
                "features": verified.proof.feature_set_sha256,
                "input": verified.proof.input_sha256,
                "output": verified.proof.output_sha256,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    if computation.data.height == 0:
        return _blocked(
            "DATA_EMPTY",
            "Verified feature output has no rows.",
            "nonempty verified output",
            0,
            "M3-B output",
            "Provide a nonempty synthetic or qualified dataset.",
        )

    source_hash = hashlib.sha256(
        json.dumps(
            contract.dataset.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    code_hash = hashlib.sha256(
        json.dumps(
            {
                "frozen_source_sha256": frozen_source_hash,
                "current_source_sha256": current_source_hash,
                "runner": versions,
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    identity = PermitIdentity(
        frozen_session_sha256=frozen["frozen_sha256"],
        spec_sha256=frozen["spec_sha256"],
        config_sha256=config_hash,
        data_sha256=data_hash,
        source_sha256=source_hash,
        code_sha256=code_hash,
        feature_proof_sha256=proof_hash,
        engine="ml4t.backtest",
        engine_version=engine_version,
        intent_sha256=hashlib.sha256(intent.model_dump_json().encode()).hexdigest(),
    )
    raw = {
        "schema_version": 1,
        "session_id": intent.session_id,
        "trial_id": intent.trial_id,
        "identity": identity.model_dump(mode="json"),
        "evaluation_start": intent.evaluation_start,
        "evaluation_end": intent.evaluation_end,
        "available_at": available,
        "costs": intent.costs.model_dump(mode="json"),
        "multiplier": intent.multiplier.model_dump(mode="json"),
        "exit_at": intent.exit_at,
        "effects": intent.effects,
        "compute_budget": intent.budget.model_dump(mode="json"),
        "independent_audit": intent.independent_audit.model_dump(mode="json"),
        "live_order_authority": False,
    }
    canonical = RunPermitV1.model_construct(
        **{
            **raw,
            "identity": identity,
            "costs": intent.costs,
            "multiplier": intent.multiplier,
            "compute_budget": intent.budget,
            "independent_audit": intent.independent_audit,
            "permit_sha256": "0" * 64,
        }
    )
    digest = _json_sha256(canonical.model_dump(mode="json", exclude={"permit_sha256"}))
    permit = RunPermitV1.model_validate({**raw, "permit_sha256": digest})
    return GateReport(
        status="PASS",
        reason_code="PERMIT_ISSUED",
        summary="Identity-bound research permit issued.",
        expected="verified frozen trial intent",
        observed="all preflight checks passed",
        where_found="frozen session, M3-B verifier, and permit request",
        next_safe_action="Run only the declared bounded research computation and independent audit.",
        permit=permit,
    )
