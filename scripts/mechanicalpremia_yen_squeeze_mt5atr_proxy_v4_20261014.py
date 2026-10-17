"""Broker-neutral Yen Squeeze price proxy, fully accounted by ml4t-backtest.

The installed Engine owns all market fills and the account ledger. Features are
computed by ml4t-engineer; no custom fill or PnL path exists in this module.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import polars as pl
from ml4t.backtest import (
    BacktestConfig, DataFeed, Engine, ExecutionMode, OrderSide, OrderType,
    StopFillMode, Strategy,
)
from ml4t.backtest.config import FillOrdering, ShareType, SlippageType

from scripts.mechanicalpremia_yen_squeeze_mt5atr_features_20261014 import (
    prepare_minute_bars,
)

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data/processed/mechanicalpremia_yen_squeeze_mvp_20261014"
SESSION = "mechanicalpremia-yen-squeeze-mt5atr-v4-20261014"
USDJPY = DATA_DIR / "USDJPY_2023_2024_1m.parquet"
GBPJPY = DATA_DIR / "GBPJPY_2023_2024_1m.parquet"
CADJPY = ROOT / "data/processed/mechanicalpremia_yen_squeeze_proxy_20261014/CADJPY_2023_2024_1m.parquet"
DEV_END = datetime(2025, 1, 1, tzinfo=timezone.utc)
JPY_PER_USD = 150.0


class YenSqueezeProxy(Strategy):
    """Native-order strategy with the predeclared one-minute protection gap."""

    def __init__(self, symbols: tuple[str, ...], lookback: int, quote_half_spread: float):
        if lookback not in (20, 500):
            raise ValueError("lookback must be preregistered 20 or 500")
        self.symbols = symbols
        self.lookback = lookback
        self.quote_half_spread = quote_half_spread
        self.pending: dict[str, tuple[str, datetime, float]] = {}
        self.last_decision: dict[str, datetime] = {}
        self.protective: dict[str, str] = {}
        self.initial_stop: dict[str, float] = {}
        self.entry_gap_bars: list[dict[str, Any]] = []
        self.gap_breaches: list[dict[str, Any]] = []
        self.expired: list[str] = []
        self.ambiguous_minutes: list[dict[str, Any]] = []
        self.order_events: list[dict[str, Any]] = []
        self._known_fill_ids: set[str] = set()
        self._fill_cursor = 0  # Observe each native fill once; O(number of fills), not O(bars*fills).

    def on_data(self, timestamp: datetime, data: dict[str, dict], context: dict[str, Any], broker: Any) -> None:
        for symbol in self.symbols:
            raw = data.get(symbol)
            if raw is None:
                continue
            bar = {**raw, **raw.get("signals", {})}
            position = broker.get_position(symbol)
            self._observe_fills(timestamp, broker)

            # Expire through the native broker API on the first symbol bar at/after expiry.
            for order_id, (order_symbol, expiry, _atr) in tuple(self.pending.items()):
                if order_symbol != symbol:
                    continue
                order = broker.get_order(order_id)
                status = getattr(getattr(order, "status", None), "value", None)
                if status != "pending":
                    self.pending.pop(order_id, None)
                elif timestamp >= expiry:
                    if broker.cancel_order(order_id):
                        self.expired.append(order_id)
                        self.order_events.append({"ts": timestamp.isoformat(), "event": "expire_cancel", "id": order_id})
                    self.pending.pop(order_id, None)

            if position is not None:
                self._protect_or_manage(symbol, timestamp, bar, position, broker)
                continue
            # Clear completed protection references; retain live entry orders and
            # allow both directional source orders to coexist (no OCO).
            self.protective.pop(symbol, None)
            atr = bar.get("atr14")
            median = bar.get("atr100_upper_median")
            available = bar.get("available_at")
            if (atr is None or median is None or available is None or available > timestamp
                    or not float(atr) < float(median)
                    or self.last_decision.get(symbol) == available):
                continue
            self.last_decision[symbol] = available
            upper, lower = bar.get(f"donchian{self.lookback}_0"), bar.get(f"donchian{self.lookback}_1")
            if upper is None or lower is None:
                continue
            ask = float(bar["close"]) + self.quote_half_spread
            bid = float(bar["close"]) - self.quote_half_spread
            expiry = timestamp + timedelta(hours=1)
            equity = float(broker.get_account_value())
            # Engine prices are scaled JPY quote values; position quantity is
            # base units, giving USD PnL natively at the frozen 150 JPY/USD.
            size = equity * 0.01 / (2.0 * float(atr))
            if float(upper) > ask:
                self._submit(symbol, size, float(upper),
                             expiry, float(atr), broker, timestamp)
            if float(lower) < bid:
                self._submit(symbol, -size, float(lower),
                             expiry, float(atr), broker, timestamp)
            if float(bar["high"]) >= float(upper) and float(bar["low"]) <= float(lower):
                self.ambiguous_minutes.append({"symbol": symbol, "timestamp": timestamp.isoformat(), "state": "bar_spans_both_channels_after_decision"})

    def _submit(self, symbol: str, quantity: float, stop_price: float,
                expiry: datetime, atr: float, broker: Any, timestamp: datetime) -> None:
        order = broker.submit_order(
            symbol, quantity,
            side=OrderSide.BUY if quantity > 0 else OrderSide.SELL,
            order_type=OrderType.STOP, stop_price=stop_price,
        )
        if order is not None:
            self.pending[order.order_id] = (symbol, expiry, atr)
            self.order_events.append({"ts": timestamp.isoformat(), "event": "entry_submit", "id": order.order_id, "symbol": symbol, "qty": quantity, "stop": stop_price})

    def _observe_fills(self, timestamp: datetime, broker: Any) -> None:
        fills = getattr(broker, "fills", ())
        for fill in fills[self._fill_cursor:]: 
            fill_id = getattr(fill, "fill_id", None) or f"{getattr(fill, 'order_id', '')}:{getattr(fill, 'timestamp', '')}"
            if fill_id in self._known_fill_ids:
                continue
            self._known_fill_ids.add(fill_id)
            self.order_events.append({"ts": timestamp.isoformat(), "event": "native_fill_observed", "id": str(fill_id), "order_id": getattr(fill, "order_id", None), "symbol": getattr(fill, "asset", None) or getattr(fill, "symbol", None)})
        self._fill_cursor = len(fills)

    def _protect_or_manage(self, symbol: str, timestamp: datetime, bar: dict,
                           position: Any, broker: Any) -> None:
        order_id = self.protective.get(symbol)
        order = broker.get_order(order_id) if order_id else None
        status = getattr(getattr(order, "status", None), "value", None)
        if status != "pending":
            atr = bar.get("atr14")
            if atr is None:
                return
            long = position.quantity > 0
            distance = 2.0 * float(atr)
            stop = float(position.entry_price) - distance if long else float(position.entry_price) + distance
            protective = broker.submit_order(
                symbol, -position.quantity,
                side=OrderSide.SELL if long else OrderSide.BUY,
                order_type=OrderType.STOP, stop_price=stop,
            )
            if protective is None:
                raise RuntimeError(f"native protective stop rejected: {symbol} {timestamp}")
            self.protective[symbol] = protective.order_id
            self.initial_stop[symbol] = stop
            crossed = (float(bar["low"]) <= stop if long
                       else float(bar["high"]) >= stop)
            self.entry_gap_bars.append({"symbol": symbol, "timestamp": timestamp.isoformat(), "stop": stop, "breached_during_entry_bar": crossed})
            if crossed:
                self.gap_breaches.append({"symbol": symbol, "timestamp": timestamp.isoformat(), "stop": stop, "decision": "submit_native_market_exit_next_eligible_bar"})
                broker.cancel_order(protective.order_id)
                exit_order = broker.submit_order(
                    symbol, -position.quantity,
                    side=OrderSide.SELL if long else OrderSide.BUY,
                    order_type=OrderType.MARKET,
                )
                if exit_order is None:
                    raise RuntimeError("native delayed-gap market exit was rejected")
                self.order_events.append({"ts": timestamp.isoformat(), "event": "unprotected_breach_market_exit", "id": exit_order.order_id, "symbol": symbol})
                return
            self.order_events.append({"ts": timestamp.isoformat(), "event": "protective_stop_submit", "id": protective.order_id, "symbol": symbol, "stop": stop})
            return

        atr = bar.get("atr14")
        if atr is None:
            return
        long = position.quantity > 0
        mark = (float(bar.get("bid", float(bar["close"]) - self.quote_half_spread))
                if long else float(bar.get("ask", float(bar["close"]) + self.quote_half_spread)))
        distance = 2.0 * float(atr)
        proposed = mark - distance if long else mark + distance
        old = float(order.stop_price)
        point = 0.01 / JPY_PER_USD
        improves = proposed > old + 2 * point if long else proposed < old - 2 * point
        if improves and not broker.update_order(order.order_id, stop_price=proposed):
            raise RuntimeError("native protective stop update failed")


def load_prices() -> pl.DataFrame:
    """Load only the two frozen 2023-2024 files, then scale to USD numeraire."""
    frames = []
    for symbol, path, naive in (
        ("USDJPY", USDJPY, False),
        ("GBPJPY", GBPJPY, True),
        ("CADJPY", CADJPY, False),
    ):
        frame = prepare_minute_bars(pl.read_parquet(path), naive_is_utc=naive)
        if frame.filter(pl.col("timestamp") >= pl.lit(DEV_END)).height:
            raise ValueError(f"protected boundary violation in {symbol}")
        frame = frame.with_columns(pl.lit(symbol).alias("symbol"))
        frames.append(frame)
    return pl.concat(frames, how="diagonal_relaxed").sort("timestamp", "symbol")


def build_feed(minutes: pl.DataFrame) -> DataFeed:
    signal_columns = [name for name in minutes.columns if name in {
        "atr14", "atr100_upper_median", "available_at", "donchian20_0",
        "donchian20_1", "donchian500_0", "donchian500_1",
    }]
    prices = minutes.with_columns(
        (pl.col("open") / JPY_PER_USD).alias("open"),
        (pl.col("high") / JPY_PER_USD).alias("high"),
        (pl.col("low") / JPY_PER_USD).alias("low"),
        (pl.col("close") / JPY_PER_USD).alias("close"),
    )
    for name in signal_columns:
        if name in ("atr14", "atr100_upper_median"):
            prices = prices.with_columns((pl.col(name) / JPY_PER_USD).alias(name))
        if name.startswith("donchian"):
            prices = prices.with_columns((pl.col(name) / JPY_PER_USD).alias(name))
    signals = prices.select("timestamp", "symbol", *signal_columns)
    return DataFeed(
        prices_df=prices.drop(signal_columns), signals_df=signals,
        entity_col="symbol", timestamp_col="timestamp",
    )


def run_engine(minutes: pl.DataFrame, *, lookback: int, roundtrip_jpy: float):
    if minutes.filter(pl.col("timestamp") >= pl.lit(DEV_END)).height:
        raise ValueError("protected 2025+ data reached Engine boundary")
    slip = (roundtrip_jpy / 2.0) / JPY_PER_USD
    strategy = YenSqueezeProxy(
        ("USDJPY", "GBPJPY", "CADJPY"), lookback,
        quote_half_spread=(roundtrip_jpy / 4.0) / JPY_PER_USD,
    )
    config = BacktestConfig(
        initial_cash=10_000.0,
        execution_mode=ExecutionMode.NEXT_BAR,
        stop_fill_mode=StopFillMode.NEXT_BAR_OPEN,
        slippage_type=SlippageType.FIXED,
        slippage_fixed=slip,
        allow_short_selling=True,
        allow_leverage=True,
        initial_margin=0.05,
        long_maintenance_margin=0.025,
        short_maintenance_margin=0.025,
        share_type=ShareType.FRACTIONAL,
        fill_ordering=FillOrdering.EXIT_FIRST,
    )
    engine = Engine(build_feed(minutes), strategy, config)
    result = engine.run()
    return strategy, engine, result
