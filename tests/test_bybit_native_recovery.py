"""#46: deterministic fault injection against native ml4t-live 0.1.2.

The feed and Bybit transport are synthetic fixtures. No network operations.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from connectors.bybit.models import BybitOrderData, BybitPositionData
from ml4t.backtest.strategy import Strategy
from ml4t.live import SafeBroker
from ml4t.live.safety import (
    ReconciliationMismatchError,
)

from src.bybit_paper_runtime import build_native_paper_engine, make_native_risk
from tests.test_bybit_paper_runtime import fixture_broker, reviewed


class NoOrderStrategy(Strategy):
    """Exercise the existing strategy callback without generating order intents."""

    def __init__(self):
        super().__init__()
        self.events = 0

    def on_data(self, timestamp, data, context, broker):
        self.events += 1


class FaultFeed:
    """Synthetic DataFeedProtocol fixture for the actual native LiveEngine."""

    def __init__(self, *, kind="terminated", fail_restarts=0, fail_stop_once=False):
        self.kind = kind
        self.fail_restarts = fail_restarts
        self.fail_stop_once = fail_stop_once
        self.starts = 0
        self.stops = 0
        self._emitted = False
        self._stop_event = asyncio.Event()

    async def start(self):
        self.starts += 1
        if self.starts > 1 and self.fail_restarts:
            self.fail_restarts -= 1
            raise ConnectionError("synthetic feed reconnect refused")
        self._emitted = False
        self._stop_event = asyncio.Event()

    def stop(self):
        self.stops += 1
        self._stop_event.set()
        if self.fail_stop_once:
            self.fail_stop_once = False
            raise RuntimeError("synthetic feed cleanup failed")

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._stop_event.is_set():
            raise StopAsyncIteration
        if not self._emitted:
            self._emitted = True
            return (
                datetime.now(UTC),
                {"BTC/USDT:USDT": {
                    "open": 80000, "high": 80100, "low": 79900,
                    "close": 80050, "volume": 10,
                }},
                {},
            )
        if self.kind == "terminated" or (self.kind == "terminate_once" and self.starts == 1):
            raise StopAsyncIteration
        await self._stop_event.wait()
        raise StopAsyncIteration


async def until(condition, *, steps=300):
    for _ in range(steps):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("native runtime did not reach expected bounded state")


def events(engine):
    return [e["kind"] if "kind" in e else e.get("event") for e in engine.operational_events]


def build(tmp_path, feed, *, attempts=2):
    account = replace(
        reviewed(tmp_path), max_recovery_attempts=attempts,
        recovery_cooldown_seconds=0.001,
    )
    broker, client = fixture_broker(tmp_path)
    strategy = NoOrderStrategy()
    engine = build_native_paper_engine(strategy, broker, feed, account)
    engine.watchdog_poll_seconds = 0.01
    # Small intervals only in this synthetic fault-injection test, never in
    # ReviewedPaperAccount or operator deployment.
    engine.feed_silence_seconds = 0.05
    return engine, broker, client, strategy


def finish(engine, broker):
    engine.broker.close_persistence()
    broker.journal.close()


def test_native_feed_silence_recovers_without_orders(tmp_path):
    feed = FaultFeed(kind="silent")
    engine, broker, client, strategy = build(tmp_path, feed)
    async def run():
        await engine.connect()
        task = asyncio.create_task(engine.run())
        try:
            await until(lambda: feed.starts >= 2 and strategy.events >= 2)
            assert any("engine_recovery_succeeded" in str(e) for e in engine.operational_events)
            assert any(e.get("reason") == "feed_silent" and "engine_recovery_attempt" in str(e)
                       for e in engine.operational_events)
            assert engine.auto_recover
            assert engine.max_recovery_attempts == 2
        finally:
            await engine.stop()
            await task
    try:
        asyncio.run(run())
    finally:
        finish(engine, broker)
    assert feed.starts == 2
    assert strategy.events >= 2
    client.create_order.assert_not_awaited()
    client.cancel_order.assert_not_awaited()
    client.edit_order.assert_not_awaited()



def test_native_broker_disconnect_recovers_with_identity_and_reconciliation(tmp_path):
    feed = FaultFeed(kind="silent")
    engine, broker, client, strategy = build(tmp_path, feed)
    async def run():
        await engine.connect()
        task = asyncio.create_task(engine.run())
        try:
            await until(lambda: strategy.events >= 1)
            broker._connected = False  # synthetic heartbeat disconnection
            await until(lambda: feed.starts >= 2 and strategy.events >= 2)
            assert any(
                e.get("reason") == "broker_disconnected"
                and "engine_recovery_succeeded" in str(e)
                for e in engine.operational_events
            )
            assert client.connect.await_count >= 2
        finally:
            await engine.stop()
            await task
    try:
        asyncio.run(run())
    finally:
        finish(engine, broker)
    client.create_order.assert_not_awaited()


def test_factory_requires_finite_recovery_budget_and_sane_bar_interval(tmp_path):
    from src.bybit_paper_runtime import PaperConfigBlocked

    account = reviewed(tmp_path)
    for replacement in (
        {"max_recovery_attempts": None},
        {"max_recovery_attempts": 0},
        {"max_recovery_attempts": 1.5},
        {"recovery_cooldown_seconds": None},
        {"recovery_cooldown_seconds": float("inf")},
    ):
        with pytest.raises(PaperConfigBlocked):
            make_native_risk(replace(account, **replacement))
    broker, client = fixture_broker(tmp_path)
    feed = FaultFeed()
    feed.timeframe = "1m"
    with pytest.raises(PaperConfigBlocked, match="cadence"):
        build_native_paper_engine(
            NoOrderStrategy(), broker, feed,
            replace(account, feed_silence_seconds=5.0),
        )
    assert not (account.state_dir / "bybit-demo-account-24680.json").exists()
    client.create_order.assert_not_awaited()
    broker.journal.close()


def test_native_recovery_exhausts_and_fails_without_unmanaged_restart(tmp_path):
    feed = FaultFeed(kind="terminated", fail_restarts=10)
    engine, broker, client, _ = build(tmp_path, feed, attempts=2)
    async def run():
        await engine.connect()
        with pytest.raises(RuntimeError, match="recovery_exhausted"):
            await engine.run()
        status = engine.runtime_status()
        assert status["runtime_state"] == "failed"
        assert status["terminal_failure_reason"] == "recovery_exhausted:feed_terminated"
        assert status["recovery_attempts"] == 2
        assert any("engine_recovery_exhausted" in str(e) for e in engine.operational_events)
        await engine.stop()
    try:
        asyncio.run(run())
    finally:
        finish(engine, broker)
    assert feed.starts == 3  # initial + exactly two native retries
    client.create_order.assert_not_awaited()


def test_native_failed_cleanup_observed_and_retried_within_bound(tmp_path):
    feed = FaultFeed(kind="terminate_once", fail_stop_once=True)
    engine, broker, client, strategy = build(tmp_path, feed, attempts=2)
    async def run():
        await engine.connect()
        task = asyncio.create_task(engine.run())
        try:
            await until(lambda: feed.starts >= 2 and strategy.events >= 2)
            evidence = str(engine.operational_events)
            assert "recovery_cleanup_failed" in str(engine.runtime_transitions)
            assert "engine_recovery_failed" in evidence
            assert "engine_recovery_succeeded" in evidence
        finally:
            await engine.stop()
            await task
    try:
        asyncio.run(run())
    finally:
        finish(engine, broker)
    assert feed.stops >= 2
    client.create_order.assert_not_awaited()



def test_recovery_does_not_normalize_unknown_broker_exposure(tmp_path):
    """Reconciliation must never silently accept an unexpected position after a failed retry."""
    feed = FaultFeed(kind="terminate_once")
    engine, broker, client, _ = build(tmp_path, feed, attempts=2)
    injected = BybitPositionData(
        symbol="BTC/USDT:USDT", side="buy", size=Decimal("0.01"),
        entry_price=Decimal(80000), mark_price=Decimal(80050),
        unrealized_pnl=None, leverage=None, liquidation_price=None,
        raw={"createdTime": "1730000000000"},
    )
    async def close_then_expose():
        client.fetch_positions.return_value = [injected]
    client.close.side_effect = close_then_expose

    async def run():
        await engine.connect()
        with pytest.raises(RuntimeError, match="recovery_exhausted"):
            await engine.run()
        assert engine.runtime_status()["runtime_state"] == "failed"
        assert any("ReconciliationMismatchError" in str(e) for e in engine.operational_events)
        assert engine.broker.reconciliation_report is not None
        assert engine.broker.reconciliation_report["clean"] is False
        await engine.stop()
    try:
        asyncio.run(run())
    finally:
        finish(engine, broker)
    client.create_order.assert_not_awaited()


def test_native_reconciliation_blocks_position_mismatch_and_clean_restart(tmp_path):
    account = reviewed(tmp_path)
    broker, client = fixture_broker(tmp_path)
    safe = SafeBroker(broker, make_native_risk(account))
    state_path = Path(safe.config.state_file)
    position = BybitPositionData(
        symbol="BTC/USDT:USDT", side="buy", size=Decimal("0.01"),
        entry_price=Decimal(80000), mark_price=Decimal(80100),
        unrealized_pnl=Decimal(1), leverage=None, liquidation_price=None,
        raw={"createdTime": "1730000000000"},
    )
    async def run():
        await safe.connect()
        await safe.disconnect()
        original = state_path.read_bytes()
        client.fetch_positions.return_value = [position]
        with pytest.raises(ReconciliationMismatchError):
            await safe.connect()
        assert state_path.read_bytes() == original
        assert safe.reconciliation_report["clean"] is False
        assert safe.persistence_status["execution_identity_validated"] is True or not broker.is_connected
        client.fetch_positions.return_value = []
        await safe.connect()
        assert safe.reconciliation_report["clean"] is True
        await safe.disconnect()
    try:
        asyncio.run(run())
    finally:
        safe.close_persistence()
        broker.journal.close()
    client.create_order.assert_not_awaited()


def test_native_reconciliation_blocks_pending_order_mismatch(tmp_path):
    account = reviewed(tmp_path)
    broker, client = fixture_broker(tmp_path)
    safe = SafeBroker(broker, make_native_risk(account))
    pending = BybitOrderData(
        order_id="synthetic-pending", client_order_id="syn",
        symbol="BTC/USDT:USDT", side="buy", order_type="limit",
        price=Decimal(80000), quantity=Decimal("0.005"),
        filled_quantity=Decimal(0), status="open",
        timestamp=1730000000000, raw={},
    )
    async def run():
        await safe.connect()
        await safe.disconnect()
        client.fetch_open_orders.return_value = [pending]
        with pytest.raises(ReconciliationMismatchError):
            await safe.connect()
        assert safe.reconciliation_report["clean"] is False
        assert safe.reconciliation_report["unexpected_pending_orders"]
        client.fetch_open_orders.return_value = []
        await safe.connect()
        assert safe.reconciliation_report["clean"] is True
        await safe.disconnect()
    try:
        asyncio.run(run())
    finally:
        safe.close_persistence()
        broker.journal.close()
    client.create_order.assert_not_awaited()





def test_unknown_submission_persists_across_clean_native_reconnect(tmp_path):
    from connectors.bybit.journal import UnknownOutcome
    from ml4t.backtest.types import OrderSide

    broker, client = fixture_broker(tmp_path)
    client.create_order.side_effect = TimeoutError("synthetic ambiguous submission")
    safe = SafeBroker(broker, make_native_risk(reviewed(tmp_path)))
    async def run():
        await safe.connect()
        safe.record_market_snapshot("BTC/USDT:USDT", 80000)
        with pytest.raises(TimeoutError, match="ambiguous"):
            await safe.submit_order_async("BTC/USDT:USDT", 0.001, side=OrderSide.BUY)
        assert broker.journal.has_unknown()
        await safe.disconnect()
        await safe.connect()
        safe.record_market_snapshot("BTC/USDT:USDT", 80000)
        with pytest.raises(UnknownOutcome):
            await safe.submit_order_async("BTC/USDT:USDT", 0.001, side=OrderSide.BUY)
        assert broker.journal.has_unknown()
        await safe.disconnect()
    try:
        asyncio.run(run())
    finally:
        safe.close_persistence()
        broker.journal.close()
    assert client.create_order.await_count == 1


def test_corrupt_native_state_blocks_and_preserves_bytes(tmp_path):
    from ml4t.live.safety import PersistenceSafetyError

    risk = make_native_risk(reviewed(tmp_path))
    state = Path(risk.state_file)
    bad_bytes = b"{this is not valid native state"
    state.write_bytes(bad_bytes)
    broker, client = fixture_broker(tmp_path)
    try:
        with pytest.raises((PersistenceSafetyError, ValueError)):
            SafeBroker(broker, risk)
        assert state.read_bytes() == bad_bytes
    finally:
        broker.journal.close()
    client.create_order.assert_not_awaited()


def test_corrupt_native_journal_blocks_and_preserves_bytes(tmp_path):
    from ml4t.live.safety import AuditJournalError

    risk = make_native_risk(reviewed(tmp_path))
    state = Path(risk.state_file)
    journal = state.with_name(f"{state.stem}-journal.jsonl")
    bad_bytes = b"{not-a-valid-audit-event}\n"
    journal.write_bytes(bad_bytes)
    broker, client = fixture_broker(tmp_path)
    try:
        with pytest.raises(AuditJournalError):
            SafeBroker(broker, risk)
        assert journal.read_bytes() == bad_bytes
    finally:
        broker.journal.close()
    client.create_order.assert_not_awaited()


def test_unwritable_state_directory_fails_before_broker_connect(tmp_path):
    account = reviewed(tmp_path)
    account.state_dir.chmod(0o500)
    broker, client = fixture_broker(tmp_path)
    try:
        with pytest.raises((OSError, RuntimeError)):
            SafeBroker(broker, make_native_risk(account))
    finally:
        account.state_dir.chmod(0o700)
        broker.journal.close()
    client.connect.assert_not_awaited()
    client.create_order.assert_not_awaited()


def test_second_writer_rejected_by_native_state_lease(tmp_path):
    account = reviewed(tmp_path)
    risk = make_native_risk(account)
    first_broker, first_client = fixture_broker(tmp_path)
    first = SafeBroker(first_broker, risk)
    second_broker, second_client = fixture_broker(tmp_path)
    try:
        with pytest.raises(RuntimeError):
            SafeBroker(second_broker, make_native_risk(account))
    finally:
        first.close_persistence()
        first_broker.journal.close()
        second_broker.journal.close()
    first_client.create_order.assert_not_awaited()
    second_client.create_order.assert_not_awaited()


def test_incomplete_provider_snapshot_rejects_connection_without_mutation(tmp_path):
    broker, client = fixture_broker(tmp_path)
    client.fetch_positions.side_effect = TimeoutError("synthetic snapshot incomplete")
    safe = SafeBroker(broker, make_native_risk(reviewed(tmp_path)))
    async def run():
        with pytest.raises(TimeoutError, match="snapshot incomplete"):
            await safe.connect()
        assert not broker.is_connected
    try:
        asyncio.run(run())
    finally:
        safe.close_persistence()
        broker.journal.close()
    client.create_order.assert_not_awaited()
