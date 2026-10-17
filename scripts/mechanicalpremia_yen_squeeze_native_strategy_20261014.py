"""Native ML4T adapter for the Mechanical Premia Yen Squeeze source rules.

This is an execution adapter, not a qualified MT5 reproduction. It requires
explicit broker terms and completed-H1 features. ML4T Engine owns all order
execution and account state.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import polars as pl
from ml4t.backtest import (
    BacktestConfig,
    CommissionType,
    DataFeed,
    Engine,
    ExecutionMode,
    OrderSide,
    OrderType,
    StopFillMode,
    Strategy,
)
from ml4t.backtest.config import ShareType
from ml4t.engineer import compute_features

from scripts.audit_mechanicalpremia_yen_squeeze_native_20261014 import (
    add_upper_median,
    build_complete_h1,
)


class UnqualifiedExecution(ValueError):
    """Raised when source broker terms or safe native stop semantics are absent."""


@dataclass(frozen=True)
class BrokerTerms:
    tick_size: float
    tick_value: float  # MQL SYMBOL_TRADE_TICK_VALUE is already in account currency
    lot_min: float
    lot_max: float
    lot_step: float
    margin_currency: str
    point_size: float
    spread: float
    account_currency: str
    quote_to_account: float

    def validate(self) -> None:
        vals = (self.tick_size, self.tick_value, self.lot_min, self.lot_max,
                self.lot_step, self.point_size, self.spread, self.quote_to_account)
        if any(value <= 0 for value in vals) or self.lot_max < self.lot_min:
            raise UnqualifiedExecution("complete positive broker and account terms are required")
        if not self.margin_currency or not self.account_currency:
            raise UnqualifiedExecution("margin_currency and account_currency are required")


def build_features(hourly: pl.DataFrame) -> pl.DataFrame:
    """Use the registered ML4T ATR14 and Donchian20/500 features."""
    frame = compute_features(
        hourly.sort("timestamp"),
        [
            {"name": "atr", "params": {"period": 14}, "output": "atr14"},
            {"name": "donchian_channels", "params": {"period": 20}, "output": "donchian20"},
            {"name": "donchian_channels", "params": {"period": 500}, "output": "donchian500"},
        ],
        timestamp_col="timestamp",
    )
    return add_upper_median(frame).with_columns(
        (pl.col("timestamp") + pl.duration(hours=1)).alias("available_at")
    )


def prepare_minute_bars(minutes: pl.DataFrame, *, naive_is_utc: bool = False) -> pl.DataFrame:
    """Attach the last completed H1 feature row to each minute bar-open."""
    hourly, _ = build_complete_h1(minutes, naive_is_utc=naive_is_utc)
    features = build_features(hourly)
    dtype = minutes.schema["timestamp"]
    if dtype.time_zone is None:
        if not naive_is_utc:
            raise ValueError("naive timestamps require explicit UTC localization")
        minutes = minutes.with_columns(pl.col("timestamp").dt.replace_time_zone("UTC"))
    joined = minutes.sort("timestamp").join_asof(
        features.sort("available_at"), left_on="timestamp", right_on="available_at", strategy="backward"
    )
    if joined.filter(pl.col("available_at").is_not_null() & (pl.col("available_at") > pl.col("timestamp"))).height:
        raise AssertionError("future H1 feature became available before its close")
    return joined


def risk_lots(balance: float, risk_fraction: float, stop_distance: float, terms: BrokerTerms) -> float:
    """Source 1% balance risk size, rounded down to the injected broker lot step."""
    terms.validate()
    if min(balance, risk_fraction, stop_distance) <= 0:
        raise ValueError("balance, risk_fraction, and stop_distance must be positive")
    cash_risk = balance * risk_fraction
    # Mirror the MQL sizing formula. Applying quote_to_account again here
    # would double-convert SYMBOL_TRADE_TICK_VALUE, which is account-denominated.
    loss_per_lot = stop_distance / terms.tick_size * terms.tick_value
    raw = cash_risk / loss_per_lot
    stepped = (raw // terms.lot_step) * terms.lot_step
    if stepped < terms.lot_min:
        raise UnqualifiedExecution("risk size is below broker minimum lot; no minimum-lot risk override")
    if stepped > terms.lot_max:
        raise UnqualifiedExecution("risk size exceeds broker maximum lot")
    return float(round(stepped, 10))


class YenSqueezeStrategy(Strategy):
    """Thin source-rule strategy using native ML4T Broker orders only.

    `synthetic_mode=True` permits adapter behavior tests. Production-equivalent
    pending-stop entries fail closed because Engine has no parent/child STOP
    facility; submitting protection in `on_data` occurs after the fill bar and
    leaves that entire bar unprotected.
    """

    def __init__(self, symbol: str, terms: BrokerTerms, *, risk_fraction: float = 0.01,
                 synthetic_mode: bool = False, lookback: int = 20):
        terms.validate()
        if lookback not in (20, 500):
            raise ValueError("source lookback must be 20; 500 is the separate prose interpretation")
        self.symbol = symbol
        self.terms = terms
        self.risk_fraction = risk_fraction
        self.synthetic_mode = synthetic_mode
        self.lookback = lookback
        self.pending: dict[str, tuple[str, datetime, float, float]] = {}
        self.expired_order_ids: list[str] = []
        self.last_decision: datetime | None = None
        self.last_manage: datetime | None = None
        self.protected_position = False
        self.protective_order_id: str | None = None
        self.protection_gap_detected = False

    def on_data(self, timestamp: datetime, data: dict[str, dict], context: dict[str, Any], broker: Any) -> None:
        bar = data.get(self.symbol)
        if bar is None:
            return
        # ML4T DataFeed exposes non-price columns through the causal signals map.
        bar = {**bar, **bar.get("signals", {})}
        position = broker.get_position(self.symbol)
        if position is not None and not self.protected_position:
            self.protection_gap_detected = True
            if not self.synthetic_mode:
                raise UnqualifiedExecution(
                    "native Engine cannot attach a protective STOP to a pending STOP entry; "
                    "on_data runs after the fill bar, so immediate source protection is unavailable"
                )
            self._submit_protection(timestamp, bar, broker, position)
            self.protected_position = True
        elif position is None:
            self.protected_position = False
            self.protective_order_id = None

        for order_id, (side, expires, distance, initial_stop) in tuple(self.pending.items()):
            order = broker.get_order(order_id)
            if order is None or getattr(order.status, "value", order.status) != "pending":
                self.pending.pop(order_id, None)
            elif timestamp >= expires:
                if broker.cancel_order(order_id):
                    self.expired_order_ids.append(order_id)
                self.pending.pop(order_id, None)

        atr = bar.get("atr14")
        median = bar.get("atr100_upper_median")
        available_at = bar.get("available_at")
        if (position is not None or self.pending or atr is None or median is None
                or available_at is None or available_at > timestamp or not atr < median):
            self._manage_stop(timestamp, bar, broker, position)
            return
        if self.last_decision == available_at:
            self._manage_stop(timestamp, bar, broker, position)
            return
        self.last_decision = available_at

        channel = "donchian20" if self.lookback == 20 else "donchian500"
        upper, lower = bar.get(f"{channel}_0"), bar.get(f"{channel}_1")
        if upper is None or lower is None:
            return
        ask = float(bar["close"]) + self.terms.spread / 2
        bid = float(bar["close"]) - self.terms.spread / 2
        expiry = timestamp + timedelta(hours=1)
        lots = risk_lots(float(broker.get_account_value()), self.risk_fraction, 2 * float(atr), self.terms)
        # Do not create an invalid stop after its threshold has already crossed.
        if float(upper) > ask:
            self._submit_entry("buy", lots, float(upper), float(upper) - 2 * float(atr), expiry, broker)
        if float(lower) < bid:
            self._submit_entry("sell", lots, float(lower), float(lower) + 2 * float(atr), expiry, broker)
        self._manage_stop(timestamp, bar, broker, position)

    def _submit_entry(self, side: str, lots: float, level: float, stop: float,
                      expiry: datetime, broker: Any) -> None:
        if not self.synthetic_mode:
            raise UnqualifiedExecution(
                "native Engine cannot provide immediate parent/child STOP protection; "
                "source-equivalent entry is disabled"
            )
        qty = lots if side == "buy" else -lots
        order = broker.submit_order(
            self.symbol, qty, side=OrderSide.BUY if qty > 0 else OrderSide.SELL,
            order_type=OrderType.STOP, stop_price=level,
        )
        if order is not None:
            self.pending[order.order_id] = (side, expiry, abs(level - stop), stop)

    def _submit_protection(self, timestamp: datetime, bar: dict, broker: Any, position: Any) -> None:
        distance = float(bar["atr14"]) * 2
        long = position.quantity > 0
        stop = float(position.entry_price) - distance if long else float(position.entry_price) + distance
        order = broker.submit_order(
            self.symbol, -position.quantity,
            side=OrderSide.SELL if long else OrderSide.BUY,
            order_type=OrderType.STOP, stop_price=stop,
        )
        if order is None:
            raise UnqualifiedExecution("native protective stop order was not accepted")
        self.protective_order_id = order.order_id

    def _manage_stop(self, timestamp: datetime, bar: dict, broker: Any, position: Any) -> None:
        if position is None or self.last_manage == timestamp or bar.get("atr14") is None:
            return
        self.last_manage = timestamp
        distance = 2 * float(bar["atr14"])
        long = position.quantity > 0
        mark = float(bar.get("bid", bar["close"] - self.terms.spread / 2)) if long else float(bar.get("ask", bar["close"] + self.terms.spread / 2))
        proposed = mark - distance if long else mark + distance
        protective = broker.get_order(self.protective_order_id) if self.protective_order_id else None
        if protective is not None and getattr(protective.status, "value", protective.status) != "pending":
            raise UnqualifiedExecution("native protective stop is no longer pending while position remains open")
        if protective is None:
            raise UnqualifiedExecution("native protective stop is absent while position remains open")
        old = protective.stop_price
        improves = old is None or (proposed > old + 2 * self.terms.point_size if long else proposed < old - 2 * self.terms.point_size)
        if improves:
            if protective:
                broker.update_order(protective.order_id, stop_price=proposed)
            # No fallback stop creation here: protection must already exist.
            # An opposing entry STOP is not a substitute for the protective exit.

    def _validate_completed_run(self) -> None:
        if self.protection_gap_detected and not self.synthetic_mode:
            raise UnqualifiedExecution("source protection gap detected")


def run_native(bars: pl.DataFrame, strategy: YenSqueezeStrategy, *, initial_cash: float = 10_000.0):
    """Run the native engine on supplied fabricated bars only."""
    if isinstance(strategy, YenSqueezeStrategy) and not strategy.synthetic_mode:
        raise UnqualifiedExecution(
            "source-equivalent run blocked: native Engine lacks verified broker terms and parent/child STOP protection"
        )
    config = BacktestConfig(
        execution_mode=ExecutionMode.NEXT_BAR,
        stop_fill_mode=StopFillMode.NEXT_BAR_OPEN,
        initial_cash=initial_cash,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=0.0,
        allow_short_selling=True,
        share_type=ShareType.FRACTIONAL,
    )
    signal_columns = [name for name in (
        "atr14", "atr100_upper_median", "available_at", "donchian20_0",
        "donchian20_1", "donchian500_0", "donchian500_1",
    ) if name in bars.columns]
    prices = bars.drop(signal_columns) if signal_columns else bars
    signals = bars.select("timestamp", "symbol", *signal_columns) if signal_columns else None
    feed = DataFeed(prices_df=prices, signals_df=signals,
                    entity_col="symbol", timestamp_col="timestamp")
    return Engine(feed, strategy, config).run()


def run_source_backtest(bars: pl.DataFrame, strategy: YenSqueezeStrategy,
                        terms: BrokerTerms | None = None):
    """Fail-closed entry point for any source-market-data execution request."""
    if terms is None:
        raise UnqualifiedExecution("source backtest requires explicit broker and account conversion terms")
    terms.validate()
    raise UnqualifiedExecution(
        "source backtest remains blocked: installed Engine cannot guarantee immediate protective STOP "
        "on pending STOP entry, and native position semantics do not certify source hedging behavior"
    )

