from __future__ import annotations

from datetime import datetime, timedelta, timezone

import polars as pl

from ml4t.backtest import AssetClass, BacktestConfig, CommissionType, ContractSpec, DataFeed, Engine
from ml4t.backtest.config import SlippageType
from ml4t.backtest.types import ExecutionMode, StopFillMode

from scripts.run_one_bar_dukascopy_phase567_20261011 import (
    ASSET, CausalOneBar, MULTIPLIER, NQ_TICK, next_boundary,
)


def test_utc_half_hour_exit_boundary_survives_fall_back_repeated_hour():
    first = datetime(2026, 11, 1, 6, 29, tzinfo=timezone.utc)
    repeated = datetime(2026, 11, 1, 7, 29, tzinfo=timezone.utc)
    assert next_boundary(first) == datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)
    assert next_boundary(repeated) == datetime(2026, 11, 1, 7, 30, tzinfo=timezone.utc)


def test_causal_strategy_uses_native_stop_and_market_fills_with_full_tick_costs():
    result, _ = run_synthetic()
    fills = result.to_fills_dataframe()
    assert fills.height == 2
    assert fills["commission"].sum() == 5.0
    assert round(fills["slippage"].sum(), 8) == 0.5
    trades = result.to_trades_dataframe()
    assert round(float(trades["gross_pnl"].sum() - trades["pnl"].sum()), 8) == 5.0


def test_native_engine_fills_both_entry_stops_before_strategy_cancels():
    result, strategy = run_synthetic(both_entry_stops=True)
    entry_fills = result.to_fills_dataframe().filter(pl.col("order_type") == "stop")
    assert entry_fills.height == 2
    oco = [row for row in strategy.ambiguous if row.get("kind") == "both_entry_stops_filled"]
    assert len(oco) == 1


def test_entry_and_protective_stop_in_same_minute_is_flagged():
    _, strategy = run_synthetic(protective_stop_candle=True)
    assert any(row.get("kind") == "entry_and_protective_stop_same_candle" for row in strategy.ambiguous)


def test_missing_exit_open_fills_at_first_observed_event_and_is_late():
    result, _ = run_synthetic(missing_boundary=True)
    trades = result.to_trades_dataframe()
    assert trades.height == 1
    assert trades["exit_time"][0].replace(tzinfo=timezone.utc) == datetime(2026, 1, 5, 17, 10, tzinfo=timezone.utc)


def test_final_missing_exit_event_leaves_no_fabricated_market_fill():
    result, _ = run_synthetic(end_before_exit=True)
    fills = result.to_fills_dataframe()
    assert fills.filter(pl.col("order_type") == "market").is_empty()


def run_synthetic(*, both_entry_stops: bool = False, protective_stop_candle: bool = False,
                  missing_boundary: bool = False, end_before_exit: bool = False):
    start = datetime(2026, 1, 5, 15, 40, tzinfo=timezone.utc)
    timestamps = [start.replace(minute=40) + timedelta(minutes=i) for i in range(97)]
    if missing_boundary:
        timestamps = [t for t in timestamps if not datetime(2026, 1, 5, 17, 0, tzinfo=timezone.utc) <= t < datetime(2026, 1, 5, 17, 10, tzinfo=timezone.utc)]
    if end_before_exit:
        timestamps = [t for t in timestamps if t < datetime(2026, 1, 5, 17, 0, tzinfo=timezone.utc)]
    prices = pl.DataFrame({
        "timestamp": timestamps,
        "asset": [ASSET] * len(timestamps),
        "open": [99.5] * len(timestamps),
        "high": [99.75] * len(timestamps),
        "low": [99.25] * len(timestamps),
        "close": [99.5] * len(timestamps),
        "volume": [1.0] * len(timestamps),
    }).with_columns(pl.col("timestamp").cast(pl.Datetime("us", "UTC")))
    prices = prices.with_columns(
        pl.when(pl.col("timestamp") == datetime(2026, 1, 5, 16, 30, tzinfo=timezone.utc))
        .then(pl.lit(100.25)).otherwise(pl.col("high")).alias("high")
    )
    if both_entry_stops or protective_stop_candle:
        prices = prices.with_columns(
            pl.when(pl.col("timestamp") == datetime(2026, 1, 5, 16, 30, tzinfo=timezone.utc))
            .then(pl.lit(97.75 if both_entry_stops else 49.75)).otherwise(pl.col("low")).alias("low")
        )
    signals = pl.DataFrame({
        "timestamp": timestamps, "asset": [ASSET] * len(timestamps),
        "next_long_stop": [100.0] * len(timestamps),
        "next_short_stop": [98.0 if not protective_stop_candle else 0.0] * len(timestamps),
        "range_proxy": [0.01] * len(timestamps),
    }).with_columns(pl.col("timestamp").cast(pl.Datetime("us", "UTC")))
    strategy = CausalOneBar()
    result = Engine(
        DataFeed(prices_df=prices, signals_df=signals), strategy,
        BacktestConfig(
            initial_cash=INITIAL_CASH, allow_short_selling=True, allow_leverage=True,
            fixed_margin_schedule={ASSET: (25_000.0, 20_000.0)},
            execution_mode=ExecutionMode.NEXT_BAR, stop_fill_mode=StopFillMode.STOP_PRICE,
            commission_type=CommissionType.PER_SHARE, commission_per_share=2.50,
            slippage_type=SlippageType.FIXED, slippage_fixed=NQ_TICK,
        ),
        contract_specs={ASSET: ContractSpec(symbol=ASSET, asset_class=AssetClass.FUTURE,
            multiplier=MULTIPLIER, tick_size=NQ_TICK, margin=25_000.0)},
    ).run()
    return result, strategy


INITIAL_CASH = 1_000_000.0
