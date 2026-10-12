from __future__ import annotations

import hashlib
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl
import pytest
import yaml

from src.research_session import (
    ResearchSessionError,
    Spec,
    check_session,
    diagnose_trial,
    init_session,
    record_trial,
    report_session,
    session_status,
)


def prepare(root: Path) -> tuple[Path, Spec]:
    """Create a small real development dataset with a distinct excluded tail."""
    (root / "data").mkdir()
    timestamps = [datetime(2023, 1, 1, tzinfo=timezone.utc) + timedelta(days=i) for i in range(4)]
    closes = [100.0, 110.0, 121.0, 1000.0]
    pl.DataFrame({
        "timestamp": timestamps, "open": closes, "high": closes,
        "low": closes, "close": closes,
    }).write_parquet(root / "data/prices.parquet")
    spec: Spec = {
        "session_id": "thesis-01", "thesis": "Persistence survives a later fixed-rule test.",
        "mechanism": "Directional pressure.", "falsifier": "No development advantage.",
        "market": "crypto", "instruments": [{"symbol": "BTCUSDT", "kind": "spot"}],
        "data": [{"id": "prices", "path": "data/prices.parquet", "role": "prices"}],
        "evaluation": {
            "development_start": "2023-01-01T00:00:00Z",
            "development_end": "2023-01-04T00:00:00Z",
            "holdout_start": "2023-01-04T00:00:00Z",
        },
        "baseline": "Descriptive price returns, not a trading result.",
        "costs": {"commission_bps": 2, "slippage_bps": 1},
        "trials": [
            {"id": "fixed-rule", "kind": "preregistered", "description": "Later fixed rule."},
            {"id": "coverage", "kind": "diagnostic", "description": "Descriptive coverage."},
        ],
    }
    path = root / "spec.yaml"
    path.write_text(yaml.safe_dump(spec), encoding="utf-8")
    return path, spec


def write_spec(path: Path, spec: Spec) -> None:
    path.write_text(yaml.safe_dump(spec), encoding="utf-8")


def test_freeze_captures_source_config_data_and_dirty_state(tmp_path):
    path, spec = prepare(tmp_path)
    (tmp_path / "src").mkdir()
    source = tmp_path / "src/example.py"
    source.write_text("VALUE = 1\n")
    config = tmp_path / "config.yaml"
    config.write_text("cost: 2\n")
    spec["config"] = "config.yaml"
    write_spec(path, spec)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run([
        "git", "-c", "user.name=Session Test", "-c", "user.email=test@example.invalid",
        "commit", "-qm", "Fixture",
    ], cwd=tmp_path, check=True, capture_output=True)
    source.write_text("VALUE = 2\n")

    frozen = init_session(path, tmp_path)

    assert frozen["identity"]["git"]["dirty"] is True
    assert frozen["identity"]["source"][0]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    config_identity = frozen["identity"]["config"]
    assert config_identity is not None
    assert config_identity["sha256"] == hashlib.sha256(config.read_bytes()).hexdigest()
    assert frozen["identity"]["runner"][0]["path"] == "src/research_session.py"
    assert frozen["identity"]["runner"][0]["sha256"] == hashlib.sha256(
        Path(__file__).resolve().parents[1].joinpath("src/research_session.py").read_bytes()
    ).hexdigest()
    assert frozen["identity"]["data"][0]["exists"] is True
    assert frozen["classification"] == "EXPLORATORY"
    assert frozen["approval_status"] == "NOT_APPROVED"
    assert check_session("thesis-01", tmp_path)["status"] == "PASS"


@pytest.mark.parametrize("field", [
    "thesis", "mechanism", "falsifier", "market", "instruments", "data",
    "evaluation", "baseline", "costs", "trials",
])
def test_missing_required_fields_reject_without_creating_session(tmp_path, field):
    path, spec = prepare(tmp_path)
    del spec[field]
    write_spec(path, spec)

    with pytest.raises(ResearchSessionError):
        init_session(path, tmp_path)

    assert not (tmp_path / "run_log").exists()


@pytest.mark.parametrize("bad", ["../escape", "a/b", "/absolute", ".", "..", "space id", ""])
def test_unsafe_session_ids_reject_without_writes(tmp_path, bad):
    path, spec = prepare(tmp_path)
    spec["session_id"] = bad
    write_spec(path, spec)

    with pytest.raises(ResearchSessionError):
        init_session(path, tmp_path)

    assert not (tmp_path / "run_log").exists()


@pytest.mark.parametrize("target", ["session", "trial", "data"])
def test_duplicate_ids_reject(tmp_path, target):
    path, spec = prepare(tmp_path)
    if target == "session":
        path.write_text(path.read_text() + "session_id: other\n")
    elif target == "trial":
        spec["trials"].append(spec["trials"][0].copy())
        write_spec(path, spec)
    else:
        spec["data"].append(spec["data"][0].copy())
        write_spec(path, spec)

    with pytest.raises(ResearchSessionError):
        init_session(path, tmp_path)

    assert not (tmp_path / "run_log").exists()


@pytest.mark.parametrize("yaml_text", ["[not, a, mapping]", "thesis: [", "!!python/object/apply:os.system ['false']"])
def test_malformed_yaml_rejects(tmp_path, yaml_text):
    path = tmp_path / "spec.yaml"
    path.write_text(yaml_text)

    with pytest.raises(ResearchSessionError):
        init_session(path, tmp_path)

    assert not (tmp_path / "run_log").exists()


def test_missing_data_is_frozen_and_reported_without_metrics(tmp_path):
    path, _ = prepare(tmp_path)
    (tmp_path / "data/prices.parquet").unlink()
    init_session(path, tmp_path)

    check = check_session("thesis-01", tmp_path)

    assert check["status"] == "BLOCKED"
    assert check["data_audits"][0]["issues"] == ["missing_data"]
    assert check["metrics_computed"] is False


def test_changed_data_identity_blocks_audit(tmp_path):
    path, _ = prepare(tmp_path)
    init_session(path, tmp_path)
    dataset = tmp_path / "data/prices.parquet"
    pl.read_parquet(dataset).head(3).write_parquet(dataset)

    check = check_session("thesis-01", tmp_path)

    assert check["status"] == "BLOCKED"
    assert "data_identity_changed" in check["data_audits"][0]["issues"]


@pytest.mark.parametrize("funding_included", [None, True])
def test_perpetual_requires_funding_when_included_or_unspecified(tmp_path, funding_included):
    path, spec = prepare(tmp_path)
    spec["instruments"][0].update(kind="perpetual", venue="binance")
    if funding_included is not None:
        spec["costs"]["funding_included"] = funding_included
    write_spec(path, spec)
    init_session(path, tmp_path)

    check = check_session("thesis-01", tmp_path)

    assert check["status"] == "BLOCKED"
    assert "BTCUSDT:missing_perpetual_funding" in check["issues"]


def test_perpetual_without_funding_is_allowed_when_excluded_from_costs(tmp_path):
    path, spec = prepare(tmp_path)
    spec["instruments"][0].update(kind="perpetual", venue="binance")
    spec["costs"]["funding_included"] = False
    write_spec(path, spec)
    init_session(path, tmp_path)

    check = check_session("thesis-01", tmp_path)

    assert check["status"] == "PASS"
    assert check["data_audits"][0]["issues"] == []



def test_perpetual_audits_actual_funding_dataset(tmp_path):
    path, spec = prepare(tmp_path)
    spec["instruments"][0].update(kind="perpetual", venue="binance")
    spec["data"].append({"id": "funding", "path": "data/funding.parquet", "role": "funding"})
    timestamps = pl.read_parquet(tmp_path / "data/prices.parquet")["timestamp"]
    pl.DataFrame({"timestamp": timestamps, "funding_rate": [0.001] * 4}).write_parquet(
        tmp_path / "data/funding.parquet"
    )
    write_spec(path, spec)
    init_session(path, tmp_path)

    check = check_session("thesis-01", tmp_path)

    assert check["status"] == "PASS"
    assert len(check["data_audits"]) == 2


def test_indices_require_instrument_identity_and_local_session(tmp_path):
    path, spec = prepare(tmp_path)
    spec["market"] = "indices"
    spec["instruments"] = [{"symbol": "NAS100", "kind": "cfd"}]
    write_spec(path, spec)
    init_session(path, tmp_path)

    check = check_session("thesis-01", tmp_path)

    assert check["status"] == "BLOCKED"
    assert set(check["issues"]) == {"NAS100:missing_identity", "NAS100:missing_session", "NAS100:missing_timezone"}


def test_index_identity_session_timezone_allow_audit(tmp_path):
    path, spec = prepare(tmp_path)
    spec["market"] = "indices"
    spec["instruments"] = [{
        "symbol": "NAS100", "kind": "cfd", "identity": "Vendor NAS100 cash CFD",
        "session": "XNYS regular", "timezone": "America/New_York",
    }]
    write_spec(path, spec)
    init_session(path, tmp_path)

    check = check_session("thesis-01", tmp_path)

    assert check["status"] == "PASS"
    assert check["approval_status"] == "NOT_APPROVED"


@pytest.mark.parametrize("boundary", ["data_symlink", "output_symlink", "traversal", "outside"])
def test_safe_filesystem_boundaries(tmp_path, boundary):
    root = tmp_path / "root"
    root.mkdir()
    path, spec = prepare(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    if boundary == "data_symlink":
        (root / "data/link.parquet").symlink_to(root / "data/prices.parquet")
        spec["data"][0]["path"] = "data/link.parquet"
    elif boundary == "output_symlink":
        (root / "run_log").symlink_to(outside, target_is_directory=True)
    elif boundary == "traversal":
        spec["data"][0]["path"] = "data/../data/prices.parquet"
    else:
        spec["data"][0]["path"] = str(outside / "prices.parquet")
    write_spec(path, spec)

    with pytest.raises(ResearchSessionError):
        init_session(path, root)

    assert list(outside.iterdir()) == []


def test_init_rerun_preserves_frozen_bytes(tmp_path):
    path, _ = prepare(tmp_path)
    init_session(path, tmp_path)
    frozen_path = tmp_path / "run_log/research_sessions/thesis-01/frozen_spec.json"
    before = frozen_path.read_bytes()

    with pytest.raises(ResearchSessionError):
        init_session(path, tmp_path)

    assert frozen_path.read_bytes() == before


def test_terminal_failed_record_and_pending_trial_are_preserved(tmp_path):
    path, _ = prepare(tmp_path)
    init_session(path, tmp_path)
    artifact = tmp_path / "failure.txt"
    artifact.write_text("An existing runner failed before producing metrics.\n")
    record_trial("thesis-01", "fixed-rule", "failed", artifact, tmp_path)

    report = report_session("thesis-01", tmp_path)

    assert [item["status"] for item in report["trials"]] == ["failed", "pending"]
    record = report["trials"][0]["record"]
    assert record is not None
    assert record["artifact_generation_verified"] is False
    assert record["artifact"]["sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert report["approval_status"] == "NOT_APPROVED"
    assert report["metrics_computed"] is False


def test_duplicate_terminal_record_never_replaces_failure(tmp_path):
    path, _ = prepare(tmp_path)
    init_session(path, tmp_path)
    artifact = tmp_path / "failure.txt"
    artifact.write_text("Failure")
    record_trial("thesis-01", "fixed-rule", "failed", artifact, tmp_path)
    terminal = tmp_path / "run_log/research_sessions/thesis-01/trials/fixed-rule.json"
    before = terminal.read_bytes()

    with pytest.raises(ResearchSessionError):
        record_trial("thesis-01", "fixed-rule", "completed", artifact, tmp_path)

    assert terminal.read_bytes() == before


def test_completed_unmanaged_trial_remains_unverified(tmp_path):
    path, _ = prepare(tmp_path)
    init_session(path, tmp_path)
    artifact = tmp_path / "backtest-result.json"
    artifact.write_text('{"status":"completed"}\n')

    record = record_trial("thesis-01", "fixed-rule", "completed", artifact, tmp_path)

    assert record["status"] == "completed"
    assert record["artifact_generation_verified"] is False


@pytest.mark.parametrize("trial", ["undeclared", "../escape", "a/b"])
def test_invalid_trial_record_rejects(tmp_path, trial):
    path, _ = prepare(tmp_path)
    init_session(path, tmp_path)
    artifact = tmp_path / "result.json"
    artifact.write_text("{}")

    with pytest.raises(ResearchSessionError):
        record_trial("thesis-01", trial, "completed", artifact, tmp_path)

    assert list((tmp_path / "run_log/research_sessions/thesis-01/trials").iterdir()) == []


def test_historical_review_is_frozen_and_not_preregistered(tmp_path):
    path, spec = prepare(tmp_path)
    artifact = tmp_path / "old.json"
    artifact.write_text('{"status":"APPROVED","sharpe":99}')
    spec["trials"].append({
        "id": "old-study", "kind": "historical_review", "description": "Historical review only.",
        "artifact": "old.json",
    })
    write_spec(path, spec)
    init_session(path, tmp_path)
    record_trial("thesis-01", "old-study", "completed", artifact, tmp_path)

    report = report_session("thesis-01", tmp_path)

    record = report["trials"][-1]["record"]
    assert record is not None
    assert record["kind"] == "historical_review"
    assert report["evidence"][0]["approval_status"] == "NOT_APPROVED"
    assert "sharpe" not in report


def test_concurrent_records_have_exactly_one_terminal_winner(tmp_path):
    path, _ = prepare(tmp_path)
    init_session(path, tmp_path)
    artifact = tmp_path / "result.json"
    artifact.write_text("{}")

    def attempt() -> str:
        try:
            record_trial("thesis-01", "fixed-rule", "completed", artifact, tmp_path)
            return "created"
        except ResearchSessionError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))

    assert sorted(results) == ["created", "rejected"]
    assert report_session("thesis-01", tmp_path)["trials"][0]["status"] == "completed"


def test_diagnose_executes_development_only_descriptive_returns(tmp_path):
    path, _ = prepare(tmp_path)
    init_session(path, tmp_path)

    result = diagnose_trial("thesis-01", "coverage", tmp_path)

    diagnostic = result["diagnostic"]
    summary = diagnostic["summaries"][0]
    assert result["status"] == "completed"
    assert summary["rows"] == 3
    assert summary["cumulative_price_return"] == pytest.approx(0.21)
    assert summary["mean_bar_return"] == pytest.approx(0.1)
    assert diagnostic["holdout_scored"] is False
    assert diagnostic["strategy_evidence"] is False
    artifact = tmp_path / result["artifact"]["path"]
    assert result["artifact"]["sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()


def test_diagnose_missing_data_preserves_failed_attempt(tmp_path):
    path, _ = prepare(tmp_path)
    (tmp_path / "data/prices.parquet").unlink()
    init_session(path, tmp_path)

    result = diagnose_trial("thesis-01", "coverage", tmp_path)

    assert result["status"] == "failed"
    assert result["diagnostic"]["summaries"] == []
    assert report_session("thesis-01", tmp_path)["trials"][1]["status"] == "failed"


def test_diagnose_rerun_preserves_artifact_and_record(tmp_path):
    path, _ = prepare(tmp_path)
    init_session(path, tmp_path)
    result = diagnose_trial("thesis-01", "coverage", tmp_path)
    artifact = tmp_path / result["artifact"]["path"]
    before = artifact.read_bytes()

    with pytest.raises(ResearchSessionError):
        diagnose_trial("thesis-01", "coverage", tmp_path)

    assert artifact.read_bytes() == before


def test_diagnose_rejects_holdout_overlap_before_execution(tmp_path):
    path, spec = prepare(tmp_path)
    spec["evaluation"]["development_end"] = "2023-01-05T00:00:00Z"
    write_spec(path, spec)
    with pytest.raises(ResearchSessionError):
        init_session(path, tmp_path)

    assert not (tmp_path / "run_log").exists()


@pytest.mark.parametrize("kind", ["perpetul", "PERPETUAL", "unknown"])
def test_unknown_instrument_kind_rejects_at_freeze(tmp_path, kind):
    path, spec = prepare(tmp_path)
    spec["instruments"][0]["kind"] = kind
    write_spec(path, spec)

    with pytest.raises(ResearchSessionError):
        init_session(path, tmp_path)

    assert not (tmp_path / "run_log").exists()


def test_diagnostic_requires_development_bounds_at_freeze(tmp_path):
    path, spec = prepare(tmp_path)
    spec["evaluation"] = {"method": "chronological"}
    write_spec(path, spec)

    with pytest.raises(ResearchSessionError):
        init_session(path, tmp_path)

    assert not (tmp_path / "run_log").exists()


def test_session_status_reads_trial_records_without_running_data_audit(
    tmp_path, monkeypatch
):
    import src.research_session as session_module

    path, _ = prepare(tmp_path)
    init_session(path, tmp_path)
    monkeypatch.setattr(
        session_module,
        "check_session",
        lambda *_: pytest.fail("lightweight status must not run a data audit"),
    )

    result = session_status("thesis-01", tmp_path)

    assert result["status"] == "STATUS"
    assert result["data_audit_performed"] is False
    assert [trial["status"] for trial in result["trials"]] == ["pending", "pending"]
