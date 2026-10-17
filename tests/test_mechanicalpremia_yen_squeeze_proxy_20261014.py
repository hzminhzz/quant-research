"""Native Engine capability gates for the Yen Squeeze proxy."""
from datetime import datetime, timedelta, timezone

import polars as pl
import pytest

from ml4t.backtest import (
    BacktestConfig, DataFeed, Engine, ExecutionMode, OrderSide,
    OrderType, Strategy,
)
from ml4t.backtest.config import FillOrdering, ShareType, SlippageType


class _RoundTrip(Strategy):
    def __init__(self, direction=1):
        self.i = 0
        self.direction = direction

    def on_data(self, timestamp, data, context, broker):
        if self.i == 0:
            broker.submit_order("X", self.direction, side=OrderSide.BUY if self.direction > 0 else OrderSide.SELL, order_type=OrderType.MARKET)
        elif self.i == 1:
            broker.submit_order("X", -self.direction, side=OrderSide.SELL if self.direction > 0 else OrderSide.BUY, order_type=OrderType.MARKET)
        self.i += 1


@pytest.mark.parametrize("slippage", [0.01, 0.02, 0.03])
@pytest.mark.parametrize("direction", [1, -1])
def test_engine_fixed_slippage_sign_and_repeated_fill_cost(slippage, direction):
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    prices = pl.DataFrame({
        "timestamp": [start + timedelta(minutes=i) for i in range(3)],
        "symbol": ["X"] * 3,
        "open": [100.0] * 3,
        "high": [101.0] * 3,
        "low": [99.0] * 3,
        "close": [100.0] * 3,
        "volume": [1.0] * 3,
    })
    config = BacktestConfig(
        initial_cash=1_000.0,
        execution_mode=ExecutionMode.NEXT_BAR,
        slippage_type=SlippageType.FIXED,
        slippage_fixed=slippage,
        allow_short_selling=True,
        share_type=ShareType.FRACTIONAL,
        fill_ordering=FillOrdering.EXIT_FIRST,
    )
    result = Engine(
        DataFeed(prices_df=prices, entity_col="symbol", timestamp_col="timestamp"),
        _RoundTrip(direction), config,
    ).run()
    fills = result.to_fills_dataframe()
    assert fills.height == 2
    assert fills["side"].to_list() == (["buy", "sell"] if direction > 0 else ["sell", "buy"])
    assert fills["price"].to_list() == pytest.approx(
        [100.0 + slippage, 100.0 - slippage] if direction > 0 else [100.0 - slippage, 100.0 + slippage]
    )
    assert fills["slippage"].to_list() == pytest.approx([slippage, slippage])
    assert result.metrics["total_slippage"] == pytest.approx(2 * slippage)
    assert result.metrics["final_value"] == pytest.approx(1_000.0 - 2 * slippage)
    assert result.to_trades_dataframe().filter(pl.col("status") == "closed").height == 1


def test_engine_retains_both_same_bar_opposite_stop_fills_without_oco():
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    prices = pl.DataFrame({
        "timestamp": [start + timedelta(minutes=i) for i in range(3)],
        "symbol": ["X"] * 3,
        "open": [100.0, 100.0, 100.0],
        "high": [101.0, 110.0, 101.0],
        "low": [99.0, 90.0, 99.0],
        "close": [100.0] * 3,
        "volume": [1.0] * 3,
    })

    class SubmitBoth(Strategy):
        submitted = False

        def on_data(self, timestamp, data, context, broker):
            if not self.submitted:
                self.submitted = True
                broker.submit_order("X", 1, side=OrderSide.BUY, order_type=OrderType.STOP, stop_price=105.0)
                broker.submit_order("X", -1, side=OrderSide.SELL, order_type=OrderType.STOP, stop_price=95.0)

    result = Engine(
        DataFeed(prices_df=prices, entity_col="symbol", timestamp_col="timestamp"),
        SubmitBoth(),
        BacktestConfig(initial_cash=1_000.0, execution_mode=ExecutionMode.NEXT_BAR, allow_short_selling=True),
    ).run()
    fills = result.to_fills_dataframe()
    assert fills.height == 2
    assert fills["timestamp"].n_unique() == 1
    assert fills["side"].to_list() == ["buy", "sell"]
    assert result.to_trades_dataframe().filter(pl.col("status") == "closed").height == 1
    # The engine's sequential native treatment realizes a loss and closes the
    # net position. This is a counted ambiguity, not a source OCO guarantee.
    assert result.metrics["final_value"] == pytest.approx(990.0)

