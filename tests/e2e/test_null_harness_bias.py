"""Null tests: the backtest harness must not manufacture edge from nothing.

These tests make no claim that any real strategy has alpha. They assert only
that a signal carrying no information earns nothing. A strategy that passes
them has proved nothing about itself; a strategy that fails them has proved
the harness is broken.

The null is taken over independent draws of the (price path, signal) pair, not
over permutations of one signal on one path. Permuting a dense signal on a
single path keeps roughly the same bar coverage, so the mean outcome tracks
that path's own drift and the test would report harness bias that is really
just a trending market. Averaging over fresh paths removes that confound.

Friction is handled separately. A random timer is expected to lose after costs
and to break even before them, so the two regimes carry opposite assertions.
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.backtest import run_intraday_backtest
from tests.e2e._market import DEFAULT_HOLDING_BARS, ohlcv, random_walk

pytestmark = pytest.mark.e2e

N_BARS = 1024
DRAWS = 60
SEED = 20261009
SIGNAL_DENSITY = 0.30
MEAN_STD_ERRORS = 3.0


def _draw(index: int) -> pl.DataFrame:
    closes = random_walk(N_BARS, seed=SEED + index)
    rng = np.random.default_rng(SEED + 100_000 + index)
    return ohlcv(closes, rng.random(N_BARS) < SIGNAL_DENSITY)


def _run(frame: pl.DataFrame, commission_bps: float, slippage_bps: float) -> dict:
    return run_intraday_backtest(
        frame,
        entry_signal_col="signal",
        holding_bars=DEFAULT_HOLDING_BARS,
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
    )


def _collect(commission_bps: float, slippage_bps: float) -> tuple[np.ndarray, np.ndarray]:
    returns, sharpes, trade_counts = [], [], []
    for index in range(DRAWS):
        result = _run(_draw(index), commission_bps, slippage_bps)
        returns.append(result["total_return_pct"])
        sharpes.append(result["annualized_sharpe"])
        trade_counts.append(result["total_trades"])

    assert max(trade_counts) > 0, "no draw produced a trade, so nothing was measured"
    return np.asarray(returns), np.asarray(sharpes)


def _standard_error(values: np.ndarray) -> tuple[float, float]:
    mean = float(np.mean(values))
    spread = float(np.std(values, ddof=1))
    assert spread > 0.0, "every draw produced the same value, so nothing was measured"
    return mean, spread / np.sqrt(values.size)


def test_flat_market_produces_zero_pnl() -> None:
    """A constant price with no signals must report exactly no activity."""
    frame = ohlcv(np.full(512, 100.0), np.zeros(512, dtype=bool))
    result = _run(frame, commission_bps=2.0, slippage_bps=1.0)

    assert result["total_trades"] == 0
    assert result["ending_equity"] == result["initial_capital"]
    assert result["total_return_pct"] == 0.0
    assert result["win_rate_pct"] == 0.0
    assert result["max_drawdown_pct"] == 0.0
    assert result["annualized_sharpe"] == 0.0

    equity = result["daily_equity"]
    assert equity.height >= 3, "too few daily marks to build a Sharpe ratio"
    assert equity["equity"].to_list() == pytest.approx([100_000.0] * equity.height)


def test_informationless_signal_has_zero_mean_return_before_friction() -> None:
    """With no costs, a random timer must break even in expectation."""
    returns, sharpes = _collect(commission_bps=0.0, slippage_bps=0.0)

    mean, standard_error = _standard_error(returns)
    assert abs(mean) < MEAN_STD_ERRORS * standard_error, (
        f"mean return {mean:.4f}% is more than {MEAN_STD_ERRORS} standard errors "
        f"({standard_error:.4f}%) from zero; the harness manufactures edge from "
        "an informationless signal"
    )

    mean_sharpe, sharpe_error = _standard_error(sharpes)
    assert abs(mean_sharpe) < MEAN_STD_ERRORS * sharpe_error, (
        f"mean Sharpe {mean_sharpe:.4f} is more than {MEAN_STD_ERRORS} standard "
        f"errors ({sharpe_error:.4f}) from zero"
    )


def test_informationless_signal_is_not_profitable_after_friction() -> None:
    """With documented costs, a random timer must lose on average."""
    returns, sharpes = _collect(commission_bps=2.0, slippage_bps=1.0)

    mean, standard_error = _standard_error(returns)
    assert mean < -MEAN_STD_ERRORS * standard_error, (
        f"mean return {mean:.4f}% is not confidently negative "
        f"(threshold {-MEAN_STD_ERRORS * standard_error:.4f}%); friction is not "
        "being charged to a signal that carries no information"
    )

    mean_sharpe, sharpe_error = _standard_error(sharpes)
    assert mean_sharpe < -MEAN_STD_ERRORS * sharpe_error, (
        f"mean Sharpe {mean_sharpe:.4f} is not confidently negative"
    )


def test_trade_count_never_exceeds_signal_count() -> None:
    """Each trade consumes one signal bar; the engine cannot invent entries."""
    frame = _draw(0)
    result = _run(frame, commission_bps=2.0, slippage_bps=1.0)

    assert result["total_trades"] > 0
    assert result["total_trades"] <= int(frame["signal"].sum())
