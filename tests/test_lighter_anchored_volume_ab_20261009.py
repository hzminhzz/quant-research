"""Verify anchored independent cycles, linked hedge, and limit-only fill constraints."""

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest
import yaml

from scripts.run_lighter_anchored_volume_ab_20261009 import (
    DEFAULT_CONFIG,
    AnchoredVolumeStrategy,
    Cycle,
    WholeClipVolumeGate,
    price_feed,
    report_one,
    round_price,
    round_qty,
)


@pytest.fixture
def config():
    return yaml.safe_load(DEFAULT_CONFIG.read_text())


def synthetic(n: int = 20, volume: float = 10.0, lows=None, highs=None):
    origin = datetime(2026, 2, 22, tzinfo=UTC)
    times = [origin + timedelta(minutes=i) for i in range(n)]
    data = {
        "timestamp": times,
        "open_spy": [100.0] * n,
        "high_spy": highs if highs is not None else [100.2] * n,
        "low_spy": lows if lows is not None else [99.8] * n,
        "close_spy": [100.0] * n,
        "volume_spy": [volume] * n,
        "open_qqq": [100.0] * n,
        "high_qqq": highs if highs is not None else [100.2] * n,
        "low_qqq": lows if lows is not None else [99.8] * n,
        "close_qqq": [100.0] * n,
        "volume_qqq": [volume] * n,
        "rolling_beta": [0.3] * n,
    }
    return pl.DataFrame(data)


def test_volume_gate_blocks_zero_and_oversized_clips():
    gate = WholeClipVolumeGate(max_fraction=0.25)
    assert gate.calculate(1.0, 0.0, 100.0).fillable_quantity == 0
    assert gate.calculate(1.0, 3.0, 100.0).fillable_quantity == 0
    assert gate.calculate(1.0, 4.0, 100.0).fillable_quantity == 1


def test_orders_round_away_from_mid_and_quantity_down():
    assert round_price(100.019, 1, 0.01) == 100.01
    assert round_price(100.011, -1, 0.01) == 100.02
    assert round_qty(0.11234567, 0.0001) == pytest.approx(0.1123)


def test_cashflow_revaluation_for_single_and_two_leg_baskets():
    spy = Cycle("spy", anchor={"SPY": 100.0})
    spy.qty["SPY"] = 1.0
    spy.cashflow = -99.0
    spy.carry = 0.20
    assert spy.value_if_flat({"SPY": 100.0, "QQQ": 100.0}) == pytest.approx(0.8)
    linked = Cycle("linked")
    linked.qty = {"SPY": 1.0, "QQQ": -0.3}
    linked.cashflow = -99.0 + 30.0
    linked.carry = 0.2
    assert linked.value_if_flat({"SPY": 100, "QQQ": 100}) == pytest.approx(0.8)


def test_independent_anchors_are_not_shared(config):
    a = AnchoredVolumeStrategy("A", config, 0.3, 1.0, 0.0)
    assert set(a.groups) == {"spy", "qqq"}
    spy, qqq = a.groups["spy"], a.groups["qqq"]
    spy.anchor = {"SPY": 100, "QQQ": 100}
    qqq.anchor = {"SPY": 100, "QQQ": 100}
    spy.last_anchor = {"SPY": 100, "QQQ": 100}
    spy.anchor = {"SPY": 102, "QQQ": 100}
    assert qqq.anchor["SPY"] == 100


def test_hedge_is_linked_for_0_50_75_100_percent(config):
    for variant in ("A0", "A1", "A2", "A3", "A4"):
        s = AnchoredVolumeStrategy(variant, config, 0.3, 1, 0)
        assert set(s.groups) == {"linked"}


def test_zero_volume_means_no_maker_fills(config):
    prices, context = price_feed(synthetic(6, volume=0), 1.0)
    for v in ("A", "A0", "A3"):
        row = report_one(v, prices, context, config, 0.3, 1.0, 0.0)
        assert row["estimated_maker_notional_usdc"] == 0
        assert row["simulated_maker_fills"] == 0


def test_both_independent_baskets_can_complete_without_loss(config):
    prices, context = price_feed(synthetic(16), 1.0)
    result = report_one("A", prices, context, config, 0.3, 1.0, 0.0)
    assert result["simulated_maker_fills"] > 0
    assert result["unattributed_fills"] == 0
    assert result["group_results"]["spy"]["completed_negative_cycles"] == 0
    assert result["group_results"]["qqq"]["completed_negative_cycles"] == 0
    assert result["group_results"]["spy"]["completed_cycles"] >= 1
    assert result["group_results"]["qqq"]["completed_cycles"] >= 1


def test_qqq_can_recycle_shorts_while_spy_long_remains_underwater(config):
    n = 36
    frame = synthetic(n).with_columns(
        pl.Series("high_spy", [100.2, 100.2] + [98.1] * (n - 2)),
        pl.Series("low_spy", [99.8, 99.8] + [97.9] * (n - 2)),
        pl.Series("close_spy", [100.0, 100.0] + [98.0] * (n - 2)),
    )
    prices, context = price_feed(frame, 1.0)
    row = report_one("A", prices, context, config, 0.3, 1.0, 0.0)
    assert row["group_results"]["qqq"]["completed_cycles"] >= 3
    assert row["group_results"]["spy"]["completed_cycles"] == 0
    assert row["group_results"]["spy"]["open_inventory"].get("SPY", 0) > 0


def test_stricter_participation_prevents_fills(config):
    prices, context = price_feed(synthetic(8, volume=0.1), 1.0)
    row = report_one("A", prices, context, config, 0.3, 0.25, 0.0)
    assert row["simulated_maker_fills"] == 0


def test_fixed_anchor_exit_requires_nonnegative_cashflow(config):
    s = AnchoredVolumeStrategy("A", config, 0.3, 1.0, 0.0)
    g = s.groups["spy"]
    g.anchor = {"SPY": 100.0, "QQQ": 100.0}
    g.qty["SPY"] = 1.0
    g.cashflow = -100.0
    g.carry = 0.5
    required = s._single_exit_price(g, "SPY", {"SPY": 99, "QQQ": 99})
    assert required >= 100.55
