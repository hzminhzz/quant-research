from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import polars as pl

from scripts import run_one_bar_nq_percent_stop_yearly_20261012 as runner
from scripts import run_one_bar_dukascopy_phase567_20261011 as phase


class FakeBroker:
    def __init__(self, position=None):
        self.position = position
        self.orders = []

    def get_position(self, _asset):
        return self.position

    def submit_order(self, asset, quantity, **kwargs):
        order = SimpleNamespace(asset=asset, quantity=quantity, kwargs=kwargs,
            status=SimpleNamespace(value="pending"), order_id=str(len(self.orders)))
        self.orders.append(order)
        return order

    def cancel_order(self, _order_id):
        for order in self.orders:
            if order.order_id == _order_id:
                order.status.value = "cancelled"


def test_2021_and_2026_stop_distances_and_directional_ticks():
    long_2021 = runner.percent_stop_price(14598.25, "long")
    short_2021 = runner.percent_stop_price(14598.25, "short")
    assert long_2021 == 14548.25
    assert short_2021 == 14648.25
    assert 49.75 <= 14598.25 - long_2021 <= 50.0
    assert 50.0 <= short_2021 - 14598.25 <= 50.25

    long_2026 = runner.percent_stop_price(25828.5, "long")
    short_2026 = runner.percent_stop_price(25828.5, "short")
    assert 88.25 <= 25828.5 - long_2026 <= 88.5
    assert 88.5 <= short_2026 - 25828.5 <= 88.75
    assert (long_2026 / 0.25).is_integer()
    assert (short_2026 / 0.25).is_integer()


def test_filled_contract_gets_one_fixed_protective_stop_and_two_entry_orders():
    strategy = runner.PercentStopStrategy(date(2026, 12, 31))
    broker = FakeBroker()
    timestamp = datetime(2026, 1, 5, 23, 29, tzinfo=timezone.utc)  # 17:29 Chicago
    strategy.on_data(timestamp, {runner.ASSET: {"signals": {
        "next_long_stop": 25800.0, "next_short_stop": 25700.0}}}, {}, broker)
    assert [order.quantity for order in broker.orders] == [1, -1]
    assert all(order.kwargs["order_type"] == phase.OrderType.STOP for order in broker.orders)

    broker.orders[0].status.value = "filled"
    broker.position = SimpleNamespace(quantity=1.0, entry_price=25800.25)
    strategy.on_data(datetime(2026, 1, 5, 23, 30, tzinfo=timezone.utc),
        {runner.ASSET: {"open": 25800.25, "high": 25801.0, "low": 25800.0,
                        "signals": {}}}, {}, broker)
    assert broker.orders[1].status.value == "cancelled"
    stop_order = broker.orders[-1]
    stop_price = stop_order.kwargs["stop_price"]
    assert stop_order.quantity == -1.0
    assert stop_price == runner.percent_stop_price(25800.25, "long")

    broker.position.entry_price = 26000.0
    strategy.on_data(datetime(2026, 1, 5, 23, 31, tzinfo=timezone.utc),
        {runner.ASSET: {"open": 25800.0, "high": 25801.0, "low": 25799.0,
                        "signals": {}}}, {}, broker)
    assert broker.orders[-1] is stop_order
    assert strategy.trade["stop"] == stop_price
    assert strategy.trade_metadata[0]["stop_fraction"] == runner.STOP_FRACTION
    assert strategy.trade_metadata[0]["quantity"] == 1


def test_session_day_uses_chicago_dst_boundaries():
    # The spring-forward day has no local 02:xx timestamps; UTC-to-Chicago stays causal.
    before = datetime(2021, 3, 14, 7, 29, tzinfo=timezone.utc)
    after = datetime(2021, 3, 14, 8, 0, tzinfo=timezone.utc)
    assert runner.chicago_session_day(before) == date(2021, 3, 13)
    assert runner.chicago_session_day(after) == date(2021, 3, 13)
    assert runner.next_30m_boundary(before) == datetime(2021, 3, 14, 7, 30, tzinfo=timezone.utc)
    assert runner.chicago_session_day(datetime(2021, 3, 14, 21, 59, tzinfo=timezone.utc)) == date(2021, 3, 13)
    assert runner.chicago_session_day(datetime(2021, 3, 14, 22, 0, tzinfo=timezone.utc)) == date(2021, 3, 14)


def test_two_filled_entries_per_chicago_session_day_is_the_cap():
    strategy = runner.PercentStopStrategy(date(2026, 12, 31))
    broker = FakeBroker()
    signals = {"next_long_stop": 25800.0, "next_short_stop": 25700.0}
    strategy.on_data(datetime(2026, 1, 5, 23, 29, tzinfo=timezone.utc),
        {runner.ASSET: {"signals": signals}}, {}, broker)
    first_entry = broker.orders[0]
    first_entry.status.value = "filled"
    broker.position = SimpleNamespace(quantity=1.0, entry_price=25800.25)
    strategy.on_data(datetime(2026, 1, 5, 23, 30, tzinfo=timezone.utc),
        {runner.ASSET: {"open": 25800.25, "high": 25801.0, "low": 25800.0, "signals": {}}}, {}, broker)
    broker.position = None
    strategy.on_data(datetime(2026, 1, 5, 23, 31, tzinfo=timezone.utc),
        {runner.ASSET: {"open": 25800.0, "high": 25801.0, "low": 25799.0, "signals": {}}}, {}, broker)

    strategy.on_data(datetime(2026, 1, 6, 5, 59, tzinfo=timezone.utc),
        {runner.ASSET: {"signals": signals}}, {}, broker)  # 23:59 Chicago, same Globex day
    second_entry = strategy.entry_orders[0]
    second_entry.status.value = "filled"
    broker.position = SimpleNamespace(quantity=1.0, entry_price=25801.0)
    strategy.on_data(datetime(2026, 1, 6, 6, 0, tzinfo=timezone.utc),
        {runner.ASSET: {"open": 25801.0, "high": 25802.0, "low": 25800.5, "signals": {}}}, {}, broker)
    assert strategy.max_daily_entries == 2
    order_count = len(broker.orders)

    broker.position = None
    strategy.on_data(datetime(2026, 1, 6, 6, 1, tzinfo=timezone.utc),
        {runner.ASSET: {"open": 25801.0, "high": 25802.0, "low": 25800.0, "signals": {}}}, {}, broker)
    strategy.on_data(datetime(2026, 1, 6, 6, 29, tzinfo=timezone.utc),
        {runner.ASSET: {"signals": signals}}, {}, broker)
    assert len(broker.orders) == order_count


def test_scheduled_market_exit_is_submitted_at_next_30m_boundary():
    strategy = runner.PercentStopStrategy(date(2026, 12, 31))
    timestamp = datetime(2026, 1, 5, 23, 30, tzinfo=timezone.utc)
    broker = FakeBroker(SimpleNamespace(quantity=1.0, entry_price=25800.25))
    protective = broker.submit_order(runner.ASSET, -1.0,
        order_type=phase.OrderType.STOP, stop_price=25700.0)
    strategy.stop_order = protective
    strategy.trade = {"scheduled_exit": datetime(2026, 1, 6, 0, 0, tzinfo=timezone.utc),
        "stop": 25700.0}
    strategy.on_data(datetime(2026, 1, 5, 23, 59, tzinfo=timezone.utc),
        {runner.ASSET: {"open": 25800.0, "high": 25801.0, "low": 25799.0, "signals": {}}}, {}, broker)
    assert protective.status.value == "cancelled"
    exit_order = broker.orders[-1]
    assert exit_order.kwargs["order_type"] == phase.OrderType.MARKET
    assert exit_order.quantity == -1.0
    assert strategy.trade["exit_submitted_at"] == datetime(2026, 1, 5, 23, 59, tzinfo=timezone.utc)


def test_native_stop_price_gap_fills_at_open_with_frozen_fraction_and_costs(tmp_path: Path, monkeypatch):
    timestamps = [datetime(2021, 1, 4, 23, minute, tzinfo=timezone.utc) for minute in (29, 30, 31)]
    feed = pl.DataFrame({
        "timestamp": timestamps, "asset": [runner.ASSET] * 3,
        "open": [100.0, 100.0, 98.0], "high": [100.0, 101.0, 99.0],
        "low": [100.0, 100.0, 97.0], "close": [100.0, 100.5, 98.0],
        "volume": [1.0, 1.0, 1.0], "next_long_stop": [100.25] * 3,
        "next_short_stop": [99.75] * 3, "range_proxy": [0.01] * 3,
    })
    strategy_state = {}

    def strategy_factory():
        strategy_state["strategy"] = runner.PercentStopStrategy(date(2021, 1, 31))
        return strategy_state["strategy"]

    monkeypatch.setattr(phase, "CausalOneBar", strategy_factory)
    monkeypatch.setattr(phase, "OUT", tmp_path)
    metrics = phase.run_native(feed, "synthetic", 2.5, 0.25)
    fills = pl.read_csv(tmp_path / "synthetic/fills.csv", try_parse_dates=True)
    protective = fills.filter((pl.col("order_type") == "stop") & (pl.col("exit_reason") == "signal"))
    assert protective.height == 1
    stop_row = protective.row(0, named=True)
    assert stop_row["reference_price"] == 98.0
    assert stop_row["reference_price"] - stop_row["price"] == 0.25
    assert stop_row["price"] == 97.75  # adverse slippage follows the gap-open trigger fill
    actual_entry = strategy_state["strategy"].trade_metadata[0]["entry_price"]
    assert stop_row["stop_price"] == runner.percent_stop_price(actual_entry, "long")
    assert metrics["native_engine_metrics"]["total_commission"] == 5.0
    assert metrics["slippage_cost_usd"] == 10.0
    assert strategy_state["strategy"].trade_metadata[0]["quantity"] == 1.0
