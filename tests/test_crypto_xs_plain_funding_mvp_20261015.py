"""Focused causal and native-ledger tests for the plain funding MVP."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest
from ml4t.backtest import BacktestConfig, DataFeed, Engine
from ml4t.backtest.config import ExecutionPrice, ShareType
from ml4t.backtest.types import ExecutionMode

from scripts.run_crypto_xs_plain_funding_mvp_20261015 import (
    FundingBasketStrategy,
    attach_funding_24h,
    build_baskets,
    funding_cashflow,
)


def test_trailing_24h_funding_uses_actual_variable_events_and_is_causal():
    decision = datetime(2020, 1, 2, 0, tzinfo=UTC)
    decisions = pl.DataFrame({
        "symbol": ["AAAUSDT"],
        "decision_ts": [decision],
    })
    funding = pl.DataFrame({
        "symbol": ["AAAUSDT"] * 5,
        "timestamp": [
            datetime(2019, 12, 31, 23, tzinfo=UTC),
            datetime(2020, 1, 1, 1, tzinfo=UTC),
            datetime(2020, 1, 1, 8, tzinfo=UTC),
            datetime(2020, 1, 1, 20, tzinfo=UTC),
            datetime(2020, 1, 2, 0, 0, 0, 1000, tzinfo=UTC),
        ],
        "funding_rate": [0.9, 0.001, 0.002, 0.003, 0.004],
        "funding_interval_hours": [8, 7, 12, 4, 4],
        "mark_price": [100.0] * 5,
    })
    out = attach_funding_24h(decisions, funding)
    assert out.height == 1
    assert out["cum_funding_24h"][0] == pytest.approx(0.010)
    assert out["funding_events_24h"][0] == 4
    assert out["funding_observed_ts"][0] <= decision + timedelta(minutes=1)


def test_build_baskets_uses_exact_five_lowest_and_highest_funding_names():
    ts = datetime(2020, 6, 1, tzinfo=UTC)
    symbols = [f"S{i:02d}USDT" for i in range(20)]
    panel = pl.DataFrame({
        "decision_ts": [ts] * 20,
        "symbol": symbols,
        "cum_funding_24h": [i / 10000 for i in range(20)],
    })
    basket = build_baskets(panel)[ts]
    assert set(k for k, v in basket.items() if v > 0) == set(symbols[:5])
    assert set(k for k, v in basket.items() if v < 0) == set(symbols[-5:])
    assert sum(abs(v) for v in basket.values()) == pytest.approx(1.0)
    assert sum(basket.values()) == pytest.approx(0.0)


def test_funding_cashflow_sign_convention():
    assert funding_cashflow(2.0, 100.0, 0.001) == pytest.approx(-0.2)
    assert funding_cashflow(-2.0, 100.0, 0.001) == pytest.approx(0.2)
    assert funding_cashflow(2.0, 100.0, -0.001) == pytest.approx(0.2)


def test_native_broker_cash_ledger_receives_actual_funding_cashflow():
    start = datetime(2020, 6, 1, tzinfo=UTC)
    rows = []
    for i in range(4):
        ts = start + timedelta(hours=i)
        for symbol in ("A", "B"):
            rows.append({
                "timestamp": ts,
                "symbol": symbol,
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 1000.0,
            })
    prices = pl.DataFrame(rows).sort("timestamp", "symbol")
    event_hour = start + timedelta(hours=1)
    events = {
        event_hour: [
            {
                "timestamp": event_hour + timedelta(milliseconds=1),
                "symbol": "A",
                "funding_rate": 0.001,
                "mark_price": 100.0,
            },
            {
                "timestamp": event_hour + timedelta(milliseconds=1),
                "symbol": "B",
                "funding_rate": 0.002,
                "mark_price": 100.0,
            },
        ]
    }
    strategy = FundingBasketStrategy(
        {start: {"A": 0.5, "B": -0.5}},
        events,
        apply_funding=True,
        flatten_ts=start + timedelta(hours=2),
    )
    config = BacktestConfig(
        initial_cash=100_000,
        allow_short_selling=True,
        allow_leverage=True,
        share_type=ShareType.FRACTIONAL,
        execution_mode=ExecutionMode.NEXT_BAR,
        execution_price=ExecutionPrice.OPEN,
    )
    result = Engine(
        DataFeed(prices_df=prices, entity_col="symbol", timestamp_col="timestamp"),
        strategy,
        config,
    ).run()
    assert len(strategy.funding_ledger) == 2
    assert sum(row["cashflow"] for row in strategy.funding_ledger) == pytest.approx(50.0)
    assert result.metrics["final_value"] == pytest.approx(100_050.0)
    assert result.portfolio_state[-1][5] == 0
