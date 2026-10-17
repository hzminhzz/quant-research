from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import fields

import polars as pl
from ml4t.backtest import (
    BacktestConfig,
    DataFeed,
    Engine,
    OrderSide,
    OrderType,
    Strategy,
)

from scripts.audit_mechanicalpremia_yen_squeeze_native_20261014 import (
    add_native_features,
    add_upper_median,
    build_complete_h1,
)


def _bars(count: int) -> pl.DataFrame:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    highs = [101.0] * count
    lows = [99.0] * count
    highs[100] = 140.0
    lows[110] = 60.0
    return pl.DataFrame(
        {
            "timestamp": [start + timedelta(hours=index) for index in range(count)],
            "open": [100.0] * count,
            "high": highs,
            "low": lows,
            "close": [100.0] * count,
            "volume": [1.0] * count,
        }
    )


def test_native_atr_donchian_windows_and_upper_median_match_examples() -> None:
    bars = _bars(520)
    features = add_native_features(bars)

    # The supplied bars have a constant two-point range at the first ATR window.
    assert features["atr14"][14] == 2.0
    # Donchian outputs are upper, lower, and midpoint. At row 500, the
    # 20-bar channel excludes the early extrema while the 500-bar channel
    # still contains them.
    row = features.row(500, named=True)
    assert row["donchian20_0"] < row["donchian500_0"]
    assert row["donchian20_1"] > row["donchian500_1"]
    assert row["atr100_upper_median"] is not None


def test_upper_median_uses_order_statistic_50_and_includes_current_observation() -> None:
    observations = pl.DataFrame({"atr14": [float("nan"), *range(100)]})
    result = add_upper_median(observations)
    assert result["atr100_upper_median"][99] is None
    assert result["atr100_upper_median"][100] == 50


def test_complete_hour_aggregation_excludes_missing_minute_without_filling() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    timestamps = [start + timedelta(minutes=i) for i in range(180) if i != 70]
    minute = pl.DataFrame(
        {
            "timestamp": timestamps,
            "open": [100.0] * len(timestamps),
            "high": [101.0] * len(timestamps),
            "low": [99.0] * len(timestamps),
            "close": [100.0] * len(timestamps),
            "volume": [1.0] * len(timestamps),
        }
    )
    hourly, counts = build_complete_h1(minute)
    assert hourly.height == 2
    assert counts["candidate_hours"] == 3
    assert counts["excluded_incomplete_hours"] == 1
    assert hourly["timestamp"].to_list() == [start, start + timedelta(hours=2)]


def test_naive_timestamps_require_explicit_utc_assumption() -> None:
    start = datetime(2024, 1, 1)
    minute = pl.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=i) for i in range(60)],
            "open": [100.0] * 60,
            "high": [101.0] * 60,
            "low": [99.0] * 60,
            "close": [100.0] * 60,
            "volume": [1.0] * 60,
        }
    )
    try:
        build_complete_h1(minute)
    except ValueError as error:
        assert "explicit UTC" in str(error)
    else:
        raise AssertionError("naive timestamps were accepted without an assumption")


def test_minute_bar_open_timestamps_must_align_to_exact_minute() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    minute = pl.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=i) + (timedelta(seconds=1) if i == 10 else timedelta()) for i in range(60)],
            "open": [100.0] * 60,
            "high": [101.0] * 60,
            "low": [99.0] * 60,
            "close": [100.0] * 60,
            "volume": [1.0] * 60,
        }
    )
    try:
        build_complete_h1(minute)
    except ValueError as error:
        assert "align to exact minutes" in str(error)
    else:
        raise AssertionError("misaligned minute bars were aggregated into H1")


def test_features_at_minute_clock_are_not_available_before_h1_close() -> None:
    hourly = _bars(520)
    features = add_native_features(hourly)
    assert features["available_at"][0] == hourly["timestamp"][0] + timedelta(hours=1)
    assert features["available_at"][100] == hourly["timestamp"][100] + timedelta(hours=1)


def test_appending_future_bar_does_not_change_completed_features() -> None:
    original = _bars(520)
    extended = pl.concat(
        [
            original,
            pl.DataFrame(
                {
                    "timestamp": [original["timestamp"][-1] + timedelta(hours=1)],
                    "open": [100.0],
                    "high": [200.0],
                    "low": [1.0],
                    "close": [100.0],
                    "volume": [1.0],
                }
            ),
        ]
    )
    left = add_native_features(original)
    right = add_native_features(extended)
    assert left.select("atr14", "donchian20_0", "donchian20_1", "atr100_upper_median").equals(
        right.head(original.height).select("atr14", "donchian20_0", "donchian20_1", "atr100_upper_median")
    )


def test_native_next_bar_stop_uses_gap_open_and_future_timestamp() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = pl.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=i) for i in range(3)],
            "symbol": ["TEST"] * 3,
            "open": [100.0, 110.0, 111.0],
            "high": [101.0, 112.0, 112.0],
            "low": [99.0, 109.0, 110.0],
            "close": [100.0, 111.0, 111.0],
            "volume": [1.0] * 3,
        }
    )

    class StopOnFirstBar(Strategy):
        submitted = False

        def on_data(self, timestamp, data, context, broker):
            if not self.submitted:
                self.submitted = True
                broker.submit_order(
                    "TEST",
                    1,
                    side=OrderSide.BUY,
                    order_type=OrderType.STOP,
                    stop_price=105.0,
                )

    config = BacktestConfig(
        execution_mode="next_bar",
        stop_fill_mode="next_bar_open",
        initial_cash=10_000.0,
        allow_short_selling=True,
    )
    result = Engine(
        DataFeed(prices_df=bars, entity_col="symbol", timestamp_col="timestamp"),
        StopOnFirstBar(),
        config,
    ).run()

    assert len(result.fills) == 1
    fill = result.fills[0]
    assert fill.order_type == "stop"
    assert fill.stop_price == 105.0
    assert fill.price == 110.0  # Worse of trigger and next eligible bar open.
    assert fill.timestamp == start + timedelta(minutes=1)
    assert result.trades[0].status == "open"
    assert result.equity_curve[-1][1] == 10_001.0


def test_native_order_stop_can_be_updated_and_pending_order_cancelled() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = pl.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=i) for i in range(3)],
            "symbol": ["TEST"] * 3,
            "open": [100.0] * 3,
            "high": [101.0] * 3,
            "low": [99.0] * 3,
            "close": [100.0] * 3,
            "volume": [1.0] * 3,
        }
    )

    class UpdateThenCancel(Strategy):
        order_id = None
        order_obj = None
        update_succeeded = False
        cancel_succeeded = False
        final_status = None

        def on_data(self, timestamp, data, context, broker):
            if self.order_id is None:
                order = broker.submit_order(
                    "TEST",
                    1,
                    side=OrderSide.BUY,
                    order_type=OrderType.STOP,
                    stop_price=200.0,
                )
                self.order_id = order.order_id
                self.order_obj = order
            elif timestamp == start + timedelta(minutes=1):
                self.update_succeeded = broker.update_order(self.order_id, stop_price=190.0)
                self.cancel_succeeded = broker.cancel_order(self.order_id)
                self.final_status = broker.get_order(self.order_id).status.value

    strategy = UpdateThenCancel()
    result = Engine(
        DataFeed(prices_df=bars, entity_col="symbol", timestamp_col="timestamp"),
        strategy,
        BacktestConfig(execution_mode="next_bar", initial_cash=10_000.0),
    ).run()

    assert strategy.update_succeeded
    assert strategy.cancel_succeeded
    assert strategy.final_status == "cancelled"
    assert result.fills == []
    # The native Order contract has no timestamp-based expiry field. A Strategy
    # must cancel at its chosen expiry clock using the native broker API.
    assert "expires_at" not in {field.name for field in fields(type(strategy.order_obj))}

