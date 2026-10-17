"""Compare anchored independent DCA cycles against linked SPY/QQQ hedge variants.

Runs the installed ml4t.backtest Engine and its native resting LIMIT order
execution. Estimates are NOT a validated maker fill model: historical bid/ask,
trade aggressor, queue position, funding, and Arcus reward eligibility absent.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
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

from scripts.run_lighter_spy_qqq_grid_comparison import estimate_beta, load_panel

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config/research_sessions/lighter_anchored_volume_ab_20261009.yaml"
ARTIFACTS = ROOT / "run_log/lighter_anchored_volume_ab_20261009"


def iso(s: str) -> datetime:
    return datetime.fromisoformat(s).astimezone(UTC)


def round_price(p: float, side: int, tick: float) -> float:
    # Passive limit buys round DOWN; passive sells round UP.
    return round((math.floor(p / tick + 1e-9) if side > 0 else math.ceil(p / tick - 1e-9)) * tick, 4)


def round_qty(q: float, lot: float) -> float:
    return math.floor(q / lot + 1e-9) * lot


@dataclass
class WholeClipVolumeGate(ExecutionLimits):
    """Conservative all-or-none candle participation constraint.

    Requires enough *total reported* traded volume in the bar to support
    a resting clip; cannot establish contra-side volume or queue priority.
    """

    max_fraction: float = 1.0

    def calculate(self, order_quantity, bar_volume, price):
        ok = bar_volume is not None and bar_volume > 0 and order_quantity <= bar_volume * self.max_fraction + 1e-12
        return ExecutionResult(
            fillable_quantity=order_quantity if ok else 0.0,
            remaining_quantity=0.0 if ok else order_quantity,
            adjusted_price=price,
            participation_rate=order_quantity / bar_volume if ok else 0.0,
        )


@dataclass
class Cycle:
    name: str
    anchor: dict[str, float] = field(default_factory=dict)
    qty: dict[str, float] = field(default_factory=lambda: {"SPY": 0.0, "QQQ": 0.0})
    cashflow: float = 0.0
    carry: float = 0.0
    level: int = 0
    entries: int = 0
    phase: str = "accumulate"
    first_fill_bar: int | None = None
    volume: float = 0.0
    cycles: int = 0
    clean_volume: float = 0.0
    completed_net: float = 0.0
    realized_cycle_nets: list[float] = field(default_factory=list)
    exit_breakeven_failures: int = 0
    holdings: list[int] = field(default_factory=list)
    first_anchor: dict[str, float] = field(default_factory=dict)
    last_anchor: dict[str, float] = field(default_factory=dict)
    quote_ids: dict[str, str] = field(default_factory=dict)
    last_quote_bar: dict[str, int] = field(default_factory=dict)

    def is_flat(self) -> bool:
        return all(abs(v) < 1e-8 for v in self.qty.values())

    def value_if_flat(self, marks: dict[str, float]) -> float:
        return self.cashflow + sum(self.qty[s] * marks[s] for s in self.qty) - self.carry


class AnchoredVolumeStrategy(Strategy):
    def __init__(self, variant: str, conf: dict, base_beta: float, max_participation: float, carry_bps: float):
        super().__init__()
        self.variant = variant
        self.conf = conf
        self.base_beta = base_beta
        self.beta = base_beta
        self.participation = max_participation
        self.carry_bps = carry_bps
        self.groups = (
            {"spy": Cycle("spy"), "qqq": Cycle("qqq")}
            if variant == "A"
            else {"linked": Cycle("linked")}
        )
        self.risk = conf["risk"]
        self.params = conf["orders"]
        self.last_fill_idx = 0
        self.bar = 0
        self.pending_meta: dict[str, tuple[str, str, str, int]] = {}
        self.halted = False
        self.kill_reason: str | None = None
        self.market_orders = 0
        self.maker_volume = 0.0
        self.taker_volume = 0.0
        self.taker_cost = 0.0
        self.carry_total = 0.0
        self.min_equity = float(self.risk["starting_usdc"])
        self.highwater = self.min_equity
        self.max_dd = 0.0
        self.max_gross = 0.0
        self.max_beta_residual = 0.0
        self.max_unhedged_usd = 0.0
        self.rejects = 0
        self.quote_submissions = 0
        self.quote_cancels = 0
        self.unattributed_fills = 0
        self.entry_fills = 0
        self.exit_fills = 0
        self.hedge_fills = 0
        self.crossed_after_quote = 0
        self.halt_at_bar: int | None = None
        self.risk_refill_attempts = 0

    def _group_for(self, asset: str) -> Cycle:
        return self.groups[asset.lower() if self.variant == "A" else "linked"]

    def _cancel(self, group: Cycle, logical: str, broker) -> None:
        oid = group.quote_ids.pop(logical, None)
        if oid is not None:
            if broker.cancel_order(oid):
                self.quote_cancels += 1
            self.pending_meta.pop(oid, None)
            self._order_cache.pop(oid, None)
        group.last_quote_bar.pop(logical, None)

    def _cancel_group(self, group: Cycle, broker) -> None:
        for name in list(group.quote_ids):
            self._cancel(group, name, broker)

    def _reconcile(self, broker, marks: dict[str, float]) -> None:
        fills = broker.fills[self.last_fill_idx:]
        self.last_fill_idx = len(broker.fills)
        # Track fills through native broker, never infer them from price alone.
        for f in fills:
            meta = self.pending_meta.pop(f.order_id, None)
            if meta is None:
                self.unattributed_fills += 1
                continue
            groupname, logical, kind, level = meta
            group = self.groups[groupname]
            if group.quote_ids.get(logical) == f.order_id:
                group.quote_ids.pop(logical, None)
                group.last_quote_bar.pop(logical, None)
            signed_q = float(f.quantity) * (1 if f.side.value.lower() == "buy" else -1)
            if kind != "panic":
                group.qty[f.asset] += signed_q
                if abs(group.qty[f.asset]) < 1e-8:
                    group.qty[f.asset] = 0.0
                group.cashflow -= signed_q * float(f.price)
                fill_notional = abs(signed_q * float(f.price))
                group.volume += fill_notional
                self.maker_volume += fill_notional
                if group.first_fill_bar is None:
                    group.first_fill_bar = self.bar
                if kind == "entry":
                    group.entries += 1
                    group.level = max(group.level, level + 1)
                    self.entry_fills += 1
                elif kind == "hedge":
                    self.hedge_fills += 1
                else:
                    self.exit_fills += 1
            else:
                group.qty[f.asset] += signed_q
                if abs(group.qty[f.asset]) < 1e-8:
                    group.qty[f.asset] = 0.0
                group.cashflow -= signed_q * float(f.price)
                self.taker_volume += abs(signed_q * float(f.price))
                rate = (
                    self.conf["assumptions"]["emergency_taker_fee_bps"]
                    + self.conf["assumptions"]["emergency_taker_slippage_bps"]
                ) / 10000
                self.taker_cost += abs(signed_q * float(f.price)) * rate

        # Rejected/cancelled orders do not count as filled volume.
        for oid, (groupname, logical, _kind, _level) in list(self.pending_meta.items()):
            order = broker.get_order(oid)
            if order and order.status in (OrderStatus.REJECTED, OrderStatus.CANCELLED):
                self.pending_meta.pop(oid, None)
                g = self.groups[groupname]
                if g.quote_ids.get(logical) == oid:
                    g.quote_ids.pop(logical, None)
                    g.last_quote_bar.pop(logical, None)
                if order.status is OrderStatus.REJECTED:
                    self.rejects += 1

        for group in self.groups.values():
            if group.entries and group.is_flat() and not self.halted:
                net = group.cashflow - group.carry
                group.cycles += 1
                group.completed_net += net
                group.realized_cycle_nets.append(net)
                group.clean_volume += group.volume
                if net < -0.005:
                    group.exit_breakeven_failures += 1
                group.holdings.append(self.bar - (group.first_fill_bar or self.bar))
                self._cancel_group(group, broker)
                group.anchor = dict(marks)
                group.last_anchor = dict(marks)
                group.cashflow = 0.0
                group.carry = 0.0
                group.level = 0
                group.entries = 0
                group.volume = 0.0
                group.phase = "accumulate"
                group.first_fill_bar = None

    def _max_cost(self, current: dict[str, float], include_pending: bool) -> tuple[float, dict[str, float]]:
        holdings = {"SPY": 0.0, "QQQ": 0.0}
        for group in self.groups.values():
            for sym in holdings:
                holdings[sym] += abs(group.qty[sym] * current[sym])
        if include_pending:
            for group in self.groups.values():
                for oid in group.quote_ids.values():
                    meta = self.pending_meta.get(oid)
                    if not meta or meta[2] not in ("entry", "hedge"):
                        continue
                    order = self._order_cache.get(oid)
                    if order is not None:
                        holdings[order.asset] += abs(order.quantity * order.limit_price)
        return sum(holdings.values()), holdings

    def _reserve_ok(self, symbol: str, new_notional: float, marks: dict[str, float]) -> bool:
        gross, holds = self._max_cost(marks, include_pending=True)
        own_cap = self.risk["max_spy_inventory_usdc"] if symbol == "SPY" else self.risk["max_qqq_inventory_usdc"]
        return gross + new_notional <= self.risk["max_gross_usdc"] + 1e-6 and holds[symbol] + new_notional <= own_cap + 1e-6

    def _quote(
        self,
        group: Cycle,
        logical: str,
        kind: str,
        asset: str,
        signed_qty: float,
        desired_price: float,
        level: int,
        marks: dict[str, float],
        broker,
        force_after: int | None = None,
    ) -> bool:
        if self.halted:
            return False
        tick = float(self.params["precision_price"])
        lot = float(self.params["precision_qty"])
        side = 1 if signed_qty > 0 else -1
        price = round_price(desired_price, side, tick)
        qty = round_qty(abs(signed_qty), lot)
        if qty * price < float(self.params["min_hedge_notional_usdc"]) or qty <= 0:
            self._cancel(group, logical, broker)
            return False
        if (side > 0 and price >= marks[asset] - tick * 0.5) or (side < 0 and price <= marks[asset] + tick * 0.5):
            self._cancel(group, logical, broker)
            self.crossed_after_quote += 1
            return False
        # A resting order must have been submitted before the next price bar.
        oldid = group.quote_ids.get(logical)
        if oldid:
            old = broker.get_order(oldid)
            if old and old.status is OrderStatus.PENDING:
                changed = abs(old.limit_price - price) / price * 10000 >= 5.0 or abs(old.quantity - qty) * price >= 10.0
                if kind == "exit":
                    # Never retain a worse exit quote than the newly calculated
                    # cycle-breakeven floor, even when the delta is under 5 bps.
                    changed = (
                        (side < 0 and old.limit_price < price - tick / 2)
                        or (side > 0 and old.limit_price > price + tick / 2)
                        or abs(old.quantity - qty) > lot / 2
                    )
                timed = force_after is not None and self.bar - group.last_quote_bar.get(logical, self.bar) >= force_after
                if not changed and not timed:
                    return True
            self._cancel(group, logical, broker)
        if kind in ("entry", "hedge") and not self._reserve_ok(asset, qty * price, marks):
            return False
        signed_q = qty if side > 0 else -qty
        order = broker.submit_order(asset, signed_q, order_type=OrderType.LIMIT, limit_price=price)
        if order is None or order.status is OrderStatus.REJECTED:
            self.rejects += 1
            return False
        group.quote_ids[logical] = order.order_id
        group.last_quote_bar[logical] = self.bar
        self.pending_meta[order.order_id] = (group.name, logical, kind, level)
        self._order_cache[order.order_id] = order
        self.quote_submissions += 1
        return True

    def _quote_by_notional(
        self, group: Cycle, logical: str, kind: str, asset: str, signed_dollars: float,
        limit: float, level: int, marks: dict[str, float], broker, force_after=None
    ) -> bool:
        return self._quote(
            group, logical, kind, asset, signed_dollars / limit, limit,
            level, marks, broker, force_after=force_after
        )

    def _single_exit_price(self, group: Cycle, sym: str, marks: dict[str, float]) -> float:
        qty = group.qty[sym]
        target = (group.carry + self.params["exit_cash_reserve_usdc"] - group.cashflow) / qty
        anchor = group.anchor[sym]
        offset = float(self.params["maker_exit_offset_bps"]) / 10000
        if qty > 0:
            return max(target, anchor, marks[sym] * (1 + offset))
        return min(target, anchor, marks[sym] * (1 - offset))

    def _manage_single(self, group: Cycle, sym: str, marks: dict[str, float], broker) -> None:
        side = 1 if sym == "SPY" else -1
        qty = group.qty[sym]
        if qty != 0:
            limit = self._single_exit_price(group, sym, marks)
            self._quote(group, "exit", "exit", sym, -qty, limit, 0, marks, broker)
        else:
            self._cancel(group, "exit", broker)
        if group.level >= int(self.risk["maximum_levels"]):
            self._cancel(group, "entry", broker)
            return
        if qty and "exit" in group.quote_ids:
            price = broker.get_order(group.quote_ids["exit"]).limit_price
            proximity = abs(marks[sym] / price - 1) * 10000
            favorable = (side > 0 and marks[sym] >= price * 0.998) or (side < 0 and marks[sym] <= price * 1.002)
            if favorable and proximity <= self.params["force_cancel_if_exit_near_bps"]:
                self._cancel(group, "entry", broker)
                return
        step = float(self.params["grid_spacing_bps"]) / 10000
        anchor = group.anchor[sym]
        offset = (self.params["first_entry_bps"] / 10000) if group.level == 0 else step * group.level
        target = anchor * (1 - side * offset)
        notional = self.params["spy_clip_usdc"] if sym == "SPY" else self.params["qqq_clip_usdc"]
        self._quote_by_notional(group, "entry", "entry", sym, side * notional, target, group.level, marks, broker)

    def _current_beta(self, context) -> float:
        if self.variant != "A4":
            return self.base_beta
        x = context.get("rolling_beta")
        if x is None or not math.isfinite(float(x)):
            return self.base_beta
        # Smooth rapidly moving statistical estimates rather than churning a hedge.
        if self.bar % 60 == 0:
            self.beta = max(0.1, min(1.5, 0.9 * self.beta + 0.1 * float(x)))
        return self.beta

    def _manage_linked(self, group: Cycle, marks: dict[str, float], context: dict, broker) -> None:
        qty_spy = group.qty["SPY"]
        qty_qqq = group.qty["QQQ"]
        offset = float(self.params["maker_exit_offset_bps"]) / 10000
        budget = self.params["exit_cash_reserve_usdc"]
        if group.phase == "accumulate" and qty_spy > 0:
            # Require SPY's starting reference to be recovered, and the
            # *combined* position to cover all recorded cycle carry.
            projected = group.value_if_flat(marks)
            if marks["SPY"] >= group.anchor["SPY"] and projected >= budget:
                group.phase = "exit"
                self._cancel(group, "entry", broker)
                self._cancel(group, "hedge", broker)

        if group.phase == "exit":
            self._cancel(group, "entry", broker)
            self._cancel(group, "hedge", broker)
            candidates: dict[str, float] = {}
            for sym in ("SPY", "QQQ"):
                qty = group.qty[sym]
                if abs(qty) <= 1e-8:
                    self._cancel(group, "exit_" + sym, broker)
                    continue
                candidates[sym] = marks[sym] * (1 + offset if qty > 0 else 1 - offset)
            # Lock in *aggregate* net breakeven if BOTH maker limits execute,
            # even after one leg has already closed at a different price.
            expected = group.cashflow - group.carry + sum(group.qty[sym] * p for sym, p in candidates.items())
            deficit = budget - expected
            if deficit > 0:
                if group.qty["SPY"] > 0:
                    candidates["SPY"] += deficit / group.qty["SPY"]
                elif group.qty["QQQ"] < 0:
                    candidates["QQQ"] -= deficit / abs(group.qty["QQQ"])
            for sym, limit in candidates.items():
                self._quote(group, "exit_" + sym, "exit", sym, -group.qty[sym], limit, 0, marks, broker)
            return

        self._cancel(group, "exit_SPY", broker)
        self._cancel(group, "exit_QQQ", broker)

        if self.variant != "A0" and qty_spy > 0:
            ratio = {"A1": 0.5, "A2": 0.75, "A3": 1.0, "A4": 1.0}[self.variant]
            target_q_notional = -ratio * self.beta * qty_spy * marks["SPY"]
            delta = target_q_notional - qty_qqq * marks["QQQ"]
            if abs(delta) >= self.params["min_hedge_notional_usdc"]:
                px = marks["QQQ"] * (
                    1 + self.params["hedge_quote_offset_bps"] / 10000 if delta < 0
                    else 1 - self.params["hedge_quote_offset_bps"] / 10000
                )
                self._quote_by_notional(
                    group, "hedge", "hedge", "QQQ", delta, px, 0,
                    marks, broker, force_after=self.params["hedge_quote_refresh_minutes"]
                )
            else:
                self._cancel(group, "hedge", broker)
        else:
            self._cancel(group, "hedge", broker)

        deficit = 0.0
        if self.variant != "A0" and qty_spy > 0:
            ratio = {"A1": 0.5, "A2": 0.75, "A3": 1, "A4": 1}[self.variant]
            deficit = abs(ratio * self.beta * qty_spy * marks["SPY"] + qty_qqq * marks["QQQ"])
        self.max_unhedged_usd = max(self.max_unhedged_usd, deficit)
        if deficit > self.params["max_hedge_shortfall_usdc"]:
            self._cancel(group, "entry", broker)
            return
        if group.level >= int(self.risk["maximum_levels"]):
            self._cancel(group, "entry", broker)
            return
        if qty_spy and marks["SPY"] >= group.anchor["SPY"] * 0.999:
            self._cancel(group, "entry", broker)
            return
        step = self.params["grid_spacing_bps"] / 10000
        distance = self.params["first_entry_bps"] / 10000 if group.level == 0 else step * group.level
        limit = group.anchor["SPY"] * (1 - distance)
        self._quote_by_notional(group, "entry", "entry", "SPY", self.params["spy_clip_usdc"], limit, group.level, marks, broker)

    def _panic(self, marks: dict[str, float], broker, reason: str) -> None:
        self.halted = True
        self.kill_reason = reason
        self.halt_at_bar = self.bar
        for group in self.groups.values():
            self._cancel_group(group, broker)
        for asset in ("SPY", "QQQ"):
            qty = sum(g.qty[asset] for g in self.groups.values())
            if abs(qty) > 1e-8:
                # Market taker emergency; only exception to post-only maker limits.
                g = self._group_for(asset)
                order = broker.submit_order(asset, -qty, order_type=OrderType.MARKET)
                if order is None:
                    self.risk_refill_attempts += 1
                else:
                    logical = "panic_" + asset
                    g.quote_ids[logical] = order.order_id
                    self.pending_meta[order.order_id] = (g.name, logical, "panic", 0)
                    self.market_orders += 1

    def on_data(self, timestamp, data, context, broker) -> None:
        self.bar += 1
        if not {"SPY", "QQQ"}.issubset(data):
            return
        marks = {s: float(data[s]["close"]) for s in ("SPY", "QQQ")}
        self._order_cache = {o.order_id: o for o in broker.get_pending_orders()}
        self._reconcile(broker, marks)
        for g in self.groups.values():
            if not g.anchor:
                g.anchor = dict(marks)
                g.first_anchor = dict(marks)
                g.last_anchor = dict(marks)
            if not g.is_flat():
                charge = sum(abs(g.qty[s]) * marks[s] for s in ("SPY", "QQQ")) * self.carry_bps / (10000 * 1440)
                g.carry += charge
                self.carry_total += charge
        gross, _ = self._max_cost(marks, include_pending=False)
        self.max_gross = max(self.max_gross, gross)
        self.max_beta_residual = max(
            self.max_beta_residual,
            abs(self.base_beta * sum(g.qty["SPY"] for g in self.groups.values()) * marks["SPY"] + sum(g.qty["QQQ"] for g in self.groups.values()) * marks["QQQ"]),
        )
        equity = float(broker.get_account_value()) - self.carry_total - self.taker_cost
        self.min_equity = min(self.min_equity, equity)
        self.highwater = max(self.highwater, equity)
        self.max_dd = max(self.max_dd, self.highwater - equity)
        if not self.halted and (
            equity < float(self.risk["starting_usdc"]) - self.risk["stop_drawdown_usdc"]
            or self.max_dd >= self.risk["stop_drawdown_usdc"]
            or gross >= self.risk["mark_gross_emergency_usdc"]
        ):
            self._panic(marks, broker, "drawdown_or_gross_limit")
        if self.halted:
            return
        if self.variant == "A":
            self._manage_single(self.groups["spy"], "SPY", marks, broker)
            self._order_cache = {o.order_id: o for o in broker.get_pending_orders()}
            self._manage_single(self.groups["qqq"], "QQQ", marks, broker)
        else:
            self._current_beta(context)
            self._manage_linked(self.groups["linked"], marks, context, broker)


def add_dynamic_beta(panel: pl.DataFrame, calibration_beta: float) -> pl.DataFrame:
    h = (
        panel.group_by_dynamic("timestamp", every="1h")
        .agg(pl.col("close_spy").last(), pl.col("close_qqq").last())
        .sort("timestamp")
        .with_columns(
            pl.col("close_spy").log().diff().alias("rs"),
            pl.col("close_qqq").log().diff().alias("rq"),
        )
        .with_columns(
            (pl.rolling_cov("rs", "rq", window_size=336, min_samples=336) /
             pl.col("rq").rolling_var(window_size=336, min_samples=336))
            .shift(1).alias("rolling_beta")
        )
        .select("timestamp", "rolling_beta")
    )
    return panel.join_asof(h, on="timestamp", strategy="backward").with_columns(
        pl.when(pl.col("rolling_beta").is_between(0.1, 1.5))
        .then(pl.col("rolling_beta"))
        .otherwise(calibration_beta)
        .alias("rolling_beta")
    )


def price_feed(panel: pl.DataFrame, penetration_ticks: float):
    tick = 0.01 * penetration_ticks
    pieces = []
    for sym in ("SPY", "QQQ"):
        lower = sym.lower()
        # An order has to be passed by a full tick to count as a touch.
        # NEXT_BAR ensures it already rested before the qualifying 1m range.
        pieces.append(
            panel.select(
                "timestamp",
                pl.lit(sym).alias("symbol"),
                pl.col(f"open_{lower}").alias("open"),
                (pl.col(f"high_{lower}") - tick).alias("high"),
                (pl.col(f"low_{lower}") + tick).alias("low"),
                pl.col(f"close_{lower}").alias("close"),
                pl.col(f"volume_{lower}").alias("volume"),
            )
        )
    return (
        pl.concat(pieces).sort("timestamp", "symbol"),
        panel.select("timestamp", "rolling_beta"),
    )


def report_one(name: str, prices, context, conf: dict, beta: float, max_part: float, carry_bps: float):
    risk = conf["risk"]
    config = BacktestConfig(
        initial_cash=risk["starting_usdc"],
        share_type=ShareType.FRACTIONAL,
        allow_short_selling=True,
        allow_leverage=True,
        execution_mode=ExecutionMode.NEXT_BAR,
        commission_type=CommissionType.PERCENTAGE,
        commission_rate=0.0,
        slippage_type=SlippageType.PERCENTAGE,
        slippage_rate=0.0,
        partial_fills_allowed=False,
    )
    strategy = AnchoredVolumeStrategy(name, conf, beta, max_part, carry_bps)
    feed = DataFeed(prices_df=prices, context_df=context, entity_col="symbol", timestamp_col="timestamp")
    engine = Engine(feed, strategy, config, execution_limits=WholeClipVolumeGate(max_fraction=max_part))
    result = engine.run()
    equity = float(engine.equity_curve[-1][1]) - strategy.carry_total - strategy.taker_cost
    groups = {}
    for key, group in strategy.groups.items():
        groups[key] = {
            "completed_cycles": group.cycles,
            "completed_cycle_volume_usdc": round(group.clean_volume, 4),
            "completed_cycle_pnl_usdc": round(group.completed_net, 4),
            "completed_negative_cycles": group.exit_breakeven_failures,
            "min_completed_cycle_pnl_usdc": round(min(group.realized_cycle_nets), 6) if group.realized_cycle_nets else None,
            "negative_cycle_pnl_usdc": [round(p, 6) for p in group.realized_cycle_nets if p < -0.005],
            "open_inventory": {s: round(q, 7) for s, q in group.qty.items() if abs(q) > 1e-8},
            "open_cycle_volume_usdc": round(group.volume, 4),
            "open_cycle_cashflow_usdc": round(group.cashflow, 4),
            "accrued_open_cycle_carry_usdc": round(group.carry, 4),
            "cycle_anchor_first": group.first_anchor,
            "cycle_anchor_latest": group.last_anchor,
            "median_holding_min": statistics.median(group.holdings) if group.holdings else None,
            "p95_holding_min": round(float(np.percentile(group.holdings, 95)), 1) if group.holdings else None,
        }
    completed = sum(g.clean_volume for g in strategy.groups.values())
    max_dd = max(strategy.max_dd, 1e-9)
    return {
        "variant": name,
        "estimated_maker_notional_usdc": round(strategy.maker_volume, 4),
        "completed_cycle_maker_notional_usdc": round(completed, 4),
        "completed_volume_per_drawdown_usdc": round(completed / max_dd, 3),
        "net_pnl_ex_points_usdc": round(equity - risk["starting_usdc"], 4),
        "ending_equity_usdc": round(equity, 4),
        "max_drawdown_usdc": round(strategy.max_dd, 4),
        "max_gross_usdc": round(strategy.max_gross, 4),
        "max_beta_residual_usdc": round(strategy.max_beta_residual, 4),
        "max_hedge_shortfall_usdc": round(strategy.max_unhedged_usd, 4),
        "total_assumed_carry_usdc": round(strategy.carry_total, 5),
        "emergency_taker_notional_usdc": round(strategy.taker_volume, 4),
        "emergency_taker_cost_usdc": round(strategy.taker_cost, 5),
        "simulated_maker_fills": strategy.entry_fills + strategy.exit_fills + strategy.hedge_fills,
        "entry_fills": strategy.entry_fills,
        "exit_fills": strategy.exit_fills,
        "hedge_fills": strategy.hedge_fills,
        "limit_quotes_submitted": strategy.quote_submissions,
        "limit_quotes_cancelled": strategy.quote_cancels,
        "halted": strategy.halted,
        "kill_reason": strategy.kill_reason,
        "first_halt_bar": strategy.halt_at_bar,
        "rejected_orders": strategy.rejects,
        "unattributed_fills": strategy.unattributed_fills,
        "broker_end_positions": {s: round(broker_position.quantity, 7) for s, broker_position in engine.broker.positions.items()},
        "group_results": groups,
        "ml4t_engine_sharpe": result.metrics.get("sharpe"),
        "warning": "Estimated candidate maker fills only. OHLCV does not establish maker queue/fill probability.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--phase", choices=["smoke", "development", "oos"], default="smoke")
    parser.add_argument("--variants", nargs="+", choices=["A", "A0", "A1", "A2", "A3", "A4"], default=["A", "A0", "A1", "A2", "A3", "A4"])
    parser.add_argument("--max-participation", type=float, default=1.0, help="Max fraction of reported minute volume available to one clip")
    parser.add_argument("--carry-bps-per-day", type=float, default=0.0, help="Assumed gross-notional carry cost daily, not verified funding")
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()
    if not 0 < args.max_participation <= 1 or not 0 <= args.carry_bps_per_day <= 50:
        raise ValueError("unsupported participation/carry assumptions")
    conf = yaml.safe_load(args.config.read_text())
    panel = load_panel({"source": {"data_root": conf["source"]["root"]}})
    ev = conf["evaluation"]
    base_beta, corr, calibration_hours = estimate_beta(panel, iso(ev["calibration_end_exclusive"]))
    panel = add_dynamic_beta(panel, base_beta)
    start = iso(ev["development_start"] if args.phase != "oos" else ev["oos_start"])
    end = iso(ev["development_end_exclusive"] if args.phase != "oos" else ev["oos_end_exclusive"])
    if args.phase == "smoke":
        end = min(end, start + timedelta(days=4))
    panel = panel.filter((pl.col("timestamp") >= start) & (pl.col("timestamp") < end))
    prices, context = price_feed(panel, conf["orders"]["penetration_ticks"])
    print(json.dumps({"event": "start", "phase": args.phase, "minute_bars": panel.height, "calibration_beta": base_beta, "calibration_corr": corr, "calibration_hours": calibration_hours, "participation": args.max_participation, "carry_bps_day": args.carry_bps_per_day}), flush=True)
    results = []
    for name in args.variants:
        row = report_one(name, prices, context, conf, base_beta, args.max_participation, args.carry_bps_per_day)
        print(json.dumps({"event": "variant", "name": name, "maker_volume": row["estimated_maker_notional_usdc"], "completed_volume": row["completed_cycle_maker_notional_usdc"], "max_dd": row["max_drawdown_usdc"], "pnl": row["net_pnl_ex_points_usdc"], "cycles": sum(g["completed_cycles"] for g in row["group_results"].values()), "halted": row["halted"], "errors": row["unattributed_fills"]}), flush=True)
        results.append(row)
    record = {
        "session_id": conf["session_id"], "status": conf["status"],
        "phase": args.phase, "start": start.isoformat(), "end": end.isoformat(),
        "bar_count_per_market": panel.height, "calibration_beta": base_beta,
        "calibration_correlation": corr, "max_participation": args.max_participation,
        "assumed_gross_carry_bps_per_day": args.carry_bps_per_day,
        "data_limitations": conf["assumptions"], "results": results,
    }
    if not args.no_save:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        tag = "_".join(args.variants) if len(args.variants) < 6 else "all"
        outfile = ARTIFACTS / f"{args.phase}_{tag}_participation{args.max_participation:g}_carry{args.carry_bps_per_day:g}.json"
        outfile.write_text(json.dumps(record, indent=2, sort_keys=True, default=str) + "\n")
        print("REPORT", str(outfile), flush=True)


if __name__ == "__main__":
    main()
