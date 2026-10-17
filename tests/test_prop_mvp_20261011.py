from datetime import datetime, timedelta, timezone

import polars as pl

from ml4t.backtest import BacktestConfig, DataFeed, Engine
from ml4t.backtest.config import CommissionType, ExecutionMode, ShareType, SlippageType

from scripts.run_prop_mvp_20261011 import CashHold, OpeningRange, TargetSignal, add_opening_signals


def test_target_signal_only_trades_on_direction_changes():
    class Broker:
        def __init__(self):
            self.orders = []

        def order_target_percent(self, symbol, target):
            self.orders.append((symbol, target))

    strategy = TargetSignal(0.5)
    broker = Broker()
    bar = {"BTCUSDT": {"signals": {"signal": 1}, "close": 100.0}}
    strategy.on_data(datetime.now(timezone.utc), bar, {}, broker)
    strategy.on_data(datetime.now(timezone.utc), bar, {}, broker)
    bar["BTCUSDT"]["signals"]["signal"] = -1
    strategy.on_data(datetime.now(timezone.utc), bar, {}, broker)
    assert broker.orders == [("BTCUSDT", 0.5), ("BTCUSDT", -0.5)]


def test_opening_range_uses_completed_window_and_flattens_before_close():
    start = datetime(2026, 7, 1, 13, 30, tzinfo=timezone.utc)
    timestamps = [start + timedelta(minutes=5 * i) for i in range(79)]
    frame = pl.DataFrame({
        "timestamp": timestamps,
        "symbol": ["NAS100"] * len(timestamps),
        "open": [100.0] * len(timestamps),
        "high": [101.0] * len(timestamps),
        "low": [99.0] * len(timestamps),
        "close": [100.0] * len(timestamps),
        "volume": [1] * len(timestamps),
    }).with_columns(
        pl.when(pl.col("timestamp") == start + timedelta(minutes=15))
        .then(102.0).otherwise(pl.col("open")).alias("open")
    )
    signaled = add_opening_signals(frame, 5)
    row = signaled.filter(pl.col("timestamp") == start + timedelta(minutes=15))
    assert row["signal"].item() == 1
    close_row = signaled.filter(pl.col("local_time") == pl.time(15, 50))
    assert close_row["signal"].item() == 0


def test_native_opening_range_exit_fills_on_last_reliable_bar():
    start = datetime(2026, 7, 1, 13, 30, tzinfo=timezone.utc)
    timestamps = [start + timedelta(minutes=5 * i) for i in range(78)]
    frame = pl.DataFrame({
        "timestamp": timestamps,
        "symbol": ["NAS100"] * len(timestamps),
        "open": [100.0] * len(timestamps),
        "high": [101.0] * len(timestamps),
        "low": [99.0] * len(timestamps),
        "close": [100.0] * len(timestamps),
        "volume": [1] * len(timestamps),
    }).with_columns(
        pl.when(pl.col("timestamp") == start + timedelta(minutes=15))
        .then(102.0).otherwise(pl.col("open")).alias("open")
    )
    signaled = add_opening_signals(frame, 5)
    prices = signaled.select("timestamp", "symbol", "open", "high", "low", "close", "volume")
    signals = signaled.select("timestamp", "symbol", "signal")
    cfg = BacktestConfig(initial_cash=25_000, allow_short_selling=True,
                         share_type=ShareType.FRACTIONAL, execution_mode=ExecutionMode.NEXT_BAR,
                         commission_type=CommissionType.PERCENTAGE, commission_rate=0.0002,
                         slippage_type=SlippageType.PERCENTAGE, slippage_rate=0.0003)
    result = Engine(DataFeed(prices_df=prices, signals_df=signals), OpeningRange(), cfg).run()
    trades = result.to_trades_dataframe()
    assert trades.height == 1
    assert trades["entry_time"].item() == datetime(2026, 7, 1, 13, 50)
    assert trades["exit_time"].item().date() == trades["entry_time"].item().date()
    assert trades["exit_time"].item().time() == datetime(2000, 1, 1, 19, 55).time()


def test_cash_control_runs_through_native_engine_without_orders():
    start = datetime(2026, 7, 1, 13, 30, tzinfo=timezone.utc)
    prices = pl.DataFrame({
        "timestamp": [start + timedelta(minutes=5 * i) for i in range(3)],
        "symbol": ["NAS100"] * 3,
        "open": [100.0] * 3, "high": [101.0] * 3, "low": [99.0] * 3,
        "close": [100.0] * 3, "volume": [1] * 3,
    })
    signals = prices.select("timestamp", "symbol").with_columns(pl.lit(1).alias("signal"))
    cfg = BacktestConfig(initial_cash=25_000, allow_short_selling=True,
                         share_type=ShareType.FRACTIONAL, execution_mode=ExecutionMode.NEXT_BAR)
    result = Engine(DataFeed(prices_df=prices, signals_df=signals), CashHold(), cfg).run()
    assert result.metrics["total_return"] == 0.0
    assert result.to_fills_dataframe().is_empty()
