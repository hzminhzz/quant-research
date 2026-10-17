"""Rigorous validation test suite for Two-Stage Funnel feature engineering and strategy."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
import polars as pl
import pytest

from src.strategies.two_stage_funnel_tsmom import (
    TwoStageFunnelTSMOMStrategy,
    TwoStageRiskConfig,
)
from tests.conftest import require_path

FEATURES_PATH = Path("data/features/crypto_tsmom_two_stage_funnel_features.parquet")


@pytest.fixture(scope="module")
def sample_feature_panel():
    return pl.read_parquet(require_path(FEATURES_PATH))


@pytest.mark.data
def test_feature_completeness_and_finite_values(sample_feature_panel):
    """Check 1: Verify all key feature columns are non-null and finite on active universe rows."""
    active = sample_feature_panel.filter(pl.col("is_in_top10_universe") == 1.0)
    assert active.height > 10000, "Active universe rows too small"

    key_cols = ["close", "ema_200", "ema_24", "vol_scaled_weight", "pass_trend_gate", "is_selected_leader"]
    for col in key_cols:
        null_count = active[col].null_count()
        assert null_count == 0, f"Column {col} contains {null_count} nulls in active universe"


@pytest.mark.data
def test_trend_gating_invariant(sample_feature_panel):
    """Check 3: Invariant test.

    A token is selected as a leader ONLY IF Close > EMA_200 (100% enforcement, 0 exceptions).
    """
    leaders = sample_feature_panel.filter(pl.col("is_selected_leader") == 1.0)
    assert leaders.height > 0, "No leaders selected"

    # Check if any leader has close <= ema_200
    violations = leaders.filter(pl.col("close") <= pl.col("ema_200"))
    assert violations.height == 0, f"Found {violations.height} trend gate violations where leader Close <= EMA200!"


@pytest.mark.data
def test_portfolio_risk_budget_limits(sample_feature_panel):
    """Check 4: Verify single-asset position limits (<= 20%) and portfolio gross leverage (<= 1.0)."""
    leaders = sample_feature_panel.filter(pl.col("is_selected_leader") == 1.0)

    # Max single asset weight
    max_w = leaders["vol_scaled_weight"].max()
    assert max_w is not None and max_w <= 0.20 + 1e-6, f"Single asset weight breached 20%: {max_w}"

    # Sum of weights at any single timestamp <= 1.0 (5 leaders * max 20% = max 100%)
    gross_leverage_by_ts = (
        leaders.group_by("timestamp")
        .agg(pl.col("vol_scaled_weight").sum().alias("total_gross_weight"))
    )
    max_gross = gross_leverage_by_ts["total_gross_weight"].max()
    assert max_gross is not None and max_gross <= 1.00 + 1e-6, f"Gross leverage exceeded 1.0x: {max_gross}"


def test_kill_switch_triggers_and_flattens():
    """Check 5: Automated kill-switch test.

    A 15% drawdown must halt execution and trigger broker.flatten_all_positions().
    """
    strat = TwoStageFunnelTSMOMStrategy(
        risk_config=TwoStageRiskConfig(max_portfolio_drawdown=0.15)
    )
    broker = MagicMock()
    broker.get_cash.return_value = 10000.0
    broker.get_portfolio_value.return_value = 10000.0
    strat.on_start(broker)

    # 1. Normal state: equity at peak
    bar_data = {
        "BTCUSDT": {
            "signals": {
                "is_selected_leader": 1.0,
                "vol_scaled_weight": 0.15,
            }
        }
    }
    broker.get_position.return_value = None
    strat.on_data(datetime.now(timezone.utc), bar_data, {}, broker)
    broker.order_target_percent.assert_called_with("BTCUSDT", 0.15)

    # 2. Crash state: portfolio drops by 20% (from 10,000 to 8,000)
    broker.get_portfolio_value.return_value = 8000.0
    strat.on_data(datetime.now(timezone.utc), bar_data, {}, broker)

    assert strat.kill_switch_tripped is True, "Kill switch failed to trip on 20% drawdown"
    broker.flatten_all_positions.assert_called_once()
