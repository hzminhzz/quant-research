"""Synthetic managed DAG executes native engine under frozen authority."""

import json
import subprocess
import sys
from pathlib import Path

from src.pipeline import CaseStudyPipelineReport, ManagedResearchPipeline, StageContract
from src.strategies.base import StrategyPlugin
from src.strategies.synthetic_bracket import SyntheticBracket
from src.synthesis import compute_dsr_audit
from tests.test_run_permit import intent, setup_trial


def test_registry_and_no_stage_count_approval(tmp_path):
    runner = ManagedResearchPipeline(tmp_path)
    plan = runner.plan("synthetic_bracket_v1")
    assert plan["status"] == "READY"
    assert "ml4t.backtest" in plan["capabilities"]
    assert isinstance(SyntheticBracket(), StrategyPlugin)
    assert runner.plan("unregistered")["status"] == "BLOCKED"
    stage = StageContract(1, "legacy", [], [], True)
    assert not CaseStudyPipelineReport("SYN", "1m", *([stage] * 7)).is_production_ready


def test_legacy_single_trial_cannot_manufacture_dsr():
    assert compute_dsr_audit(3.0, [3.0])["dsr_probability"] is None
    assert compute_dsr_audit(3.0, [3.0, 1.0, -0.1])["status"] == "INCONCLUSIVE"


def test_governed_synthetic_run_and_duplicate_block(tmp_path):
    bars, _, _, evidence = setup_trial(tmp_path)
    runner = ManagedResearchPipeline(tmp_path)
    request = intent(bars, evidence)
    result = runner.run_synthetic(
        session_id="permit-synthetic", trial_id="synthetic-trial",
        intent=request, job_name="ml4t-synthetic-rebuild")
    assert result["status"] == "PASS", result
    assert result["audit"]["trade_count"] == 1
    assert result["live_order_authority"] is False
    duplicate = runner.run_synthetic(
        session_id="permit-synthetic", trial_id="synthetic-trial",
        intent=request, job_name="ml4t-synthetic-rebuild")
    assert duplicate["status"] == "BLOCKED"
    assert duplicate["reason_code"] == "EVIDENCE_REUSABLE"


def test_refuses_wrong_trial_and_real_product(tmp_path, monkeypatch):
    bars, _, _, evidence = setup_trial(tmp_path, cfd=True)
    runner = ManagedResearchPipeline(tmp_path)
    request = intent(bars, evidence, source_vendor="Dukascopy",
                     source_symbol="USATECH.IDX/USD")

    def forbidden_data_load(*args, **kwargs):
        raise AssertionError("unsupported source data was read before rejection")

    monkeypatch.setattr("src.pipeline.pl.read_parquet", forbidden_data_load)
    assert runner.run_synthetic(session_id="permit-synthetic", trial_id="wrong",
                                intent=request, job_name="synthetic-rebuild")["reason_code"] == "TRIAL_IDENTITY_MISMATCH"
    assert runner.run_synthetic(session_id="permit-synthetic", trial_id="synthetic-trial",
                                intent=request, job_name="synthetic-rebuild")["reason_code"] == "REAL_MARKET_RUN_UNSUPPORTED"


def test_cli_executes_frozen_synthetic_path(tmp_path):
    bars, _, _, evidence = setup_trial(tmp_path)
    (tmp_path / "intent.json").write_text(json.dumps(intent(bars, evidence)), encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "scripts/research.py"
    run = subprocess.run(
        [sys.executable, str(script), "run-synthetic", "--root", str(tmp_path),
         "--session", "permit-synthetic", "--trial", "synthetic-trial",
         "--intent", "intent.json", "--job-name", "ml4t-synthetic-cli"],
        capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stderr + run.stdout
    assert json.loads(run.stdout)["audit"]["trade_count"] == 1
