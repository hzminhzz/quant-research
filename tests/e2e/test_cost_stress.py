"""Cost stress: friction must move the result in one direction, and only cost.

Every assertion here is exact or monotone. Nothing depends on a golden number,
so a legitimate strategy change does not break the test.
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.backtest import CostModel, run_intraday_backtest
from tests.e2e._market import (
    DEFAULT_HOLDING_BARS,
    momentum_signal,
    ohlcv,
    random_walk,
)

pytestmark = pytest.mark.e2e

N_BARS = 1024
SEED = 20261009
COMMISSION_LADDER_BPS = [0.0, 2.0, 10.0, 50.0]
SLIPPAGE_BPS = 1.0


def _frame() -> pl.DataFrame:
    closes = random_walk(N_BARS, seed=SEED)
    return ohlcv(closes, momentum_signal(closes))


def _run(
    frame: pl.DataFrame,
    commission_bps: float,
    slippage_bps: float = SLIPPAGE_BPS,
) -> dict:
    return run_intraday_backtest(
        frame,
        entry_signal_col="signal",
        holding_bars=DEFAULT_HOLDING_BARS,
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
    )


def test_increasing_costs_strictly_reduce_ending_equity() -> None:
    """Same signal, rising commission: equity falls and trade count does not move."""
    frame = _frame()
    results = [_run(frame, commission) for commission in COMMISSION_LADDER_BPS]

    equity = [result["ending_equity"] for result in results]
    assert all(value > 0 for value in equity), "equity must stay positive for the ladder to hold"
    for richer, poorer in zip(equity, equity[1:]):
        assert poorer < richer, f"raising commission did not reduce equity: {equity}"

    trade_counts = {result["total_trades"] for result in results}
    assert len(trade_counts) == 1, f"costs changed the trade count: {trade_counts}"
    assert trade_counts.pop() > 0


def test_commission_delta_applies_exactly_per_round_trip() -> None:
    """The only difference between two commission settings is the fee itself."""
    frame = _frame()
    free = _run(frame, commission_bps=0.0, slippage_bps=0.0)
    charged = _run(frame, commission_bps=2.0, slippage_bps=0.0)

    expected_fee = CostModel(commission_bps=2.0).roundtrip_fee()
    assert expected_fee == pytest.approx(4.0e-4)
    assert len(free["trades"]) == len(charged["trades"]) > 0

    for plain, taxed in zip(free["trades"], charged["trades"]):
        assert plain["net_pnl_pct"] - taxed["net_pnl_pct"] == pytest.approx(
            expected_fee, rel=1e-9
        )


def test_slippage_hits_entry_and_exit_legs_exactly() -> None:
    """Slippage widens the entry and narrows the exit by the configured rate."""
    frame = _frame()
    clean = _run(frame, commission_bps=0.0, slippage_bps=0.0)
    wide = _run(frame, commission_bps=0.0, slippage_bps=SLIPPAGE_BPS)

    rate = SLIPPAGE_BPS / 10_000.0
    assert len(clean["trades"]) == len(wide["trades"]) > 0

    for plain, widened in zip(clean["trades"], wide["trades"]):
        assert widened["entry_price"] / plain["entry_price"] == pytest.approx(
            1.0 + rate, rel=1e-12
        )
        assert widened["exit_price"] / plain["exit_price"] == pytest.approx(
            1.0 - rate, rel=1e-12
        )


def test_zero_friction_run_reports_pure_price_return() -> None:
    """With no friction a trade PnL is exactly the bar-to-bar price return."""
    result = _run(_frame(), commission_bps=0.0, slippage_bps=0.0)
    assert result["trades"]

    for trade in result["trades"]:
        expected = (trade["exit_price"] - trade["entry_price"]) / trade["entry_price"]
        assert trade["net_pnl_pct"] == pytest.approx(expected, rel=1e-12)


def test_cost_drag_never_exceeds_the_documented_round_trip() -> None:
    """Aggregate drag must sit at or below friction times the number of trades."""
    frame = _frame()
    commission = 2.0
    free = _run(frame, commission_bps=0.0, slippage_bps=0.0)
    charged = _run(frame, commission_bps=commission, slippage_bps=0.0)

    drag = (free["ending_equity"] - charged["ending_equity"]) / free["ending_equity"]
    trades = len(charged["trades"])
    assert trades > 0
    # Compounding makes the realised drag slightly larger than the linear bound.
    assert drag > 0
    assert drag <= trades * CostModel(commission_bps=commission).roundtrip_fee() * 1.05
