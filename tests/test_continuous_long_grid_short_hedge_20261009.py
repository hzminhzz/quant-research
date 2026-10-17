"""Contracts for uninterrupted anchored long grid with hedge-only shorts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import yaml
from ml4t.backtest.types import OrderStatus

from scripts.run_continuous_long_grid_short_hedge_20261009 import (
    CONF,
    HedgeFirstContinuous,
    dataset_panel,
    derive_run_config,
    utc,
)
from scripts.run_hyperliquid_xyz_full_ladder_ab_20261009 import CFG_PATH


class DummyBroker:
    def __init__(self):
        self.orders = {}
        self.created = 0
        self.cancelled = 0

    def get_order(self, id_):
        return self.orders.get(id_)

    def cancel_order(self, id_):
        order = self.orders[id_]
        order.status = OrderStatus.CANCELLED
        self.cancelled += 1
        return True

    def submit_order(self, asset, signed_qty, order_type=None, limit_price=None):
        self.created += 1
        order = SimpleNamespace(
            order_id=f"test{self.created}",
            asset=asset,
            quantity=abs(signed_qty),
            status=OrderStatus.PENDING,
            limit_price=limit_price,
            direction="buy" if signed_qty > 0 else "sell",
        )
        self.orders[order.order_id] = order
        return order


@pytest.fixture
def spec():
    return yaml.safe_load(CONF.read_text())


@pytest.fixture
def config(spec):
    base = yaml.safe_load(CFG_PATH.read_text())
    return derive_run_config(base, spec, spec["datasets"][0], partial=True)


def test_long_only_grid_and_hedge_cap_frozen(config):
    assert config["capital"]["starting_cash_usdc"] == 600
    assert config["capital"]["leverage"] == 10
    assert config["capital"]["peak_to_trough_stop_usdc"] == 200
    assert config["capital"]["max_gross_usdc"] == 6000
    assert config["order"]["n_levels"] == 20
    assert config["order"]["clip_usdc"] == 100
    assert config["trials"][0]["arm"] == "dynamic_hedge"
    assert config["trials"][0]["subbasket"] is False


def test_standalone_short_never_quoted_when_no_long_filled(config):
    s = HedgeFirstContinuous("A4", config, 0.63, True, False, 0)
    broker = DummyBroker()
    s.baskets["pair"].anchor = {"SP500": 7000, "XYZ100": 30000}
    marks = {"SP500": 7000, "XYZ100": 30000}
    s._linked(marks, {"rolling_beta": 0.63}, broker)
    assert len([m for m in s.orders.values() if m.role == "entry"]) == 20
    assert len([m for m in s.orders.values() if m.asset == "XYZ100"]) == 0


def test_short_exit_always_precedes_long_exit_and_does_not_chase(config):
    s = HedgeFirstContinuous("A4", config, 0.63, True, False, 0)
    broker = DummyBroker()
    b = s.baskets["pair"]
    b.anchor = {"SP500": 7000, "XYZ100": 30000}
    b.phase = "exit"
    b.signed_qty.update({"SP500": 0.1, "XYZ100": -0.02})
    b.cashflow = -700 + 600
    prices = {"SP500": 7050, "XYZ100": 29500}
    s._linked(prices, {}, broker)
    assert "exit:XYZ100" in b.orders
    assert "exit:SP500" not in b.orders
    oid = b.orders["exit:XYZ100"]
    created = broker.created
    # A fixed passive cover limit must not get canceled and chased every bar.
    s._linked({"SP500": 7055, "XYZ100": 29450}, {}, broker)
    assert b.orders["exit:XYZ100"] == oid
    assert broker.created == created
    # After the cover actually fills, only the long basket may exit.
    b.signed_qty["XYZ100"] = 0.0
    b.cashflow -= 0.02 * 29490
    s._linked({"SP500": 7055, "XYZ100": 29490}, {}, broker)
    assert "exit:XYZ100" not in b.orders
    assert "exit:SP500" in b.orders
    ask = broker.orders[b.orders["exit:SP500"]]
    required = (b.carry + config["order"]["net_breakeven_reserve_usdc"] - b.cashflow) / b.signed_qty["SP500"]
    assert ask.limit_price >= required - 1e-8


def test_hedge_reduction_cannot_create_independent_long(config):
    s = HedgeFirstContinuous("A4", config, 0.63, True, False, 0)
    broker = DummyBroker()
    b = s.baskets["pair"]
    b.anchor = {"SP500": 7000, "XYZ100": 30000}
    b.signed_qty.update({"SP500": 0.1, "XYZ100": -0.02})
    s._quote_hedge_only({"SP500": 7000, "XYZ100": 30000}, broker)
    reductions = [x for x in s.orders.values() if x.role == "hedge_reduce"]
    assert len(reductions) == 1
    assert reductions[0].side == 1
    assert reductions[0].qty_requested <= abs(b.signed_qty["XYZ100"]) + 1e-8


def test_datasets_are_distinct_venues(spec):
    kinds = [d["id"] for d in spec["datasets"]]
    assert kinds == ["hyperliquid_hip3", "lighter_spy_qqq"]
    assert utc(spec["datasets"][1]["trading_start"]) < utc(spec["datasets"][0]["trading_start"])
    assert spec["datasets"][1]["price_tick"] != spec["datasets"][0]["price_tick"]


def test_smoke_load_real_data_without_merge(config, spec):
    panel = dataset_panel(spec["datasets"][0], config)
    assert panel.height > 200000
    assert panel["timestamp"].is_sorted()
    assert panel["timestamp"].n_unique() == panel.height
