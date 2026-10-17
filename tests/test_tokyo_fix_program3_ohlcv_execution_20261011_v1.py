"""Small deterministic independent execution-oracle regressions."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from scripts.verify_tokyo_fix_program3_ohlcv_execution_20261011_v1 import (
    dollar_pnl, expected_limit_fill, strict_cross, verify_run,
)

JST = ZoneInfo("Asia/Tokyo")
DAY = date(2024, 1, 5)


def bars():
    start = datetime(2024, 1, 5, 9, 54, tzinfo=JST)
    return [{"timestamp": start + timedelta(minutes=i), "session": DAY,
             "minute": 594 + i, "open": 150.0, "high": 150.0,
             "low": 149.98, "close": 150.0} for i in range(17)]


def test_strict_touch_and_buffer_for_both_sides():
    assert not strict_cross("sell", 150.0, 149.0, 150.0, 0.0)
    assert strict_cross("sell", 150.0001, 149.0, 150.0, 0.0)
    assert not strict_cross("sell", 150.005, 149.0, 150.0, 0.5)
    assert strict_cross("sell", 150.006, 149.0, 150.0, 0.5)
    assert not strict_cross("buy", 151.0, 150.0, 150.0, 0.0)
    assert strict_cross("buy", 151.0, 149.9999, 150.0, 0.0)
    assert not strict_cross("buy", 151.0, 149.995, 150.0, 0.5)
    assert strict_cross("buy", 151.0, 149.994, 150.0, 0.5)


@pytest.mark.parametrize("ref,limit,high,buffer", [
    (107.282, 107.282, 107.287, .5),
    (105.07, 105.075, 105.075, 0),
    (109.478, 109.483, 109.488, .5),
    (158.4835, 158.4935, 158.4935, 0),
    (157.182, 157.192, 157.197, .5),
])
def test_real_snapshot_decimal_exact_touch_is_never_cross(ref, limit, high, buffer):
    assert not strict_cross("sell", high, ref, limit, buffer)


def test_float_dust_cannot_create_strict_cross():
    assert not strict_cross("sell", 158.49350000000004, 158.4, 158.4885, .5)


def test_library_proxy_returns_do_not_use_mutated_future_bars():
    from ml4t.engineer import compute_features
    start = datetime(2024, 1, 5, 8, 30, tzinfo=JST)
    source = pl.DataFrame({"timestamp": [start + timedelta(minutes=i) for i in range(121)],
        "session": [DAY] * 121, "open": [150 + i * .001 for i in range(121)],
        "high": [150.01 + i * .001 for i in range(121)],
        "low": [149.99 + i * .001 for i in range(121)],
        "close": [150 + i * .001 for i in range(121)], "volume": [1.0] * 121})
    specs = [{"name": "multi_horizon_returns", "params": {"horizons": [1, 12, 24, 84], "log_returns": True}}]
    original = compute_features(source, specs, group_col="session", timestamp_col="timestamp", assume_sorted=True)
    future = source.with_columns(*[pl.when(pl.col("timestamp") >= start + timedelta(minutes=85))
        .then(pl.col(c) * 2).otherwise(pl.col(c)).alias(c) for c in ("open", "high", "low", "close")])
    mutated = compute_features(future, specs, group_col="session", timestamp_col="timestamp", assume_sorted=True)
    last_closed = start + timedelta(minutes=84)
    columns = [c for c in original.columns if c.startswith("multi_horizon_returns")]
    assert original.filter(pl.col("timestamp") == last_closed).select(columns).equals(
        mutated.filter(pl.col("timestamp") == last_closed).select(columns))


def test_no_same_bar_or_late_fill_and_ttl_boundary():
    source = bars()
    source[1]["high"] = 151.0  # Submission bar is excluded.
    source[4]["high"] = 150.01  # Final valid TTL=3 bar, 09:58.
    source[5]["high"] = 151.0  # 09:59 is outside both TTLs.
    assert expected_limit_fill(source, 150.0, 1, 0.0) is None
    assert expected_limit_fill(source, 150.0, 3, 0.0)["minute"] == 598
    source[4]["high"] = 150.0
    assert expected_limit_fill(source, 150.0, 3, 0.0) is None


def test_first_cross_is_selected_without_exit_knowledge():
    source = bars()
    source[2]["high"] = 150.01
    before = expected_limit_fill(source, 150.0, 3, 0.0)
    source[16]["open"] = 1000.0
    assert expected_limit_fill(source, 150.0, 3, 0.0) == before


def test_fixed_notional_jpy_to_usd_conversion_and_cost():
    assert dollar_pnl(150.0, 149.0) == pytest.approx(10000.0 / 149.0)
    assert dollar_pnl(150.0, 149.0, 1.4) == pytest.approx(9860.0 / 149.0)
    assert dollar_pnl(149.0, 150.0) == pytest.approx(-10000.0 / 150.0)
    with pytest.raises(ValueError):
        dollar_pnl(150.0, 0.0)


def fixture_run(fill=True):
    source = bars()
    source[2]["high"] = 150.01 if fill else 150.0
    panel = pl.DataFrame({"session": [DAY], "gotobi": [True], "ordinary": [False]})
    submit = source[1]["timestamp"]
    entry = {"session": DAY, "role": "entry", "submitted_at": submit,
             "fill_at": source[2]["timestamp"] if fill else None,
             "price": 150.0 if fill else None, "limit": 150.0,
             "quantity": -10000.0, "status": "filled" if fill else "cancelled"}
    orders = [entry]
    trades = []
    if fill:
        orders.append({"session": DAY, "role": "exit", "submitted_at": source[15]["timestamp"],
            "fill_at": source[16]["timestamp"], "price": 150.0,
            "limit": None, "quantity": 10000.0, "status": "filled"})
        trades.append({"session": DAY, "entry": 150.0, "exit": 150.0,
            "entry_time": source[2]["timestamp"], "exit_time": source[16]["timestamp"],
            "pnl_jpy": 0.0, "gross_usd": 0.0})
    trade_schema = {"session": pl.Date, "entry": pl.Float64, "exit": pl.Float64,
        "entry_time": pl.Datetime(time_zone="Asia/Tokyo"), "exit_time": pl.Datetime(time_zone="Asia/Tokyo"),
        "pnl_jpy": pl.Float64, "gross_usd": pl.Float64}
    return pl.DataFrame(orders), pl.DataFrame(trades, schema=trade_schema), panel, pl.DataFrame(source)


def test_audit_native_fill_and_missed_cancel_accounting():
    assert verify_run("limit_o0_t1_b0", *fixture_run())["fills_checked"] == 2
    assert verify_run("limit_o0_t1_b0", *fixture_run(False))["missed_checked"] == 1


def test_audit_rejects_phantom_fill():
    orders, trades, panel, source = fixture_run()
    source = source.with_columns(pl.lit(150.0).alias("high"))
    with pytest.raises(AssertionError, match="Phantom fill"):
        verify_run("limit_o0_t1_b0", orders, trades, panel, source)


def test_audit_rejects_wrong_close_timing():
    orders, trades, panel, source = fixture_run()
    orders = orders.with_columns(pl.when(pl.col("role") == "exit")
        .then(pl.col("fill_at") + pl.duration(minutes=1)).otherwise(pl.col("fill_at")).alias("fill_at"))
    with pytest.raises(AssertionError, match="Exit is not 10:10"):
        verify_run("limit_o0_t1_b0", orders, trades, panel, source)


def test_audit_rejects_wrong_usd_conversion_and_live_missed_order():
    orders, trades, panel, source = fixture_run()
    with pytest.raises(AssertionError, match="USD conversion"):
        verify_run("limit_o0_t1_b0", orders, trades.with_columns(pl.lit(10.0).alias("gross_usd")), panel, source)
    orders, trades, panel, source = fixture_run(False)
    with pytest.raises(AssertionError, match="remains active"):
        verify_run("limit_o0_t1_b0", orders.with_columns(pl.lit("pending").alias("status")), trades, panel, source)


@pytest.mark.parametrize("cross_minute,ttl,expected", [(596, 1, 596), (598, 3, 598), (597, 1, None), (599, 3, None), (595, 1, None)])
def test_native_engine_eligibility_gate_ttl_and_close(cross_minute, ttl, expected):
    """Exercise installed Engine matching and cancellation, without a simulation loop."""
    from ml4t.backtest import BacktestConfig, DataFeed, Engine, ExecutionMode, OrderStatus, OrderType, Strategy
    from ml4t.backtest.config import CommissionType, ExecutionPrice, ShareType, SlippageType
    from ml4t.backtest.execution.limits import PositiveVolumeLimit

    class Probe(Strategy):
        def on_start(self, broker):
            self.entry = None
            self.exit = None

        def on_data(self, timestamp, data, context, broker):
            local = timestamp.astimezone(JST)
            minute = local.hour * 60 + local.minute
            if minute == 595:
                self.entry = broker.submit_order("USDJPY", -10000.0,
                    order_type=OrderType.LIMIT, limit_price=150.0)
            if minute == 595 + ttl and self.entry.status != OrderStatus.FILLED:
                assert broker.cancel_order(self.entry.order_id)
            if minute == 609 and broker.get_position("USDJPY"):
                self.exit = broker.close_position("USDJPY", order_type=OrderType.MARKET)

        def on_end(self, broker):
            assert not broker.get_position("USDJPY")

    source = bars()
    source[cross_minute - 594]["high"] = 150.02
    source[cross_minute - 594]["open"] = 150.01
    source[cross_minute - 594]["close"] = 150.01
    # Synthetic eligibility volume is not observed FX volume.
    prices = pl.DataFrame(source).with_columns(pl.lit("USDJPY").alias("symbol"),
        pl.when((pl.col("minute") == cross_minute) | (pl.col("minute") == 610))
          .then(pl.lit(1.0)).otherwise(pl.lit(0.0)).alias("volume"))
    strategy = Probe()
    config = BacktestConfig(initial_cash=1500000.0, allow_short_selling=True,
        allow_leverage=True, initial_margin=.5, execution_mode=ExecutionMode.NEXT_BAR,
        execution_price=ExecutionPrice.OPEN, share_type=ShareType.FRACTIONAL,
        commission_type=CommissionType.NONE, commission_rate=0.0,
        slippage_type=SlippageType.NONE, slippage_rate=0.0, partial_fills_allowed=False)
    Engine(DataFeed(prices_df=prices), strategy, config, execution_limits=PositiveVolumeLimit()).run()
    if expected is None:
        assert strategy.entry.status == OrderStatus.CANCELLED
        assert strategy.entry.filled_at is None
        assert strategy.exit is None
    else:
        assert strategy.entry.status == OrderStatus.FILLED
        assert strategy.entry.filled_at == source[expected - 594]["timestamp"]
        assert strategy.entry.filled_price == pytest.approx(150.0)
        assert strategy.exit.status == OrderStatus.FILLED
        assert strategy.exit.filled_at == source[16]["timestamp"]
        assert strategy.exit.filled_price == pytest.approx(150.0)
