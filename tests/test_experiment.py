"""Tests for Experiment Tracking and Deflated Sharpe Ratio calculation."""

import tempfile
from pathlib import Path
from src.experiment import TrialRecord, log_trial, load_trials, compute_deflated_sharpe


def test_trial_logging_and_loading():
    with tempfile.TemporaryDirectory() as tmpdir:
        ledger = Path(tmpdir) / "trials.jsonl"
        tr = TrialRecord(
            trial_id="test-001",
            strategy_name="Test Strategy",
            symbol="TEST/USD",
            timeframe="15m",
            parameters={"lookback": 20},
            total_return_pct=15.0,
            annualized_sharpe=1.2,
            max_drawdown_pct=10.0,
            win_rate_pct=55.0,
            total_trades=100,
        )
        log_trial(tr, ledger_path=ledger)
        records = load_trials(ledger_path=ledger)
        assert len(records) == 1
        assert records[0]["trial_id"] == "test-001"
        assert records[0]["annualized_sharpe"] == 1.2


def test_deflated_sharpe_computation():
    all_sharpes = [0.1, -0.2, 0.4, 0.8, -0.5, 0.3, 0.6]
    observed_sr = 0.8
    dsr = compute_deflated_sharpe(observed_annualized_sharpe=observed_sr, all_sharpes=all_sharpes)
    assert dsr["n_trials"] == len(all_sharpes)
    assert dsr["haircut_sharpe"] < observed_sr
    assert 0.0 <= dsr["dsr_probability"] <= 1.0
