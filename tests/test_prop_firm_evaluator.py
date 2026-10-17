"""Unit and integration tests for PropFirmEvaluator and PropFirmChallengeWrapper."""

from datetime import datetime, timedelta, timezone
import polars as pl
import pytest

from ml4t.backtest import Strategy, Engine, DataFeed, BacktestConfig
from ml4t.backtest.config import ShareType
from src.prop_firm_evaluator import (
    prepare_dual_timeframe_pit,
    PropFirmConfig,
    PropFirmChallengeWrapper,
    PropFirmEvaluator,
)


def test_zero_lookahead_within_same_hour():
    """Verifies that mutating prices within hour 170 (minutes 1 to 59) CANNOT alter signals at 170:00."""
    start_dt = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    n_minutes = 200 * 60

    timestamps = [start_dt + timedelta(minutes=m) for m in range(n_minutes)]
    base_prices = [100.0 + (i * 0.01) for i in range(n_minutes)]

    df_base = pl.DataFrame({
        "timestamp": timestamps,
        "symbol": ["BTC"] * n_minutes,
        "open": base_prices,
        "high": base_prices,
        "low": base_prices,
        "close": base_prices,
        "volume": [10.0] * n_minutes,
    })

    df_pit_orig = prepare_dual_timeframe_pit(df_base)

    # Signal at 170:00
    h170_ts = start_dt + timedelta(hours=170)
    orig_row = df_pit_orig.filter(pl.col("timestamp") == h170_ts)
    assert orig_row["roc_168h"][0] is not None, "ROC after 168h must be non-null"
    assert orig_row["ema_120h"][0] is not None, "EMA must be non-null"

    orig_roc = float(orig_row["roc_168h"][0])
    orig_ema = float(orig_row["ema_120h"][0])

    # Mutate minutes 1 through 59 of the SAME hour (hour 170)
    mutated_prices = list(base_prices)
    for m in range(170 * 60 + 1, 170 * 60 + 60):
        mutated_prices[m] = 999999.0

    df_mut = pl.DataFrame({
        "timestamp": timestamps,
        "symbol": ["BTC"] * n_minutes,
        "open": mutated_prices,
        "high": mutated_prices,
        "low": mutated_prices,
        "close": mutated_prices,
        "volume": [10.0] * n_minutes,
    })

    df_pit_mut = prepare_dual_timeframe_pit(df_mut)
    mut_row = df_pit_mut.filter(pl.col("timestamp") == h170_ts)

    mut_roc = float(mut_row["roc_168h"][0])
    mut_ema = float(mut_row["ema_120h"][0])

    assert orig_roc == mut_roc, f"Lookahead in ROC: {orig_roc} != {mut_roc}"
    assert orig_ema == mut_ema, f"Lookahead in EMA: {orig_ema} != {mut_ema}"


def test_engine_integration_with_two_distinct_strategies():
    """Verifies that PropFirmChallengeWrapper works inside real Engine runs with two distinct strategies."""
    # Build 10 days of hourly data for a test asset
    start_dt = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    timestamps = [start_dt + timedelta(hours=h) for h in range(240)]
    prices = [100.0 * (1.002 ** h) for h in range(240)]  # Strong steady uptrend

    df_prices = pl.DataFrame({
        "timestamp": timestamps,
        "symbol": ["BTC"] * 240,
        "open": prices,
        "high": [p * 1.001 for p in prices],
        "low": [p * 0.999 for p in prices],
        "close": prices,
        "volume": [100.0] * 240,
    })
    df_signals = pl.DataFrame({
        "timestamp": timestamps,
        "symbol": ["BTC"] * 240,
        "is_hour_close": [1] * 240,
    })

    cfg = BacktestConfig(
        initial_cash=10000.0,
        share_type=ShareType.FRACTIONAL,
        allow_short_selling=True,
    )

    # Strategy 1: Always Long (+15% profit target expected on strong uptrend)
    class AlwaysLongStrategy(Strategy):
        def on_data(self, timestamp, data, context, broker):
            pos = broker.get_position("BTC")
            if pos is None or pos.quantity <= 0:
                broker.order_target_percent("BTC", 0.90)

    config_target = PropFirmConfig(initial_balance=10000.0, target_pct=0.15, static_floor_pct=0.10)
    wrapper1 = PropFirmChallengeWrapper(inner_strategy=AlwaysLongStrategy(), config=config_target)

    try:
        Engine(DataFeed(prices_df=df_prices, signals_df=df_signals), wrapper1, cfg).run()
    except StopIteration:
        pass

    assert wrapper1.outcome == "PASSED", f"Expected PASSED, got {wrapper1.outcome}"
    assert wrapper1.final_equity >= 11500.0, f"Expected final equity >= 11500, got {wrapper1.final_equity}"

    # Strategy 2: Always Short (-10% static floor breach expected on strong uptrend)
    class AlwaysShortStrategy(Strategy):
        def on_data(self, timestamp, data, context, broker):
            pos = broker.get_position("BTC")
            if pos is None or pos.quantity >= 0:
                broker.order_target_percent("BTC", -0.90)

    config_floor = PropFirmConfig(initial_balance=10000.0, target_pct=0.15, static_floor_pct=0.10)
    wrapper2 = PropFirmChallengeWrapper(inner_strategy=AlwaysShortStrategy(), config=config_floor)

    try:
        Engine(DataFeed(prices_df=df_prices, signals_df=df_signals), wrapper2, cfg).run()
    except StopIteration:
        pass

    assert wrapper2.outcome == "BREACHED_STATIC_FLOOR", f"Expected BREACHED_STATIC_FLOOR, got {wrapper2.outcome}"
    assert wrapper2.final_equity <= 9000.0, f"Expected final equity <= 9000, got {wrapper2.final_equity}"


def test_evaluator_fast_cohort_execution():
    """Verifies that PropFirmEvaluator runs multiple cohorts via O(1) binary search slicing."""
    start_dt = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    timestamps = [start_dt + timedelta(hours=h) for h in range(100)]
    prices = [100.0 * (1.002 ** h) for h in range(100)]

    df_prices = pl.DataFrame({
        "timestamp": timestamps,
        "symbol": ["BTC"] * 100,
        "open": prices,
        "high": prices,
        "low": prices,
        "close": prices,
        "volume": [100.0] * 100,
    })
    df_signals = pl.DataFrame({
        "timestamp": timestamps,
        "symbol": ["BTC"] * 100,
    })

    class SimpleLong(Strategy):
        def on_data(self, timestamp, data, context, broker):
            if broker.get_position("BTC") is None:
                broker.order_target_percent("BTC", 0.50)

    evaluator = PropFirmEvaluator(
        prices_df=df_prices,
        signals_df=df_signals,
        strategy_factory=SimpleLong,
        config=PropFirmConfig(initial_balance=10000.0, target_pct=0.05, max_evaluation_days=3),
    )

    cohorts = [start_dt + timedelta(hours=h) for h in [0, 10, 20]]
    report = evaluator.run_cohorts(cohorts)

    assert report["total_cohorts"] == 3
    assert len(report["cohort_records"]) == 3
    assert report["completed_cohorts"] == 3
