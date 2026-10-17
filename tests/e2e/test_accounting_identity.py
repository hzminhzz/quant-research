"""Accounting identity: the reported summary must reconcile to the trade ledger.

Each test rebuilds a reported metric from ``result["trades"]`` and requires an
exact match. A silent change in the engine's money handling breaks these even
when the headline Sharpe still looks reasonable.
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.backtest import run_intraday_backtest
from tests.e2e._market import (
    BARS_PER_DAY,
    DEFAULT_HOLDING_BARS,
    ohlcv,
    periodic_signal,
    random_walk,
)

pytestmark = pytest.mark.e2e

N_BARS = 1536
EVERY = 12
SEED = 20261009
INITIAL_CAPITAL = 100_000.0


@pytest.fixture(scope="module")
def result() -> dict:
    """One flat-at-the-end run, shared by every reconciliation test."""
    closes = random_walk(N_BARS, seed=SEED)
    frame = ohlcv(closes, periodic_signal(N_BARS, EVERY))
    run = run_intraday_backtest(
        frame,
        entry_signal_col="signal",
        holding_bars=DEFAULT_HOLDING_BARS,
        initial_capital=INITIAL_CAPITAL,
    )
    assert run["total_trades"] > 0
    return run


def test_trade_pnl_compounds_to_ending_equity(result: dict) -> None:
    compounded = float(result["initial_capital"])
    for trade in result["trades"]:
        compounded *= 1.0 + trade["net_pnl_pct"]

    assert result["ending_equity"] == pytest.approx(compounded, rel=1e-12)


def test_final_daily_mark_equals_ending_equity(result: dict) -> None:
    """The last bar must sit flat, so the last daily mark is settled cash."""
    daily = result["daily_equity"]
    assert daily["equity"][-1] == pytest.approx(result["ending_equity"], rel=1e-12)


def test_total_return_reconciles_with_ending_equity(result: dict) -> None:
    expected = (
        (result["ending_equity"] - result["initial_capital"])
        / result["initial_capital"]
        * 100.0
    )
    assert result["total_return_pct"] == pytest.approx(expected, rel=1e-12)


def test_win_rate_and_profit_factor_reconcile_with_trade_ledger(result: dict) -> None:
    trades = result["trades"]
    pnl = np.array([trade["net_pnl_pct"] for trade in trades], dtype=float)

    wins = float(pnl[pnl > 0].sum())
    losses = float(np.abs(pnl[pnl < 0].sum()))
    win_count = int((pnl > 0).sum())

    assert result["win_rate_pct"] == pytest.approx(
        win_count / len(trades) * 100.0, rel=1e-12
    )

    if losses > 0:
        expected_factor = wins / losses
    else:
        expected_factor = 10.0 if wins > 0 else 1.0
    assert result["profit_factor"] == pytest.approx(expected_factor, rel=1e-12)


def test_equity_stays_positive_and_drawdown_stays_bounded(result: dict) -> None:
    assert result["daily_equity"]["equity"].min() > 0.0
    assert 0.0 <= result["max_drawdown_pct"] <= 100.0
    assert result["ending_equity"] > 0.0


def test_daily_marks_are_unique_and_sorted(result: dict) -> None:
    """Sharpe must come from one settled mark per calendar day, not per bar."""
    daily = result["daily_equity"]
    dates = daily["date"].to_list()

    assert dates == sorted(dates)
    assert len(dates) == len(set(dates))
    assert len(dates) >= N_BARS // BARS_PER_DAY
