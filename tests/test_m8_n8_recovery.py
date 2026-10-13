"""Adversarial recovery tests for complete, permit-bound native artifacts."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import polars as pl
import pytest

from scripts.run_m8_n8 import _restore_completed_artifact


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _permit():
    return SimpleNamespace(
        permit_sha256="a" * 64,
        session_id="m8_n8_dukascopy_nas100_cfd_30m_v1",
        trial_id="N8_primary_3cost_stress",
        identity=SimpleNamespace(
            model_dump=lambda mode: {
                "frozen_session_sha256": "b" * 64,
                "spec_sha256": "c" * 64,
                "config_sha256": "d" * 64,
                "data_sha256": "e" * 64,
                "source_sha256": "f" * 64,
                "code_sha256": "0" * 64,
                "feature_proof_sha256": "1" * 64,
                "engine": "ml4t.backtest",
                "engine_version": "0.1.7",
                "intent_sha256": "2" * 64,
            }
        ),
    )


def _artifact(root, *, audit_status="PASS", parquet=True):
    permit = _permit()
    scenarios = []
    files = {}
    for name in ("1x", "2x", "3x"):
        fills_path, equity_path = root / f"fills_{name}.parquet", root / f"equity_{name}.parquet"
        if parquet:
            pl.DataFrame(
                {"timestamp": [1], "side": ["buy"], "quantity": [1.0], "price": [10.0], "commission": [0.01]}
            ).write_parquet(fills_path)
            pl.DataFrame({"timestamp": [1], "equity": [100.0]}).write_parquet(equity_path)
        else:
            fills_path.write_bytes(b"native-fill-artifact")
            pl.DataFrame({"timestamp": [1], "equity": [100.0]}).write_parquet(equity_path)
        files[fills_path.name] = _sha(fills_path)
        files[equity_path.name] = _sha(equity_path)
        scenarios.append(
            {
                "scenario": name,
                "audit": {"status": audit_status, "fill_count": 1, "cash_position_ledger_rows": 1},
                "metrics": {},
            }
        )
    report = {
        "status": "COMPLETED",
        "attempt_id": "attempt-1",
        "permit_sha256": permit.permit_sha256,
        "session_id": permit.session_id,
        "trial_id": permit.trial_id,
        "identity": permit.identity.model_dump(mode="json"),
        "scenarios": ["1x", "2x", "3x"],
        "cost_scenarios": scenarios,
        "trade_count": 4,
    }
    report_path = root / "report.json"
    report_path.write_text(json.dumps(report))
    files["report.json"] = _sha(report_path)
    manifest = {
        "schema_version": 1,
        "attempt_id": "attempt-1",
        "permit_sha256": permit.permit_sha256,
        "session_id": permit.session_id,
        "trial_id": permit.trial_id,
        "identity": permit.identity.model_dump(mode="json"),
        "scenarios": ["1x", "2x", "3x"],
        "files": files,
    }
    (root / "manifest.json").write_text(json.dumps(manifest))
    return permit, report


def _native_replay(root, report):
    return {
        item["scenario"]: {
            "fills": pl.read_parquet(root / f"fills_{item['scenario']}.parquet"),
            "equity": pl.read_parquet(root / f"equity_{item['scenario']}.parquet"),
            "audit": item["audit"],
        }
        for item in report["cost_scenarios"]
    }


def test_m8_n8_recovery_reuses_real_complete_permit_bound_artifacts(tmp_path):
    permit, report = _artifact(tmp_path)
    assert _restore_completed_artifact(tmp_path, attempt_id="attempt-1", permit=permit, native_replay=_native_replay(tmp_path, report))["trade_count"] == 4


@pytest.mark.parametrize(
    "field,value",
    [
        ("attempt_id", "attempt-other"),
        ("permit_sha256", "9" * 64),
        ("source_sha256", "8" * 64),
    ],
)
def test_m8_n8_recovery_rejects_wrong_attempt_permit_or_source(tmp_path, field, value):
    permit, report = _artifact(tmp_path)
    replay = _native_replay(tmp_path, report)
    with pytest.raises(RuntimeError, match="ARTIFACT_IDENTITY_DRIFT"):
        if field == "attempt_id":
            _restore_completed_artifact(tmp_path, attempt_id=value, permit=permit, native_replay=replay)
        elif field == "permit_sha256":
            altered = SimpleNamespace(**{**permit.__dict__, "permit_sha256": value})
            _restore_completed_artifact(tmp_path, attempt_id="attempt-1", permit=altered, native_replay=replay)
        else:
            identity = permit.identity.model_dump(mode="json")
            identity[field] = value
            altered = SimpleNamespace(**{
                **permit.__dict__,
                "identity": SimpleNamespace(model_dump=lambda mode: identity),
            })
            _restore_completed_artifact(tmp_path, attempt_id="attempt-1", permit=altered, native_replay=replay)


def test_m8_n8_recovery_rejects_hash_consistent_fake_parquet(tmp_path):
    permit, _ = _artifact(tmp_path, parquet=False)
    with pytest.raises(RuntimeError, match="ARTIFACT_PARQUET_INVALID"):
        _restore_completed_artifact(tmp_path, attempt_id="attempt-1", permit=permit, native_replay={})


def test_m8_n8_recovery_rejects_partial_artifact(tmp_path):
    permit, _ = _artifact(tmp_path)
    (tmp_path / "equity_3x.parquet").unlink()
    with pytest.raises(RuntimeError, match="ARTIFACT_PARTIAL"):
        _restore_completed_artifact(tmp_path, attempt_id="attempt-1", permit=permit, native_replay={})


def test_m8_n8_recovery_rejects_truncated_parquet_and_bad_audit(tmp_path):
    permit, _ = _artifact(tmp_path)
    path = tmp_path / "fills_1x.parquet"
    path.write_bytes(b"PAR1")
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["files"][path.name] = _sha(path)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError, match="ARTIFACT_PARQUET_INVALID"):
        _restore_completed_artifact(tmp_path, attempt_id="attempt-1", permit=permit, native_replay={})

    permit, _ = _artifact(tmp_path, audit_status="FAILED")
    with pytest.raises(RuntimeError, match="ARTIFACT_AUDIT_INVALID"):
        _restore_completed_artifact(tmp_path, attempt_id="attempt-1", permit=permit, native_replay={})


def test_m8_n8_recovery_rejects_tampered_content_even_when_complete(tmp_path):
    permit, report = _artifact(tmp_path)
    replay = _native_replay(tmp_path, report)
    with (tmp_path / "fills_1x.parquet").open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(RuntimeError, match="ARTIFACT_IDENTITY_DRIFT"):
        _restore_completed_artifact(tmp_path, attempt_id="attempt-1", permit=permit, native_replay=replay)


def test_m8_n8_recovery_rejects_rehashed_altered_fills(tmp_path):
    permit, report = _artifact(tmp_path)
    replay = _native_replay(tmp_path, report)
    path = tmp_path / "fills_1x.parquet"
    pl.read_parquet(path).with_columns(pl.lit(99.0).alias("price")).write_parquet(path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["files"][path.name] = _sha(path)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError, match="ARTIFACT_NATIVE_REPLAY_MISMATCH"):
        _restore_completed_artifact(tmp_path, attempt_id="attempt-1", permit=permit, native_replay=replay)


def test_m8_n8_recovery_rejects_duplicate_cost_scenario(tmp_path):
    permit, report = _artifact(tmp_path)
    report["cost_scenarios"][2]["scenario"] = "2x"
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["files"][path.name] = _sha(path)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError, match="ARTIFACT_PARTIAL"):
        _restore_completed_artifact(tmp_path, attempt_id="attempt-1", permit=permit, native_replay={})


def test_m8_n8_recovery_rejects_missing_cost_scenario(tmp_path):
    permit, report = _artifact(tmp_path)
    report["cost_scenarios"] = report["cost_scenarios"][:2]
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["files"][path.name] = _sha(path)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError, match="ARTIFACT_PARTIAL"):
        _restore_completed_artifact(tmp_path, attempt_id="attempt-1", permit=permit, native_replay={})


def test_m8_n8_recovery_requires_independent_native_replay(tmp_path):
    permit, _ = _artifact(tmp_path)
    with pytest.raises(RuntimeError, match="ARTIFACT_NATIVE_REPLAY_REQUIRED"):
        _restore_completed_artifact(tmp_path, attempt_id="attempt-1", permit=permit)


def test_m8_n8_recovery_rejects_missing_audit(tmp_path):
    permit, report = _artifact(tmp_path)
    del report["cost_scenarios"][0]["audit"]
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["files"][path.name] = _sha(path)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError, match="ARTIFACT_AUDIT_INVALID"):
        _restore_completed_artifact(tmp_path, attempt_id="attempt-1", permit=permit, native_replay={})
