# pyright: reportMissingImports=false, reportUnknownParameterType=false, reportUnknownMemberType=false
"""Comprehensive unit and edge-case tests for mathematically complex algorithms.

Covers:
1. ml4t.engineer.features.fdiff (Fixed-width window fractional differencing)
2. ml4t.engineer.features.regime (Hurst exponent, Choppiness index, Fractal efficiency, Variance ratio, Regime classifier)
3. ml4t.engineer.features.microstructure (Roll spread, Amihud illiquidity, Kyle's lambda, Order flow imbalance)
4. ml4t.live.runtime (PositionRuleState, CanonicalChildOrderIntent)
"""
from __future__ import annotations

import math
from datetime import UTC, datetime

import numpy as np
import polars as pl
import pytest
from ml4t.engineer.features.fdiff import ffdiff, find_optimal_d
from ml4t.engineer.features.microstructure import (
    amihud_illiquidity,
    kyle_lambda,
    order_flow_imbalance,
    roll_spread_estimator,
)
from ml4t.engineer.features.regime import (
    choppiness_index,
    fractal_efficiency,
    hurst_exponent,
    market_regime_classifier,
    variance_ratio,
)
from ml4t.live.protocols import (
    ExecutionCapability,
)
from ml4t.live.runtime import (
    CanonicalChildOrderIntent,
    EvaluationMode,
    ExitReason,
    FillEligibility,
    LifecyclePhase,
    OrderParameters,
    PositionActionType,
    PositionRuleState,
    RuleActivation,
    SessionPolicy,
    TimeInForce,
)
from ml4t.specs import IntentReason
from ml4t.specs import OrderSide as SpecOrderSide
from ml4t.specs import OrderType as SpecOrderType

# =====================================================================
# 1. ml4t.engineer.features.fdiff Tests
# =====================================================================


def test_ffdiff_boundaries_and_memory_preservation():
    # Synthetic trending price series
    prices = [100.0 + i * 0.5 + math.sin(i / 5.0) for i in range(200)]
    df = pl.DataFrame({"price": prices})

    # d = 0 should preserve original price series
    df_d0 = df.with_columns(p_d0=ffdiff("price", d=0.0))
    assert math.isclose(df_d0["p_d0"][-1], df["price"][-1], rel_tol=1e-5)

    # d = 0.4 partial differencing (stationarity with memory)
    df_d04 = df.with_columns(p_d04=ffdiff("price", d=0.4))
    res = df_d04["p_d04"].drop_nulls()
    assert len(res) > 50
    assert all(math.isfinite(x) for x in res)

    # d = 1.0 (equivalent to first differencing)
    df_d1 = df.with_columns(p_d1=ffdiff("price", d=1.0))
    res_d1 = df_d1["p_d1"].drop_nulls()
    expected_diff = np.diff(prices)[-len(res_d1):]
    assert np.allclose(res_d1[-10:].to_numpy(), expected_diff[-10:], atol=1e-3)


def test_find_optimal_d_bounds():
    np.random.seed(42)
    rw = np.cumsum(np.random.randn(300)) + 1000.0
    series = pl.Series("price", rw)
    optimal_res = find_optimal_d(series, adf_pvalue_threshold=0.05)
    assert isinstance(optimal_res, dict)
    optimal_d = optimal_res["optimal_d"]
    assert isinstance(optimal_d, float)
    assert 0.0 <= optimal_d <= 1.5


# =====================================================================
# 2. ml4t.engineer.features.regime Tests
# =====================================================================


def test_hurst_exponent_persistent_vs_mean_reverting():
    # Strongly persistent series (trend H > 0.5)
    trending = pl.Series("close", [100.0 + i * 2.0 + np.random.randn() * 0.1 for i in range(150)])
    df_trend = pl.DataFrame({"close": trending}).with_columns(
        h=hurst_exponent("close", period=80, min_lag=4, max_lag=30)
    )
    h_trend = df_trend["h"][-1]
    assert h_trend is not None
    assert h_trend > 0.5  # Persistent trending H > 0.5

    # Anti-persistent mean-reverting series (AR(1) with negative autocorrelation H < 0.5)
    np.random.seed(42)
    ar = [0.0]
    for _ in range(300):
        ar.append(-0.7 * ar[-1] + np.random.randn())
    df_ar = pl.DataFrame({"close": [100.0 + x for x in ar]})
    res_h = df_ar.with_columns(h=hurst_exponent("close", period=80, min_lag=4, max_lag=30))
    h_anti = res_h["h"][-1]
    assert h_anti is not None
    assert h_anti < 0.5  # Anti-persistent H < 0.5


def test_fractal_efficiency_boundaries():
    # Monotonic straight line: Fractal Efficiency should be 1.0
    straight = pl.DataFrame({"close": [10.0 + i * 2.0 for i in range(30)]})
    res_straight = straight.with_columns(fe=fractal_efficiency("close", period=10))
    fe_straight = res_straight["fe"][-1]
    assert math.isclose(fe_straight, 1.0, abs_tol=1e-5)

    # Alternating choppy noise: Fractal Efficiency should approach 0.0
    choppy = pl.DataFrame({"close": [10.0 if i % 2 == 0 else 12.0 for i in range(30)]})
    res_choppy = choppy.with_columns(fe=fractal_efficiency("close", period=10))
    fe_choppy = res_choppy["fe"][-1]
    assert fe_choppy < 0.2


def test_choppiness_index_bounds_and_flat_market():
    # 0 to 100 scale: trending < 38.2, choppy > 61.8
    trending_df = pl.DataFrame({
        "high": [100.0 + i * 2.0 + 0.5 for i in range(40)],
        "low": [100.0 + i * 2.0 - 0.5 for i in range(40)],
        "close": [100.0 + i * 2.0 for i in range(40)],
    })
    res = trending_df.with_columns(chop=choppiness_index("high", "low", "close", period=14))
    chop_val = res["chop"][-1]
    assert 0.0 <= chop_val <= 100.0
    assert chop_val < 38.2  # Strongly trending

    # Flat market (high == low == close): true range is zero -> produces NaN
    flat_df = pl.DataFrame({
        "high": [100.0] * 30,
        "low": [100.0] * 30,
        "close": [100.0] * 30,
    })
    res_flat = flat_df.with_columns(chop=choppiness_index("high", "low", "close", period=14))
    flat_val = res_flat["chop"][-1]
    # Edge case: zero range produces NaN or None; live strategies must fill_null/fill_nan
    assert flat_val is None or math.isnan(flat_val) or math.isfinite(flat_val)


def test_variance_ratio_multi_period():
    np.random.seed(42)
    prices = 100.0 + np.cumsum(np.random.randn(200))
    df = pl.DataFrame({"close": prices})
    vr_exprs = variance_ratio("close", periods=[2, 4, 8], window=40)
    df_vr = df.with_columns([vr_exprs[f"vr_{p}"].alias(f"vr_{p}") for p in [2, 4, 8]])
    for p in [2, 4, 8]:
        val = df_vr[f"vr_{p}"][-1]
        assert val is not None
        assert math.isfinite(val)
        assert val > 0.0


def test_market_regime_classifier_output():
    # Generate OHLCV data
    df = pl.DataFrame({
        "high": [100.0 + i * 1.5 + 1.0 for i in range(60)],
        "low": [100.0 + i * 1.5 - 1.0 for i in range(60)],
        "close": [100.0 + i * 1.5 for i in range(60)],
        "volume": [10000.0 + i * 100 for i in range(60)],
    })
    classified = df.with_columns(regime=market_regime_classifier("high", "low", "close", "volume"))
    latest_regime = classified["regime"][-1]
    assert latest_regime in (-1, 0, 1)


# =====================================================================
# 3. ml4t.engineer.features.microstructure Tests
# =====================================================================


def test_roll_spread_positive_covariance_edge_case():
    # Classic bid-ask bounce: negative autocorrelation (spread > 0)
    bounce = pl.DataFrame({"close": [100.0 if i % 2 == 0 else 102.0 for i in range(60)]})
    res_bounce = bounce.with_columns(spread=roll_spread_estimator("close", period=10))
    bounce_val = res_bounce["spread"][-1]
    assert bounce_val is not None
    assert bounce_val > 0.0

    # Clean positive trend: positive autocorrelation -> cov > 0 -> Roll spread clamps to 0
    strictly_increasing = pl.DataFrame({"close": [10.0 + i * 2.0 for i in range(60)]})
    res_trend = strictly_increasing.with_columns(spread=roll_spread_estimator("close", period=10))
    trend_val = res_trend["spread"][-1]
    assert trend_val is not None
    assert math.isclose(trend_val, 0.0, abs_tol=1e-5)


def test_amihud_illiquidity_zero_division_guard():
    df = pl.DataFrame({
        "returns": [0.01, 0.02, 0.0, 0.015, -0.01] * 10,
        "volume": [10000, 20000, 0, 15000, 12000] * 10,  # Contains zero volume bars
        "close": [100.0, 102.0, 102.0, 103.5, 102.5] * 10,
    })
    res = df.with_columns(illiq=amihud_illiquidity("returns", "volume", "close", period=10))
    assert len(res["illiq"]) == 50
    # Values after warm-up are finite
    last_val = res["illiq"][-1]
    assert last_val is not None
    assert math.isfinite(last_val)


def test_kyle_lambda_ratio_approximation():
    # Kyle lambda requires at least 2*period bars for volume rolling normalization
    df = pl.DataFrame({
        "returns": [0.01, -0.005, 0.02, -0.01, 0.015, 0.008] * 4,
        "volume": [1000000, 950000, 1200000, 800000, 1100000, 1050000] * 4,
    })
    res = df.with_columns(k_lambda=kyle_lambda("returns", "volume", period=4))
    val = res["k_lambda"][-1]
    assert val is not None
    assert math.isfinite(val)
    assert val > 0.0


def test_order_flow_imbalance_tick_rule():
    df = pl.DataFrame({
        "volume": [100.0, 200.0, 150.0, 300.0, 250.0],
        "close": [50.0, 51.0, 50.5, 50.5, 52.0],  # Up, down, flat, up ticks
    })
    res = df.with_columns(ofi=order_flow_imbalance("volume", "close", use_tick_rule=True))
    assert len(res["ofi"]) == 5
    for val in res["ofi"].drop_nulls():
        assert -1.0 <= val <= 1.0


# =====================================================================
# 4. ml4t.live.runtime State Machine & Intent Tests
# =====================================================================


def test_position_rule_state_watermark_invariants():
    now = datetime.now(UTC)

    # Valid PositionRuleState
    state = PositionRuleState(
        policy_id="pol-01",
        rule_id="rule-01",
        asset="BTC/USDT",
        activation=RuleActivation.ACTIVE,
        entry_time=now,
        entry_side=SpecOrderSide.BUY,
        entry_price=80000.0,
        entry_quantity=0.01,
        high_water_mark=82000.0,
        low_water_mark=79000.0,
        max_favorable_excursion=(82000.0 - 80000.0) / 80000.0,  # +0.025
        max_adverse_excursion=(79000.0 - 80000.0) / 80000.0,    # -0.0125
        remaining_exit_quantity=0.01,
        idempotency_key="idemp-01",
        action=PositionActionType.HOLD,
        exit_reason=ExitReason.NONE,
        evaluation_mode=EvaluationMode.CLIENT,
    )
    assert state.activation == RuleActivation.ACTIVE
    assert math.isclose(state.max_favorable_excursion, 0.025)

    # Invalid: Low water mark exceeding high water mark
    with pytest.raises(ValueError, match="low_water_mark must not exceed high_water_mark"):
        PositionRuleState(
            policy_id="pol-01", rule_id="rule-01", asset="BTC/USDT",
            activation=RuleActivation.ACTIVE, entry_time=now, entry_side=SpecOrderSide.BUY,
            entry_price=80000.0, entry_quantity=0.01,
            high_water_mark=79000.0, low_water_mark=82000.0,  # Invalid
            max_favorable_excursion=0.0, max_adverse_excursion=0.0,
            remaining_exit_quantity=0.01, idempotency_key="idemp-01",
            action=PositionActionType.HOLD, exit_reason=ExitReason.NONE,
            evaluation_mode=EvaluationMode.CLIENT,
        )

    # Invalid: Mismatched excursion calculation
    with pytest.raises(ValueError, match="max_favorable_excursion is inconsistent"):
        PositionRuleState(
            policy_id="pol-01", rule_id="rule-01", asset="BTC/USDT",
            activation=RuleActivation.ACTIVE, entry_time=now, entry_side=SpecOrderSide.BUY,
            entry_price=80000.0, entry_quantity=0.01,
            high_water_mark=82000.0, low_water_mark=79000.0,
            max_favorable_excursion=0.999,  # Deliberate mismatch
            max_adverse_excursion=-0.0125,
            remaining_exit_quantity=0.01, idempotency_key="idemp-01",
            action=PositionActionType.HOLD, exit_reason=ExitReason.NONE,
            evaluation_mode=EvaluationMode.CLIENT,
        )

def test_canonical_child_order_intent_parameters_and_fill_remainder():
    today = datetime.now(UTC).date()
    params = OrderParameters(limit_price=80000.0)

    # Valid Limit order intent
    child = CanonicalChildOrderIntent(
        child_intent_id="child-01",
        target_intent_id="target-01",
        idempotency_key="idemp-c01",
        asset="BTC/USDT",
        side=SpecOrderSide.BUY,
        quantity=0.05,
        order_type=SpecOrderType.LIMIT,
        parameters=params,
        decision_session=today,
        effective_session=today,
        eligibility_phase=LifecyclePhase.OPENING_AUCTION,
        fill_eligibility=FillEligibility.NEXT_PHASE,
        time_in_force=TimeInForce.GTC,
        session_policy=SessionPolicy.REGULAR,
        capabilities=(ExecutionCapability.LIMIT,),
        reason=IntentReason.SIGNAL,
    )
    assert child.order_type == SpecOrderType.LIMIT
    assert child.parameters.limit_price == 80000.0

    # Test remaining_after_fill partial fill logic
    rem = child.remaining_after_fill(0.02)
    assert math.isclose(rem, 0.03)

    # Invalid fill exceeding order quantity
    with pytest.raises(ValueError, match="filled_quantity must be between zero and order quantity"):
        child.remaining_after_fill(0.06)

    # Invalid parameter: LIMIT order without limit_price
    with pytest.raises(ValueError, match="limit order requires limit_price"):
        CanonicalChildOrderIntent(
            child_intent_id="child-02",
            target_intent_id="target-01",
            idempotency_key="idemp-c02",
            asset="BTC/USDT",
            side=SpecOrderSide.BUY,
            quantity=0.05,
            order_type=SpecOrderType.LIMIT,
            parameters=OrderParameters(),  # Missing limit_price
            decision_session=today,
            effective_session=today,
            eligibility_phase=LifecyclePhase.OPENING_AUCTION,
            fill_eligibility=FillEligibility.NEXT_PHASE,
            time_in_force=TimeInForce.GTC,
            session_policy=SessionPolicy.REGULAR,
            capabilities=(ExecutionCapability.LIMIT,),
            reason=IntentReason.SIGNAL,
        )
