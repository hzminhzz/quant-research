"""Unit tests for UnifiedPortfolio fill-driven sleeve attribution and fail-closed risk gating."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
import pytest

from ml4t.backtest import Strategy, OrderType
from src.portfolio.unified_portfolio import UnifiedPortfolio


class MockMasterBroker:
    def __init__(self, initial_equity: float = 5000.0):
        self._equity = initial_equity
        self._cash = initial_equity
        self.orders: list[dict[str, Any]] = []

    def equity(self) -> float:
        return self._equity

    def get_cash(self) -> float:
        return self._cash

    def submit_order(
        self,
        asset: str,
        quantity: float,
        order_type: Any = OrderType.MARKET,
        limit_price: float | None = None,
        stop_price: float | None = None,
        reduce_only: bool = False,
        **kwargs: Any,
    ) -> Any:
        oid = f"ord-{len(self.orders)+1}"
        order_dict = {
            "order_id": oid,
            "asset": asset,
            "quantity": quantity,
            "order_type": order_type,
            "limit_price": limit_price,
            "stop_price": stop_price,
            "reduce_only": reduce_only,
        }
        self.orders.append(order_dict)

        @dataclass
        class OrderResult:
            order_id: str
            filled_price: float | None = None

        return OrderResult(order_id=oid)


class DummyStopStrategy(Strategy):
    def __init__(self, asset: str, stop_price: float):
        super().__init__()
        self.asset = asset
        self.stop_price = stop_price

    def on_data(self, timestamp: datetime, data: dict[str, Any], context: dict[str, Any], broker: Any) -> None:
        broker.submit_order(
            self.asset,
            0.05,
            order_type=OrderType.STOP,
            stop_price=self.stop_price,
        )


class ConcreteStrategy(Strategy):
    def on_data(self, timestamp: datetime, data: dict[str, Any], context: dict[str, Any], broker: Any) -> None:
        pass


def test_contingent_stop_orders_preserved_to_broker():
    master = MockMasterBroker(initial_equity=5000.0)
    b0 = DummyStopStrategy("xyz:XYZ100", stop_price=28500.0)
    portfolio = UnifiedPortfolio(b0, ConcreteStrategy(), ConcreteStrategy(), ConcreteStrategy())
    portfolio.on_start(master)

    now = datetime(2026, 10, 17, 10, 0, tzinfo=UTC)
    data = {"xyz:XYZ100": {"close": 28000.0}}
    portfolio.on_data(now, data, {}, master)

    assert len(master.orders) == 1
    submitted = master.orders[0]
    assert submitted["asset"] == "xyz:XYZ100"
    assert submitted["quantity"] == 0.05
    assert submitted["order_type"] == OrderType.STOP
    assert submitted["stop_price"] == 28500.0


def test_fill_driven_sleeve_attribution_and_partial_fills():
    master = MockMasterBroker(initial_equity=5000.0)

    class OrderingStrategy(Strategy):
        def __init__(self, asset: str, qty: float):
            super().__init__()
            self.asset = asset
            self.qty = qty

        def on_data(self, timestamp: datetime, data: dict[str, Any], context: dict[str, Any], broker: Any) -> None:
            broker.submit_order(self.asset, self.qty)

    # Sleeve B0 orders 0.02 XYZ100
    b0 = OrderingStrategy("xyz:XYZ100", 0.02)
    # Sleeve C3 orders 0.01 XYZ100 (same asset, overlapping!)
    c3 = OrderingStrategy("xyz:XYZ100", 0.01)

    portfolio = UnifiedPortfolio(b0, c3, ConcreteStrategy(), ConcreteStrategy())
    portfolio.on_start(master)

    now = datetime(2026, 10, 17, 10, 0, tzinfo=UTC)
    data = {"xyz:XYZ100": {"close": 28000.0}}
    portfolio.on_data(now, data, {}, master)

    assert len(master.orders) == 2
    b0_order_id = master.orders[0]["order_id"]
    c3_order_id = master.orders[1]["order_id"]

    @dataclass
    class FillEvent:
        order_id: str
        asset: str
        quantity: float
        price: float

    # Initial state: proxies see 0
    assert portfolio.proxies["b0"].get_position("xyz:XYZ100") is None
    assert portfolio.proxies["c3"].get_position("xyz:XYZ100") is None

    # Partial fill on B0's order: 0.01 out of 0.02
    portfolio.on_fill(FillEvent(order_id=b0_order_id, asset="xyz:XYZ100", quantity=0.01, price=28050.0))
    assert portfolio.proxies["b0"].get_position("xyz:XYZ100").quantity == 0.01
    assert portfolio.proxies["c3"].get_position("xyz:XYZ100") is None  # C3 untouched!

    # Complete fill on B0's order: total 0.02
    portfolio.on_fill(FillEvent(order_id=b0_order_id, asset="xyz:XYZ100", quantity=0.02, price=28050.0))
    assert portfolio.proxies["b0"].get_position("xyz:XYZ100").quantity == 0.02

    # Duplicate fill event does not double count
    portfolio.on_fill(FillEvent(order_id=b0_order_id, asset="xyz:XYZ100", quantity=0.02, price=28050.0))
    assert portfolio.proxies["b0"].get_position("xyz:XYZ100").quantity == 0.02

    # Fill on C3's order
    portfolio.on_fill(FillEvent(order_id=c3_order_id, asset="xyz:XYZ100", quantity=0.01, price=28055.0))
    assert portfolio.proxies["c3"].get_position("xyz:XYZ100").quantity == 0.01


def test_fail_closed_on_missing_broker_equity():
    class BrokenBroker:
        def equity(self):
            return 0.0  # Invalid equity

    portfolio = UnifiedPortfolio(ConcreteStrategy(), ConcreteStrategy(), ConcreteStrategy(), ConcreteStrategy())
    with pytest.raises(RuntimeError, match="non-positive"):
        portfolio.on_start(BrokenBroker())


def test_trailing_drawdown_floor_breach():
    master = MockMasterBroker(initial_equity=5000.0)
    portfolio = UnifiedPortfolio(ConcreteStrategy(), ConcreteStrategy(), ConcreteStrategy(), ConcreteStrategy(),
                                 starting_balance=5000.0, trailing_dd_pct=0.08)
    portfolio.on_start(master)

    day1 = datetime(2026, 10, 17, 10, 0, tzinfo=UTC)
    data = {"xyz:XYZ100": {"close": 28000.0}}

    # Day 1: normal step at 5000
    portfolio.on_data(day1, data, {}, master)
    assert not portfolio.halted

    # Day 1 close: equity drops to 4800 (daily loss 200 < 250 limit)
    master._equity = 4800.0
    portfolio.on_data(datetime(2026, 10, 17, 23, 0, tzinfo=UTC), data, {}, master)
    assert not portfolio.halted

    # Day 2: 00:00 UTC resets day_start_balance to 4800. Daily loss limit for Day 2 is 5% * 4800 = 240.
    # Equity drops to 4595 (Day 2 daily loss = 4800 - 4595 = 205 < 240 limit).
    # But cumulative equity 4595 breaches the HWM trailing floor (5000 - 400 = 4600).
    master._equity = 4595.0
    day2 = datetime(2026, 10, 18, 10, 0, tzinfo=UTC)
    portfolio.on_data(day2, data, {}, master)
    assert portfolio.halted
    assert "Trailing drawdown floor breached" in portfolio.halt_reason
