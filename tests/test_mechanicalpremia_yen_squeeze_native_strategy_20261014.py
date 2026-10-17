from __future__ import annotations

from datetime import datetime, timedelta, timezone

import polars as pl
import pytest
from ml4t.backtest import OrderSide, OrderType, Strategy

from scripts.mechanicalpremia_yen_squeeze_native_strategy_20261014 import (
    BrokerTerms,
    UnqualifiedExecution,
    YenSqueezeStrategy,
    build_features,
    risk_lots,
    run_native,
    run_source_backtest,
)


TERMS = BrokerTerms(0.001, 1.0, 0.01, 10.0, 0.01, "JPY", 0.001, 0.002, "USD", 0.01)


def _features() -> pl.DataFrame:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return pl.DataFrame({
        "timestamp": [start + timedelta(minutes=i) for i in range(5)],
        "symbol": ["TEST"] * 5,
        "open": [100.0, 100.0, 110.0, 111.0, 111.0],
        "high": [101.0, 101.0, 112.0, 112.0, 112.0],
        "low": [99.0, 99.0, 109.0, 110.0, 110.0],
        "close": [100.0, 100.0, 111.0, 111.0, 111.0],
        "volume": [1.0] * 5,
        "atr14": [1.0] * 5,
        "atr100_upper_median": [2.0] * 5,
        "available_at": [start] * 5,
        "donchian20_0": [105.0] * 5,
        "donchian20_1": [95.0] * 5,
        "donchian500_0": [105.0] * 5,
        "donchian500_1": [95.0] * 5,
    })


def test_registered_features_use_native_atr_and_donchian_and_are_causal() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = pl.DataFrame({
        "timestamp": [start + timedelta(hours=i) for i in range(520)],
        "open": [100.0] * 520,
        "high": [101.0] * 520,
        "low": [99.0] * 520,
        "close": [100.0] * 520,
        "volume": [1.0] * 520,
    })
    features = build_features(bars)
    assert features["atr14"][14] == 2.0
    assert features["available_at"][25] == bars["timestamp"][25] + timedelta(hours=1)
    assert features["donchian20_0"][30] == 101.0
    assert features["atr100_upper_median"][113] == 2.0


def test_future_feature_availability_cannot_create_order() -> None:
    bars = _features().with_columns(pl.lit(datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=1)).alias("available_at"))
    strategy = YenSqueezeStrategy("TEST", TERMS, synthetic_mode=True)
    result = run_native(bars, strategy)
    assert result.fills == []


def test_native_engine_gap_fill_and_cash_equity_reconcile() -> None:
    class EntryOnce(Strategy):
        def __init__(self):
            self.done = False

        def on_data(self, timestamp, data, context, broker):
            if not self.done:
                self.done = True
                broker.submit_order("TEST", 1, side=OrderSide.BUY,
                                    order_type=OrderType.STOP, stop_price=105.0)

    result = run_native(_features(), EntryOnce())
    assert len(result.fills) == 1
    assert result.fills[0].price == 110.0
    assert result.fills[0].timestamp == _features()["timestamp"][2]
    assert result.equity_curve[-1][1] == pytest.approx(10_001.0)
    assert result.trades[0].status == "open"


def test_adapter_submits_source_entry_stops_to_native_engine() -> None:
    strategy = YenSqueezeStrategy("TEST", TERMS, synthetic_mode=True)
    result = run_native(_features(), strategy)
    assert len(result.fills) == 1
    assert result.fills[0].side == OrderSide.BUY
    assert result.fills[0].price == 110.0
    assert strategy.protection_gap_detected is True
    # Source has no OCO: the opposite entry stays pending after the buy fill.
    # It must not be mistaken for, or repriced as, the protective stop.
    assert len(strategy.pending) == 1
    assert strategy.protective_order_id is not None
    assert strategy.protective_order_id not in strategy.pending
    # Native Engine equity after MQL tick-value sizing (no double conversion).
    assert result.equity_curve[-1][1] == pytest.approx(10_000.05)


def test_adapter_cancels_pending_entry_at_one_hour_using_native_broker() -> None:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = pl.concat([
        _features().head(1).with_columns(pl.lit(base).alias("timestamp")),
        _features().head(1).with_columns(pl.lit(base + timedelta(hours=1)).alias("timestamp")),
        _features().head(1).with_columns(pl.lit(base + timedelta(hours=1, minutes=1)).alias("timestamp")),
    ])
    # Keep both stop thresholds outside the range so only the one-hour expiry acts.
    bars = bars.with_columns(
        pl.lit(120.0).alias("donchian20_0"), pl.lit(80.0).alias("donchian20_1"),
        pl.lit(120.0).alias("donchian500_0"), pl.lit(80.0).alias("donchian500_1"),
        pl.lit(base).alias("available_at"),
    )
    strategy = YenSqueezeStrategy("TEST", TERMS, synthetic_mode=True)
    result = run_native(bars, strategy)
    assert result.fills == []
    assert strategy.pending == {}
    assert len(strategy.expired_order_ids) == 2


def test_native_engine_updates_pending_stop_without_custom_fill_logic() -> None:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = pl.DataFrame({
        "timestamp": [base + timedelta(minutes=i) for i in range(4)],
        "symbol": ["TEST"] * 4,
        "open": [100.0] * 4, "high": [101.0] * 4, "low": [99.0] * 4,
        "close": [100.0] * 4, "volume": [1.0] * 4,
    })

    class UpdateStop(Strategy):
        order_id = None
        updated_price = None

        def on_data(self, timestamp, data, context, broker):
            if self.order_id is None:
                order = broker.submit_order("TEST", 1, order_type=OrderType.STOP, stop_price=200.0)
                self.order_id = order.order_id
            elif timestamp == base + timedelta(minutes=1):
                assert broker.update_order(self.order_id, stop_price=190.0)
                self.updated_price = broker.get_order(self.order_id).stop_price

    strategy = UpdateStop()
    result = run_native(bars, strategy)
    assert strategy.updated_price == 190.0
    assert result.fills == []


def test_strategy_rejects_source_equivalent_execution_before_order_submission() -> None:
    strategy = YenSqueezeStrategy("TEST", TERMS)
    with pytest.raises(UnqualifiedExecution, match="parent/child STOP protection"):
        run_native(_features(), strategy)


def test_source_backtest_entrypoint_fails_closed_for_missing_terms_and_engine_gap() -> None:
    strategy = YenSqueezeStrategy("TEST", TERMS)
    with pytest.raises(UnqualifiedExecution, match="explicit broker"):
        run_source_backtest(_features(), strategy)
    with pytest.raises(UnqualifiedExecution, match="immediate protective STOP"):
        run_source_backtest(_features(), strategy, TERMS)


def test_broker_terms_and_sizing_fail_closed() -> None:
    with pytest.raises(UnqualifiedExecution, match="complete positive"):
        risk_lots(10_000, 0.01, 0.2, BrokerTerms(0, 1, 0.01, 1, 0.01, "JPY", 0.001, 0.01, "USD", 0.01))
    with pytest.raises(UnqualifiedExecution, match="below broker minimum"):
        risk_lots(1, 0.01, 2.0, TERMS)

