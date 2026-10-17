from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest
import yaml

from scripts.run_metals_dual_grid_mvp_20261010 import (
    BETA_COLUMN,
    add_beta,
    make_two_minute_panel,
    run_arm,
)


def test_two_minute_aggregation_drops_incomplete_bucket() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [
        {
            "timestamp": start + timedelta(minutes=i),
            "symbol": symbol,
            "open": 100.0 + i,
            "high": 101.0 + i,
            "low": 99.0 + i,
            "close": 100.5 + i,
            "volume": 2.0,
        }
        for symbol in ("XAU", "XAG")
        for i in range(5)
    ]

    bars = make_two_minute_panel(pl.DataFrame(rows))
    xau = bars.filter(pl.col("symbol") == "XAU")

    assert bars.height == 4
    assert xau["timestamp"].to_list() == [start, start + timedelta(minutes=2)]
    assert xau.row(0, named=True) == {
        "timestamp": start,
        "symbol": "XAU",
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.5,
        "volume": 4.0,
    }


def test_beta_at_a_bar_excludes_that_bar_return() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    xau_returns = [
        0.001, -0.0004, 0.0007, -0.0008, 0.0003, 0.0012,
        -0.0006, 0.0009, -0.001, 0.0005, 0.0008, -0.0002,
    ]
    xag_returns = [
        0.0006, -0.0003, 0.0005, -0.0005, 0.0002, 0.0009,
        -0.0004, 0.0007, -0.0008, 0.0004, 0.0006, -0.0001,
    ]
    rows = []
    for symbol, returns in (("XAU", xau_returns), ("XAG", xag_returns)):
        close = 100.0
        for i, ret in enumerate(returns):
            close *= 1 + ret
            timestamp = start + timedelta(minutes=2 * i)
            rows.append({
                "timestamp": timestamp,
                "symbol": symbol,
                "open": close,
                "high": close + 0.01,
                "low": close - 0.01,
                "close": close,
                "volume": 10.0,
            })
    panel = pl.DataFrame(rows).sort(["symbol", "timestamp"])
    shock_index = 8
    shock_time = start + timedelta(minutes=2 * shock_index)
    shocked = panel.with_columns(
        pl.when(
            (pl.col("symbol") == "XAG")
            & (pl.col("timestamp") == shock_time)
        )
        .then(pl.col("close") * 1.05)
        .otherwise(pl.col("close"))
        .alias("close")
    )

    original_beta = add_beta(panel, lookback_bars=3)
    shocked_beta = add_beta(shocked, lookback_bars=3)
    current = start + timedelta(minutes=2 * shock_index)
    following = current + timedelta(minutes=2)
    original_now = original_beta.filter(
        (pl.col("symbol") == "XAU") & (pl.col("timestamp") == current)
    )[BETA_COLUMN][0]
    shocked_now = shocked_beta.filter(
        (pl.col("symbol") == "XAU") & (pl.col("timestamp") == current)
    )[BETA_COLUMN][0]
    original_next = original_beta.filter(
        (pl.col("symbol") == "XAU") & (pl.col("timestamp") == following)
    )[BETA_COLUMN][0]
    shocked_next = shocked_beta.filter(
        (pl.col("symbol") == "XAU") & (pl.col("timestamp") == following)
    )[BETA_COLUMN][0]

    assert shocked_now == pytest.approx(original_now)
    assert shocked_next != pytest.approx(original_next)


def test_risk_stop_flattens_signed_inventory() -> None:
    config_path = (
        Path(__file__).resolve().parents[1]
        / "config/research_sessions/metals_dual_grid_mvp_20261010.yaml"
    )
    cfg = yaml.safe_load(config_path.read_text())
    cfg["capital"]["max_gross_notional_usdc"] = 100.0
    start = datetime(2026, 2, 21, 16, 0, tzinfo=UTC)
    rows = [
        {
            "timestamp": start + timedelta(minutes=2 * bar),
            "symbol": symbol,
            "open": price,
            "high": price + (0.3 if bar else 0.0),
            "low": price - (0.3 if bar else 0.0),
            "close": price,
            "volume": volume,
            BETA_COLUMN: 1.5,
        }
        for bar in range(30)
        for symbol, price, volume in (("XAU", 100.0, 100.0), ("XAG", 50.0, 200.0))
    ]

    result = run_arm(
        pl.DataFrame(rows).sort(["symbol", "timestamp"]), cfg, "B"
    )

    assert result["risk_halted"]
    assert result["emergency_taker_notional_usdc"] > 0
    assert result["rejected_emergency_orders"] == 0
    assert result["unfilled_emergency_orders"] == 0
    assert result["unfinished_inventory_usdc"] == 0
    assert result["ending_inventory_notional_usdc"] == {"XAU": 0.0, "XAG": 0.0}
