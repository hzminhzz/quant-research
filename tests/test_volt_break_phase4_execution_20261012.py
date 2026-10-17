from datetime import datetime, timedelta, timezone

import polars as pl

from ml4t.backtest import (
    AssetClass,
    BacktestConfig,
    ContractSpec,
    DataFeed,
    Engine,
    ExecutionMode,
    OrderType,
    StopFillMode,
    Strategy,
)
from ml4t.backtest.risk import PositionAction, PositionRule, PositionState, RuleChain


ASSET = "USATECH.IDX/USD"


def run_engine(rows, strategy, start=None):
    start = start or datetime(2024, 1, 8, 15, 0, tzinfo=timezone.utc)
    prices = pl.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=i) for i in range(len(rows))],
            "asset": [ASSET] * len(rows),
            "open": [row[0] for row in rows],
            "high": [row[1] for row in rows],
            "low": [row[2] for row in rows],
            "close": [row[3] for row in rows],
            "volume": [1.0] * len(rows),
        }
    )
    config = BacktestConfig(
        initial_cash=1_000_000,
        allow_short_selling=True,
        allow_leverage=True,
        fixed_margin_schedule={ASSET: (25_000.0, 20_000.0)},
        execution_mode=ExecutionMode.NEXT_BAR,
        stop_fill_mode=StopFillMode.STOP_PRICE,
    )
    spec = ContractSpec(
        symbol=ASSET,
        asset_class=AssetClass.FUTURE,
        multiplier=20,
        tick_size=0.25,
        margin=25_000.0,
    )
    return Engine(DataFeed(prices_df=prices), strategy, config, contract_specs={ASSET: spec}).run()


class NextOpenSignal(Strategy):
    def __init__(self, signal_time):
        self.fill = None
        self.signal_time = signal_time

    def on_data(self, timestamp, data, context, broker):
        if timestamp == self.signal_time:
            broker.submit_order(ASSET, 1)
        position = broker.get_position(ASSET)
        if position and self.fill is None:
            self.fill = (timestamp, position.entry_price)


def test_completed_0959_minute_callback_fills_at_1000_open():
    signal_time = datetime(2024, 1, 8, 15, 59, tzinfo=timezone.utc)
    strategy = NextOpenSignal(signal_time)
    result = run_engine(
        [(100.0, 101.0, 99.0, 100.5), (102.0, 103.0, 101.0, 102.5)],
        strategy,
        signal_time,
    )
    fills = result.to_fills_dataframe()
    assert fills.height == 1
    assert fills["price"][0] == 102.0
    assert fills["timestamp"][0].replace(tzinfo=timezone.utc) == datetime(
        2024, 1, 8, 16, 0, tzinfo=timezone.utc
    )


def test_signal_callback_at_1000_fills_one_minute_late_at_1001():
    signal_time = datetime(2024, 1, 8, 16, 0, tzinfo=timezone.utc)
    strategy = NextOpenSignal(signal_time)
    result = run_engine(
        [(100.0, 101.0, 99.0, 100.5), (102.0, 103.0, 101.0, 102.5)],
        strategy,
        signal_time,
    )
    fills = result.to_fills_dataframe()
    assert fills.height == 1
    assert fills["timestamp"][0].replace(tzinfo=timezone.utc) == datetime(
        2024, 1, 8, 16, 1, tzinfo=timezone.utc
    )


class EntryThenIndependentBracket(Strategy):
    def __init__(self):
        self.entered = False
        self.bracket_submitted = False

    def on_data(self, timestamp, data, context, broker):
        position = broker.get_position(ASSET)
        if not self.entered:
            broker.submit_order(ASSET, 1)
            self.entered = True
        elif position and not self.bracket_submitted:
            broker.submit_order(ASSET, -1, order_type=OrderType.LIMIT, limit_price=105.0)
            broker.submit_order(ASSET, -1, order_type=OrderType.STOP, stop_price=95.0)
            self.bracket_submitted = True


class EntryThenProtectiveStop(Strategy):
    def __init__(self):
        self.entered = False
        self.stop_submitted = False

    def on_data(self, timestamp, data, context, broker):
        position = broker.get_position(ASSET)
        if not self.entered:
            broker.submit_order(ASSET, 1)
            self.entered = True
        elif position and not self.stop_submitted:
            broker.submit_order(ASSET, -1, order_type=OrderType.STOP, stop_price=95.0)
            self.stop_submitted = True


def test_stop_market_gap_fills_at_source_open_beyond_stop_level():
    result = run_engine(
        [
            (100.0, 101.0, 99.0, 100.0),
            (100.0, 101.0, 99.0, 100.0),
            (90.0, 95.0, 89.0, 91.0),
        ],
        EntryThenProtectiveStop(),
    )
    fills = result.to_fills_dataframe()
    stop_fill = fills.filter(pl.col("order_type") == "stop")
    assert stop_fill.height == 1
    assert stop_fill["price"][0] == 90.0
    assert stop_fill["stop_price"][0] == 95.0


def test_independent_bracket_siblings_both_fill_when_one_minute_hits_target_and_stop():
    result = run_engine(
        [
            (100.0, 101.0, 99.0, 100.0),
            (100.0, 101.0, 99.0, 100.0),
            (100.0, 110.0, 90.0, 100.0),
        ],
        EntryThenIndependentBracket(),
    )
    fills = result.to_fills_dataframe()
    exit_fills = fills.filter(pl.col("side") == "sell")
    assert exit_fills.height == 2
    assert exit_fills["timestamp"].n_unique() == 1
    assert set(exit_fills["price"]) == {95.0, 105.0}
    assert result.to_trades_dataframe().filter(pl.col("status") == "open").height == 1


def test_bracket_submitted_after_entry_fill_leaves_entry_minute_unprotected():
    result = run_engine(
        [
            (100.0, 101.0, 99.0, 100.0),
            (100.0, 160.0, 10.0, 100.0),
        ],
        EntryThenIndependentBracket(),
    )
    fills = result.to_fills_dataframe()
    assert fills.height == 1
    assert fills["side"][0] == "buy"
    assert fills["timestamp"][0].replace(tzinfo=timezone.utc) == datetime(
        2024, 1, 8, 15, 1, tzinfo=timezone.utc
    )


class FixedPointBracket:
    """One native position rule: stop-first stress handling for absolute points."""

    def evaluate(self, state: PositionState) -> PositionAction:
        if not state.is_long:
            return PositionAction.hold()
        stop = state.entry_price - 75.0
        target = state.entry_price + 40.0
        if state.bar_open is not None and state.bar_open <= stop:
            return PositionAction.exit_full("stop_gap", fill_price=state.bar_open)
        if state.bar_low is not None and state.bar_low <= stop:
            return PositionAction.exit_full("stop", fill_price=stop)
        if state.bar_high is not None and state.bar_high >= target:
            fill = state.bar_open if state.bar_open is not None and state.bar_open >= target else target
            return PositionAction.exit_full("target", fill_price=fill)
        return PositionAction.hold()


class PositionRuleStrategy(Strategy):
    def __init__(self, rules):
        self.rules = rules
        self.entry_submitted = False
        self.rule_states = []

    def on_start(self, broker):
        broker.set_position_rules(self.rules, asset=ASSET)

    def on_data(self, timestamp, data, context, broker):
        if not self.entry_submitted:
            broker.submit_order(ASSET, 1)
            self.entry_submitted = True


def test_native_position_rule_does_not_evaluate_entry_fill_minute():
    rule = FixedPointBracket()
    strategy = PositionRuleStrategy(rule)
    result = run_engine(
        [
            (100.0, 101.0, 99.0, 100.0),
            (100.0, 145.0, 90.0, 100.0),  # entry bar crosses both barriers
            (100.0, 101.0, 99.0, 100.0),
        ],
        strategy,
    )
    fills = result.to_fills_dataframe()
    assert fills.height == 1
    assert fills["side"][0] == "buy"
    assert result.to_trades_dataframe().filter(pl.col("status") == "open").height == 1


def test_rule_chain_stop_first_dual_touch_uses_one_engine_owned_exit():
    class Hold:
        def evaluate(self, state):
            return PositionAction.hold()

    # RuleChain short-circuits after one action. A single bracket rule can
    # express fixed-point stop priority without submitting sibling orders.
    strategy = PositionRuleStrategy(RuleChain([FixedPointBracket(), Hold()]))
    result = run_engine(
        [
            (100.0, 101.0, 99.0, 100.0),
            (100.0, 101.0, 99.0, 100.0),
            (100.0, 145.0, 20.0, 100.0),
        ],
        strategy,
    )
    fills = result.to_fills_dataframe()
    exits = fills.filter(pl.col("side") == "sell")
    assert exits.height == 1
    assert exits["price"][0] == 25.0
    assert result.to_trades_dataframe().filter(pl.col("status") == "open").height == 0


def test_custom_position_rule_uses_fixed_point_levels_at_different_price_scales():
    # Exercise two independent Engine runs. Absolute point barriers must not
    # scale with entry price as percentage rules do.
    observations = []
    for entry in (100.0, 1000.0):
        strategy = PositionRuleStrategy(FixedPointBracket())
        result = run_engine(
            [
                (entry, entry + 1, entry - 1, entry),
                (entry, entry + 1, entry - 1, entry),
                (entry + 10, entry + 41, entry + 5, entry + 30),
            ],
            strategy,
        )
        exits = result.to_fills_dataframe().filter(pl.col("side") == "sell")
        observations.append(exits["price"][0])
    assert observations == [140.0, 1040.0]


def test_position_rule_stop_gap_and_single_target_touch_fill_once():
    for rows, expected, expected_pnl in (
        ([(100, 101, 99, 100), (100, 101, 99, 100), (20, 30, 15, 25)], 20.0, -1600.0),
        ([(100, 101, 99, 100), (100, 101, 99, 100), (100, 110, 20, 90)], 25.0, -1500.0),
        ([(100, 101, 99, 100), (100, 101, 99, 100), (100, 145, 95, 140)], 140.0, 800.0),
    ):
        result = run_engine(rows, PositionRuleStrategy(FixedPointBracket()))
        exits = result.to_fills_dataframe().filter(pl.col("side") == "sell")
        assert exits.height == 1
        assert exits["price"][0] == expected
        closed = result.to_trades_dataframe().filter(pl.col("status") == "closed")
        assert closed.height == 1
        assert closed["pnl"][0] == expected_pnl
        assert result.metrics["final_value"] == 1_000_000 + expected_pnl


def test_next_open_hard_exit_order_at_1429_fills_at_1430_open():
    class BoundaryExit(Strategy):
        entered = False

        def on_data(self, timestamp, data, context, broker):
            if timestamp.minute == 28 and not self.entered:
                broker.submit_order(ASSET, 1)
                self.entered = True
            if timestamp.minute == 29:
                broker.submit_order(ASSET, -1)

    start = datetime(2024, 1, 8, 20, 28, tzinfo=timezone.utc)  # 14:28 CT
    result = run_engine(
        [(100, 101, 99, 100), (100, 101, 99, 100), (103, 104, 102, 103)],
        BoundaryExit(),
        start,
    )
    fills = result.to_fills_dataframe()
    exit_fill = fills.filter(pl.col("side") == "sell")
    assert exit_fill.height == 1
    assert exit_fill["price"][0] == 103.0
    assert exit_fill["timestamp"][0].replace(tzinfo=timezone.utc) == datetime(
        2024, 1, 8, 20, 30, tzinfo=timezone.utc
    )
    trade = result.to_trades_dataframe().filter(pl.col("status") == "closed")
    assert trade.height == 1
    assert trade["pnl"][0] == 60.0
    assert result.metrics["final_value"] == 1_000_060.0
