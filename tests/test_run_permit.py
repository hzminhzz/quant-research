from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest
import yaml
from pydantic import ValidationError

from src.research_control.contracts import ResearchContractV1
from src.research_control.feature_gateway import FeatureComputation, FeatureGateway
from src.research_control.run_permit import RunPermitV1, preflight_run
from src.research_session import init_session


def setup_trial(root, *, holdout=False, count=85, cfd=False):
    root.mkdir(parents=True, exist_ok=True)
    (root / "src").mkdir()
    (root / "src/strategy.py").write_text("RULE_VERSION = 1\n", encoding="utf-8")
    rows = []
    start = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    for i in range(count):
        close = 100.0 + i * 0.1
        rows.append(
            {
                "timestamp": start + timedelta(minutes=i),
                "symbol": "USATECH.IDX/USD" if cfd else "SYN",
                "open": close,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close + 0.1,
                "volume": float(100 + i),
            }
        )
    data = pl.DataFrame(rows)
    data.write_parquet(root / "bars.parquet")
    contract = ResearchContractV1.model_validate(
        {
            "schema_version": 1,
            "session_id": "permit-synthetic",
            "dataset": {
                "requested_product": "Dukascopy USATECH.IDX/USD CFD price proxy"
                if cfd
                else "Synthetic research fixture",
                "source_vendor": "Dukascopy" if cfd else "Synthetic",
                "source_symbol": "USATECH.IDX/USD" if cfd else "SYN",
                "catalog_dataset_key": None,
                "external_exception_id": "synthetic-cfd-fixture"
                if cfd
                else "synthetic-fixture",
                "authority": "staged_noncanonical",
                "product_class": "cfd" if cfd else "spot",
                "role": "price_proxy",
                "volume_semantics": "broker_tick_or_quote_proxy" if cfd else "unknown",
                "timeframe": "1m",
                "timestamp_convention": "bar_start",
                "timezone": "America/Chicago" if cfd else "UTC",
                "group_columns": ["symbol"],
            },
            "feature_set": [
                {
                    "id": "typical_price",
                    "provider": {
                        "kind": "engineer.native",
                        "name": "typprice",
                        "params": {},
                    },
                    "inputs": {"high": "high", "low": "low", "close": "close"},
                }
            ],
            "strategy": {"rule_id": "synthetic-rule", "engine": "ml4t.backtest"},
            "evaluation": {"development": ["2026-01-05", "2026-01-06"]},
        }
    )
    contract_path = root / "feature-contract.yaml"
    contract_path.write_text(
        yaml.safe_dump(contract.model_dump(mode="json")), encoding="utf-8"
    )
    evidence = {}
    for name, contents in (
        ("costs.json", '{"commission_bps": 0, "slippage_bps": 0}'),
        (
            "multiplier.json",
            (
                '{"value": 1.0, "unit": "synthetic unit", "source_symbol": "USATECH.IDX/USD"}'
                if cfd
                else '{"value": 1.0, "unit": "synthetic unit", "source_symbol": "SYN"}'
            ),
        ),
        ("audit.py", "independent synthetic audit"),
    ):
        path = root / name
        path.write_text(contents, encoding="utf-8")
        evidence[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    spec = {
        "session_id": contract.session_id,
        "thesis": "Synthetic permit acceptance fixture.",
        "mechanism": "No market claim; verify permit identities.",
        "falsifier": "Any identity or gate mismatch blocks permit issuance.",
        "market": "indices" if cfd else "crypto",
        "instruments": (
            [
                {
                    "symbol": "USATECH.IDX/USD",
                    "kind": "cfd",
                    "identity": "Synthetic Dukascopy CFD fixture",
                    "session": "weekday fixture",
                    "timezone": "America/Chicago",
                }
            ]
            if cfd
            else [{"symbol": "SYN", "kind": "spot"}]
        ),
        "data": [{"id": "synthetic", "path": "bars.parquet", "role": "prices"}],
        "evaluation": {
            "development_start": "2026-01-05T00:00:00Z",
            "development_end": "2026-01-06T00:00:00Z",
        },
        "baseline": "No strategy result.",
        "costs": {"commission_bps": 0, "slippage_bps": 0},
        "trials": [
            {
                "id": "synthetic-trial",
                "kind": "preregistered",
                "description": "Data-free synthetic gate test.",
            }
        ],
        "config": "feature-contract.yaml",
        "evidence": list(evidence),
    }
    if holdout:
        spec["evaluation"]["development_end"] = "2026-01-05T15:50:00Z"
        spec["evaluation"]["holdout_start"] = "2026-01-05T15:50:00Z"
    (root / "session.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    init_session(root / "session.yaml", root)
    computation = FeatureGateway().compute(data, contract)

    return data, contract, computation, evidence


def intent(
    data, evidence, *, source_vendor="Synthetic", source_symbol="SYN", **changes
):
    last_available = data["timestamp"][-1] + timedelta(minutes=1)
    last_executable_open = data["timestamp"][-1]
    payload = {
        "schema_version": 1,
        "session_id": "permit-synthetic",
        "trial_id": "synthetic-trial",
        "evaluation_start": "2026-01-05T14:30:00Z",
        "evaluation_end": last_available.isoformat(),
        "decision_at": last_executable_open.isoformat(),
        "exit_at": last_executable_open.isoformat(),
        "required_exit_available_at": last_executable_open.isoformat(),
        "expected_source_vendor": source_vendor,
        "expected_source_symbol": source_symbol,
        "expected_catalog_dataset_key": None,
        "costs": {
            "commission_bps": 0,
            "slippage_bps": 0,
            "source": "synthetic",
            "evidence_path": "costs.json",
            "source_sha256": evidence["costs.json"],
        },
        "multiplier": {
            "value": 1.0,
            "unit": "synthetic unit",
            "instrument_symbol": source_symbol,
            "source": "synthetic",
            "evidence_path": "multiplier.json",
            "source_sha256": evidence["multiplier.json"],
        },
        "effects": ["READ_ONLY", "EVIDENCE_APPEND"],
        "budget": {
            "max_wall_seconds": 60,
            "max_cpu_seconds": 60,
            "max_memory_mb": 512,
            "max_trials": 1,
        },
        "requested_compute": {
            "max_wall_seconds": 10,
            "max_cpu_seconds": 10,
            "max_memory_mb": 128,
            "max_trials": 1,
        },
        "independent_audit": {
            "method": "separate source arithmetic",
            "implementation": "audit.py",
            "version": "1",
            "source_sha256": evidence["audit.py"],
            "evidence_path": "audit.py",
            "checks": ["source rows", "availability"],
        },
    }
    payload.update(changes)
    return payload


def gate(root, data, contract, computation, evidence, **changes):
    return preflight_run(
        str(root),
        intent(
            data,
            evidence,
            source_vendor=contract.dataset.source_vendor,
            source_symbol=contract.dataset.source_symbol,
            **changes,
        ),
        computation,
        data,
        contract,
    )


def test_synthetic_frozen_trial_issues_identity_bound_research_only_permit(tmp_path):
    data, contract, computation, evidence = setup_trial(tmp_path)
    result = gate(tmp_path, data, contract, computation, evidence)
    assert result.status == "PASS"
    assert result.reason_code == "PERMIT_ISSUED"
    assert result.permit.identity.feature_proof_sha256
    assert result.permit.identity.data_sha256
    assert result.permit.identity.source_sha256
    assert result.permit.identity.code_sha256
    assert result.permit.identity.engine_version == "0.1.7"
    assert result.permit.live_order_authority is False
    assert result.permit.effects == ["READ_ONLY", "EVIDENCE_APPEND"]
    with pytest.raises(ValidationError, match="permit_sha256"):
        RunPermitV1.model_validate(
            result.permit.model_dump(mode="json") | {"trial_id": "changed"}
        )


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("missing_exit", "DATA_SESSION_MISMATCH"),
        ("source_alias", "SOURCE_IDENTITY_CONFLICT"),
        ("unknown_multiplier", "MULTIPLIER_UNKNOWN"),
        ("undeclared_trial", "TRIAL_UNDECLARED"),
        ("holdout", "HOLDOUT_EXPOSED"),
        ("stale_data", "IDENTITY_DRIFT"),
        ("stale_code", "IDENTITY_DRIFT"),
        ("new_code", "IDENTITY_DRIFT"),
        ("budget", "BUDGET_EXCEEDED"),
        ("audit", "AUDIT_RECIPE_MISSING"),
        ("stale_evidence", "IDENTITY_DRIFT"),
        ("live_order", "LIVE_ORDER_AUTHORITY_FORBIDDEN"),
    ],
)
def test_preflight_fails_closed_with_stable_reason_codes(tmp_path, case, reason):
    data, contract, computation, evidence = setup_trial(
        tmp_path, holdout=case == "holdout", count=80, cfd=case == "missing_exit"
    )
    changes = {}
    if case == "missing_exit":
        changes["evaluation_end"] = "2026-01-05T15:55:00Z"
        changes["required_exit_available_at"] = "2026-01-05T15:55:00Z"
        changes["exit_at"] = "2026-01-05T15:55:00Z"
    elif case == "source_alias":
        changes["expected_source_symbol"] = "NQ.F"
    elif case == "unknown_multiplier":
        changes["multiplier"] = {
            "value": 0,
            "unit": "",
            "source": "",
            "evidence_path": "",
            "source_sha256": "0" * 64,
        }
    elif case == "undeclared_trial":
        changes["trial_id"] = "not-registered"
    elif case == "holdout":
        changes["evaluation_start"] = "2026-01-05T15:50:00Z"
        changes["evaluation_end"] = "2026-01-05T15:55:00Z"
        changes["exit_at"] = "2026-01-05T15:55:00Z"
        changes["required_exit_available_at"] = "2026-01-05T15:55:00Z"
        changes["decision_at"] = "2026-01-05T15:55:00Z"
    elif case == "budget":
        changes["requested_compute"] = {
            "max_wall_seconds": 61,
            "max_cpu_seconds": 10,
            "max_memory_mb": 128,
            "max_trials": 1,
        }
    elif case == "audit":
        changes["independent_audit"] = {}
    elif case == "live_order":
        changes["effects"] = ["LIVE_ORDER"]
    elif case == "stale_evidence":
        (tmp_path / "costs.json").write_text("changed", encoding="utf-8")
    elif case == "stale_data":
        data.write_parquet(tmp_path / "bars.parquet")
        (tmp_path / "bars.parquet").write_bytes(b"changed")
    elif case == "stale_code":
        (tmp_path / "src/strategy.py").write_text(
            "RULE_VERSION = 2\n", encoding="utf-8"
        )
    elif case == "new_code":
        (tmp_path / "src/new_strategy.py").write_text(
            "RULE_VERSION = 2\n", encoding="utf-8"
        )

    result = gate(tmp_path, data, contract, computation, evidence, **changes)
    assert result.status == "BLOCKED"
    assert result.reason_code == reason
    assert result.expected is not None
    assert result.observed is not None
    assert result.where_found
    assert result.next_safe_action


def test_runtime_signed_feature_proof_is_required_and_forgery_blocks(tmp_path):
    data, contract, computation, evidence = setup_trial(tmp_path)
    assert gate(tmp_path, data, contract, computation, evidence).status == "PASS"
    forged = FeatureComputation(
        data, replace(computation.proof, output_sha256="0" * 64)
    )
    result = gate(tmp_path, data, contract, forged, evidence)
    assert result.status == "BLOCKED"
    assert result.reason_code == "FEATURE_PROOF_INVALID"
    assert result.observed == "FEATURE_PROOF_FORGED"


def test_m2_source_contract_rejects_lse_nq_alias_for_dukascopy(tmp_path):
    _, contract, _, _ = setup_trial(tmp_path)
    raw = contract.model_dump(mode="python")
    raw["dataset"].update(
        requested_product="Dukascopy USATECH.IDX/USD CFD price proxy",
        source_vendor="Dukascopy",
        source_symbol="NQ.F",
        catalog_dataset_key="lse_futures_minute_NQ",
        authority="secondary",
        product_class="cfd",
    )
    with pytest.raises(ValidationError, match="not Dukascopy"):
        ResearchContractV1.model_validate(raw)
