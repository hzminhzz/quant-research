"""Non-routing ML4T shadow run for the exploratory XYZ100 breakout.

Run: ``uv run python scripts/run_one_bar_shadow_xyz100.py``
NullBroker prevents exchange orders. Shadow entries/exits fill at the trigger
or observed 30-minute open; OHLC cannot establish intrabar event order.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
from ccxt.base.errors import ExchangeNotAvailable, NetworkError, RequestTimeout
from ml4t.backtest import Strategy
from ml4t.backtest.types import OrderType
from ml4t.engineer import compute_features
from ml4t.live import LiveEngine, LiveRiskConfig, SafeBroker
from ml4t.live.cli.main import NullBroker
from ml4t.live.feeds.crypto_feed import CryptoFeed
from ml4t.specs import ExecutionCapability, MarketEvent

STATE_DIR = Path.home() / ".local" / "state" / "xyz100_shadow"
SYMBOL = "XYZ-XYZ100/USDC:USDC"
LOOKBACK = 50
STOP_POINTS = 1000.0
MAX_DAILY_ENTRIES = 2
HALF_HOUR = timedelta(minutes=30)
LOG = logging.getLogger("xyz100-shadow")


def ensure_private_state_dir(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.stat().st_mode & 0o077:
        raise PermissionError(f"shadow state directory is not private: {path}")
    return path


class ResilientCryptoFeed(CryptoFeed):
    """Retry transient Hyperliquid WebSocket failures without resetting state."""

    _iterator: AsyncIterator[MarketEvent]

    def __aiter__(self) -> ResilientCryptoFeed:
        self._iterator = super().__aiter__()
        return self

    async def __anext__(self) -> MarketEvent:
        return await self._iterator.__anext__()

    async def _stream_ohlcv_for_symbol(self, symbol: str) -> None:
        attempt = 0
        try:
            while self._running:
                try:
                    candles = await self.exchange.watch_ohlcv(
                        symbol,
                        self.timeframe,
                        limit=2,
                    )
                except (NetworkError, RequestTimeout, ExchangeNotAvailable):
                    attempt += 1
                    delay = min(2 ** min(attempt - 1, 5), 30)
                    LOG.warning(
                        "ohlcv_stream_retry symbol=%s attempt=%s delay_seconds=%s",
                        symbol,
                        attempt,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                attempt = 0
                await self._process_candle_batch(candles, symbol)
        except asyncio.CancelledError:
            LOG.info("OHLCV stream for %s cancelled", symbol)
        except Exception as error:
            self._stream_failed(error, stream=f"ohlcv:{symbol}")
            LOG.exception("OHLCV stream for %s failed", symbol)



def breakout_side(
    *, high: float, low: float, long_stop: float, short_stop: float
) -> str | None:
    """Return a side only when exactly one breakout level was touched."""
    long_hit = high >= long_stop
    short_hit = low <= short_stop
    if long_hit == short_hit:
        return None
    return "long" if long_hit else "short"


def half_hour_start(timestamp: datetime) -> datetime:
    minute = timestamp.minute - timestamp.minute % 30
    return timestamp.replace(minute=minute, second=0, microsecond=0)


def next_half_hour(timestamp: datetime) -> datetime:
    return half_hour_start(timestamp) + HALF_HOUR


def chicago_session_day(timestamp: datetime) -> str:
    from zoneinfo import ZoneInfo

    local = timestamp.astimezone(ZoneInfo("America/Chicago"))
    day = local.date() if local.hour >= 17 else local.date() - timedelta(days=1)
    return day.isoformat()


def donchian_levels(bars: list[dict[str, Any]]) -> tuple[float, float]:
    frame = pl.DataFrame(bars[-LOOKBACK:]).select(
        "timestamp", "open", "high", "low", "close", "volume"
    )
    result = compute_features(
        frame,
        [{"name": "donchian_channels", "params": {"period": LOOKBACK}}],
        timestamp_col="timestamp",
        assume_sorted=True,
    )
    if not isinstance(result, pl.DataFrame):
        raise TypeError("ML4T Engineer must return a DataFrame for DataFrame input")
    row = result.row(-1, named=True)
    return float(row["donchian_channels_0"]), float(row["donchian_channels_1"])


class ShadowIntentBroker(NullBroker):
    """Allow stop/limit intents only in SafeBroker's virtual portfolio."""

    @property
    def execution_capabilities(self) -> frozenset[ExecutionCapability]:
        return frozenset(
            {
                ExecutionCapability.STOP_LIMIT,
                ExecutionCapability.LIMIT,
            }
        )


class SignedEquitySafeBroker(SafeBroker):
    """Use signed position value for shadow account equity and drawdown checks."""

    async def get_account_value_async(self) -> float:
        if not self.config.shadow_mode:
            return await super().get_account_value_async()
        cash = await self.get_cash_async()
        market_value = sum(
            position.quantity * (position.current_price or position.entry_price)
            for position in self.positions.values()
        )
        return cash + market_value


class OneBarXYZ100(Strategy):
    def __init__(self) -> None:
        self.history: list[dict[str, Any]] = []
        self.long_stop: float | None = None
        self.short_stop: float | None = None
        self.arm_after: datetime | None = None
        self.entries_by_day: dict[str, int] = {}
        self.position: dict[str, Any] | None = None
        self.last_exit_bar: datetime | None = None

    def seed_history(self, candles: list[list[Any]], arm_after: datetime) -> None:
        self.history = [
            {
                "timestamp": datetime.fromtimestamp(row[0] / 1000, UTC),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
            for row in candles[-LOOKBACK:]
        ]
        if len(self.history) < LOOKBACK:
            raise RuntimeError(f"Need {LOOKBACK} complete 30-minute candles")
        self.long_stop, self.short_stop = donchian_levels(self.history)
        self.arm_after = arm_after

    def on_data(self, timestamp, data, context, broker) -> None:
        bar = data[SYMBOL]
        completion = context.get("_market_event", {}).get("completion")
        exited = False

        if self.arm_after is not None and timestamp >= self.arm_after:
            if self.position is not None:
                position = self.position
                stop_hit = (
                    float(bar["low"]) <= position["stop"]
                    if position["side"] == "long"
                    else float(bar["high"]) >= position["stop"]
                )
                if stop_hit:
                    order = broker.submit_order(
                        SYMBOL,
                        -position["quantity"],
                        order_type=OrderType.STOP_LIMIT,
                        stop_price=position["stop"],
                        limit_price=position["stop"],
                    )
                    LOG.info("shadow_exit reason=stop price=%.8f", order.filled_price)
                    self.last_exit_bar = half_hour_start(timestamp)
                    self.position = None
                    exited = True
                elif timestamp >= position["exit_at"]:
                    order = broker.submit_order(
                        SYMBOL,
                        -position["quantity"],
                        order_type=OrderType.LIMIT,
                        limit_price=float(bar["open"]),
                    )
                    LOG.info(
                        "shadow_exit reason=next_30m_open price=%.8f",
                        order.filled_price,
                    )
                    self.last_exit_bar = half_hour_start(timestamp)
                    self.position = None
                    exited = True

            if (
                not exited
                and half_hour_start(timestamp) != self.last_exit_bar
                and self.position is None
                and self.long_stop is not None
                and self.short_stop is not None
            ):
                side = breakout_side(
                    high=float(bar["high"]),
                    low=float(bar["low"]),
                    long_stop=self.long_stop,
                    short_stop=self.short_stop,
                )
                if (
                    float(bar["high"]) >= self.long_stop
                    and float(bar["low"]) <= self.short_stop
                ):
                    LOG.warning("ambiguous_both_breakout_levels at %s", timestamp.isoformat())
                elif side is not None:
                    day = chicago_session_day(timestamp)
                    if self.entries_by_day.get(day, 0) < MAX_DAILY_ENTRIES:
                        level = self.long_stop if side == "long" else self.short_stop
                        quantity = 1.0 if side == "long" else -1.0
                        order = broker.submit_order(
                            SYMBOL,
                            quantity,
                            order_type=OrderType.STOP_LIMIT,
                            stop_price=level,
                            limit_price=level,
                        )
                        self.entries_by_day[day] = self.entries_by_day.get(day, 0) + 1
                        self.position = {
                            "side": side,
                            "quantity": quantity,
                            "stop": float(order.filled_price)
                            - STOP_POINTS * (1 if side == "long" else -1),
                            "exit_at": half_hour_start(timestamp) + HALF_HOUR,
                        }
                        LOG.info(
                            "shadow_entry side=%s trigger=%.8f time=%s",
                            side,
                            level,
                            timestamp.isoformat(),
                        )

        if completion == "complete":
            bar_time = timestamp.astimezone(UTC)
            if not self.history or bar_time > self.history[-1]["timestamp"]:
                self.history.append(
                    {
                        "timestamp": bar_time,
                        "open": float(bar["open"]),
                        "high": float(bar["high"]),
                        "low": float(bar["low"]),
                        "close": float(bar["close"]),
                        "volume": float(bar["volume"]),
                    }
                )
                self.history = self.history[-LOOKBACK:]
                if len(self.history) == LOOKBACK:
                    self.long_stop, self.short_stop = donchian_levels(self.history)


async def run() -> None:
    strategy = OneBarXYZ100()
    feed = ResilientCryptoFeed(
        exchange="hyperliquid",
        symbols=[SYMBOL],
        timeframe="30m",
        stream_ohlcv=True,
        experimental=True,
    )
    output = ensure_private_state_dir(STATE_DIR)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    broker = SignedEquitySafeBroker(
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
            max_daily_loss=2_000.0,
            max_drawdown_pct=0.05,
            # ponytail: evolving bars lack quotes; LiveEngine still checks event age.
            max_price_deviation_pct=None,
            max_data_staleness_seconds=None,
            state_file=str(output / f"{run_id}_risk.json"),
            journal_file=str(output / f"{run_id}_audit.jsonl"),
        ),
    )
    try:
        await feed.start()
        now = datetime.now(UTC)
        candles = await feed.exchange.fetch_ohlcv(SYMBOL, "30m", limit=LOOKBACK + 2)
        now_ms = int(now.timestamp() * 1000)
        complete = [row for row in candles if int(row[0]) + 30 * 60_000 <= now_ms]
        strategy.seed_history(complete, next_half_hour(now))
        engine = LiveEngine(
            strategy,
            broker,
            feed,
            feed_silence_seconds=180.0,
            halt_on_unhealthy=True,
            max_event_age_seconds=3600.0,
        )
        await engine.connect()
        print(
            f"run_id={run_id} mode=shadow destination=NullBroker "
            f"armed_after={strategy.arm_after.isoformat()}",
            flush=True,
        )
        await engine.run()
    finally:
        feed.stop()
        await feed.close()
        await broker.disconnect()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(run())


if __name__ == "__main__":
    main()
