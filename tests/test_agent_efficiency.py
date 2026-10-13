"""M7-B fixed positive/adversarial research-agent regression corpus.

No protected holdout, live trading, external provider or production artifact writes.
"""

import numpy as np
import pytest
import talib
from ml4t.backtest import run_backtest
from pydantic import ValidationError

from src.research_control.attempts import AttemptLedger
from src.research_control.casefile import (
    build_casefile,
    explain_blocker,
    inspect_resume,
)
from src.research_control.contracts import ResearchContractV1
from src.research_control.dukascopy_migration import dukascopy_feature_contract
from src.research_control.efficiency import measure_operator_case
from src.research_control.execution import (
    StopFirstBracket,
    independent_fill_audit,
)
from src.research_control.feature_gateway import (
    FeatureGateway,
    _adx_reference,
)
from src.research_control.run_permit import preflight_run
from src.research_session import ResearchSessionError, record_trial
from tests.test_native_execution import (
    UnsafeNativeBracket,
    config,
    synthetic_both_hit,
)
from tests.test_research_control import bars, contract, native
from tests.test_run_permit import gate, intent, setup_trial


# Positive: installed native registry and exact source/cause provider proof.
def test_positive_native_adx():
    result = FeatureGateway().compute(bars(), contract([native()]))
    assert result.proof.checks["native_execution_through_engineer"]
    assert result.data["adx_14"].is_not_null().sum() > 0


# Positive: approved reusable extension, not spoofed native VWAP.
def test_positive_approved_vwap_extension():
    request = contract(
        [
            {
                "id": "session_vwap",
                "provider": {
                    "kind": "extension.approved",
                    "extension_id": "cash_open_vwap",
                    "version": "1.0.0",
                    "session_open": "08:30",
                    "timezone": "America/Chicago",
                },
                "inputs": {
                    "high": "high",
                    "low": "low",
                    "close": "close",
                    "volume": "volume",
                },
            }
        ]
    )
    data = FeatureGateway().compute(bars(), request)
    assert data.proof.checks["completed_bar_availability"]
    assert data.data["session_vwap"].is_not_null().sum() > 0


# Positive: verified native execution, stop-first, sibling OCO and cash.
def test_positive_native_execution_and_audit():
    sample = synthetic_both_hit()
    strategy = StopFirstBracket(
        "SYN",
        signal_at=sample["timestamp"][1],
        quantity=1,
        stop_price=95,
        limit_price=110,
    )
    simulation = run_backtest(sample, strategy, config=config())
    audit = independent_fill_audit(simulation, strategy, sample, initial_cash=1000)
    assert audit.status == "PASS"
    assert audit.live_execution_qualified is False


# Positive: repeatable recovery returns same running attempt without more files.
def test_positive_recovery_idempotency_and_duplicate_job_prevention(tmp_path):
    sample, contract_obj, computation, evidence = setup_trial(tmp_path)
    permit = gate(tmp_path, sample, contract_obj, computation, evidence)
    jobs = [set()]
    ledger = AttemptLedger(
        tmp_path, permit.permit.session_id, list_jobs=lambda: jobs[0]
    )
    first = ledger.claim(permit, job_name="ml4t-corpus", command="native")
    assert first.status == "LAUNCH"
    blocked = [
        ledger.claim(permit, job_name="ml4t-corpus", command="native") for _ in range(5)
    ]
    assert len(blocked) == 5 and all(v.status == "BLOCKED" for v in blocked)
    assert len(ledger.latest()) == 1  # 5 duplicate attempts prevented
    ledger.transition(first.attempt_id, "RUNNING")
    jobs[0] = {"ml4t-corpus"}
    assert (
        ledger.claim(permit, job_name="ml4t-corpus", command="native").status
        == "RESUME"
    )
    for _ in range(3):
        result = inspect_resume(
            tmp_path,
            permit.permit.session_id,
            first.attempt_id,
            list_jobs=lambda: jobs[0],
        )
        assert result["status"] == "RUNNING"
    assert len(ledger.latest()) == 1


# Adversarial: vendor NQ.F cannot impersonate Dukascopy CFD.
def test_adversarial_lse_nq_source_alias_rejected():
    payload = dukascopy_feature_contract("corpus").model_dump(mode="json")
    payload["dataset"]["source_symbol"] = "NQ.F"
    payload["dataset"]["catalog_dataset_key"] = "lse_futures_minute_NQ"
    with pytest.raises(ValidationError, match="not Dukascopy"):
        ResearchContractV1.model_validate(payload)


# Adversarial: t decision cannot use t+1 feature availability.
def test_adversarial_future_feature_rejected(tmp_path):
    data, request, computation, evidence = setup_trial(tmp_path)
    payload = intent(data, evidence)
    payload["decision_at"] = data["timestamp"][0].isoformat()
    result = preflight_run(str(tmp_path), payload, computation, data, request)
    assert result.status == "BLOCKED"
    assert result.reason_code == "FEATURE_CAUSALITY_FAIL"


# Adversarial: falsely claiming native VWAP should fail schema.
def test_adversarial_false_native_vwap_rejected():
    payload = contract([native()]).model_dump(mode="json")
    payload["feature_set"][0]["provider"] = {
        "kind": "engineer.native",
        "name": "vwap",
        "params": {},
    }
    with pytest.raises(ValidationError, match="FEATURE_UNSUPPORTED"):
        ResearchContractV1.model_validate(payload)


# Adversarial: missing frozen session must fail casefile.
def test_adversarial_missing_session_not_ready(tmp_path):
    with pytest.raises((ResearchSessionError, ValueError, OSError)):
        build_casefile(tmp_path, "nonexistent", list_jobs=lambda: set())


# Adversarial: known native default OCO chooses take profit on dual-hit.
def test_adversarial_unsafe_limit_first_engine_fill_rejected():
    sample = synthetic_both_hit()
    strategy = UnsafeNativeBracket(
        "SYN",
        signal_at=sample["timestamp"][1],
        quantity=1,
        stop_price=95,
        limit_price=110,
    )
    simulation = run_backtest(sample, strategy, config=config())
    assert (
        independent_fill_audit(
            simulation, strategy, sample, initial_cash=1000
        ).reason_code
        == "ENGINE_EXECUTION_INVALID"
    )


# Adversarial: fake agent done/worker-PASS has no evidentiary authority.
def test_adversarial_fake_worker_done_rejected():
    assert (
        explain_blocker(
            {
                "status": "PASS",
                "reason_code": "WORKER_DONE",
                "observed": "trust me, success",
            }
        )["reason_code"]
        == "ASSERTED_SUCCESS_NOT_EVIDENCE"
    )


# Real failure regression: earlier ADX oracle warmed Wilder DM/TR one bar too late.
def test_regression_wilder_initialization_matches_independent_talib():
    rng = np.random.default_rng(11)
    base = 100 + np.cumsum(rng.normal(0, 0.6, 100))
    high = base + rng.uniform(0.1, 0.8, 100)
    low = base - rng.uniform(0.1, 0.8, 100)
    close = base
    verified = np.array(_adx_reference(high.tolist(), low.tolist(), close.tolist(), 14))
    independent = talib.ADX(high, low, close, timeperiod=14)
    assert np.isnan(verified[:27]).all()
    assert np.max(np.abs(verified[27:] - independent[27:])) < 1e-8
    assert np.isfinite(verified[27])


# Measured baseline and managed answers must match. Instrument forbidden raw reads.
def test_benchmark_frozen_source_and_attempt_answer_parity(tmp_path):
    data, request, computation, evidence = setup_trial(tmp_path)
    permit = gate(tmp_path, data, request, computation, evidence)
    jobs = lambda: set()
    attempt = AttemptLedger(tmp_path, request.session_id, list_jobs=jobs).claim(
        permit, job_name="ml4t-benchmark", command="native"
    )
    assert attempt.status == "LAUNCH"

    report = measure_operator_case(
        tmp_path, request.session_id, samples=3, list_jobs=jobs
    )
    assert report["baseline"]["answer_complete"]
    assert report["managed"]["answer_complete"]
    assert report["baseline"]["tool_calls"] == 2
    assert report["managed"]["tool_calls"] == 1
    assert report["redundant_market_data_reads_measured"] == 0
    assert report["attempt_identity_count"] == 1
    assert report["attempt_identities"][0]["attempt_id"] == attempt.attempt_id
    assert report["attempt_identities"][0]["status"] == "PLANNED"
    assert report["source_identity"]["spec_sha256"]
    assert report["native_feature_count"] == 1
    assert report["approved_extension_count"] == 5
    assert report["no_live_trading"] is True


def test_casefile_evidence_ref_uses_terminal_record_envelope(tmp_path):
    setup_trial(tmp_path)
    artifact = tmp_path / "result.json"
    artifact.write_text('{"result": "recorded"}', encoding="utf-8")
    record_trial("permit-synthetic", "synthetic-trial", "completed", artifact, tmp_path)

    view = build_casefile(tmp_path, "permit-synthetic", list_jobs=lambda: set())

    assert "result.json" in view["evidence_refs"]
