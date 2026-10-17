"""Recovery tests: the backtest must report an edge that is actually present.

A harness that reports zero for every input is as broken as one that reports
profit for every input. These tests inject a known drift into the exact bars a
position would hold, then require the reported PnL to take the injected sign.
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.backtest import run_intraday_backtest
from tests.e2e._market import (
    DEFAULT_HOLDING_BARS,
    drift_during_holding,
    ohlcv,
    periodic_signal,
)

pytestmark = pytest.mark.e2e

N_BARS = 1536
EVERY = 12
SEED = 20261009
INJECTED_DRIFT = 0.001
MIN_TRADES = 10


def _run(injected_drift: float) -> tuple[pl.DataFrame, dict]:
    signal = periodic_signal(N_BARS, EVERY)
    closes = drift_during_holding(
        n=N_BARS,
        seed=SEED,
        signal=signal,
        holding_bars=DEFAULT_HOLDING_BARS,
        per_bar_drift=injected_drift,
    )
    frame = ohlcv(closes, signal)
    result = run_intraday_backtest(
        frame,
        entry_signal_col="signal",
        holding_bars=DEFAULT_HOLDING_BARS,
    )
    return frame, result


@pytest.mark.parametrize(
    "injected_drift, expected_sign",
    [(INJECTED_DRIFT, 1), (-INJECTED_DRIFT, -1)],
    ids=["drift_positive", "drift_negative"],
)
def test_harness_sign_tracks_injected_drift(injected_drift: float, expected_sign: int) -> None:
    """The reported PnL must follow the sign of the drift inside holding bars."""
    _, result = _run(injected_drift)

    assert result["total_trades"] >= MIN_TRADES
    per_trade = np.array([t["net_pnl_pct"] for t in result["trades"]], dtype=float)
    mean_trade = float(np.mean(per_trade))

    assert np.sign(mean_trade) == expected_sign, (
        f"injected drift {injected_drift:+.4f} produced mean trade PnL "
        f"{mean_trade:+.6f}"
    )
    assert np.sign(result["total_return_pct"]) == expected_sign, (
        f"injected drift {injected_drift:+.4f} produced total return "
        f"{result['total_return_pct']:+.4f}%"
    )


def test_injected_edge_survives_documented_costs() -> None:
    """A drift far above the friction model must still report positive PnL."""
    _, result = _run(INJECTED_DRIFT)

    per_trade = np.array([t["net_pnl_pct"] for t in result["trades"]], dtype=float)
    # Default friction: 2 bps commission per leg plus 1 bps slippage per leg.
    assert float(np.min(per_trade)) > -0.02, "a single trade lost far more than the drift budget"
    assert float(np.mean(per_trade)) > 4 * (2 * 2.0 / 10_000), (
        "mean trade PnL does not clear four times the documented round-trip commission"
    )


def test_every_timeout_exit_holds_the_configured_bar_count() -> None:
    """No exit signal is supplied, so every exit must be a clean timeout."""
    _, result = _run(INJECTED_DRIFT)

    reasons = {t["reason"] for t in result["trades"]}
    assert reasons == {"timeout"}, f"unexpected exit reasons: {reasons}"
    assert {t["bars_held"] for t in result["trades"]} == {DEFAULT_HOLDING_BARS}
