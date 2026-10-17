"""P0 execution-contract tests for the frozen FX support study."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl
import pytest

from ml4t.backtest import (
    BacktestConfig,
    DataFeed,
    Engine,
    ExecutionMode,
    OrderStatus,
    OrderType,
    Strategy,
)
from ml4t.backtest.config import CommissionType, ExecutionPrice, ShareType, SlippageType
from tests.conftest import require_path

ROOT = Path(__file__).resolve().parents[1]
SESSION = "fx_support_ml4t_execution_20261008"


def _times(n: int = 5) -> list[datetime]:
    start = datetime(2024, 1, 2, tzinfo=timezone.utc)
    return [start + timedelta(minutes=5 * i) for i in range(n)]


def _bars(*, n: int = 5, opens=None, highs=None, lows=None, closes=None) -> pl.DataFrame:
    opens = opens or [1.10000] * n
    highs = highs or [1.10100] * n
    lows = lows or [1.09900] * n
    closes = closes or [1.10000] * n
    return pl.DataFrame({
        "timestamp": _times(n), "symbol": ["EURUSD"] * n,
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": [1000.0] * n,
    })


def _config(*, cash: float = 100_000.0) -> BacktestConfig:
    return BacktestConfig(
        execution_mode=ExecutionMode.NEXT_BAR,
        execution_price=ExecutionPrice.OPEN,
        initial_cash=cash,
        allow_leverage=False,
        share_type=ShareType.INTEGER,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=0.000025,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=0.00005,
    )


class _DecisionAt(Strategy):
    def __init__(self, decision_time: datetime):
        self.decision_time = decision_time
        self.entry = None

    def on_data(self, timestamp, data, context, broker):
        if timestamp == self.decision_time:
            self.entry = broker.submit_order("EURUSD", 1000)


def test_next_bar_submitted_after_decision_fills_one_bar_later() -> None:
    """Prove the P0 conflict with actual order timestamps and engine fills."""
    timestamps = _times(10)
    event_open = timestamps[0]
    decision = event_open + timedelta(minutes=30)
    assert decision == timestamps[6]
    required_first_open = decision
    strategy = _DecisionAt(decision)
    result = Engine(DataFeed(prices_df=_bars(n=10)), strategy, _config()).run()

    assert strategy.entry is not None
    assert strategy.entry.created_at == decision
    assert strategy.entry.status is OrderStatus.FILLED
    assert strategy.entry.filled_at == timestamps[7]
    assert result.metrics["num_fills"] == 1
    assert strategy.entry.filled_at != required_first_open
    # The earliest next-open fill is one full 5m step after a decision that
    # the strategy can first make at the decision timestamp.


class _BracketFixture(Strategy):
    def __init__(self, *, mode: str):
        self.mode = mode
        self.entry = None
        self.stop = None
        self.target = None
        self.close_order = None

    def on_data(self, timestamp, data, context, broker):
        if timestamp == _times()[0]:
            self.entry = broker.submit_order("EURUSD", 1000)
            return
        if timestamp == _times()[1] and broker.get_position("EURUSD"):
            if self.mode == "terminal":
                self.close_order = broker.close_position("EURUSD", order_type=OrderType.MOC)
                return
            self.stop = broker.submit_order(
                "EURUSD", -1000, order_type=OrderType.STOP, stop_price=1.09000
            )
            self.stop.parent_id = "fixture-oco"
            self.target = broker.submit_order(
                "EURUSD", -1000, order_type=OrderType.LIMIT, limit_price=1.11000
            )
            self.target.parent_id = "fixture-oco"


@pytest.mark.parametrize("mode, expected_exit, expected_status", [
    ("gap", 1.08000, OrderStatus.CANCELLED),
    ("tie", 1.09000, OrderStatus.CANCELLED),
])
def test_native_oco_priority_target_and_gap_fills(mode, expected_exit, expected_status) -> None:
    opens = [1.10000, 1.10000, 1.08000 if mode == "gap" else 1.10000, 1.10000, 1.10000]
    highs = [1.10100, 1.10100, 1.12000 if mode != "gap" else 1.08500, 1.10100, 1.10100]
    lows = [1.09900, 1.09900, 1.08000 if mode in ("tie", "gap") else 1.09500, 1.09900, 1.09900]
    strategy = _BracketFixture(mode=mode)
    result = Engine(
        DataFeed(prices_df=_bars(opens=opens, highs=highs, lows=lows)),
        strategy,
        _config(),
    ).run()

    assert strategy.entry is not None and strategy.entry.status is OrderStatus.FILLED
    assert strategy.entry.filled_at == _times()[1]
    assert strategy.stop is not None and strategy.target is not None
    assert strategy.stop.status is OrderStatus.FILLED
    assert strategy.target.status is expected_status
    assert strategy.stop.filled_at == _times()[2]
    if mode == "gap":
        assert strategy.stop.filled_price <= expected_exit
        assert strategy.stop.filled_price == pytest.approx(expected_exit * (1 - 0.00005))
    else:
        assert strategy.stop.filled_price == pytest.approx(expected_exit * (1 - 0.00005))
    assert len(result.trades) == 1
    assert result.trades[0].exit_price == pytest.approx(expected_exit * (1 - 0.00005))
    assert result.metrics["num_fills"] == 2


def test_target_wins_when_only_target_is_touched() -> None:
    highs = [1.10100, 1.10100, 1.12000, 1.10100, 1.10100]
    lows = [1.09900, 1.09900, 1.09500, 1.09900, 1.09900]
    strategy = _BracketFixture(mode="target")
    result = Engine(
        DataFeed(prices_df=_bars(highs=highs, lows=lows)),
        strategy,
        _config(),
    ).run()
    assert strategy.target is not None and strategy.stop is not None
    assert strategy.target.status is OrderStatus.FILLED
    assert strategy.stop.status is OrderStatus.CANCELLED
    assert strategy.target.filled_price == pytest.approx(1.11000 * (1 - 0.00005))
    assert result.trades[0].exit_price == pytest.approx(1.11000 * (1 - 0.00005))


def test_terminal_close_and_cash_rejection_are_recorded() -> None:
    terminal = _BracketFixture(mode="terminal")
    result = Engine(DataFeed(prices_df=_bars(n=3)), terminal, _config()).run()
    assert terminal.entry is not None and terminal.close_order is not None
    assert terminal.entry.filled_at == _times()[1]
    assert terminal.close_order.status is OrderStatus.FILLED
    assert terminal.close_order.filled_at == _times()[1]
    assert result.trades[0].status == "closed"
    assert result.trades[0].exit_time == _times()[1]

    class Oversized(Strategy):
        def __init__(self):
            self.order = None

        def on_data(self, timestamp, data, context, broker):
            if timestamp == _times()[0]:
                self.order = broker.submit_order("EURUSD", 100_000)

    oversized = Oversized()
    Engine(DataFeed(prices_df=_bars()), oversized, _config(cash=50_000)).run()
    assert oversized.order is not None
    assert oversized.order.status is OrderStatus.REJECTED
    assert oversized.order.rejection_code in {"insufficient_cash", "order_validation_failed"}


def test_round_trip_cost_units_match_frozen_fractional_rates() -> None:
    strategy = _BracketFixture(mode="terminal")
    result = Engine(DataFeed(prices_df=_bars(n=3)), strategy, _config()).run()
    trade = result.trades[0]
    expected_commission = abs(trade.quantity * trade.entry_price) * 0.000025
    expected_commission += abs(trade.quantity * trade.exit_price) * 0.000025
    assert trade.fees == pytest.approx(expected_commission, rel=1e-10)
    assert trade.entry_slippage == pytest.approx(1.1 * 0.00005, rel=1e-10)
    assert result.metrics["total_commission"] == pytest.approx(expected_commission, rel=1e-10)
    expected_slippage = abs(trade.quantity) * (trade.entry_slippage + trade.exit_slippage)
    assert result.metrics["total_slippage"] == pytest.approx(expected_slippage, rel=1e-10)


@pytest.mark.data
def test_frozen_oof_and_panel_identity_without_holdout_reads() -> None:
    frozen = json.loads(
        require_path(
            "run_log/research_sessions/fx_support_ml4t_execution_20261008/frozen_spec.json"
        ).read_text()
    )
    evidence = {item["path"]: item for item in frozen["identity"]["evidence"]}
    paths = [
        "data/features/fx_support_conditions_20261008.parquet",
        "data/features/fx_support_conditions_20261008_manifest.json",
        "run_log/fx_support_conditions_20261008_ml_v2/I4_purged_lightgbm_v2/scored_events.parquet",
    ]
    for relative in paths:
        digest = hashlib.sha256(require_path(relative).read_bytes()).hexdigest()
        assert evidence[relative]["sha256"] == digest

    panel_manifest = json.loads((ROOT / paths[1]).read_text())
    parent_path = ROOT / panel_manifest["source"]["path"]
    assert hashlib.sha256(parent_path.read_bytes()).hexdigest() == panel_manifest["source"]["sha256"]

    oof = pl.read_parquet(ROOT / paths[2])
    assert oof.height == 730
    assert oof.filter(pl.col("selected")).height == 112
    assert oof["event_timestamp"].max().year == 2024
    last_decision = oof.select(
        (pl.col("event_timestamp") + pl.duration(minutes=30)).max()
    ).item()
    assert last_decision.year == 2024
    assert oof.filter(pl.col("pred_probability") >= 0.30).height == 112
