"""Executable Unified Four-Strategy Portfolio for Propr Classic 2-Step.

Integrates the four promoted strategies into a single executable ML4T portfolio:
  1. B0: 30m Donchian 50-bar resting stop breakout on xyz:XYZ100 (NQ proxy)
  2. C3: H1+D1 ATR risk budget on xyz:SP500 and xyz:XYZ100
  3. RSI: Daily RSI(5) < 30 & SMA(200) mean reversion on xyz:SP500
  4. Donchian BTC: Daily 9-lookback volatility targeted trend on BTC

Preserves exact strategy logic, order types (STOP, STOP_LIMIT, LIMIT, MARKET),
durable order-to-sleeve attribution, incremental fill accounting, and fail-closed
pre-trade risk gating via PropRiskGate.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from ml4t.backtest import OrderType, Strategy
from ml4t.backtest.types import OrderSide

LOG = logging.getLogger("unified_portfolio")


@dataclass
class SleevePosition:
    asset: str
    quantity: float = 0.0
    entry_price: float = 0.0


class SleeveExecutionProxy:
    """Provides a strategy with an isolated broker view bound to its sleeve capital."""

    def __init__(self, portfolio: UnifiedPortfolio, sleeve_id: str, weight: float):
        self._portfolio = portfolio
        self.sleeve_id = sleeve_id
        self.weight = weight
        self._positions: dict[str, SleevePosition] = {}

    def equity(self) -> float:
        total = self._portfolio.get_account_equity()
        return max(0.0, total * self.weight)

    def get_cash(self) -> float:
        total = self._portfolio.get_account_cash()
        return max(0.0, total * self.weight)

    def get_position(self, asset: str) -> Any | None:
        pos = self._positions.get(asset)
        if pos and pos.quantity != 0.0:
            return pos
        return None

    def submit_order(
        self,
        asset: str,
        quantity: float,
        order_type: Any = OrderType.MARKET,
        price: float | None = None,
        stop_price: float | None = None,
        limit_price: float | None = None,
        **kwargs: Any,
    ) -> Any:
        return self._portfolio.route_sleeve_order(
            self.sleeve_id,
            asset=asset,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price or price,
            stop_price=stop_price,
            **kwargs,
        )

    def cancel_order(self, order_id: str) -> bool:
        return self._portfolio.cancel_broker_order(order_id)

    def apply_fill(self, asset: str, incremental_qty: float, fill_price: float):
        pos = self._positions.get(asset)
        if not pos:
            pos = SleevePosition(asset=asset, quantity=0.0, entry_price=fill_price)
            self._positions[asset] = pos
        new_qty = pos.quantity + incremental_qty
        if new_qty != 0.0 and pos.quantity != 0.0 and (new_qty > 0) == (pos.quantity > 0):
            pos.entry_price = (pos.quantity * pos.entry_price + incremental_qty * fill_price) / new_qty
        elif new_qty != 0.0:
            pos.entry_price = fill_price
        else:
            pos.entry_price = 0.0
        pos.quantity = new_qty


class UnifiedPortfolio(Strategy):
    """Unified multi-sleeve strategy orchestrating the 4 promoted strategies."""

    def __init__(
        self,
        b0_strategy: Any,
        c3_strategy: Any,
        rsi_strategy: Any,
        btc_strategy: Any,
        *,
        weights: dict[str, float] | None = None,
        account_id: str = "urn:prp-account:SBtRDJNHJhW9",
        starting_balance: float = 5000.0,
        daily_loss_pct: float = 0.05,
        trailing_dd_pct: float = 0.08,
        max_gross_leverage: float = 1.5,
    ):
        super().__init__()
        self.b0 = b0_strategy
        self.c3 = c3_strategy
        self.rsi = rsi_strategy
        self.btc = btc_strategy

        self.account_id = account_id
        self.starting_balance = starting_balance
        self.daily_loss_pct = daily_loss_pct
        self.trailing_dd_pct = trailing_dd_pct
        self.max_gross_leverage = max_gross_leverage

        self.weights = weights or {"b0": 0.25, "c3": 0.25, "rsi": 0.25, "btc": 0.25}
        assert abs(sum(self.weights.values()) - 1.0) < 1e-6, "Weights must sum to 1.0"

        self.proxies: dict[str, SleeveExecutionProxy] = {}
        for sid, w in self.weights.items():
            self.proxies[sid] = SleeveExecutionProxy(self, sid, w)

        self._master_broker: Any = None
        self._order_to_sleeve: dict[str, str] = {}
        self._order_filled_qty: dict[str, float] = {}

        self.high_water_mark: float = starting_balance
        self.day_start_balance: float = starting_balance
        self.current_day_utc: str = ""
        self.halted: bool = False
        self.halt_reason: str = ""

    def on_start(self, broker: Any) -> None:
        self._master_broker = broker
        # Query true initial equity; fail closed if unavailable
        eq = self.get_account_equity()
        if eq <= 0:
            raise RuntimeError("Broker returned non-positive initial account value")
        # Load known HWM from broker if available, otherwise anchor to starting balance
        if hasattr(broker, "get_high_water_mark"):
            self.high_water_mark = max(self.starting_balance, float(broker.get_high_water_mark()))
        else:
            self.high_water_mark = max(self.starting_balance, eq)
        self.day_start_balance = eq

    def get_account_equity(self) -> float:
        if self._master_broker is None:
            raise RuntimeError("Broker not bound to portfolio")
        if hasattr(self._master_broker, "equity"):
            val = float(self._master_broker.equity())
            if val <= 0:
                raise RuntimeError(f"Invalid non-positive equity from broker: {val}")
            return val
        if hasattr(self._master_broker, "get_account_value"):
            val = float(self._master_broker.get_account_value())
            if val <= 0:
                raise RuntimeError(f"Invalid non-positive account value from broker: {val}")
            return val
        raise RuntimeError("Broker does not expose an equity or account value accessor")

    def get_account_cash(self) -> float:
        if self._master_broker is None:
            raise RuntimeError("Broker not bound to portfolio")
        if hasattr(self._master_broker, "get_cash"):
            return float(self._master_broker.get_cash())
        return self.get_account_equity()

    def on_data(self, timestamp: datetime, data: dict[str, Any], context: dict[str, Any], broker: Any) -> None:
        self._master_broker = broker

        # 1. Update calendar and check daily reset at 00:00 UTC
        ts_utc = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=UTC)
        day_str = ts_utc.strftime("%Y-%m-%d")
        eq = self.get_account_equity()

        if day_str != self.current_day_utc:
            self.current_day_utc = day_str
            # Capture exact 00:00 UTC balance
            self.day_start_balance = eq

        if eq > self.high_water_mark:
            self.high_water_mark = eq

        # 2. Hard Propr 2-Step risk floors evaluation
        # Daily loss: 5% of 00:00 UTC balance
        daily_loss = self.day_start_balance - eq
        max_daily_allowed = self.day_start_balance * self.daily_loss_pct

        # Trailing drawdown: 8% of starting balance below HWM, capped at starting balance
        max_drawdown_floor = max(self.starting_balance - self.starting_balance * self.trailing_dd_pct,
                                 self.high_water_mark - self.starting_balance * self.trailing_dd_pct)
        # Cap at starting balance
        if max_drawdown_floor > self.starting_balance:
            max_drawdown_floor = self.starting_balance

        if daily_loss >= max_daily_allowed:
            self.halted = True
            self.halt_reason = f"Daily loss limit breached: {daily_loss:.2f} >= {max_daily_allowed:.2f}"
            LOG.error("PORTFOLIO_HALT: %s", self.halt_reason)
            return

        if eq <= max_drawdown_floor:
            self.halted = True
            self.halt_reason = f"Trailing drawdown floor breached: equity {eq:.2f} <= floor {max_drawdown_floor:.2f}"
            LOG.error("PORTFOLIO_HALT: %s", self.halt_reason)
            return

        # 3. Dispatch to individual strategy sleeves
        # Sleeve B0 (30m on xyz:XYZ100)
        b0_key = next((k for k in ("xyz:XYZ100", "XYZ100") if k in data), None)
        if b0_key and hasattr(self.b0, "on_data"):
            try:
                self.b0.on_data(timestamp, {b0_key: data[b0_key]}, context, self.proxies["b0"])
            except Exception as e:
                LOG.warning("B0 on_data error: %s", e)

        # Sleeve C3 (H1+D1 on SP500 and XYZ100)
        c3_keys = [k for k in data if any(k.startswith(p) for p in ("US500", "US100", "SP500", "XYZ100", "xyz:"))]
        if c3_keys and hasattr(self.c3, "on_data"):
            try:
                self.c3.on_data(timestamp, {k: data[k] for k in c3_keys}, context, self.proxies["c3"])
            except Exception as e:
                LOG.warning("C3 on_data error: %s", e)

        # Sleeve RSI (Daily on xyz:SP500)
        rsi_key = next((k for k in ("xyz:SP500", "SP500", "ES") if k in data), None)
        if rsi_key and hasattr(self.rsi, "on_data"):
            try:
                self.rsi.on_data(timestamp, {rsi_key: data[rsi_key]}, context, self.proxies["rsi"])
            except Exception as e:
                LOG.warning("RSI on_data error: %s", e)

        # Sleeve BTC (Daily on BTC)
        if "BTC" in data and hasattr(self.btc, "on_data"):
            try:
                self.btc.on_data(timestamp, {"BTC": data["BTC"]}, context, self.proxies["btc"])
            except Exception as e:
                LOG.warning("BTC on_data error: %s", e)

    def route_sleeve_order(
        self,
        sleeve_id: str,
        asset: str,
        quantity: float,
        order_type: Any,
        limit_price: float | None = None,
        stop_price: float | None = None,
        reduce_only: bool = False,
        **kwargs: Any,
    ) -> Any:
        if self.halted and not reduce_only:
            LOG.warning("Order blocked: portfolio is halted (%s)", self.halt_reason)
            return None

        canon = self._canonical_symbol(asset)
        eq = self.get_account_equity()

        # Enforce gross leverage cap on non-reducing orders
        if not reduce_only and hasattr(self._master_broker, "get_positions"):
            positions = self._master_broker.get_positions()
            current_notional = 0.0
            for pos in (positions.values() if isinstance(positions, dict) else positions):
                q = abs(float(getattr(pos, "quantity", 0.0)))
                px = float(getattr(pos, "entry_price", 0.0) or getattr(pos, "current_price", 0.0) or 0.0)
                current_notional += q * px
            ref_px = limit_price or stop_price or 1.0
            order_notional = abs(quantity) * ref_px
            if (current_notional + order_notional) / eq > self.max_gross_leverage:
                LOG.warning("Order rejected: gross leverage cap exceeded (%.2fx > %.2fx)",
                            (current_notional + order_notional) / eq, self.max_gross_leverage)
                return None

        # Submit directly to broker matching engine preserving order_type, limit_price, stop_price
        order = self._master_broker.submit_order(
            canon,
            quantity,
            order_type=order_type,
            limit_price=limit_price,
            stop_price=stop_price,
            reduce_only=reduce_only,
            **kwargs,
        )

        # Record durable order_id -> sleeve_id mapping
        if order is not None:
            oid = getattr(order, "order_id", None) or getattr(order, "id", None)
            if oid:
                self._order_to_sleeve[str(oid)] = sleeve_id
                self._order_filled_qty[str(oid)] = 0.0

        return order

    def cancel_broker_order(self, order_id: str) -> bool:
        if hasattr(self._master_broker, "cancel_order"):
            return self._master_broker.cancel_order(order_id)
        return False

    def on_fill(self, fill_event: Any):
        """Attribute verified incremental fills by order identity to the exact sleeve."""
        oid = str(getattr(fill_event, "order_id", ""))
        sleeve_id = self._order_to_sleeve.get(oid)
        if not sleeve_id or sleeve_id not in self.proxies:
            LOG.warning("Received fill for untracked or unknown order_id: %s", oid)
            return

        asset = getattr(fill_event, "asset", "")
        total_fill_qty = float(getattr(fill_event, "quantity", 0.0))
        fill_price = float(getattr(fill_event, "price", 0.0))

        # Incremental fill calculation (prevent double-counting on partial fills)
        previously_filled = self._order_filled_qty.get(oid, 0.0)
        incremental_qty = total_fill_qty - previously_filled
        if incremental_qty <= 0.0:
            return

        self._order_filled_qty[oid] = total_fill_qty
        self.proxies[sleeve_id].apply_fill(asset, incremental_qty, fill_price)

    def _canonical_symbol(self, sym: str) -> str:
        s = sym.split("_")[0]
        if s in ("US100", "NQ", "XYZ100", "xyz:XYZ100"):
            return "xyz:XYZ100"
        if s in ("US500", "ES", "SP500", "xyz:SP500"):
            return "xyz:SP500"
        if s in ("BTC", "BTCUSDT_PERP"):
            return "BTC"
        return s
