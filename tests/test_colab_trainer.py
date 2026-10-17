"""Tests for Google Colab remote GPU training worker and ATS integration."""
from __future__ import annotations

import hashlib
import subprocess
from datetime import timedelta
from pathlib import Path

import polars as pl
import pytest

from src.engine.colab_trainer import ColabTrainer
from src.engine.common import QuantError
from src.engine.spec_parser import CandidateSpec

ROOT = Path(__file__).resolve().parents[1]


def _make_sample_spec(tmp_path: Path) -> CandidateSpec:
    panel_dir = tmp_path / "panel"
    panel_dir.mkdir(parents=True, exist_ok=True)
    (panel_dir / "manifest.json").write_text("{}", encoding="utf-8")

    return CandidateSpec.model_validate({
        "candidate_id": "test_crypto_xs_lgb_v1",
        "selection_family_id": "test_crypto_xs_family",
        "thesis": "Test remote ML training hypothesis",
        "panel_root": str(panel_dir),
        "windows": {
            "train": {"start": "2021-01-01T00:00:00Z", "end": "2023-01-01T00:00:00Z"},
            "validation": {"start": "2023-01-01T00:00:00Z", "end": "2024-01-01T00:00:00Z"},
            "protected": {"start": "2024-01-01T00:00:00Z", "end": "2025-01-01T00:00:00Z"},
        },
        "features": [
            {"name": "lgb_signal", "native": "roc", "params": {"period": 24}},
            {"name": "baseline_mom", "native": "roc", "params": {"period": 24}},
            {"name": "atr_24h", "native": "atr", "params": {"period": 24}},
        ],
        "signal": "lgb_signal",
        "baseline": "baseline_mom",
        "allocation": {
            "long_count": 2,
            "short_count": 2,
            "atr_feature": "atr_24h",
        },
        "universe": {
            "minimum_assets": 5,
            "top_n": 10,
        },
    })


def test_prepare_training_data_slices_strictly_train_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    spec = _make_sample_spec(tmp_path)
    trainer = ColabTrainer(spec, run_log=tmp_path / "run_log")

    requested_windows = []

    def mock_load(self, start=None, end=None):
        requested_windows.append((start, end))
        # Generate sample rows strictly in requested window
        rows = [
            {
                "timestamp": start + timedelta(hours=i),
                "symbol": "BTCUSDT",
                "open": 100.0,
                "high": 105.0,
                "low": 99.0,
                "close": 102.0,
                "volume": 10.0,
                "carry_rate": 0.0,
                "spread_bps": 0.0,
                "session_id": 1,
                "bar_in_session": i,
                "is_tradable": True,
            }
            for i in range(10)
        ]
        return pl.DataFrame(rows)
    from src.data_vault import DataVault
    monkeypatch.setattr(DataVault, "__init__", lambda self, root, **kw: None)
    monkeypatch.setattr(DataVault, "load", mock_load)
    out_file = tmp_path / "train.arrow"
    meta = trainer.prepare_training_data(out_file)

    assert meta["rows"] == 10
    assert meta["symbols"] == 1
    assert out_file.is_file()
    # Confirm strictly train window was requested
    assert len(requested_windows) == 1
    req_start, req_end = requested_windows[0]
    assert req_start == spec.windows.train.start
    assert req_end == spec.windows.train.end


def test_prepare_training_data_rejects_leak_or_invalid_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    spec = _make_sample_spec(tmp_path)
    trainer = ColabTrainer(spec, run_log=tmp_path / "run_log")

    # Simulate vault returning timestamps at or after train_end
    def mock_leaking_load(self, start=None, end=None):
        return pl.DataFrame([
            {
                "timestamp": spec.windows.train.end + timedelta(hours=1),
                "symbol": "BTCUSDT",
                "open": 100.0,
                "high": 105.0,
                "low": 99.0,
                "close": 102.0,
                "volume": 10.0,
                "carry_rate": 0.0,
                "spread_bps": 0.0,
                "session_id": 1,
                "bar_in_session": 1,
                "is_tradable": True,
            }
        ])

    from src.data_vault import DataVault
    monkeypatch.setattr(DataVault, "__init__", lambda self, root, **kw: None)
    monkeypatch.setattr(DataVault, "load", mock_leaking_load)
    out_file = tmp_path / "train.arrow"
    with pytest.raises(QuantError, match="Data contains 1 rows at or beyond train_end"):
        trainer.prepare_training_data(out_file)


def test_colab_trainer_handles_vm_allocation_failure_with_guaranteed_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    spec = _make_sample_spec(tmp_path)
    trainer = ColabTrainer(spec, run_log=tmp_path / "run_log")

    import shutil
    monkeypatch.setattr(shutil, "which", lambda cmd: "/bin/sh")
    monkeypatch.setattr(trainer, "prepare_training_data", lambda out: {"rows": 10, "sha256": "0" * 64})
    executed_commands = []

    def mock_run(cmd, *args, **kwargs):
        executed_commands.append(list(cmd))
        if cmd[1] == "new":
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="400 Out of GPU quota")
        if cmd[1] == "stop":
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", mock_run)

    script = tmp_path / "train.py"
    script.write_text("print('train')", encoding="utf-8")

    with pytest.raises(QuantError, match="Failed to allocate Colab T4 session: 400 Out of GPU quota"):
        trainer.train(script, gpu="T4")

    # Verify colab stop was called in cleanup
    assert any(cmd[1] == "stop" for cmd in executed_commands)


def test_colab_trainer_successful_run_and_artifact_export(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    spec = _make_sample_spec(tmp_path)
    run_log = tmp_path / "run_log"
    trainer = ColabTrainer(spec, run_log=run_log)
    import shutil
    monkeypatch.setattr(shutil, "which", lambda cmd: "/bin/sh")
    monkeypatch.setattr(trainer, "prepare_training_data", lambda out: {"rows": 10, "sha256": "0" * 64})
    dummy_model_bytes = b"mocked_cloudpickle_model_content_for_testing"
    expected_sha = hashlib.sha256(dummy_model_bytes).hexdigest()

    def mock_run(cmd, *args, **kwargs):
        if cmd[1] == "download":
            # cmd is [colab, download, -s, session, remote_path, local_path]
            dest = Path(cmd[5])
            dest.write_bytes(dummy_model_bytes)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="OK", stderr="")

    monkeypatch.setattr(subprocess, "run", mock_run)

    script = tmp_path / "train.py"
    script.write_text("print('train')", encoding="utf-8")

    out_candidate = tmp_path / "output_candidate.yaml"
    artifact, updated_spec = trainer.train(script, gpu="T4", output_candidate_path=out_candidate)

    assert artifact.sha256 == expected_sha
    assert (ROOT / artifact.path).is_file() or (run_log / "python_features" / f"{expected_sha}.pkl").is_file()
    assert updated_spec.python_feature_artifact is not None
    assert updated_spec.python_feature_artifact.sha256 == expected_sha
    assert out_candidate.is_file()


def test_quant_cli_train_remote_subcommand(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    spec = _make_sample_spec(tmp_path)
    spec_yaml = tmp_path / "spec_template.yaml"
    from src.engine.spec_parser import export_spec
    export_spec(spec, spec_yaml)

    dummy_model_bytes = b"cli_mocked_model"
    expected_sha = hashlib.sha256(dummy_model_bytes).hexdigest()

    def mock_run(cmd, *args, **kwargs):
        if len(cmd) > 1 and cmd[1] == "download":
            dest = Path(cmd[5])
            dest.write_bytes(dummy_model_bytes)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="OK", stderr="")
    import shutil
    monkeypatch.setattr(shutil, "which", lambda cmd: "/bin/sh")
    monkeypatch.setattr(subprocess, "run", mock_run)
    from src.data_vault import DataVault
    monkeypatch.setattr(DataVault, "__init__", lambda self, root, **kw: None)
    monkeypatch.setattr(DataVault, "load", lambda self, start=None, end=None: pl.DataFrame([
        {
            "timestamp": start + timedelta(hours=i),
            "symbol": "BTCUSDT",
            "open": 100.0,
            "high": 105.0,
            "low": 99.0,
            "close": 102.0,
            "volume": 10.0,
            "carry_rate": 0.0,
            "spread_bps": 0.0,
            "session_id": 1,
            "bar_in_session": i,
            "is_tradable": True,
        }
        for i in range(5)
    ]))

    script = tmp_path / "train.py"
    script.write_text("print('train')", encoding="utf-8")

    out_yaml = tmp_path / "trained_candidate.yaml"

    from scripts.quant import main
    exit_code = main([
        "train-remote",
        str(spec_yaml),
        "--training-script", str(script),
        "--run-log", str(tmp_path / "run_log"),
        "-o", str(out_yaml),
    ])

    assert exit_code == 0
    assert out_yaml.is_file()
    from src.engine.spec_parser import parse_spec
    loaded = parse_spec(out_yaml)
    assert loaded.python_feature_artifact is not None
    assert loaded.python_feature_artifact.sha256 == expected_sha
