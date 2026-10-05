from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from src.labeling import ORBTradeEvent
from src.models import train_meta_classifier_cpcv
from src.validation import ValidationContractError
from src.validated_orb_pipeline import (
    FinalOOSGuard,
    RunnerContractError,
    ValidatedORBRunner,
    audit_manifest,
    build_canonical_events,
    compute_performance_report,
    select_development_threshold,
    split_development_and_final_oos,
)

UTC = timezone.utc


def make_event(decision: datetime, *, exit_minutes: int = 10, label: int = 1) -> ORBTradeEvent:
    entry = decision + timedelta(minutes=5)
    exit_time = entry + timedelta(minutes=exit_minutes)
    return ORBTradeEvent(
        entry_time=entry.isoformat(), exit_time=exit_time.isoformat(),
        decision_time=decision.isoformat(), session_name="cash", date=str(decision.date()),
        symbol="DE30/EUR", direction=1, entry_price=100.0,
        exit_price=101.0 if label else 99.0, or_high=101.0, or_low=99.0,
        or_range=2.0, atr20=1.0, delta=2.0, upper_barrier=106.0,
        lower_barrier=98.0, holding_bars=2,
        exit_reason="profit_target" if label else "stop_loss", label=label,
        realized_return=0.01 if label else -0.01, r_multiple=1.0 if label else -1.0,
        features={"rvol_1h": float(label + 1)},
    )


def write_market_file(path: Path, start: datetime, rows: int = 8) -> dict[str, object]:
    ts = [start + timedelta(minutes=5 * i) for i in range(rows)]
    frame = pl.DataFrame({
        "symbol": ["DE30_EUR"] * rows,
        "timestamp": ts,
        "open": [100.0] * rows,
        "high": [101.0] * rows,
        "low": [99.0] * rows,
        "close": [100.5] * rows,
        "volume": [10] * rows,
    }).with_columns(pl.col("timestamp").dt.replace_time_zone("UTC"))
    frame.write_parquet(path)
    close_sum = frame["close"].sum()
    fingerprint_payload = "\n".join(value.isoformat() for value in frame["timestamp"].to_list())
    fingerprint_payload += f"\n{close_sum!r}"
    return {
        "file": path.name,
        "symbol": "DE30_EUR",
        "row_count": rows,
        "bar_duration_seconds": 300,
        "bar_open_assumption": "LSE candle timestamp = bar OPEN (start of interval)",
        "source_timezone": "UTC",
        "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "content_fingerprint": hashlib.sha256(fingerprint_payload.encode()).hexdigest(),
        "schema": {name: str(dtype) for name, dtype in frame.schema.items()},
        "min_timestamp": ts[0].isoformat(),
        "max_timestamp": ts[-1].isoformat(),
        "duplicate_rows": 0,
        "is_sorted": True,
        "null_counts": {name: 0 for name in frame.columns},
        "dev_rows": rows,
        "oos_rows": 0,
    }


def test_preflight_audits_only_in_scope_files_and_preserves_external_warning(tmp_path: Path):
    market = tmp_path / "DE30_EUR_5m_2017_2026.parquet"
    entry = write_market_file(market, datetime(2026, 7, 1, tzinfo=UTC))
    manifest = {
        "vendor_semantics": {"bar_open_assumption": "bar OPEN", "timezone_rule": "UTC"},
        "data_quality_warnings": ["BTCUSD has a gap"],
        "data_quality_warning_details": [{"file": "BTCUSD.parquet", "strategy_scope": "out_of_scope"}],
        "files": [entry],
    }
    manifest_path = tmp_path / "_manifest.json"
    manifest_path.write_text(json.dumps(manifest))

    result = audit_manifest(
        manifest_path,
        required_files={market.name},
        boundary=datetime(2026, 8, 1, tzinfo=UTC),
        expected_timestamp_semantics={"status": "verified", "convention": "open", "timezone": "UTC"},
    )

    assert result["data_code_readiness"] == "READY"
    assert result["blocking_reasons"] == []
    assert result["nonblocking_warnings"] == ["BTCUSD has a gap"]
    assert result["files"][0]["sha256_verified"] is True


def test_manifest_readback_detects_hash_and_ohlc_failures(tmp_path: Path):
    market = tmp_path / "DE30_EUR_5m_2017_2026.parquet"
    entry = write_market_file(market, datetime(2026, 7, 1, tzinfo=UTC))
    frame = pl.read_parquet(market).with_columns(pl.lit(98.0).alias("high"))
    frame.write_parquet(market)
    manifest_path = tmp_path / "_manifest.json"
    manifest_path.write_text(json.dumps({
        "vendor_semantics": {"bar_open_assumption": "bar OPEN", "timezone_rule": "UTC"},
        "files": [entry],
    }))

    result = audit_manifest(
        manifest_path, {market.name}, datetime(2026, 8, 1, tzinfo=UTC),
        expected_timestamp_semantics={"status": "verified", "convention": "open", "timezone": "UTC"},
    )
    assert result["data_code_readiness"] == "BLOCKED"
    assert any("sha256" in reason for reason in result["blocking_reasons"])
    assert any("ohlc" in reason for reason in result["blocking_reasons"])


def test_split_censors_development_labels_reaching_boundary():
    boundary = datetime(2026, 8, 1, tzinfo=UTC)
    events = [
        make_event(boundary - timedelta(hours=2)),
        make_event(boundary - timedelta(minutes=10), exit_minutes=10),
        make_event(boundary + timedelta(minutes=5)),
    ]
    split = split_development_and_final_oos(events, boundary)
    assert len(split.development) == 1
    assert len(split.censored) == 1
    assert len(split.final_oos) == 1


def test_threshold_selection_records_every_candidate_and_uses_deterministic_tie_break():
    scores = np.array([0.1, 0.4, 0.6, 0.9])
    returns = np.array([-0.01, 0.02, -0.01, 0.03])
    result = select_development_threshold(
        scores, returns, candidates=[0.3, 0.5, 0.8], minimum_selection_count=1
    )
    assert len(result.trials) == 3
    assert result.threshold == 0.8
    assert result.objective == "mean_net_return"
    assert result.tie_break == "higher_threshold_then_more_selections"


def test_final_oos_guard_is_repository_global_across_run_ids(tmp_path: Path):
    registry = tmp_path / "run_log" / "validated" / "_final_oos_claims"
    guard = FinalOOSGuard(registry, "validated-orb-de30-jp225", datetime(2026, 8, 1, tzinfo=UTC))
    claim = guard.claim({"run_id": "run-a", "frozen_hash": "abc", "data_provenance": []})
    assert claim.exists()
    with pytest.raises(RunnerContractError, match="already claimed"):
        FinalOOSGuard(
            registry, "validated-orb-de30-jp225", datetime(2026, 8, 1, tzinfo=UTC)
        ).claim({"run_id": "run-b", "frozen_hash": "retuned", "data_provenance": []})
    assert not guard.completion_path.exists()


def test_manifest_missing_or_mismatched_metadata_blocks(tmp_path: Path):
    market = tmp_path / "DE30_EUR_5m_2017_2026.parquet"
    entry = write_market_file(market, datetime(2026, 7, 1, tzinfo=UTC))
    del entry["content_fingerprint"]
    entry["min_timestamp"] = "2020-01-01T00:00:00+00:00"
    manifest_path = tmp_path / "_manifest.json"
    manifest_path.write_text(json.dumps({
        "vendor_semantics": {"bar_open_assumption": "bar OPEN", "timezone_rule": "UTC"},
        "files": [entry],
    }))
    result = audit_manifest(
        manifest_path, {market.name}, datetime(2026, 8, 1, tzinfo=UTC),
        expected_timestamp_semantics={"status": "verified", "convention": "open", "timezone": "UTC"},
    )
    assert result["data_code_readiness"] == "BLOCKED"
    assert "manifest_field_missing_DE30_EUR_5m_2017_2026.parquet_content_fingerprint" in result["blocking_reasons"]
    assert "manifest_min_timestamp_mismatch_DE30_EUR_5m_2017_2026.parquet" in result["blocking_reasons"]


@pytest.mark.parametrize("semantics", [
    {"status": "unknown", "convention": "open", "timezone": "UTC"},
    {"status": "verified", "convention": "close", "timezone": "UTC"},
])
def test_timestamp_semantics_unknown_or_mismatched_block(tmp_path: Path, semantics: dict[str, str]):
    market = tmp_path / "DE30_EUR_5m_2017_2026.parquet"
    entry = write_market_file(market, datetime(2026, 7, 1, tzinfo=UTC))
    manifest_path = tmp_path / "_manifest.json"
    manifest_path.write_text(json.dumps({
        "vendor_semantics": {"bar_open_assumption": "bar OPEN", "timezone_rule": "UTC"},
        "files": [entry],
    }))
    result = audit_manifest(
        manifest_path, {market.name}, datetime(2026, 8, 1, tzinfo=UTC),
        expected_timestamp_semantics=semantics,
    )
    assert result["data_code_readiness"] == "BLOCKED"
    assert any("timestamp_semantics" in reason for reason in result["blocking_reasons"])


def test_unmatched_manifest_warning_blocks(tmp_path: Path):
    market = tmp_path / "DE30_EUR_5m_2017_2026.parquet"
    entry = write_market_file(market, datetime(2026, 7, 1, tzinfo=UTC))
    manifest_path = tmp_path / "_manifest.json"
    manifest_path.write_text(json.dumps({
        "vendor_semantics": {"bar_open_assumption": "bar OPEN", "timezone_rule": "UTC"},
        "data_quality_warnings": ["unstructured warning"],
        "data_quality_warning_details": [],
        "files": [entry],
    }))
    result = audit_manifest(
        manifest_path, {market.name}, datetime(2026, 8, 1, tzinfo=UTC),
        expected_timestamp_semantics={"status": "verified", "convention": "open", "timezone": "UTC"},
    )
    assert "unmatched_data_quality_warnings" in result["blocking_reasons"]


def test_truncated_manifest_blocks_without_reading_data(tmp_path: Path):
    manifest_path = tmp_path / "_manifest.json"
    manifest_path.write_text('{"files": [')
    result = audit_manifest(
        manifest_path, {"missing.parquet"}, datetime(2026, 8, 1, tzinfo=UTC),
        expected_timestamp_semantics={"status": "verified", "convention": "open", "timezone": "UTC"},
    )
    assert result["data_code_readiness"] == "BLOCKED"
    assert result["blocking_reasons"] == ["manifest_invalid"]


def test_performance_report_separates_costs_daily_returns_years_and_stress():
    events = [
        make_event(datetime(2024, 1, 2, tzinfo=UTC), label=1),
        make_event(datetime(2025, 1, 2, tzinfo=UTC), label=0),
        make_event(datetime(2025, 1, 3, tzinfo=UTC), label=1),
    ]
    report = compute_performance_report(
        events, selected=np.array([True, True, True]), roundtrip_cost_bps=6.0,
        bootstrap_block_lengths=[1, 2, 3], bootstrap_samples=20, random_state=7,
    )
    assert report["trade_count"] == 3
    assert report["costs"]["roundtrip_bps"] == 6.0
    assert set(report["annual_breakdown"]) == {"2024", "2025"}
    assert len(report["daily_returns"]) > 3
    assert sum(item["return"] != 0.0 for item in report["daily_returns"]) == 3
    assert [x["block_length"] for x in report["bootstrap_stress"]] == [1, 2, 3]
    assert report["dsr_status"] == "DSR_UNREPRODUCIBLE"
    assert report["verdict"] == "NOT_APPROVED"


def test_temporal_cpcv_reports_every_fold_and_fails_closed_on_insufficient_fold():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    events = [make_event(start + timedelta(hours=i), label=i % 2) for i in range(20)]
    with pytest.raises(ValidationContractError, match="CPCV fold"):
        train_meta_classifier_cpcv(
            events,
            feature_cols=["rvol_1h"],
            n_groups=4,
            n_test_groups=1,
            require_temporal_contract=True,
        )


def test_temporal_cpcv_returns_diagnostics_for_every_combination():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    events = [make_event(start + timedelta(hours=i), label=i % 2) for i in range(80)]
    result = train_meta_classifier_cpcv(
        events,
        feature_cols=["rvol_1h"],
        n_groups=4,
        n_test_groups=1,
        require_temporal_contract=True,
    )
    assert len(result.fold_diagnostics) == 4
    assert all(fold["status"] == "FIT" for fold in result.fold_diagnostics)


def test_runner_requires_exact_versioned_output_and_refuses_overwrite(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    config = root / "config.yaml"
    manifest = root / "manifest.json"
    config.write_text("{}")
    manifest.write_text("{}")
    with pytest.raises(RunnerContractError, match="exactly"):
        ValidatedORBRunner(
            root=root,
            config_path=config,
            manifest_path=manifest,
            run_id="run-1",
            output_dir=root / "elsewhere",
        )
    runner = ValidatedORBRunner(
        root=root, config_path=config, manifest_path=manifest, run_id="run-1"
    )
    runner.reserve_output()
    with pytest.raises(RunnerContractError, match="overwrite refused"):
        runner.reserve_output()


def test_canonical_runner_source_never_calls_legacy_session_hours():
    source = (Path(__file__).parents[1] / "src" / "validated_orb_pipeline.py").read_text()
    assert "session_hours=" not in source
    assert "extract_events_and_labels(" in source


def test_canonical_event_builder_uses_session_and_bar_specs(tmp_path: Path):
    start = datetime(2026, 1, 15, 6, tzinfo=UTC)
    rows = []
    for index in range(60):
        timestamp = start + timedelta(minutes=5 * index)
        open_, high, low, close = 100.0, 100.1, 99.9, 100.0
        if datetime(2026, 1, 15, 7, 55, tzinfo=UTC) <= timestamp <= datetime(2026, 1, 15, 8, 50, tzinfo=UTC):
            high, low = 101.0, 99.0
        if timestamp == datetime(2026, 1, 15, 8, 55, tzinfo=UTC):
            open_, high, low, close = 101.8, 102.2, 101.7, 102.0
        elif timestamp >= datetime(2026, 1, 15, 9, tzinfo=UTC):
            open_, high, low, close = 102.0, 102.4, 101.8, 102.2
        rows.append({
            "symbol": "DE30_EUR", "timestamp": timestamp, "open": open_,
            "high": high, "low": low, "close": close, "volume": 1000,
        })
    market = tmp_path / "DE30_EUR_5m_2017_2026.parquet"
    pl.DataFrame(rows).write_parquet(market)
    manifest = tmp_path / "_manifest.json"
    manifest.write_text(json.dumps({"files": [{
        "file": market.name, "bar_duration_seconds": 300, "source_timezone": "UTC",
        "bar_open_assumption": "bar OPEN",
    }]}))
    config = {
        "universe": {"symbols": ["DE30/EUR"]},
        "sessions": {"DE30_cash_open": {
            "timezone": "Europe/Berlin", "local_open": "09:00",
            "opening_range": "1h", "candidate_window": "90m",
        }},
        "execution": {"roundtrip_friction_bps": 6.0},
    }
    events = build_canonical_events(
        config, manifest, datetime(2027, 1, 1, tzinfo=UTC), include_final_oos=True,
        validated_files={market.name: {
            "bar_duration_seconds": 300, "source_timezone": "UTC", "timestamp_convention": "open"
        }},
    )
    assert len(events) == 1
    assert events[0].session_name == "DE30_cash_open"
    assert events[0].decision_time == "2026-01-15T09:00:00+00:00"
    assert "spx_alignment" not in events[0].features or events[0].features["spx_alignment"] == 0.0


def _runner_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "repo"
    data = root / "data" / "processed"
    config_dir = root / "config"
    data.mkdir(parents=True)
    config_dir.mkdir()
    entries = []
    for name in ("DE30_EUR_5m_2017_2026.parquet", "JP225_USD_5m_2017_2026.parquet"):
        entries.append(write_market_file(data / name, datetime(2026, 7, 1, tzinfo=UTC), rows=12))
    manifest = data / "_manifest.json"
    manifest.write_text(json.dumps({
        "vendor_semantics": {"bar_open_assumption": "bar OPEN", "timezone_rule": "UTC"},
        "data_quality_warnings": [], "data_quality_warning_details": [], "files": entries,
    }))
    config = config_dir / "setup.yaml"
    config.write_text("""
universe: {symbols: [DE30/EUR, JP225/USD]}
validation:
  final_oos_start: '2026-08-01T00:00:00Z'
  development_end: '2026-07-31T23:59:59Z'
  cpcv: {n_groups: 4, n_test_groups: 1, embargo_duration: 1d}
data_contracts:
  timestamp_semantics: {status: verified, convention: open, timezone: UTC}
execution: {roundtrip_friction_bps: 6.0}
sessions: {}
""")
    status = root / "run_log" / "validation_status.json"
    status.parent.mkdir(parents=True)
    status.write_text(json.dumps({"status": "NOT_APPROVED", "blocking_gates": ["DSR_UNREPRODUCIBLE"]}))
    return root, config, manifest


class _PredictableModel:
    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return np.column_stack((np.full(len(X), 0.2), np.full(len(X), 0.8)))


def _model_result(count: int, *, passed: bool = True) -> SimpleNamespace:
    diagnostics = [
        {"fold": i, "status": "FIT", "auc": value, "train_count": 40, "test_count": 20}
        for i, value in enumerate((0.55, 0.60, 0.65, 0.70))
    ]
    return SimpleNamespace(
        model=_PredictableModel(), oof_scores=np.linspace(0.35, 0.85, count),
        oof_coverage=np.ones(count, dtype=int), passed_quality_gate=passed,
        mean_auc=0.625, std_auc=0.0559, min_auc=0.55, max_auc=0.70,
        fold_diagnostics=diagnostics,
    )


def _development_events() -> list[ORBTradeEvent]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [make_event(start + timedelta(hours=6 * i), label=i % 2) for i in range(60)]


def test_runner_development_lifecycle_writes_gate_ledger_audit_and_commit(tmp_path: Path, monkeypatch):
    root, config, manifest = _runner_repo(tmp_path)
    events = _development_events()
    monkeypatch.setattr("src.validated_orb_pipeline.build_canonical_events", lambda *a, **k: events)
    monkeypatch.setattr("src.validated_orb_pipeline.train_meta_classifier_cpcv", lambda *a, **k: _model_result(len(events)))
    runner = ValidatedORBRunner(root=root, config_path=config, manifest_path=manifest, run_id="dev-ok")
    result = runner.run(evaluate_final_oos=False, append_trial=True)
    output = root / "run_log" / "validated" / "dev-ok"
    assert result["final_oos_status"] == "FINAL_OOS_NOT_OPENED"
    assert json.loads((output / "development_gate.json").read_text())["passed"] is True
    evidence = json.loads((output / "development_evidence.json").read_text())
    assert evidence["auc_distribution"] == pytest.approx({"mean": .625, "std": .0559, "min": .55, "max": .70})
    assert evidence["failed_fold_count"] == 0
    assert evidence["oof_coverage"]["complete"] is True
    assert (output / "config.snapshot.yaml").read_text() == config.read_text()
    assert json.loads((output / "ledger_status.json").read_text())["status"] == "DURABLE"
    assert (output / "run.commit.json").exists()
    assert result["verdict"] == "NOT_APPROVED"


def test_development_gate_failure_blocks_final_oos_without_global_claim(tmp_path: Path, monkeypatch):
    root, config, manifest = _runner_repo(tmp_path)
    events = _development_events()
    monkeypatch.setattr("src.validated_orb_pipeline.build_canonical_events", lambda *a, **k: events)
    monkeypatch.setattr("src.validated_orb_pipeline.train_meta_classifier_cpcv", lambda *a, **k: _model_result(len(events), passed=False))
    runner = ValidatedORBRunner(root=root, config_path=config, manifest_path=manifest, run_id="gate-fail")
    result = runner.run(evaluate_final_oos=True, append_trial=True)
    assert result["verdict"] == "BLOCKED"
    assert not (root / "run_log" / "validated" / "_final_oos_claims").exists()
    assert json.loads((runner.output_dir / "development_gate.json").read_text())["passed"] is False


def test_runner_global_claim_blocks_second_run_id(tmp_path: Path, monkeypatch):
    root, config, manifest = _runner_repo(tmp_path)
    development = _development_events()
    final = [make_event(datetime(2026, 8, 2, tzinfo=UTC))]
    monkeypatch.setattr(
        "src.validated_orb_pipeline.build_canonical_events",
        lambda *a, **k: development + final if k["include_final_oos"] else development,
    )
    monkeypatch.setattr("src.validated_orb_pipeline.train_meta_classifier_cpcv", lambda events, **k: _model_result(len(events)))
    first = ValidatedORBRunner(root=root, config_path=config, manifest_path=manifest, run_id="oos-a")
    assert first.run(evaluate_final_oos=True, append_trial=True)["final_oos_status"] == "FINAL_OOS_COMPLETE"
    second = ValidatedORBRunner(root=root, config_path=config, manifest_path=manifest, run_id="oos-b")
    with pytest.raises(RunnerContractError, match="already claimed"):
        second.run(evaluate_final_oos=True, append_trial=True)


def test_resume_final_oos_uses_committed_development_without_refitting(tmp_path: Path, monkeypatch):
    root, config, manifest = _runner_repo(tmp_path)
    development = _development_events()
    final = [make_event(datetime(2026, 8, 2, tzinfo=UTC))]
    monkeypatch.setattr(
        "src.validated_orb_pipeline.build_canonical_events",
        lambda *a, **k: development + final if k["include_final_oos"] else development,
    )
    monkeypatch.setattr(
        "src.validated_orb_pipeline.train_meta_classifier_cpcv",
        lambda events, **k: _model_result(len(events)),
    )
    runner = ValidatedORBRunner(root=root, config_path=config, manifest_path=manifest, run_id="resume-oos")
    runner.run(evaluate_final_oos=False, append_trial=True)
    monkeypatch.setattr(
        "src.validated_orb_pipeline.train_meta_classifier_cpcv",
        lambda *a, **k: pytest.fail("resume must not refit the development model"),
    )

    result = runner.resume_final_oos()

    output = root / "run_log" / "validated" / "resume-oos"
    assert result["final_oos_status"] == "FINAL_OOS_COMPLETE"
    assert result["final_oos_metrics"]["trade_count"] == 1
    assert (output / "final_oos_scores.parquet").exists()
    assert (output / "final_oos_metrics.json").exists()
    receipt = json.loads((output / "final_oos_resume.json").read_text())
    assert receipt["development_commit_sha256"]
    assert json.loads((root / "run_log" / "validated" / "_final_oos_claims").glob("*.complete.json").__next__().read_text())["status"] == "FINAL_OOS_COMPLETE"


def test_ledger_append_failure_leaves_run_incomplete_without_commit(tmp_path: Path, monkeypatch):
    root, config, manifest = _runner_repo(tmp_path)
    events = _development_events()
    monkeypatch.setattr("src.validated_orb_pipeline.build_canonical_events", lambda *a, **k: events)
    monkeypatch.setattr("src.validated_orb_pipeline.train_meta_classifier_cpcv", lambda *a, **k: _model_result(len(events)))
    runner = ValidatedORBRunner(root=root, config_path=config, manifest_path=manifest, run_id="ledger-fail")
    monkeypatch.setattr(runner, "_append_trial", lambda result: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        runner.run(evaluate_final_oos=False, append_trial=True)
    assert json.loads((runner.output_dir / "ledger_status.json").read_text())["status"] == "FAILED"
    assert json.loads((runner.output_dir / "result.json").read_text())["run_completion"] == "INCOMPLETE"
    assert not (runner.output_dir / "run.commit.json").exists()
