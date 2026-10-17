from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from scripts.run_crypto_xs_plain_funding_phase4_20261015 import (
    _verify_cost_ledger,
    daily_metrics,
    gate,
)


def test_daily_metrics_uses_negative_drawdown_convention():
    start = datetime(2020, 1, 1, tzinfo=UTC)
    frame = pl.DataFrame({
        "timestamp": [start + timedelta(days=i) for i in range(4)],
        "equity": [100.0, 110.0, 99.0, 120.0],
    })
    metrics, daily, yearly = daily_metrics(frame)
    assert metrics["max_drawdown"] == pytest.approx(-0.10)
    assert daily.height == 4
    assert "2020" in yearly


def test_cost_ledger_reconciles_native_metrics():
    fills = pl.DataFrame({
        "commission": [1.0, 2.0],
        "slippage": [0.1, 0.2],
        "quantity": [10.0, 20.0],
    })
    result = _verify_cost_ledger(
        fills, {"total_commission": 3.0, "total_slippage": 5.0}
    )
    assert result == {"commission": 3.0, "slippage": 5.0}


def test_phase4_gate_has_frozen_terminal_semantics():
    base = {
        "total_return": 0.10,
        "funding_cashflow_usdt": 100.0,
        "daily_risk": {"daily_sharpe": 0.8, "max_drawdown": -0.20},
    }
    stress = {"total_return": 0.02}
    assert gate(base, stress, {"same_sign": True}) == ("VALIDATE", [])
    decision, reasons = gate(
        {**base, "daily_risk": {"daily_sharpe": 0.2, "max_drawdown": -0.20}},
        stress,
        {"same_sign": True},
    )
    assert decision == "REJECT"
    assert any("Sharpe" in item for item in reasons)
    assert gate(base, stress, {"same_sign": False})[0] == "INCONCLUSIVE"
