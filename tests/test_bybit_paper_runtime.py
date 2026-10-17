"""Issue #45 native paper tests: every exchange call is synthetic."""
import asyncio
from dataclasses import replace
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from connectors.bybit.broker import BybitLiveBroker
from connectors.bybit.config import BybitConfig, Environment, Mode
from connectors.bybit.journal import BybitIntentJournal
from connectors.bybit.models import BybitBalance, BybitOrderData
from ml4t.backtest.strategy import Strategy
from ml4t.backtest.types import OrderSide, OrderType
from ml4t.live import SafeBroker
from ml4t.live.safety import RiskLimitError

from src.bybit_paper_runtime import (
    PaperConfigBlocked,
    ReviewedPaperAccount,
    build_native_paper_engine,
    make_native_risk,
)


class OneBarStrategy(Strategy):
    """Identical Strategy.on_data boundary for backtest and live."""
    def __init__(self):
        super().__init__()
        self.orders = []

    def on_data(self, timestamp, data, context, broker):
        if not self.orders:
            order = broker.submit_order(
                "BTC/USDT:USDT", 0.001, side=OrderSide.BUY, order_type=OrderType.MARKET
            )
            self.orders.append(order)


def reviewed(tmp_path):
    store = tmp_path / "private"
    store.mkdir(mode=0o700)
    return ReviewedPaperAccount(
        account_uid="24680", strategy_id="synthetic-onebar",
        allowed_assets=frozenset({"BTC/USDT:USDT"}),
        max_order_shares=0.01, max_order_value=1000.0,
        max_position_shares=0.02, max_position_value=2000.0,
        max_total_exposure=5000.0, max_positions=1,
        max_orders_per_minute=4, max_daily_loss=100.0,
        max_drawdown_pct=0.05, max_price_deviation_pct=0.05,
        max_data_staleness_seconds=300.0, dedup_window_seconds=1.0,
        feed_silence_seconds=130.0, max_event_age_seconds=300.0,
        max_recovery_attempts=3, recovery_cooldown_seconds=0.01,
        state_dir=store, reviewed=True,
    )


def fixture_broker(tmp_path, environment=Environment.DEMO):
    client = MagicMock()
    client.config = BybitConfig(
        environment=environment, mode=Mode.EXECUTION,
        api_key="synthetic-demo-key", api_secret="synthetic-demo-secret",
        expected_demo_uid="24680",
    )
    client.demo_identity_verified = environment is Environment.DEMO
    client.connect = AsyncMock()
    client.close = AsyncMock()
    client.fetch_balance = AsyncMock(return_value={
        "USDT": BybitBalance("USDT", Decimal(5000), Decimal(5000), Decimal(0), {}),
    })
    client.fetch_positions = AsyncMock(return_value=[])
    client.fetch_open_orders = AsyncMock(return_value=[])
    client.create_order = AsyncMock(return_value=BybitOrderData(
        order_id="synthetic-order", client_order_id="syn-intent",
        symbol="BTC/USDT:USDT", side="buy", order_type="market",
        price=Decimal(80000), quantity=Decimal("0.001"),
        filled_quantity=Decimal("0.001"), status="filled",
        timestamp=1730000000000, raw={},
    ))
    client.cancel_order = AsyncMock(return_value=True)
    client.edit_order = AsyncMock()
    broker = BybitLiveBroker(client=client, journal=BybitIntentJournal(tmp_path / "provider.sqlite"))
    return broker, client


def test_config_never_uses_native_unreviewed_defaults(tmp_path):
    a = reviewed(tmp_path)
    risk = make_native_risk(a)
    assert risk.execution_mode.value == "paper"
    assert risk.fail_on_reconciliation_mismatch
    assert risk.fail_on_journal_error
    assert risk.allowed_assets == {"BTC/USDT:USDT"}
    assert risk.max_daily_loss == 100.0
    assert risk.max_total_exposure == 5000.0
    assert risk.max_data_staleness_seconds == 300.0
    assert risk.journal_file is None  # native journal derives from native state path
    assert a.account_uid in risk.state_file


@pytest.mark.parametrize("override", [
    {"reviewed": False}, {"max_order_value": None},
    {"max_total_exposure": None}, {"max_daily_loss": None},
    {"max_orders_per_minute": None}, {"max_drawdown_pct": None},
    {"max_data_staleness_seconds": None}, {"feed_silence_seconds": None},
    {"allowed_assets": frozenset()}, {"max_order_shares": -1.0},
    {"max_order_value": 3000.0}, {"strategy_id": ""},
])
def test_missing_or_unsafe_risk_fields_fail_closed(tmp_path, override):
    with pytest.raises(PaperConfigBlocked):
        make_native_risk(replace(reviewed(tmp_path), **override))


def test_native_owner_exclusivity_and_mainnet_denial(tmp_path):
    a = reviewed(tmp_path)
    broker, _ = fixture_broker(tmp_path)
    feed = MagicMock()
    feed.timeframe = "1m"
    first = build_native_paper_engine(OneBarStrategy(), broker, feed, a)
    try:
        second_broker, _ = fixture_broker(tmp_path, Environment.DEMO)
        with pytest.raises(RuntimeError):  # native SecureStateStore writer lease
            build_native_paper_engine(
                OneBarStrategy(), second_broker, feed,
                replace(a, strategy_id="independent-second-strategy"),
            )
        second_broker.journal.close()
    finally:
        first.broker.close_persistence()
        broker.journal.close()

    broker2, client2 = fixture_broker(tmp_path, Environment.MAINNET)
    with pytest.raises(PaperConfigBlocked, match="Demo"):
        build_native_paper_engine(OneBarStrategy(), broker2, feed, a)
    client2.create_order.assert_not_awaited()
    broker2.journal.close()


def test_synthetic_native_paper_engine_strategy_feed_broker_path(tmp_path):
    from datetime import UTC, datetime

    from connectors.bybit.feed import BybitKlineFeed
    now = datetime.now(UTC)
    t0 = (now.timestamp() - 150) * 1000
    exchange = MagicMock()
    exchange.watch_ohlcv = AsyncMock(side_effect=[
        [[t0, 80000, 80100, 79900, 80050, 10],
         [t0 + 60000, 80050, 80200, 80000, 80150, 15]],
        asyncio.CancelledError(),
    ])
    exchange.close = AsyncMock()
    feed = BybitKlineFeed(
        asset="BTC/USDT:USDT", symbol="BTC/USDT:USDT",
        exchange=exchange, max_age_seconds=300,
        silence_seconds=5, now_fn=lambda: now,
    )
    account = reviewed(tmp_path)
    broker, client = fixture_broker(tmp_path)
    strat = OneBarStrategy()
    engine = build_native_paper_engine(strat, broker, feed, account)
    # Synthetic client is still checked for identity by native SafeBroker.
    async def run():
        try:
            await engine.connect()
            task = asyncio.create_task(engine.run())
            for _ in range(150):
                if strat.orders or task.done():
                    break
                await asyncio.sleep(0.01)
            await engine.stop()
            await task
        finally:
            await engine.stop()
    try:
        asyncio.run(run())
    finally:
        engine.broker.close_persistence()
        broker.journal.close()
    assert len(strat.orders) == 1
    assert client.create_order.await_count == 1
    assert strat.orders[0].order_id == "synthetic-order"
    assert engine.runtime_status()["runtime_state"] == "stopped"
    assert engine.auto_recover is True
    assert engine.max_recovery_attempts == 3
    assert engine.recovery_cooldown_seconds == 0.01


def test_partial_fill_keeps_pending_state(tmp_path):
    broker, client = fixture_broker(tmp_path)
    client.create_order.return_value = BybitOrderData(
        order_id="partial-1", client_order_id="intent-1",
        symbol="BTC/USDT:USDT", side="buy", order_type="limit",
        price=Decimal(80000), quantity=Decimal("0.005"),
        filled_quantity=Decimal("0.002"), status="partially_filled",
        timestamp=1730000000000, raw={},
    )
    safe = SafeBroker(broker, make_native_risk(reviewed(tmp_path)))
    async def run():
        await safe.connect()
        safe.record_market_snapshot("BTC/USDT:USDT", 80000)
        order = await safe.submit_order_async(
            "BTC/USDT:USDT", 0.005, side=OrderSide.BUY,
            order_type=OrderType.LIMIT, limit_price=80000,
        )
        assert order.status.value == "pending"
        assert order.filled_quantity == 0.002
        await safe.disconnect()
    try:
        asyncio.run(run())
    finally:
        safe.close_persistence()
        broker.journal.close()
    assert client.create_order.await_count == 1


def test_unknown_submission_refuses_second_network_attempt(tmp_path):
    from connectors.bybit.journal import UnknownOutcome

    broker, client = fixture_broker(tmp_path)
    client.create_order.side_effect = TimeoutError("synthetic timeout")
    safe = SafeBroker(broker, make_native_risk(reviewed(tmp_path)))
    async def run():
        await safe.connect()
        safe.record_market_snapshot("BTC/USDT:USDT", 80000)
        with pytest.raises(TimeoutError, match="synthetic"):
            await safe.submit_order_async("BTC/USDT:USDT", 0.001, side=OrderSide.BUY)
        assert broker.journal.has_unknown()
        with pytest.raises((UnknownOutcome, RiskLimitError)):
            await safe.submit_order_async("BTC/USDT:USDT", 0.001, side=OrderSide.BUY)
        await safe.disconnect()
    try:
        asyncio.run(run())
    finally:
        safe.close_persistence()
        broker.journal.close()
    assert client.create_order.await_count == 1


def test_stale_feed_event_refused_before_native_strategy_dispatch(tmp_path):
    from datetime import UTC, datetime, timedelta

    from connectors.bybit.feed import BybitKlineFeed
    from connectors.bybit.journal import UnknownOutcome

    now = datetime.now(UTC)
    feed = BybitKlineFeed(
        asset="BTC/USDT:USDT", max_age_seconds=60,
        now_fn=lambda: now,
    )
    old_start_ms = int((now - timedelta(hours=1)).timestamp() * 1000)
    with pytest.raises(UnknownOutcome, match="stale"):
        feed._create_market_event([
            old_start_ms, 80000, 80100, 79900, 80050, 10,
        ])


def test_capability_rejection_does_not_reach_bybit(tmp_path):
    broker, client = fixture_broker(tmp_path)
    safe = SafeBroker(broker, make_native_risk(reviewed(tmp_path)))
    async def run():
        await safe.connect()
        safe.record_market_snapshot("BTC/USDT:USDT", 80000)
        with pytest.raises(ValueError):
            await safe.submit_order_async(
                "BTC/USDT:USDT", 0.001, side=OrderSide.BUY,
                order_type="unsupported-order-kind",
            )
        await safe.disconnect()
    try:
        asyncio.run(run())
    finally:
        safe.close_persistence()
        broker.journal.close()
    client.create_order.assert_not_awaited()


def test_native_paper_risk_limit_and_duplicate_intent(tmp_path):
    account = reviewed(tmp_path)
    broker, client = fixture_broker(tmp_path)
    safe = SafeBroker(broker, make_native_risk(account))
    async def run():
        await safe.connect()
        safe.record_market_snapshot("BTC/USDT:USDT", 80000.0)
        with pytest.raises(RiskLimitError):
            await safe.submit_order_async("BTC/USDT:USDT", 1.0, side=OrderSide.BUY)
        first = await safe.submit_order_async("BTC/USDT:USDT", 0.001, side=OrderSide.BUY)
        assert first.order_id == "synthetic-order"
        with pytest.raises(RiskLimitError):
            await safe.submit_order_async("BTC/USDT:USDT", 0.001, side=OrderSide.BUY)
        await safe.disconnect()
    try:
        asyncio.run(run())
    finally:
        safe.close_persistence()
        broker.journal.close()
    assert client.create_order.await_count == 1
