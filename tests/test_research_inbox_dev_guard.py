"""Positive Stage 3 synthetic safety test: protected Stage 4 must remain unreachable."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.data_vault import DataVault, PanelBuilder
from src.engine.common import QuantError
from src.engine.funnel import ResearchFunnel
from src.engine.spec_parser import CandidateSpec, export_spec
from tests.dual_mode_fixtures import make_panel
from tests.dual_mode_fixtures import test_spec as synthetic_spec
from tests.test_dual_mode_funnel import positive_fixture


def test_native_stage3_pass_dev_only_never_claims_or_reads_protected(tmp_path, monkeypatch):
    from src.oracle import stage3_falsifier

    def synthetic_dsr(candidate, others, periods_per_year, *, historical_trial_count=0):
        return {"status": "COMPUTED", "probability": 1.0,
                "has_adequate_sample": True, "scope": "synthetic-only-stub",
                "n_trials_aligned": 10, "n_trials_raw": 10,
                "n_trials_effective": 10.0}

    def forbidden(*args, **kwargs):
        pytest.fail("development-only factory must never invoke protected claim or data read")

    monkeypatch.setattr(stage3_falsifier, "scoped_dsr", synthetic_dsr)
    monkeypatch.setattr(DataVault, "unlock_holdout", forbidden)
    monkeypatch.setattr(DataVault, "load_holdout", forbidden)
    spec = positive_fixture(tmp_path)
    run_log = tmp_path / "logs"
    result = ResearchFunnel(run_log=run_log, isolate=False).run(spec, development_only=True)
    assert result["status"] == "DEVELOPMENT_QUALIFIED", result
    assert result["development_only"] is True
    assert result["holdout_access"] is False
    assert "4" not in result["stages"]
    assert [result["stages"][str(i)]["status"] for i in (1, 2, 3)] == ["PASS"] * 3
    assert not (run_log / "_holdout_claims").exists()
    assert not (run_log / "_holdout_exposures").exists()
    assert (Path(result["output_path"]) / "stage3.json").is_file()
    # A stage3 PASS is development research evidence, not an approval for deployment.
    assert "deployment" not in result
    records = (run_log / "trial_ledger.jsonl").read_text()
    assert "DEVELOPMENT_QUALIFIED" in records


def test_quant_cli_dev_only_falsification_never_approaches_stage4(tmp_path):
    out = tmp_path / "vault"
    PanelBuilder(tmp_path / "raw", out).publish(
        make_panel(hours=240, dynamic=True),
        provenance={"source_spec_status": "synthetic_test"})
    values = synthetic_spec(out).model_dump(mode="json")
    values["gates"]["minimum_ic"] = 1.0
    source = export_spec(CandidateSpec.model_validate(values), tmp_path / "synthetic.yaml")
    cli = Path(__file__).resolve().parents[1] / "scripts" / "quant.py"
    runlog = tmp_path / "logs"
    proc = subprocess.run(
        [sys.executable, str(cli), "run", str(source), "--development-only",
         "--run-log", str(runlog)],
        text=True, capture_output=True, check=False, timeout=100)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    assert report["status"] == "FALSIFIED_STAGE_2"
    assert report["holdout_access"] is False
    assert "4" not in report["stages"]
    assert not (runlog / "_holdout_claims").exists()


def test_dev_only_rejects_frozen_event_before_runner(tmp_path, monkeypatch):
    from src.engine import funnel
    from src.engine.event_protocol import M8N8EventSpec
    monkeypatch.setattr(funnel.ResearchFunnel, '_run_event',
                        lambda *args, **kwargs: pytest.fail('event runner must remain unreachable'))
    with pytest.raises(QuantError, match='Development-only mode currently supports'):
        ResearchFunnel(run_log=tmp_path / 'logs').run(
            M8N8EventSpec(protocol='event', strategy_id='m8_n8_cash_session_v7'),
            development_only=True)
    assert not (tmp_path / 'logs').exists()


def test_unsafe_dev_flag_types_are_rejected(tmp_path):
    with pytest.raises(QuantError, match="explicit boolean"):
        ResearchFunnel(run_log=tmp_path / "logs").run(
            "does-not-exist.yaml", development_only="no"
        )
