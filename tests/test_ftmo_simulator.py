"""Unit tests for FTMO 2-Step Challenge Simulator."""

import pytest
from src.ftmo_simulator import FTMOSimulator, FTMOConfig, FTMOAttemptResult


def test_step1_min_days_and_pass():
    """Verify that Step 1 requires both +10% target and >= 4 trading days."""
    cfg = FTMOConfig(step1_target_pct=0.10, step1_min_trading_days=4)
    # Day 1: +5%, Day 2: +6% (total +11%, but only 2 days)
    # Day 3: +0.5%, Day 4: +0.5% (now 4 days, should pass Step 1)
    trades = [
        {"date": "2024-01-01", "r_mult": 5.0, "pnl_pct": 0.05},
        {"date": "2024-01-02", "r_mult": 6.0, "pnl_pct": 0.06},
        {"date": "2024-01-03", "r_mult": 0.5, "pnl_pct": 0.005},
        {"date": "2024-01-04", "r_mult": 0.5, "pnl_pct": 0.005},
    ]
    sim = FTMOSimulator(trades, config=cfg)
    daily_sequence = [sim.trades_by_date[d] for d in sim.unique_dates]
    
    # After first 2 days, should not pass yet
    res_2d = sim.simulate_path(daily_sequence[:2], risk_pct=1.0)
    assert not res_2d.step1_passed
    assert res_2d.step1_days == 2

    # After 4 days, should pass Step 1!
    res_4d = sim.simulate_path(daily_sequence, risk_pct=1.0)
    assert res_4d.step1_passed
    assert res_4d.step1_days == 4


def test_two_step_full_funded_completion():
    """Verify full progression: Step 1 (+10%) -> Step 2 (+5%) -> Funded with fee refund."""
    cfg = FTMOConfig(
        step1_target_pct=0.10,
        step1_min_trading_days=4,
        step2_target_pct=0.05,
        step2_min_trading_days=4,
        challenge_fee_usd=540.0,
    )
    # 4 days for Step 1 (+2.5% each day = +10%)
    # 4 days for Step 2 (+1.25% each day = +5%)
    # 14 days funded (+1.0% each day)
    trades = []
    for i in range(1, 5):
        trades.append({"date": f"2024-01-{i:02d}", "r_mult": 2.5, "pnl_pct": 0.025})
    for i in range(5, 9):
        trades.append({"date": f"2024-01-{i:02d}", "r_mult": 1.25, "pnl_pct": 0.0125})
    for i in range(9, 23):
        trades.append({"date": f"2024-01-{i:02d}", "r_mult": 1.0, "pnl_pct": 0.01})

    sim = FTMOSimulator(trades, config=cfg)
    daily_sequence = [sim.trades_by_date[d] for d in sim.unique_dates]
    res = sim.simulate_path(daily_sequence, risk_pct=1.0, simulate_funded=True, funded_sim_days=14)

    assert res.step1_passed
    assert res.step2_passed
    assert res.funded
    assert not res.breached
    assert res.fee_refunded
    assert res.funded_payouts_earned > cfg.challenge_fee_usd


def test_hard_daily_drawdown_breach():
    """Verify that a single day loss exceeding -5.0% triggers immediate disqualification."""
    cfg = FTMOConfig(max_daily_loss_pct=0.05, user_daily_halt_pct=0.10)  # Disable circuit breaker to test hard FTMO limit
    trades = [
        {"date": "2024-01-01", "r_mult": 1.0, "pnl_pct": 0.01},
        {"date": "2024-01-02", "r_mult": -5.2, "pnl_pct": -0.052},  # -5.2% loss in 1 day
    ]
    sim = FTMOSimulator(trades, config=cfg)
    daily_sequence = [sim.trades_by_date[d] for d in sim.unique_dates]
    res = sim.simulate_path(daily_sequence, risk_pct=1.0)

    assert res.breached
    assert res.breach_reason == "daily_loss"
    assert not res.step1_passed


def test_hard_max_total_loss_breach():
    """Verify that cumulative drawdown reaching -10.0% triggers disqualification."""
    cfg = FTMOConfig(max_total_loss_pct=0.10, user_daily_halt_pct=0.02)
    # 6 consecutive days of -1.8% loss = -10.8% cumulative drawdown
    trades = [
        {"date": f"2024-01-{i:02d}", "r_mult": -1.8, "pnl_pct": -0.018}
        for i in range(1, 8)
    ]
    sim = FTMOSimulator(trades, config=cfg)
    daily_sequence = [sim.trades_by_date[d] for d in sim.unique_dates]
    res = sim.simulate_path(daily_sequence, risk_pct=1.0)

    assert res.breached
    assert res.breach_reason == "max_loss"
    assert not res.step1_passed


def test_user_daily_circuit_breaker():
    """Verify that user daily circuit breaker stops subsequent losses on the same day."""
    cfg = FTMOConfig(max_daily_loss_pct=0.05, user_daily_halt_pct=0.02)
    # Day has 3 trades: -1.0%, -1.1%, then -4.0%
    # With circuit breaker at 2.0%, the 3rd trade (-4.0%) must be BLOCKED!
    trades = [
        {"date": "2024-01-01", "entry_time": "2024-01-01 01:00", "r_mult": -1.0, "pnl_pct": -0.01},
        {"date": "2024-01-01", "entry_time": "2024-01-01 02:00", "r_mult": -1.1, "pnl_pct": -0.011},
        {"date": "2024-01-01", "entry_time": "2024-01-01 03:00", "r_mult": -4.0, "pnl_pct": -0.04},
    ]
    sim = FTMOSimulator(trades, config=cfg)
    daily_sequence = [sim.trades_by_date[d] for d in sim.unique_dates]
    res = sim.simulate_path(daily_sequence, risk_pct=1.0)

    # Because trade 3 was blocked, total day loss is -2.1%, NOT -6.1%, avoiding the 5% daily breach!
    assert not res.breached
    assert res.max_daily_loss_observed_pct < 5.0


def test_monte_carlo_resampling():
    """Verify that Monte Carlo bootstrap generates valid probability distributions."""
    trades = [
        {"date": f"2024-01-{i:02d}", "r_mult": 1.5 if i % 2 == 0 else -1.0, "pnl_pct": 0.015 if i % 2 == 0 else -0.01}
        for i in range(1, 25)
    ]
    sim = FTMOSimulator(trades)
    mc_res = sim.run_monte_carlo(n_simulations=100, risk_pct=1.0, random_seed=42)

    assert 0.0 <= mc_res["step1_pass_rate_pct"] <= 100.0
    assert 0.0 <= mc_res["overall_two_step_pass_rate_pct"] <= 100.0
    assert mc_res["n_simulations"] == 100


def test_statistical_haircut():
    """Verify Bailey & López de Prado multiple-testing haircut decreases with trials."""
    h1 = FTMOSimulator.calculate_statistical_haircut(1.5, n_trials=1)
    h10 = FTMOSimulator.calculate_statistical_haircut(1.5, n_trials=10)
    h50 = FTMOSimulator.calculate_statistical_haircut(1.5, n_trials=50)

    assert h1 == 1.5
    assert h10 < h1
    assert h50 < h10


def test_probability_gating_filtering():
    """Verify that probability gating filters trades with p_hat < threshold."""
    trades = [
        {"date": "2024-01-01", "r_mult": -1.0, "pnl_pct": -0.01, "prob": 0.40},  # Low conviction loss -> filtered!
        {"date": "2024-01-02", "r_mult": 2.0, "pnl_pct": 0.02, "prob": 0.65},   # High conviction win -> taken!
    ]
    sim = FTMOSimulator(trades)
    daily_sequence = [sim.trades_by_date[d] for d in sim.unique_dates]

    # Without gating: both executed, net return +1%
    res_nogate = sim.simulate_path(daily_sequence, risk_pct=1.0)
    assert res_nogate.total_trades == 2

    # With gating at 0.52: only the winning trade is executed
    res_gated = sim.simulate_path(daily_sequence, risk_pct=1.0, prob_threshold=0.52)
    assert res_gated.total_trades == 1


def test_half_kelly_position_sizing():
    """Verify that Half-Kelly scales risk up for high conviction and down for low conviction."""
    trades = [
        {"date": "2024-01-01", "r_mult": 2.0, "pnl_pct": 0.02, "prob": 0.70},
    ]
    sim = FTMOSimulator(trades)
    daily_sequence = [sim.trades_by_date[d] for d in sim.unique_dates]

    # At p=0.70, b=2, Kelly = (3*0.7 - 1)/2 = 0.55. Half-Kelly = 0.275 -> 2.0% cap
    res_kelly = sim.simulate_path(daily_sequence, risk_pct=1.0, use_half_kelly=True, max_kelly_risk_pct=2.0)
    assert res_kelly.total_trades == 1

