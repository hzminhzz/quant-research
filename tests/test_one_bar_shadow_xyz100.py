import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from ccxt.base.errors import NetworkError
from ml4t.backtest.types import OrderType
from ml4t.live import LiveRiskConfig, SafeBroker

from scripts.run_one_bar_shadow_xyz100 import (
    SYMBOL,
    OneBarXYZ100,
    ResilientCryptoFeed,
    ShadowIntentBroker,
    SignedEquitySafeBroker,
    breakout_side,
    ensure_private_state_dir,
)


def test_shadow_state_directory_requires_owner_only_permissions(
    tmp_path: Path,
) -> None:
    private_dir = ensure_private_state_dir(tmp_path / "private")
    assert private_dir.stat().st_mode & 0o077 == 0

    public_dir = tmp_path / "public"
    public_dir.mkdir()
    public_dir.chmod(0o755)
    with pytest.raises(PermissionError):
        ensure_private_state_dir(public_dir)


def test_transient_hyperliquid_disconnect_retries_without_failing_feed() -> None:
    async def exercise() -> None:

        class FakeExchange:
            calls: int = 0

            async def watch_ohlcv(
                self,
                symbol: str,
                timeframe: str,
                *,
                limit: int,
            ) -> list[list[float]]:
                self.calls += 1
                if self.calls == 1:
                    raise NetworkError("connection closed")
                timestamp_ms = int(datetime.now(UTC).timestamp() * 1000)
                return [[timestamp_ms, 100.0, 101.0, 99.0, 100.0, 1.0]]

        class FiniteFeed(ResilientCryptoFeed):
            async def _process_candle_batch(
                self,
                candles: list[list[float]],
                symbol: str,
            ) -> None:
                await super()._process_candle_batch(candles, symbol)
                self._running = False

        feed = FiniteFeed(
            exchange="hyperliquid",
            symbols=[SYMBOL],
            timeframe="30m",
            stream_ohlcv=True,
            experimental=True,
        )
        fake_exchange = FakeExchange()
        feed.exchange = fake_exchange
        feed._running = True
        await feed._stream_ohlcv_for_symbol(SYMBOL)

        assert fake_exchange.calls == 2
        assert feed.stats["candle_count"] == 1
        assert feed._failure is None

    asyncio.run(exercise())


def test_breakout_side_requires_one_unambiguous_trigger() -> None:
    assert (
        breakout_side(high=101.0, low=99.0, long_stop=100.0, short_stop=98.0)
        == "long"
    )
    assert (
        breakout_side(high=101.0, low=97.0, long_stop=100.0, short_stop=98.0)
        is None
    )
    assert (
        breakout_side(high=99.0, low=97.0, long_stop=100.0, short_stop=98.0)
        == "short"
    )
    assert (
        breakout_side(high=99.0, low=99.0, long_stop=100.0, short_stop=98.0)
        is None
    )




def test_strategy_does_not_reenter_after_exit_in_same_bar() -> None:
    timestamp = datetime(2026, 1, 1, 18, tzinfo=UTC)
    strategy = OneBarXYZ100()
    strategy.arm_after = timestamp - timedelta(minutes=30)
    strategy.long_stop = 105.0
    strategy.short_stop = 98.0
    strategy.position = {
        "side": "long",
        "quantity": 1.0,
        "stop": 95.0,
        "exit_at": timestamp,
    }
    orders = []

    class IntentBroker:
        def submit_order(self, asset, quantity, **kwargs):
            orders.append((asset, quantity, kwargs))
            return SimpleNamespace(filled_price=100.0)

    data = {
        SYMBOL: {
            "open": 100.0,
            "high": 104.0,
            "low": 97.0,
            "close": 99.0,
            "volume": 1.0,
        }
    }
    context = {"_market_event": {"completion": "evolving"}}
    broker = IntentBroker()

    strategy.on_data(timestamp, data, context, broker)
    strategy.on_data(timestamp, data, context, broker)

    assert len(orders) == 1
    assert strategy.position is None


def test_strategy_emits_one_long_intent_for_clear_breakout() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles = [
        [
            int((start + timedelta(minutes=30 * index)).timestamp() * 1000),
            30_500.0,
            31_000.0,
            30_000.0,
            30_500.0,
            1.0,
        ]
        for index in range(50)
    ]
    arm_after = start + timedelta(minutes=30 * 50)
    strategy = OneBarXYZ100()
    strategy.seed_history(candles, arm_after)
    intents = []

    class IntentBroker:
        def submit_order(self, asset, quantity, **kwargs):
            intents.append((asset, quantity, kwargs))
            return SimpleNamespace(filled_price=kwargs["limit_price"])

    strategy.on_data(
        arm_after,
        {
            SYMBOL: {
                "open": 31_000.0,
                "high": 31_001.0,
                "low": 30_500.0,
                "close": 31_001.0,
                "volume": 1.0,
            }
        },
        {"_market_event": {"completion": "evolving"}},
        IntentBroker(),
    )

    assert strategy.position is not None
    assert strategy.position["side"] == "long"
    assert len(intents) == 1
    assert intents[0][1] == 1.0
    assert intents[0][2]["stop_price"] == 31_000.0
    assert strategy.position["stop"] == 30_000.0


def test_shadow_short_mark_to_market_uses_signed_quantity(tmp_path: Path) -> None:
    async def exercise() -> None:
        safe = SignedEquitySafeBroker(
            ShadowIntentBroker(),
            LiveRiskConfig(
                execution_mode="shadow",
                allowed_assets={SYMBOL},
                max_position_value=50_000.0,
                max_position_shares=1.0,
                max_total_exposure=50_000.0,
                max_positions=1,
                max_order_value=50_000.0,
                max_order_shares=1.0,
                max_drawdown_pct=0.05,
                state_file=str(tmp_path / "risk.json"),
                journal_file=str(tmp_path / "events.jsonl"),
                max_price_deviation_pct=None,
                max_data_staleness_seconds=None,
            ),
        )
        short_order = await safe.submit_order_async(
            SYMBOL,
            -1.0,
            order_type=OrderType.LIMIT,
            limit_price=30_380.0,
        )
        assert short_order.filled_price == 30_380.0
        assert await safe.get_account_value_async() == 100_000.0

        safe.record_market_snapshot(SYMBOL, 30_348.0)
        assert await safe.get_account_value_async() == 100_032.0
        await safe.disconnect()

    asyncio.run(exercise())


def test_shadow_stop_limit_uses_trigger_price_and_never_routes(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        safe = SafeBroker(
            ShadowIntentBroker(),
            LiveRiskConfig(
                execution_mode="shadow",
                allowed_assets={SYMBOL},
                max_position_value=500.0,
                max_position_shares=1.0,
                max_total_exposure=500.0,
                max_positions=1,
                max_order_value=500.0,
                max_order_shares=1.0,
                state_file=str(tmp_path / "risk.json"),
                journal_file=str(tmp_path / "events.jsonl"),
                max_price_deviation_pct=None,
                max_data_staleness_seconds=None,
            ),
        )
        order = await safe.submit_order_async(
            SYMBOL,
            1.0,
            order_type=OrderType.STOP_LIMIT,
            stop_price=100.0,
            limit_price=100.0,
        )
        assert order.filled_price == 100.0
        assert order.status.value == "filled"
        await safe.disconnect()

    asyncio.run(exercise())
