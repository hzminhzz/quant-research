"""Twenty-level anchored grid contracts and native ML4T execution checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import polars as pl
import pytest
import yaml

from scripts.run_hyperliquid_xyz_full_ladder_ab_20261009 import (
    CFG_PATH,
    FullLadder,
    SharedVolumeBudget,
    feed,
    passive_price,
    quantize,
    trial,
)


@pytest.fixture
def cfg():
    return yaml.safe_load(CFG_PATH.read_text())


def toy_feed(cfg, n: int = 12, *, zero_vol: bool = False):
    stamps = [datetime(2026, 5, 1, tzinfo=UTC) + timedelta(minutes=i) for i in range(n)]
    df = pl.DataFrame({
        "timestamp": stamps,
        "open_sp500": [7000.0] * n,
        "high_sp500": [7100.0 if i < 3 else 7000.0 for i in range(n)],
        "low_sp500": [6900.0 if i < 3 else 7000.0 for i in range(n)],
        "close_sp500": [7000.0] * n,
        "volume_sp500": [0.0 if zero_vol else 1000.0] * n,
        "open_xyz100": [30000.0] * n,
        "high_xyz100": [30500.0 if i < 3 else 30000.0 for i in range(n)],
        "low_xyz100": [29500.0 if i < 3 else 30000.0 for i in range(n)],
        "close_xyz100": [30000.0] * n,
        "volume_xyz100": [0.0 if zero_vol else 2000.0] * n,
        "rolling_beta": [0.63] * n,
        "after_gap": [False] * n,
    })
    return feed(df, cfg)


def test_frozen_grid_and_leverage_contract(cfg):
    assert cfg["order"]["n_levels"] >= 20
    assert cfg["order"]["clip_usdc"] == 100
    assert cfg["capital"]["starting_cash_usdc"] == 600
    assert cfg["capital"]["leverage"] == 10
    assert cfg["capital"]["max_gross_usdc"] == 6000
    assert cfg["capital"]["max_per_leg_usdc"] >= cfg["order"]["n_levels"] * cfg["order"]["clip_usdc"]


def test_price_and_quantity_are_passive_and_finite():
    assert passive_price(100.199, 1, 0.1) == 100.1
    assert passive_price(100.101, -1, 0.1) == 100.2
    assert quantize(0.12345678, 0.000001) == pytest.approx(0.123456)


def test_shared_bar_volume_budget_consumes_at_most_once():
    gate = SharedVolumeBudget(0.10, partial=True)
    broker = SimpleNamespace(
        _bar_index=1,
        _current_volumes={"SP500": 10.0, "XYZ100": 20.0},
        _current_opens={"SP500": 7000.0, "XYZ100": 30000.0},
    )
    gate.bind(broker)
    x = [gate.calculate(0.4, 10.0, 7000.0).fillable_quantity for _ in range(4)]
    assert x == pytest.approx([0.4, 0.4, 0.2, 0.0])
    assert gate.consumed[(1, "SP500")] == pytest.approx(1)
    assert gate.calculate(1.7, 20.0, 30000.0).fillable_quantity == pytest.approx(1.7)
    assert gate.calculate(0.5, 20.0, 30000.0).fillable_quantity == pytest.approx(0.3)
    assert gate.max_overshoot <= 1e-9
    broker._bar_index = 2
    assert gate.calculate(0.5, 10.0, 7000.0).fillable_quantity == 0.5


def test_shared_gate_fails_closed_on_ambiguous_and_zero_volume():
    gate = SharedVolumeBudget(0.10, partial=True)
    broker = SimpleNamespace(
        _bar_index=1,
        _current_volumes={"SP500": 5.0, "XYZ100": 5.0},
        _current_opens={"SP500": 7000.0, "XYZ100": 30000.0},
    )
    gate.bind(broker)
    assert gate.calculate(0.5, 5.0, 30000.0).fillable_quantity == 0.5
    assert gate.calculate(0.2, 5.0, 9000.0).fillable_quantity == 0.0
    assert gate.ambiguous == 1
    broker._bar_index = 2
    broker._current_volumes = {"SP500": 0.0, "XYZ100": 3.0}
    assert gate.calculate(0.01, 0.0, 7000).fillable_quantity == 0.0


def test_full_ladder_uses_40_simultaneous_resting_orders(cfg):
    prices, ctx = toy_feed(cfg, n=3, zero_vol=True)
    out = trial(cfg, "A_full20", prices, ctx, init_beta=0.63)
    assert out["maximum_resting_entry_orders"] == 40
    assert out["maker_fill_events"] == 0
    assert out["candidate_maker_volume"] == 0
    assert out["maximum_reserved_entry_notional"] == pytest.approx(4000, abs=1.0)
    assert out["maximum_reserved_plus_open_gross"] <= 6000.0 + 1.0


def test_hedged_ladder_does_not_short_without_sp500_inventory(cfg):
    prices, ctx = toy_feed(cfg, n=3, zero_vol=True)
    out = trial(cfg, "A4_full20", prices, ctx, init_beta=0.63)
    assert out["maximum_resting_entry_orders"] == 20
    assert out["candidate_maker_volume"] == 0
    assert out["cycles"]["pair"]["open_signed_qty"]["XYZ100"] == 0


def test_touch_without_volume_never_makes_volume(cfg):
    prices, ctx = toy_feed(cfg, n=6, zero_vol=True)
    for variant in ("A_full20", "A_partial20", "A4_full20"):
        out = trial(cfg, variant, prices, ctx, init_beta=0.63)
        assert out["maker_fill_events"] == 0
        assert out["partial_fill_events"] == 0


def test_more_than_one_level_can_fill_same_minute_without_volume_overrun(cfg):
    prices, ctx = toy_feed(cfg, n=400, zero_vol=False)
    out = trial(cfg, "A_full20", prices, ctx, init_beta=0.63)
    assert out["maker_fill_events"] > 1
    assert out["shared_bar_budget_max_overshoot"] == pytest.approx(0)
    assert out["uncertain_asset_fill_blocks"] == 0
    assert out["maximum_reserved_plus_open_gross"] <= 6000 + 1


def test_partial_mode_preserves_order_fill_accounting(cfg):
    prices, ctx = toy_feed(cfg, n=400, zero_vol=False)
    partial = trial(cfg, "A_partial20", prices, ctx, init_beta=0.63)
    assert partial["shared_bar_budget_max_overshoot"] == pytest.approx(0)
    assert partial["candidate_maker_volume"] >= 0
    assert partial["maker_fill_events"] >= partial["partial_fill_events"]


def test_emergency_taker_is_not_a_clean_completed_maker_cycle(cfg):
    prices, context = toy_feed(cfg, n=400, zero_vol=False)
    t = datetime(2026, 5, 1, tzinfo=UTC) + timedelta(minutes=3)
    changed = (pl.col("timestamp") >= t)
    new_prices = (prices.with_columns(
        pl.when(changed & (pl.col("symbol") == "SP500")).then(6500.0)
        .when(changed & (pl.col("symbol") == "XYZ100")).then(33000.0)
        .otherwise(pl.col("open")).alias("open"),
        pl.when(changed & (pl.col("symbol") == "SP500")).then(6500.0)
        .when(changed & (pl.col("symbol") == "XYZ100")).then(33000.0)
        .otherwise(pl.col("close")).alias("close"),
        pl.when(changed & (pl.col("symbol") == "SP500")).then(6501.0)
        .when(changed & (pl.col("symbol") == "XYZ100")).then(33001.0)
        .otherwise(pl.col("high")).alias("high"),
        pl.when(changed & (pl.col("symbol") == "SP500")).then(6499.0)
        .when(changed & (pl.col("symbol") == "XYZ100")).then(32999.0)
        .otherwise(pl.col("low")).alias("low"),
    ))
    out = trial(cfg, "A_full20", new_prices, context, init_beta=0.63)
    assert out["risk_halt"]
    assert out["taker_emergency_notional"] > 0
    assert out["completed_volume"] < out["candidate_maker_volume"]
    assert sum(g["negative_completed_cycles"] for g in out["cycles"].values()) == 0


def test_unsupported_subbasket_on_hedge_rejected(cfg):
    with pytest.raises(ValueError, match="Unsupported"):
        FullLadder("A4", cfg, 0.63, True, True, 0)
