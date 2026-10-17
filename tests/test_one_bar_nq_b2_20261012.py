from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import polars as pl

from scripts.run_one_bar_nq_b2_20261012 import can_enter, mnq_quantity, protective_stop, stop_distance
from scripts.run_one_bar_nq_b2_yearly_20261012 import attach_signals, build_bars, is_evaluation_session_day, is_evaluation_session_year, metadata_for_filled_entry


def test_atr_distance_rounding_and_integer_risk_budget() -> None:
    distance = stop_distance(66.7)
    assert distance == 100.25
    assert mnq_quantity(distance) == 4
    assert mnq_quantity(distance) * distance * 2 <= 1000
    assert mnq_quantity(500.25) == 0


def test_protective_stop_uses_actual_entry_and_adverse_tick_rounding() -> None:
    assert protective_stop(100.125, 10.25, 4) == 89.75
    assert protective_stop(100.125, 10.25, -4) == 110.5


def test_daily_entry_cap_counts_filled_entries() -> None:
    day = date(2026, 10, 12)
    counts = {day: 0}
    assert can_enter(counts, day)
    counts[day] += 1
    assert can_enter(counts, day)
    counts[day] += 1
    assert not can_enter(counts, day)


def test_filled_order_keeps_its_own_atr_and_size_metadata() -> None:
    class Order:
        def __init__(self, order_id, status):
            self.order_id = order_id
            self.status = type("Status", (), {"value": status})()

    second = {"distance": 27.75, "atr20": 18.5, "signed_quantity": 18}
    filled = metadata_for_filled_entry([Order("L", "filled")], {"L": second}, 18)
    assert filled == second
    assert filled["signed_quantity"] * filled["distance"] * 2 <= 1000


def test_chicago_17_anchor_tracks_dst() -> None:
    tz = ZoneInfo("America/Chicago")
    winter = datetime(2026, 1, 5, 17, tzinfo=tz).astimezone(timezone.utc)
    summer = datetime(2026, 7, 6, 17, tzinfo=tz).astimezone(timezone.utc)
    assert winter.hour == 23
    assert summer.hour == 22


def test_warmup_bars_do_not_belong_to_annual_trading_account() -> None:
    assert not is_evaluation_session_year(datetime(2023, 12, 29, 16, tzinfo=timezone.utc), 2024)
    assert is_evaluation_session_year(datetime(2024, 1, 1, 23, tzinfo=timezone.utc), 2024)
    assert not is_evaluation_session_day(date(2025, 1, 1), 2024, date(2024, 12, 31))


def test_ml4t_atr20_is_released_only_after_complete_bar() -> None:
    start = datetime(2026, 1, 5, 23, tzinfo=timezone.utc)
    timestamps = [start + timedelta(minutes=i) for i in range(30 * 21)]
    minute = pl.DataFrame({"timestamp": timestamps, "open": [100.0] * len(timestamps),
        "high": [101.0] * len(timestamps), "low": [99.0] * len(timestamps),
        "close": [100.0] * len(timestamps), "volume": [1] * len(timestamps)})
    bars = build_bars(minute)
    first = bars.row(0, named=True)
    assert first["available_at"] == first["bar_start"] + timedelta(minutes=30)
    assert first["release_decision_at"] == first["available_at"] - timedelta(minutes=1)
    assert bars.filter(pl.col("atr20").is_finite()).height > 0
    assert bars.filter(pl.col("atr20").is_finite())["bar_start"].min() >= first["bar_start"] + timedelta(minutes=19 * 30)


def test_feature_asof_release_has_no_incomplete_bar_leakage() -> None:
    start = datetime(2026, 1, 5, 23, tzinfo=timezone.utc)
    timestamps = [start + timedelta(minutes=i) for i in range(30 * 22)]
    raw = pl.DataFrame({"timestamp": timestamps, "open": [100.0] * len(timestamps),
        "high": [101.0] * len(timestamps), "low": [99.0] * len(timestamps),
        "close": [100.0] * len(timestamps), "volume": [1] * len(timestamps)})
    bars = build_bars(raw)
    first_valid = bars.filter(pl.col("atr20").is_finite()).row(0, named=True)
    joined = attach_signals(raw, bars)
    before = joined.filter(pl.col("timestamp") == first_valid["release_decision_at"] - timedelta(minutes=1))[0, "atr20"]
    at_release = joined.filter(pl.col("timestamp") == first_valid["release_decision_at"])[0, "atr20"]
    assert before is None or math.isnan(before)
    assert at_release == first_valid["atr20"]


def test_native_engine_stop_uses_actual_fill_and_charges_each_contract_fill() -> None:
    from ml4t.backtest import AssetClass, BacktestConfig, CommissionType, ContractSpec, DataFeed, Engine, Strategy
    from ml4t.backtest.config import SlippageType
    from ml4t.backtest.types import ExecutionMode, OrderType, StopFillMode

    ts = [datetime(2026, 1, 5, 23, tzinfo=timezone.utc) + timedelta(minutes=i) for i in range(5)]
    prices = pl.DataFrame({"timestamp": ts, "asset": ["MNQ"] * 5,
        "open": [100.0, 100.0, 98.0, 98.0, 98.0], "high": [100.0, 101.0, 99.0, 99.0, 99.0],
        "low": [100.0, 99.0, 97.0, 97.0, 97.0], "close": [100.0, 100.0, 98.0, 98.0, 98.0]})

    class StopAfterFill(Strategy):
        def __init__(self): self.sent = False; self.stop = None; self.entry_price = None
        def on_data(self, timestamp, data, context, broker):
            pos = broker.get_position("MNQ")
            if not self.sent:
                broker.submit_order("MNQ", 4, order_type=OrderType.MARKET); self.sent = True
            elif pos and self.stop is None:
                self.entry_price = float(pos.entry_price)
                self.stop = protective_stop(self.entry_price, 1.0, float(pos.quantity))
                broker.submit_order("MNQ", -4, order_type=OrderType.STOP, stop_price=self.stop)

    config = BacktestConfig(initial_cash=100_000, allow_short_selling=True, allow_leverage=True,
        fixed_margin_schedule={"MNQ": (100, 50)}, execution_mode=ExecutionMode.NEXT_BAR,
        stop_fill_mode=StopFillMode.NEXT_BAR_OPEN, commission_type=CommissionType.PER_SHARE,
        commission_per_share=1.25, slippage_type=SlippageType.FIXED, slippage_fixed=0.25)
    strategy = StopAfterFill()
    result = Engine(DataFeed(prices_df=prices), strategy, config,
        contract_specs={"MNQ": ContractSpec("MNQ", AssetClass.FUTURE, multiplier=2, tick_size=.25, margin=100)}).run()
    fills = result.to_fills_dataframe()
    assert fills.height == 2
    assert fills["quantity"].abs().to_list() == [4.0, 4.0]
    assert fills["commission"].sum() == 10.0
    trades = result.to_trades_dataframe().filter(pl.col("status") == "closed")
    assert trades["total_slippage_cost"].sum() == 4.0
    assert float(fills.filter(pl.col("order_type") == "stop")["stop_price"][0]) == strategy.stop
    assert strategy.stop == protective_stop(strategy.entry_price, 1.0, 4.0)


def test_native_opposing_stops_can_both_fill_on_one_ohlc_bar() -> None:
    from ml4t.backtest import BacktestConfig, DataFeed, Engine, Strategy
    from ml4t.backtest.types import ExecutionMode, OrderType

    ts = [datetime(2026, 1, 5, 23, tzinfo=timezone.utc) + timedelta(minutes=i) for i in range(3)]
    prices = pl.DataFrame({"timestamp": ts, "asset": ["MNQ"] * 3,
        "open": [100.0, 100.0, 100.0], "high": [100.0, 102.0, 100.0],
        "low": [100.0, 98.0, 100.0], "close": [100.0, 100.0, 100.0]})

    class OpposingStops(Strategy):
        def __init__(self): self.sent = False
        def on_data(self, timestamp, data, context, broker):
            if not self.sent:
                broker.submit_order("MNQ", 1, order_type=OrderType.STOP, stop_price=101)
                broker.submit_order("MNQ", -1, order_type=OrderType.STOP, stop_price=99)
                self.sent = True

    result = Engine(DataFeed(prices_df=prices), OpposingStops(),
        BacktestConfig(initial_cash=100_000, allow_short_selling=True, allow_leverage=True,
            execution_mode=ExecutionMode.NEXT_BAR)).run()
    fills = result.to_fills_dataframe()
    assert fills.height == 2
    assert fills["timestamp"].n_unique() == 1
