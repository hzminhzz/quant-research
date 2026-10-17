"""Twenty-level anchored A versus dynamic-beta-hedged A4 backtest.

Uses installed ml4t.backtest.Engine with NEXT_BAR LIMIT fills.
SharedVolumeBudget is an execution-limit adapter: each bar/asset shares one
volume budget across all 20+ orders. Partial fills are tracked by order id.
OHLCV penetration is not a guarantee of historical maker execution.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import yaml
from ml4t.backtest import BacktestConfig, DataFeed, Engine, Strategy
from ml4t.backtest.config import CommissionType, ShareType, SlippageType
from ml4t.backtest.execution.limits import ExecutionLimits
from ml4t.backtest.execution.result import ExecutionResult
from ml4t.backtest.types import ExecutionMode, OrderStatus, OrderType

ROOT = Path(__file__).resolve().parents[1]
CFG_PATH = ROOT / "config/research_sessions/hyperliquid_xyz_20level_anchored_volume_ab_20261009.yaml"
OUT = ROOT / "run_log/hyperliquid_xyz_20level_anchored_volume_ab_20261009"
ASSETS = ("SP500", "XYZ100")


def utc(v: str) -> datetime:
    return datetime.fromisoformat(v).astimezone(UTC)


def passive_price(raw: float, side: int, tick: float) -> float:
    units = math.floor(raw / tick + 1e-10) if side > 0 else math.ceil(raw / tick - 1e-10)
    return round(units * tick, 8)


def quantize(value: float, step: float) -> float:
    return max(0.0, math.floor(value / step + 1e-10) * step)


class SharedVolumeBudget(ExecutionLimits):
    """Bar-volume limit shared by ALL orders for the same instrument.

    ExecutionLimits API lacks an asset parameter, so broker binding resolves
    asset using its current bar open and exact bar-volume pair. Ambiguous
    resolution *refuses fills*. This adapter is verified by specific tests
    and reports its ambiguity count; it is not a true queue-matching model.
    """

    def __init__(self, participation: float, partial: bool, lot_steps: dict[str, float] | None = None):
        self.participation = participation
        self.partial = partial
        self.lot_steps = lot_steps or {}
        self.broker = None
        self.last_bar = None
        self.used = defaultdict(float)
        self.limit = {}
        self.max_overshoot = 0.0
        self.ambiguous = 0
        self.consumed = defaultdict(float)

    def bind(self, broker) -> None:
        self.broker = broker

    def calculate(self, order_quantity: float, bar_volume: float | None, price: float) -> ExecutionResult:
        if self.broker is None:
            raise RuntimeError("bind SharedVolumeBudget to Engine.broker")
        bar = self.broker._bar_index
        if self.last_bar != bar:
            self.last_bar = bar
            self.used = defaultdict(float)
            self.limit = {
                asset: max(0.0, float(volume or 0.0)) * self.participation
                for asset, volume in self.broker._current_volumes.items()
            }

        candidates = [
            asset for asset, volume in self.broker._current_volumes.items()
            if bar_volume is not None and abs(float(volume) - float(bar_volume)) <= 1e-9
        ]
        if len(candidates) > 1:
            candidates = [
                asset for asset in candidates
                if asset in self.broker._current_opens
                and math.isclose(float(self.broker._current_opens[asset]), float(price), rel_tol=1e-8, abs_tol=1e-5)
            ]
        if len(candidates) != 1:
            self.ambiguous += 1
            return ExecutionResult(0.0, order_quantity, price)
        asset = candidates[0]
        remaining = max(0.0, self.limit[asset] - self.used[asset])
        size = min(max(0.0, order_quantity), remaining)
        if asset in self.lot_steps:
            size = quantize(size, self.lot_steps[asset])
        if not self.partial and size + 1e-10 < order_quantity:
            size = 0.0
        if size > 0:
            self.used[asset] += size
            self.consumed[(bar, asset)] += size
        self.max_overshoot = max(self.max_overshoot, self.used[asset] - self.limit[asset])
        return ExecutionResult(
            fillable_quantity=size,
            remaining_quantity=max(0.0, order_quantity - size),
            adjusted_price=price,
            participation_rate=size / bar_volume if bar_volume and size else 0.0,
        )


@dataclass
class Lot:
    level: int
    qty: float = 0.0
    cashflow: float = 0.0
    entry_volume: float = 0.0
    exit_volume: float = 0.0
    carry: float = 0.0
    first_bar: int | None = None


@dataclass
class Basket:
    name: str
    anchor: dict[str, float] = field(default_factory=dict)
    signed_qty: dict[str, float] = field(default_factory=lambda: {s: 0.0 for s in ASSETS})
    cashflow: float = 0.0
    carry: float = 0.0
    volume: float = 0.0
    completed_volume: float = 0.0
    completed_profit: float = 0.0
    completed: int = 0
    breakeven_failures: int = 0
    first_fill_bar: int | None = None
    latest_anchor: dict[str, float] = field(default_factory=dict)
    first_anchor: dict[str, float] = field(default_factory=dict)
    filled_levels: set[int] = field(default_factory=set)
    used_levels: set[int] = field(default_factory=set)
    lots: dict[int, Lot] = field(default_factory=dict)
    holding_bars: list[int] = field(default_factory=list)
    phase: str = "accumulate"
    orders: dict[str, str] = field(default_factory=dict)

    def flat(self) -> bool:
        return all(abs(v) < 1e-7 for v in self.signed_qty.values())

    def marked_pnl(self, marks) -> float:
        return self.cashflow + sum(self.signed_qty[s] * marks[s] for s in ASSETS) - self.carry


@dataclass
class OrderMeta:
    basket: str
    label: str
    role: str
    asset: str
    level: int
    side: int
    qty_requested: float
    limit_price: float
    created_bar: int


class FullLadder(Strategy):
    def __init__(self, arm: str, cfg: dict, beta_init: float, partial: bool, subbasket: bool, carry_bps: float):
        super().__init__()
        arm = {"independent": "A", "dynamic_hedge": "A4"}.get(arm, arm)
        if arm not in ("A", "A4") or (subbasket and arm != "A"):
            raise ValueError("Unsupported research arm")
        self.arm, self.cfg = arm, cfg
        self.cap, self.o, self.exe = cfg["capital"], cfg["order"], cfg["execution"]
        self.partial, self.subbasket, self.carry_bps = partial, subbasket, carry_bps
        self.beta = beta_init
        self.baskets = {
            "spy": Basket("spy"), "xyz": Basket("xyz")
        } if arm == "A" else {"pair": Basket("pair")}
        self.orders: dict[str, OrderMeta] = {}
        self.prev_fill = 0
        self.bar = 0
        self.prev_time: datetime | None = None
        self.halt = False
        self.halt_reason = None
        self.max_drawdown = 0.0
        self.high_water = float(self.cap["starting_cash_usdc"])
        self.max_gross = 0.0
        self.max_reserved = 0.0
        self.max_gross_plus_reserved = 0.0
        self.max_beta_residual = 0.0
        self.maker_volume = 0.0
        self.maker_events = 0
        self.partial_events = 0
        self.taker_volume = 0.0
        self.taker_cost = 0.0
        self.total_carry = 0.0
        self.entries = 0
        self.exits = 0
        self.hedge_fills = 0
        self.cancels = 0
        self.rejections = 0
        self.unknown_fills = 0
        self.quote_revisions = 0
        self.breakeven_failures = 0
        self.max_resting_entry_orders = 0
        self.hedge_remainder = 0.0
        self.first_halt_bar = None
        self.first_halt_utc = None
        self.gap_restarts = 0
        self.end_stop_unfilled = 0

    def _cancel(self, b: Basket, label: str, broker) -> None:
        oid = b.orders.pop(label, None)
        if oid is None:
            return
        order = broker.get_order(oid)
        if order is not None and order.status == OrderStatus.PENDING and broker.cancel_order(oid):
            self.cancels += 1
        self.orders.pop(oid, None)

    def _cancel_all(self, b, broker) -> None:
        for label in list(b.orders):
            self._cancel(b, label, broker)

    def _quote(self, b, label, role, asset, signed_qty, limit, level, broker, marks, allow_replace=True):
        tick = self.o.get("minimum_price_tick_by_asset", {}).get(asset, self.o["minimum_price_tick"])
        lot = self.o.get("quantity_rounding_by_asset", {}).get(asset, self.o["quantity_rounding"])
        side = 1 if signed_qty > 0 else -1
        price = passive_price(limit, side, tick)
        qty = quantize(abs(signed_qty), lot)
        if qty * price < self.o.get("minimum_order_notional_usdc", 5.0):
            return False
        # Never submit marketable limit orders. A crossed limit could behave as a taker.
        if (side > 0 and price >= marks[asset]) or (side < 0 and price <= marks[asset]):
            self._cancel(b, label, broker)
            return False
        oldid = b.orders.get(label)
        if oldid:
            old = broker.get_order(oldid)
            if old and old.status == OrderStatus.PENDING:
                # Entry levels never move while the anchored cycle remains open.
                if role == "entry" or not allow_replace:
                    return True
                # Exit price must never be retained on the wrong side of revised breakeven.
                worse = (side < 0 and old.limit_price + tick / 2 < price) or (
                    side > 0 and old.limit_price - tick / 2 > price
                )
                qty_change = abs(float(old.quantity) - qty) * price > 1
                if not worse and not qty_change:
                    return True
            self._cancel(b, label, broker)
            self.quote_revisions += 1

        if role in ("entry", "hedge") and not self._capacity(asset, qty * price, broker, marks):
            return False
        order = broker.submit_order(asset, qty if side > 0 else -qty, order_type=OrderType.LIMIT, limit_price=price)
        if order is None or order.status != OrderStatus.PENDING:
            self.rejections += 1
            return False
        b.orders[label] = order.order_id
        self.orders[order.order_id] = OrderMeta(b.name, label, role, asset, level, side, qty, price, self.bar)
        return True

    def _capacity(self, asset, amount, broker, marks):
        opened = {s: sum(abs(b.signed_qty[s] * marks[s]) for b in self.baskets.values()) for s in ASSETS}
        reserved = {s: 0.0 for s in ASSETS}
        for oid, meta in self.orders.items():
            if meta.role not in ("entry", "hedge"):
                continue
            order = broker.get_order(oid)
            if order and order.status == OrderStatus.PENDING:
                reserved[meta.asset] += float(order.quantity) * meta.limit_price
        return (
            opened[asset] + reserved[asset] + amount <= self.cap["max_per_leg_usdc"] + 1.0
            and sum(opened.values()) + sum(reserved.values()) + amount <= self.cap["max_gross_usdc"] + 1.0
        )

    def _reconcile(self, broker, marks):
        for f in broker.fills[self.prev_fill:]:
            ref = self.orders.get(f.order_id)
            if ref is None:
                self.unknown_fills += 1
                continue
            b = self.baskets[ref.basket]
            qty = float(f.quantity) * (1 if f.side.value == "buy" else -1)
            notional = abs(qty * float(f.price))
            b.signed_qty[f.asset] += qty
            b.cashflow -= qty * float(f.price)
            if abs(b.signed_qty[f.asset]) < 1e-7:
                b.signed_qty[f.asset] = 0.0
            if ref.role != "panic":
                b.volume += notional
                self.maker_volume += notional
                self.maker_events += 1
                if float(f.quantity) < ref.qty_requested - 1e-8:
                    self.partial_events += 1
                if b.first_fill_bar is None:
                    b.first_fill_bar = self.bar
                if ref.role == "entry":
                    self.entries += 1
                    b.used_levels.add(ref.level)
                    if self.subbasket:
                        lot = b.lots.setdefault(ref.level, Lot(level=ref.level))
                        lot.qty += qty
                        lot.cashflow -= qty * float(f.price)
                        lot.entry_volume += notional
                        if lot.first_bar is None:
                            lot.first_bar = self.bar
                elif ref.role == "hedge":
                    self.hedge_fills += 1
                else:
                    self.exits += 1
                    if self.subbasket:
                        lot = b.lots[ref.level]
                        lot.qty += qty
                        lot.cashflow -= qty * float(f.price)
                        lot.exit_volume += notional
            else:
                self.taker_volume += notional
                self.taker_cost += notional * self.exe["emergency_taker_cost_bps"] / 10000

            order = broker.get_order(f.order_id)
            if order and order.status != OrderStatus.PENDING:
                self.orders.pop(f.order_id, None)
                if b.orders.get(ref.label) == f.order_id:
                    b.orders.pop(ref.label, None)
                if ref.role == "entry":
                    b.filled_levels.add(ref.level)
            elif order and order.status == OrderStatus.PENDING:
                # Retain meta for subsequent fills of the same resting order.
                ref.qty_requested = max(0.0, ref.qty_requested - abs(float(f.quantity)))

        self.prev_fill = len(broker.fills)
        # Clear rejected orders. No counting submitted-but-rejected maker volume.
        for oid, ref in list(self.orders.items()):
            order = broker.get_order(oid)
            if order and order.status in (OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.FILLED):
                if order.status == OrderStatus.REJECTED:
                    self.rejections += 1
                self.orders.pop(oid, None)
                b = self.baskets[ref.basket]
                if b.orders.get(ref.label) == oid:
                    b.orders.pop(ref.label, None)

        for b in self.baskets.values():
            if self.subbasket:
                self._complete_lots(b, marks, broker)
            # Emergency market liquidations are NOT completed maker baskets.
            # Keep their losses and entry-only volume outside completion metrics.
            if not self.halt and b.first_fill_bar is not None and b.flat() and (
                b.phase == "exit" or (not self.subbasket and not any(m.basket == b.name and m.role == "entry" for m in self.orders.values()))
            ):
                self._finish(b, marks, broker)

    def _complete_lots(self, b, marks, broker):
        for level, lot in list(b.lots.items()):
            if abs(lot.qty) > 1e-7 or lot.exit_volume <= 0:
                continue
            net = lot.cashflow - lot.carry
            if net < -0.005:
                b.breakeven_failures += 1
                self.breakeven_failures += 1
            b.completed += 1
            b.completed_volume += lot.entry_volume + lot.exit_volume
            b.completed_profit += net
            b.holding_bars.append(self.bar - (lot.first_bar or self.bar))
            b.filled_levels.discard(level)
            b.used_levels.discard(level)
            self._cancel(b, f"exit:{level}", broker)
            b.lots.pop(level)

    def _finish(self, b, marks, broker):
        self._cancel_all(b, broker)
        if not self.subbasket:
            net = b.cashflow - b.carry
            if net < -0.005:
                b.breakeven_failures += 1
                self.breakeven_failures += 1
            b.completed += 1
            b.completed_volume += b.volume
            b.completed_profit += net
            b.holding_bars.append(self.bar - b.first_fill_bar)
        b.anchor = dict(marks)
        b.latest_anchor = dict(marks)
        b.signed_qty = {s: 0.0 for s in ASSETS}
        b.cashflow = 0.0
        b.carry = 0.0
        b.volume = 0.0
        b.first_fill_bar = None
        b.filled_levels.clear()
        b.used_levels.clear()
        b.lots.clear()
        b.phase = "accumulate"

    def _risk(self, broker, marks) -> bool:
        gross = sum(abs(b.signed_qty[s] * marks[s]) for b in self.baskets.values() for s in ASSETS)
        reserved = sum(
            abs(float(broker.get_order(oid).quantity) * ref.limit_price)
            for oid, ref in self.orders.items()
            if ref.role in ("entry", "hedge") and broker.get_order(oid) is not None
            and broker.get_order(oid).status == OrderStatus.PENDING
        )
        self.max_gross = max(self.max_gross, gross)
        self.max_reserved = max(self.max_reserved, reserved)
        self.max_gross_plus_reserved = max(self.max_gross_plus_reserved, gross + reserved)
        self.max_resting_entry_orders = max(
            self.max_resting_entry_orders,
            sum(ref.role == "entry" for ref in self.orders.values())
        )
        residual = (
            sum(b.signed_qty["SP500"] for b in self.baskets.values()) * marks["SP500"] * self.beta
            + sum(b.signed_qty["XYZ100"] for b in self.baskets.values()) * marks["XYZ100"]
        )
        self.max_beta_residual = max(self.max_beta_residual, abs(residual))
        equity = float(broker.get_account_value()) - self.total_carry - self.taker_cost
        self.high_water = max(self.high_water, equity)
        self.max_drawdown = max(self.max_drawdown, self.high_water - equity)
        if not self.halt and (
            equity <= self.cap["starting_cash_usdc"] - self.cap["peak_to_trough_stop_usdc"]
            or self.max_drawdown >= self.cap["peak_to_trough_stop_usdc"]
            or gross >= self.cap["max_marked_gross_usdc"]
            or equity <= 0
        ):
            self._stop(broker, "risk_loss_or_gross")
        return not self.halt

    def _stop(self, broker, reason):
        self.halt = True
        self.halt_reason = reason
        self.first_halt_bar = self.bar
        self.first_halt_utc = self.prev_time.isoformat() if self.prev_time is not None else None
        for b in self.baskets.values():
            self._cancel_all(b, broker)
        for s in ASSETS:
            qty = sum(b.signed_qty[s] for b in self.baskets.values())
            if abs(qty) < 1e-7:
                continue
            b = self.baskets["spy" if s == "SP500" else "xyz"] if self.arm == "A" else self.baskets["pair"]
            order = broker.submit_order(s, -qty, order_type=OrderType.MARKET)
            if order:
                label = f"panic:{s}"
                b.orders[label] = order.order_id
                self.orders[order.order_id] = OrderMeta(b.name, label, "panic", s, -1, -1 if qty > 0 else 1, abs(qty), 0, self.bar)
            else:
                self.end_stop_unfilled += 1

    def _anchors(self, marks):
        for b in self.baskets.values():
            if not b.anchor:
                b.anchor = dict(marks)
                b.first_anchor = dict(marks)
                b.latest_anchor = dict(marks)

    def _single_exit(self, b, asset, side, marks, broker):
        qty = b.signed_qty[asset]
        if abs(qty) < 1e-7:
            self._cancel(b, "exit", broker)
            return
        target = (b.carry + self.o["net_breakeven_reserve_usdc"] - b.cashflow) / qty
        anchor = b.anchor[asset]
        offset = self.o["maker_exit_offset_bps"] / 10000
        limit = max(target, anchor, marks[asset] * (1 + offset)) if side > 0 else min(
            target, anchor, marks[asset] * (1 - offset)
        )
        self._quote(b, "exit", "exit", asset, -qty, limit, -1, broker, marks)

    def _ladder(self, b, asset, side, broker, marks):
        for level in range(self.o["n_levels"]):
            name = f"entry:{level}"
            if level in b.filled_levels or name in b.orders:
                continue
            offset = (self.o["first_level_bps"] + self.o["step_bps"] * level) / 10000
            target = b.anchor[asset] * (1 - side * offset)
            amount = self.o["clip_usdc"]
            px = passive_price(target, side, self.o["minimum_price_tick"])
            self._quote(b, name, "entry", asset, side * amount / px, px, level, broker, marks)

    def _independent(self, marks, broker):
        for name, asset, side in (("spy", "SP500", 1), ("xyz", "XYZ100", -1)):
            b = self.baskets[name]
            if self.subbasket:
                for level, lot in list(b.lots.items()):
                    if abs(lot.qty) < 1e-7:
                        continue
                    if f"entry:{level}" in b.orders:
                        continue  # Wait for the full $100 clip before sub-basket exit.
                    target = (lot.carry + self.o["net_breakeven_reserve_usdc"] - lot.cashflow) / lot.qty
                    limit = (
                        max(target, marks[asset] * (1 + self.o["maker_exit_offset_bps"] / 10000))
                        if side > 0 else
                        min(target, marks[asset] * (1 - self.o["maker_exit_offset_bps"] / 10000))
                    )
                    self._quote(b, f"exit:{level}", "exit", asset, -lot.qty, limit, level, broker, marks)
                self._ladder(b, asset, side, broker, marks)
                continue
            if (
                b.phase == "accumulate"
                and not b.flat()
                and b.marked_pnl(marks) >= self.o["net_breakeven_reserve_usdc"]
                and ((side == 1 and marks[asset] >= b.anchor[asset])
                     or (side == -1 and marks[asset] <= b.anchor[asset]))
            ):
                b.phase = "exit"
                for label in list(b.orders):
                    if label.startswith("entry:"):
                        self._cancel(b, label, broker)
            if b.phase == "exit":
                self._single_exit(b, asset, side, marks, broker)
            else:
                self._ladder(b, asset, side, broker, marks)

    def _dynamic_beta(self, ctx):
        if self.bar % self.o["beta_update_minutes"] == 0:
            candidate = ctx.get("rolling_beta")
            if candidate is not None and np.isfinite(float(candidate)):
                clipped = min(self.o["hedge_beta_max"], max(self.o["hedge_beta_min"], float(candidate)))
                self.beta = (1 - self.o["beta_smoothing"]) * self.beta + self.o["beta_smoothing"] * clipped

    def _linked(self, marks, ctx, broker):
        b = self.baskets["pair"]
        self._dynamic_beta(ctx)
        qty_sp = b.signed_qty["SP500"]
        qty_xyz = b.signed_qty["XYZ100"]
        if b.phase == "accumulate" and qty_sp > 1e-7 and b.marked_pnl(marks) >= self.o["net_breakeven_reserve_usdc"] and marks["SP500"] >= b.anchor["SP500"]:
            b.phase = "exit"
            for label in list(b.orders):
                if label.startswith(("entry:", "hedge:")):
                    self._cancel(b, label, broker)
        if b.phase == "exit":
            for label in list(b.orders):
                if label.startswith(("entry:", "hedge:")):
                    self._cancel(b, label, broker)
            prices = {}
            offset = self.o["maker_exit_offset_bps"] / 10000
            for asset in ASSETS:
                qty = b.signed_qty[asset]
                if abs(qty) < 1e-7:
                    self._cancel(b, f"exit:{asset}", broker)
                    continue
                prices[asset] = marks[asset] * (1 + offset if qty > 0 else 1 - offset)
            expected = b.cashflow + sum(b.signed_qty[s] * px for s, px in prices.items()) - b.carry
            deficit = max(0.0, self.o["net_breakeven_reserve_usdc"] - expected)
            if deficit > 0 and "SP500" in prices and qty_sp > 0:
                prices["SP500"] += deficit / qty_sp
            elif deficit > 0 and "XYZ100" in prices and qty_xyz < 0:
                prices["XYZ100"] += deficit / qty_xyz  # negative signed quantity lowers cover price
            for asset, px in prices.items():
                self._quote(b, f"exit:{asset}", "exit", asset, -b.signed_qty[asset], px, -1, broker, marks)
            return

        self._ladder(b, "SP500", 1, broker, marks)
        if qty_sp <= 1e-7:
            for label in list(b.orders):
                if label.startswith("hedge:"):
                    self._cancel(b, label, broker)
            return
        desired = -self.beta * qty_sp * marks["SP500"]
        open_short = qty_xyz * marks["XYZ100"]
        delta = -(desired - open_short)  # dollars of additional short needed, positive
        pending = 0.0
        for label, oid in b.orders.items():
            if label.startswith("hedge:"):
                order = broker.get_order(oid)
                if order and order.status == OrderStatus.PENDING:
                    pending += float(order.quantity) * float(order.limit_price)
        deficit = delta - pending
        self.hedge_remainder = max(self.hedge_remainder, abs(deficit))
        size = self.o["hedge_activation_clip_usdc"]
        count = max(0, min(20, math.floor(deficit / size)))
        for i in range(count):
            name = f"hedge:{i}"
            if name in b.orders:
                continue
            raw = marks["XYZ100"] * (1 + (self.o["hedge_quote_offset_bps"] + 2 * i) / 10000)
            px = passive_price(raw, -1, self.o["minimum_price_tick"])
            self._quote(b, name, "hedge", "XYZ100", -size / px, px, -1, broker, marks)

    def on_data(self, timestamp, data, context, broker):
        self.bar += 1
        if not set(ASSETS).issubset(data):
            return
        marks = {s: float(data[s]["close"]) for s in ASSETS}
        self._reconcile(broker, marks)
        self._anchors(marks)

        if self.prev_time is not None:
            minutes = max(1.0, (timestamp - self.prev_time).total_seconds() / 60)
            if minutes > 1.0:
                self.gap_restarts += 1
            for b in self.baskets.values():
                gross = sum(abs(b.signed_qty[s]) * marks[s] for s in ASSETS)
                carry = gross * self.carry_bps * minutes / (10000 * 1440)
                b.carry += carry
                self.total_carry += carry
                if self.subbasket and gross:
                    for lot in b.lots.values():
                        lot.carry += carry * abs(lot.qty * marks["SP500" if b.name == "spy" else "XYZ100"]) / gross
        self.prev_time = timestamp

        if not self._risk(broker, marks):
            return
        if self.gap_restarts and context.get("after_gap"):
            # A fresh quote after missing candles is unsafe; cancel and wait.
            for b in self.baskets.values():
                self._cancel_all(b, broker)
            return

        if self.arm == "A":
            self._independent(marks, broker)
        else:
            self._linked(marks, context, broker)
        # Include the quotes placed on this very first bar in exposure metrics.
        active = [
            (meta, broker.get_order(oid)) for oid, meta in self.orders.items()
            if meta.role in ("entry", "hedge")
        ]
        reserved = sum(
            float(order.quantity) * meta.limit_price for meta, order in active
            if order is not None and order.status == OrderStatus.PENDING
        )
        opened = sum(abs(b.signed_qty[s] * marks[s]) for b in self.baskets.values() for s in ASSETS)
        self.max_reserved = max(self.max_reserved, reserved)
        self.max_gross_plus_reserved = max(self.max_gross_plus_reserved, opened + reserved)
        self.max_resting_entry_orders = max(
            self.max_resting_entry_orders,
            sum(meta.role == "entry" and order is not None and order.status == OrderStatus.PENDING
                for meta, order in active),
        )


def make_panel(cfg):
    root = Path(cfg["source"]["root"])
    def scan(sym):
        return pl.scan_parquet(str(root / f"symbol={sym}" / "**" / "data.parquet")).select(
            "timestamp",
            *[pl.col(name).alias(f"{name}_{sym.lower()}") for name in ("open", "high", "low", "close", "volume")],
        )
    a = scan("SP500").join(scan("XYZ100"), on="timestamp", how="inner").sort("timestamp").collect()
    if a.height != a["timestamp"].n_unique() or not a.height:
        raise ValueError("Missing timestamps or duplicates")
    gap = a["timestamp"].diff() > timedelta(minutes=1)
    return a.with_columns(gap.fill_null(False).alias("after_gap"))


def prepare_beta(panel, cfg):
    hours = panel.group_by_dynamic("timestamp", every="1h").agg(
        pl.col("close_sp500").last(), pl.col("close_xyz100").last()
    ).sort("timestamp").with_columns(
        pl.col("close_sp500").log().diff().alias("rs"),
        pl.col("close_xyz100").log().diff().alias("rq"),
    ).with_columns(
        (
            pl.rolling_cov("rs", "rq", window_size=336, min_samples=336)
            / pl.col("rq").rolling_var(window_size=336, min_samples=336)
        ).shift(1).alias("rolling_beta")
    )
    before = hours.filter(pl.col("timestamp") < utc(cfg["evaluation"]["calibration_end_utc"])).drop_nulls(["rs", "rq"])
    r1, r2 = before["rs"].to_numpy(), before["rq"].to_numpy()
    init = float(np.cov(r1, r2, ddof=1)[0, 1] / np.var(r2, ddof=1))
    if not 0.01 < init < 2:
        raise ValueError("Initial beta unstable")
    panel = panel.join_asof(hours.select("timestamp", "rolling_beta"), on="timestamp", strategy="backward")
    return panel.with_columns(
        pl.when(pl.col("rolling_beta").is_between(0.1, 1.5))
        .then(pl.col("rolling_beta"))
        .otherwise(init).alias("rolling_beta")
    ), init, len(before)


def feed(panel, cfg):
    tick = cfg["order"]["minimum_price_tick"] * cfg["order"]["limit_penetration_ticks"]
    pieces = []
    for sym in ASSETS:
        suf = sym.lower()
        pieces.append(panel.select(
            "timestamp",
            pl.lit(sym).alias("symbol"),
            pl.col("open_" + suf).alias("open"),
            (pl.col("high_" + suf) - tick).alias("high"),
            (pl.col("low_" + suf) + tick).alias("low"),
            pl.col("close_" + suf).alias("close"),
            pl.when(pl.col("after_gap")).then(0.0).otherwise(pl.col("volume_" + suf)).alias("volume"),
        ))
    return (
        pl.concat(pieces).sort("timestamp", "symbol"),
        panel.select("timestamp", "rolling_beta", "after_gap"),
    )


def trial(cfg, variant, prices, ctx, init_beta, *, carry_bps=0, strategy_class=FullLadder):
    spec = {t["id"]: t for t in cfg["trials"]}[variant]
    gate = SharedVolumeBudget(cfg["execution"]["volume_participation"], spec["partial_fills"], lot_steps=cfg["order"].get("quantity_rounding_by_asset"))
    strategy = strategy_class(spec["arm"], cfg, init_beta, spec["partial_fills"], spec["subbasket"], carry_bps)
    config = BacktestConfig(
        initial_cash=cfg["capital"]["starting_cash_usdc"],
        share_type=ShareType.FRACTIONAL,
        allow_short_selling=True,
        allow_leverage=True,
        execution_mode=ExecutionMode.NEXT_BAR,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=cfg["execution"]["commission_bps"] / 10000,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=0.0,
        partial_fills_allowed=spec["partial_fills"],
    )
    engine = Engine(DataFeed(prices_df=prices, context_df=ctx, entity_col="symbol", timestamp_col="timestamp"), strategy, config, execution_limits=gate)
    gate.bind(engine.broker)
    started = time.monotonic()
    engine.run()
    seconds = time.monotonic() - started
    completed = sum(b.completed_volume for b in strategy.baskets.values())
    groups = {}
    for key, b in strategy.baskets.items():
        groups[key] = {
            "cycles": b.completed,
            "completed_volume": round(b.completed_volume, 3),
            "completed_net": round(b.completed_profit, 4),
            "negative_completed_cycles": b.breakeven_failures,
            "first_anchor": b.first_anchor,
            "latest_anchor": b.latest_anchor,
            "open_signed_qty": {s: round(v, 7) for s, v in b.signed_qty.items()},
            "open_inventory_value": {s: round(b.signed_qty[s] * engine.broker.get_last_price(s), 2) for s in ASSETS},
            "open_cycle_mark_pnl": round(b.marked_pnl({s: float(engine.broker.get_last_price(s)) for s in ASSETS}), 4),
            "open_subbaskets": len(b.lots),
            "open_basket_age_minutes_approx": (strategy.bar - b.first_fill_bar) if b.first_fill_bar is not None and not b.flat() else None,
            "longest_completed_holding_minutes_approx": max(b.holding_bars) if b.holding_bars else None,
            "holding_minutes_median": statistics.median(b.holding_bars) if b.holding_bars else None,
            "holding_minutes_p95": round(float(np.percentile(b.holding_bars, 95)), 2) if b.holding_bars else None,
        }
    broker_vol = sum(abs(float(f.quantity * f.price)) for f in engine.broker.fills if f.order_type == "limit")
    if abs(broker_vol - strategy.maker_volume) > 1e-3:
        raise AssertionError(f"maker ledger mismatch {broker_vol} {strategy.maker_volume}")
    if strategy.unknown_fills or gate.max_overshoot > 1e-9:
        raise AssertionError(f"execution mismatch unknown={strategy.unknown_fills} overshoot={gate.max_overshoot}")
    return {
        "variant": variant, "elapsed_seconds": round(seconds, 2),
        "starting_margin_usdc": cfg["capital"]["starting_cash_usdc"],
        "leverage_assumed": cfg["capital"]["leverage"],
        "candidate_maker_volume": round(strategy.maker_volume, 3),
        "completed_volume": round(completed, 3),
        "volume_per_drawdown": round(completed / max(0.01, strategy.max_drawdown), 3),
        "maker_fill_events": strategy.maker_events, "partial_fill_events": strategy.partial_events,
        "entry_fill_events": strategy.entries, "exit_fill_events": strategy.exits,
        "hedge_fill_events": strategy.hedge_fills, "rejected_orders": strategy.rejections,
        "maximum_resting_entry_orders": strategy.max_resting_entry_orders,
        "maximum_reserved_entry_notional": round(strategy.max_reserved, 2),
        "maximum_reserved_plus_open_gross": round(strategy.max_gross_plus_reserved, 2),
        "maximum_open_gross": round(strategy.max_gross, 2),
        "maximum_beta_residual": round(strategy.max_beta_residual, 2),
        "largest_unhedged_target_deficit": round(strategy.hedge_remainder, 2),
        "max_drawdown_usdc": round(strategy.max_drawdown, 4),
        "taker_emergency_notional": round(strategy.taker_volume, 4),
        "taker_emergency_cost": round(strategy.taker_cost, 4),
        "assumed_carry_paid": round(strategy.total_carry, 5),
        "end_equity_ex_points": round(float(engine.equity_curve[-1][1]) - strategy.total_carry - strategy.taker_cost, 4),
        "net_pnl_ex_points": round(float(engine.equity_curve[-1][1]) - strategy.total_carry - strategy.taker_cost - cfg["capital"]["starting_cash_usdc"], 4),
        "risk_halt": strategy.halt, "risk_halt_reason": strategy.halt_reason,
        "risk_halt_bar": strategy.first_halt_bar,
        "risk_halt_utc": strategy.first_halt_utc,
        "max_orphan_short_minutes_approx": getattr(strategy, "max_orphan_short_minutes", None),
        "gap_restarts": strategy.gap_restarts,
        "uncertain_asset_fill_blocks": gate.ambiguous,
        "shared_bar_budget_max_overshoot": gate.max_overshoot,
        "cycles": groups,
        "fill_model_limitations": "Candle high/low does not establish price order, maker queue or fill eligibility; 10% combined base-volume budget is a research assumption",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, default=CFG_PATH)
    p.add_argument("--phase", choices=["smoke", "development", "later"], default="smoke")
    p.add_argument("--variants", nargs="+", default=None)
    p.add_argument("--carry-bps-per-day", type=float, default=0)
    p.add_argument("--clip-usdc", type=float, choices=[50.0, 100.0], default=None, help="Post-hoc $50 clip sensitivity only; default and frozen design stay $100")
    p.add_argument("--volume-participation", type=float, choices=[0.01, 0.10], default=None, help="Post-hoc shared candle volume cap stress; frozen default is 0.10")
    p.add_argument("--no-save", action="store_true")
    args = p.parse_args()
    cfg = yaml.safe_load(args.config.read_text())
    if cfg["order"]["n_levels"] < 20 or cfg["order"]["clip_usdc"] != 100 or cfg["capital"]["leverage"] != 10:
        raise ValueError("Mandatory 20x$100 orders, 10x leverage")
    if cfg["capital"]["starting_cash_usdc"] * cfg["capital"]["leverage"] != cfg["capital"]["max_gross_usdc"]:
        raise ValueError("$600x10 capital ceiling violated")
    if not 0 <= args.carry_bps_per_day <= 20:
        raise ValueError("Carry outside 0..20bps/day")
    if args.clip_usdc is not None:
        cfg["order"]["clip_usdc"] = args.clip_usdc
    if args.volume_participation is not None:
        cfg["execution"]["volume_participation"] = args.volume_participation
    panel, beta, hours = prepare_beta(make_panel(cfg), cfg)
    ev = cfg["evaluation"]
    start, end = (utc(ev["later_start_utc"]), utc(ev["later_end_utc"])) if args.phase == "later" else (
        utc(ev["development_start_utc"]), utc(ev["development_end_utc"])
    )
    if args.phase == "smoke":
        end = start + timedelta(days=3)
    panel = panel.filter((pl.col("timestamp") >= start) & (pl.col("timestamp") < end))
    prices, ctx = feed(panel, cfg)
    trials = [t["id"] for t in cfg["trials"]] if args.variants is None else args.variants
    declared = {t["id"] for t in cfg["trials"]}
    if not set(trials).issubset(declared):
        raise ValueError("Unknown trial")
    print(json.dumps({"phase": args.phase, "data_minute_rows_per_market": panel.height, "start": start.isoformat(), "end": end.isoformat(), "initial_return_beta": beta, "calibration_hourly_rows": hours, "trials": trials, "cost_bps_day": args.carry_bps_per_day}), flush=True)
    results = []
    for t in trials:
        row = trial(cfg, t, prices, ctx, beta, carry_bps=args.carry_bps_per_day)
        results.append(row)
        print(json.dumps({"trial": t, "secs": row["elapsed_seconds"], "fills": row["maker_fill_events"], "completed_volume": row["completed_volume"], "total_volume": row["candidate_maker_volume"], "drawdown": row["max_drawdown_usdc"], "pnl": row["net_pnl_ex_points"], "stop": row["risk_halt"], "max_resting": row["maximum_resting_entry_orders"]}), flush=True)
    if not args.no_save:
        OUT.mkdir(parents=True, exist_ok=True)
        tag = "all" if args.variants is None else "_".join(trials)
        suffix = "" if args.clip_usdc is None else f"_clip{args.clip_usdc:g}"
        if args.volume_participation is not None:
            suffix += f"_participation{args.volume_participation:g}"
        path = OUT / f"{args.phase}_{tag}_carry{args.carry_bps_per_day:g}{suffix}.json"
        path.write_text(json.dumps({"session": cfg["session_id"], "parameters": cfg, "phase": args.phase, "start": start.isoformat(), "end": end.isoformat(), "beta_calibration": beta, "results": results}, sort_keys=True, indent=2, default=str) + "\n")
        print("REPORT", path, flush=True)


if __name__ == "__main__":
    main()
