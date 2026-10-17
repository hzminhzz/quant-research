"""Tests for ATS-3 AuditSafeBroker lifecycle integration hook."""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from connectors.bybit.broker import BybitLiveBroker
from connectors.bybit.config import BybitConfig, Environment, Mode
from connectors.bybit.journal import BybitIntentJournal
from connectors.bybit.models import BybitBalance, BybitOrderData
from ml4t.backtest.strategy import Strategy
from ml4t.backtest.types import OrderSide
from ml4t.live.persistence import AcceptedOrderPersistenceError
from ml4t.live.safety import LiveRiskConfig

from src.bybit_paper_runtime import ReviewedPaperAccount, build_native_paper_engine
from src.research_control.ats3_audit_broker import AuditSafeBroker


def make_risk_config(tmp_path: Path) -> LiveRiskConfig:
    store = tmp_path / "private"
    store.mkdir(mode=0o700, exist_ok=True)
    return LiveRiskConfig(
        max_order_shares=0.01,
        max_order_value=1000.0,
        max_position_shares=0.02,
        max_position_value=2000.0,
        max_total_exposure=5000.0,
        max_positions=1,
        max_orders_per_minute=4,
        max_daily_loss=100.0,
        max_drawdown_pct=0.05,
        max_price_deviation_pct=0.05,
        max_data_staleness_seconds=300.0,
        dedup_window_seconds=1.0,
        execution_mode="paper",
        state_file=str(store / "bybit-demo-account-24680.json"),
        journal_file=str(store / "bybit-demo-account-24680-journal.jsonl"),
        fail_on_reconciliation_mismatch=True,
        fail_on_journal_error=True,
    )


def fixture_broker(tmp_path: Path):
    client = MagicMock()
    client.config = BybitConfig(
        environment=Environment.DEMO,
        mode=Mode.EXECUTION,
        api_key="synthetic-demo-key",
        api_secret="synthetic-demo-secret",
        expected_demo_uid="24680",
    )
    client.demo_identity_verified = True
    client.connect = AsyncMock()
    client.close = AsyncMock()
    client.fetch_balance = AsyncMock(
        return_value={
            "USDT": BybitBalance("USDT", Decimal(5000), Decimal(5000), Decimal(0), {}),
        }
    )
    client.fetch_positions = AsyncMock(return_value=[])
    client.fetch_open_orders = AsyncMock(return_value=[])
    client.create_order = AsyncMock(
        return_value=BybitOrderData(
            order_id="synthetic-order",
            client_order_id="syn-intent",
            symbol="BTC/USDT:USDT",
            side="buy",
            order_type="market",
            price=Decimal(80000),
            quantity=Decimal("0.001"),
            filled_quantity=Decimal("0.001"),
            status="filled",
            timestamp=1730000000000,
            raw={},
        )
    )
    client.cancel_order = AsyncMock(return_value=True)
    client.edit_order = AsyncMock()
    broker = BybitLiveBroker(
        client=client,
        journal=BybitIntentJournal(tmp_path / "provider.sqlite"),
    )
    return broker, client


def _journal_events(safe: AuditSafeBroker) -> list[dict]:
    path = Path(safe.config.journal_file)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_in_flight_transport_exception_defaults_to_unknown_outcome(tmp_path: Path):
    broker, client = fixture_broker(tmp_path)
    client.create_order.side_effect = TimeoutError("synthetic timeout")
    safe = AuditSafeBroker(broker, make_risk_config(tmp_path))

    async def run():
        await safe.connect()
        safe.record_market_snapshot("BTC/USDT:USDT", 80000)
        with pytest.raises(TimeoutError, match="synthetic"):
            await safe.submit_order_async("BTC/USDT:USDT", 0.001, side=OrderSide.BUY)
        await safe.disconnect()

    try:
        asyncio.run(run())
    finally:
        safe.close_persistence()
        broker.journal.close()

    events = _journal_events(safe)
    event_names = [e["event"] for e in events]
    assert "order_submission_intent" in event_names
    assert "order_submission_unknown" in event_names

    unknown = next(e for e in events if e["event"] == "order_submission_unknown")
    assert unknown["payload"]["classification"] == "UNKNOWN_OUTCOME"
    assert "synthetic timeout" in unknown["payload"]["error"]


def test_authoritative_rejection_records_terminal_rejection(tmp_path: Path):
    broker, client = fixture_broker(tmp_path)
    client.create_order.side_effect = PermissionError("API key lacks trading permission")
    safe = AuditSafeBroker(broker, make_risk_config(tmp_path))

    async def run():
        await safe.connect()
        safe.record_market_snapshot("BTC/USDT:USDT", 80000)
        with pytest.raises(PermissionError):
            await safe.submit_order_async("BTC/USDT:USDT", 0.001, side=OrderSide.BUY)
        await safe.disconnect()

    try:
        asyncio.run(run())
    finally:
        safe.close_persistence()
        broker.journal.close()

    events = _journal_events(safe)
    event_names = [e["event"] for e in events]
    assert "order_submission_intent" in event_names
    assert "order_submission_rejected" in event_names

    rejected = next(e for e in events if e["event"] == "order_submission_rejected")
    assert rejected["payload"]["classification"] == "TERMINAL_REJECTION"


def test_post_acceptance_persistence_failure_records_do_not_retry(tmp_path: Path):
    broker, client = fixture_broker(tmp_path)
    client.create_order.side_effect = AcceptedOrderPersistenceError("Simulated persistence write failed")
    safe = AuditSafeBroker(broker, make_risk_config(tmp_path))

    async def run():
        await safe.connect()
        safe.record_market_snapshot("BTC/USDT:USDT", 80000)
        with pytest.raises(AcceptedOrderPersistenceError):
            await safe.submit_order_async("BTC/USDT:USDT", 0.001, side=OrderSide.BUY)
        await safe.disconnect()

    try:
        asyncio.run(run())
    finally:
        safe.close_persistence()
        broker.journal.close()

    events = _journal_events(safe)
    event_names = [e["event"] for e in events]
    assert "order_submission_intent" in event_names
    assert "order_accepted_unpersisted" in event_names

    unpersisted = next(e for e in events if e["event"] == "order_accepted_unpersisted")
    assert unpersisted["payload"]["classification"] == "ACCEPTED_BUT_UNPERSISTED_DO_NOT_RETRY"


def test_task_cancellation_records_unknown_outcome(tmp_path: Path):
    broker, client = fixture_broker(tmp_path)
    client.create_order.side_effect = asyncio.CancelledError()
    safe = AuditSafeBroker(broker, make_risk_config(tmp_path))

    async def run():
        await safe.connect()
        safe.record_market_snapshot("BTC/USDT:USDT", 80000)
        with pytest.raises(asyncio.CancelledError):
            await safe.submit_order_async("BTC/USDT:USDT", 0.001, side=OrderSide.BUY)
        await safe.disconnect()

    try:
        asyncio.run(run())
    finally:
        safe.close_persistence()
        broker.journal.close()

    events = _journal_events(safe)
    event_names = [e["event"] for e in events]
    assert "order_submission_intent" in event_names
    assert "order_submission_unknown" in event_names

    unknown = next(e for e in events if e["event"] == "order_submission_unknown")
    assert unknown["payload"]["classification"] == "UNKNOWN_OUTCOME"


def test_build_native_paper_engine_wires_audit_safe_broker(tmp_path: Path):
    broker, _ = fixture_broker(tmp_path)
    store = tmp_path / "private"
    store.mkdir(mode=0o700, exist_ok=True)
    account = ReviewedPaperAccount(
        account_uid="24680",
        strategy_id="synthetic-onebar",
        allowed_assets=frozenset({"BTC/USDT:USDT"}),
        max_order_shares=0.01,
        max_order_value=1000.0,
        max_position_shares=0.02,
        max_position_value=2000.0,
        max_total_exposure=5000.0,
        max_positions=1,
        max_orders_per_minute=4,
        max_daily_loss=100.0,
        max_drawdown_pct=0.05,
        max_price_deviation_pct=0.05,
        max_data_staleness_seconds=300.0,
        dedup_window_seconds=1.0,
        feed_silence_seconds=130.0,
        max_event_age_seconds=300.0,
        max_recovery_attempts=3,
        recovery_cooldown_seconds=0.01,
        state_dir=store,
        reviewed=True,
    )

    class DummyStrat(Strategy):
        def on_data(self, timestamp, data, context, broker):
            pass

    engine = build_native_paper_engine(DummyStrat(), broker, None, account)
    assert isinstance(engine.broker, AuditSafeBroker)
    engine.broker.close_persistence()
    broker.journal.close()
