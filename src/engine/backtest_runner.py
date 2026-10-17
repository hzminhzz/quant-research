"""Native ML4T order/accounting simulation with narrowly pinned lifecycle adapters.

ML4T 0.1.7 has no public scheduled-funding API. A per-instance pre-order hook
applies funding to its native cash account. The native FillExecutor remains the
only fill/matching implementation; its extension maintains frozen protective
STOP orders after actual fills. No replacement simulation loop is used.
"""
from __future__ import annotations

import importlib.metadata
import math
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl
from ml4t.backtest import BacktestConfig, DataFeed, Engine, OrderType, Strategy
from ml4t.backtest.config import (
    CommissionType,
    ExecutionPrice,
    FillOrdering,
    ShareType,
    SlippageType,
)
from ml4t.backtest.execution.fill_executor import FillExecutor
from ml4t.backtest.types import ExecutionMode, OrderSide
from ml4t.diagnostic.metrics import sharpe_ratio

from src.portfolio.barrier_controller import barrier_leverage_scale

from .common import QuantError
from .spec_parser import CandidateSpec

ENGINE_VERSION = '0.1.7'


@dataclass
class NativeRun:
    equity: pl.DataFrame
    daily: pl.DataFrame
    fills: pl.DataFrame
    trades: pl.DataFrame
    funding: pl.DataFrame
    metrics: dict[str, Any]
    timing: list[dict[str, Any]]


class TargetStrategy(Strategy):
    def __init__(self, targets: pl.DataFrame, spec: CandidateSpec, timestamps: list):
        self.spec = spec
        self.targets = {p['timestamp'][0]: {r['symbol']: r for r in p.iter_rows(named=True)}
                        for p in targets.partition_by('timestamp', maintain_order=True)}
        self.final_signal = timestamps[-2]
        self.final_bar = timestamps[-1]
        self.desired: dict[str, tuple[float, float, Any]] = {}
        self.stop_price: dict[str, float] = {}
        self.stop_order: dict[str, str] = {}
        self.stopped_at: dict[str, Any] = {}
        self.short_entries = 0
        self.short_stops = 0
        self.timing: list[dict[str, Any]] = []
        self.protection_updates: list[dict[str, Any]] = []
        self.opening_phase = False
        self.barrier_day = None
        self.barrier_midnight_balance = None
        self.last_closed_balance = None
        self.last_closed_at = None

    def on_data(self, timestamp, data, context, broker):
        if self.spec.barrier_overlay_enabled:
            # A bar opens at `timestamp` and its close only becomes available
            # at timestamp + bar_seconds. Prague midnight must be anchored to
            # the PREVIOUS completed bar, not the current bar's future close.
            # Native cash can include short-sale proceeds; approximate balance
            # as marked equity less the native position ledger's unrealized PnL.
            local = timestamp.astimezone(ZoneInfo('Europe/Prague'))
            if self.barrier_day != local.date():
                self.barrier_day = local.date()
                self.barrier_midnight_balance = (
                    self.last_closed_balance if self.last_closed_at == timestamp else None)
            held = broker.get_positions()
            if all(symbol in data for symbol in held):
                floating = sum(position.unrealized_pnl(float(data[symbol]['close']))
                               for symbol, position in held.items())
                self.last_closed_balance = broker.equity() - floating
                self.last_closed_at = timestamp + timedelta(seconds=self.spec.bar_seconds)
            else:
                self.last_closed_balance = None
                self.last_closed_at = None
        if timestamp == self.final_bar:
            return
        liquidation = timestamp == self.final_signal
        schedule = {} if liquidation else self.targets.get(timestamp)
        if schedule is None:
            return
        positions = broker.get_positions()
        equity = broker.equity()
        leverage_scale = 1.0
        if self.spec.barrier_overlay_enabled:
            marks_available = (self.barrier_midnight_balance is not None
                               and all(name in data for name in set(positions) | set(schedule)))
            leverage_scale = barrier_leverage_scale(
                equity=equity, initial_balance=self.spec.initial_cash,
                midnight_balance=self.barrier_midnight_balance, marks_available=marks_available)
        names = sorted(set(schedule) | set(positions))
        for symbol in names:
            bar = data.get(symbol)
            if bar is None:
                if symbol in positions:
                    raise QuantError('INVALID_EXECUTION', 'A held symbol is absent at a rebalance/exit')
                continue
            row = schedule.get(symbol)
            weight = row['target_weight'] if row is not None else 0.0
            if self.stopped_at.get(symbol) == timestamp:
                weight = 0.0
            price = float(bar.get('close', bar.get('price')))
            desired = weight * leverage_scale * equity / price
            current = broker.get_position(symbol)
            current_quantity = current.quantity if current is not None else 0.0
            delta = desired - current_quantity
            if abs(delta) < 1e-10:
                continue
            distance = row['stop_loss_dist_pct'] * price if weight else 0.0
            order = broker.submit_order(symbol, delta, order_type=OrderType.MARKET)
            if order is None:
                raise QuantError('INVALID_EXECUTION', 'Native broker rejected a target delta')
            self.desired[order.order_id] = (desired, distance, timestamp)


class ProtectiveExecutor(FillExecutor):
    """Adjust quantities after stops and preserve one fixed stop per position episode."""
    def __init__(self, *args, strategy: TargetStrategy, **kwargs):
        super().__init__(*args, **kwargs)
        self.strategy = strategy
        self._protecting = False

    def execute(self, order, base_price: float) -> bool:
        s, broker = self.strategy, self.broker
        symbol = order.asset
        previous = broker.get_position(symbol)
        previous_quantity = previous.quantity if previous is not None else 0.0
        is_stop = order.order_type == OrderType.STOP
        intent = s.desired.get(order.order_id)
        if intent is not None:
            desired, distance, signal_at = intent
            if broker._current_time != signal_at + timedelta(seconds=s.spec.bar_seconds):
                broker.cancel_order(order.order_id)
                raise QuantError('INVALID_EXECUTION', 'A market order missed its exact next-bar opening')
            if s.stopped_at.get(symbol) == broker._current_time and desired != 0:
                broker.cancel_order(order.order_id)
                return False
            delta = desired - previous_quantity
            if abs(delta) < 1e-10:
                broker.cancel_order(order.order_id)
                return False
            order.quantity = abs(delta)
            order.side = OrderSide.BUY if delta > 0 else OrderSide.SELL
        executed = super().execute(order, base_price)
        if not executed:
            return executed
        current = broker.get_position(symbol)
        quantity = current.quantity if current is not None else 0.0
        if is_stop:
            if previous_quantity < 0:
                s.short_stops += 1
            s.stopped_at[symbol] = broker._current_time
            s.stop_price.pop(symbol, None)
            s.stop_order.pop(symbol, None)
            return executed
        if intent is None:
            return executed
        s.timing.append({'symbol': symbol, 'signal_bar': signal_at.isoformat(),
                         'available_at': (signal_at + timedelta(seconds=s.spec.bar_seconds)).isoformat(),
                         'fill_at': broker._current_time.isoformat(), 'desired_quantity': desired,
                         'filled_delta': quantity - previous_quantity})
        prior_stop = s.stop_order.pop(symbol, None)
        if prior_stop is not None:
            broker.cancel_order(prior_stop)
        if quantity == 0:
            s.stop_price.pop(symbol, None)
            return executed
        new_episode = previous_quantity == 0 or previous_quantity * quantity < 0
        if new_episode:
            if distance <= 0:
                raise QuantError('INVALID_EXECUTION', 'New episode has no frozen ATR distance')
            if quantity < 0:
                s.short_entries += 1
            entry = float(current.entry_price)
            stop = entry - distance if quantity > 0 else entry + distance
            if stop <= 0:
                raise QuantError('INVALID_EXECUTION', 'Frozen ATR stop would be non-positive')
            s.stop_price[symbol] = stop
        if symbol not in s.stop_price:
            raise QuantError('INVALID_EXECUTION', 'Open position lost its protective stop')
        protective = broker.submit_order(symbol, abs(quantity),
                                          side=OrderSide.SELL if quantity > 0 else OrderSide.BUY,
                                          order_type=OrderType.STOP, stop_price=s.stop_price[symbol])
        if protective is None:
            raise QuantError('INVALID_EXECUTION', 'Native protective STOP rejected')
        s.stop_order[symbol] = protective.order_id
        s.protection_updates.append({'timestamp': broker._current_time.isoformat(), 'symbol': symbol,
                                     'stop_price': s.stop_price[symbol], 'quantity': quantity,
                                     'new_episode': new_episode})
        # New entry was at this open. Evaluate its STOP through native OHLC matching,
        # including an entry-bar touch; no custom touch/fill arithmetic.
        if not self._protecting and not s.opening_phase:
            self._protecting = True
            try:
                broker._process_orders(use_open=True, order_ids={protective.order_id},
                                       include_orders_this_bar=True)
            finally:
                self._protecting = False
        return executed


def _opening_order_hook(engine: Engine, strategy: TargetStrategy) -> None:
    """Expose only opening prices before native opening orders, then intrabar range.

    Generic EXIT_FIRST may evaluate an old STOP against the entire current bar
    before a scheduled opening market exit. This adapter invokes the SAME native
    matcher in causal phases: gap stops, opening deltas, remaining intrabar stops.
    It neither calculates fill prices nor substitutes a bar simulation loop.
    """
    broker = engine.broker
    original = broker._process_orders

    def process(use_open=False, order_ids=None, order_types=None, include_orders_this_bar=False):
        if not use_open or order_ids is not None or order_types is not None:
            return original(use_open=use_open, order_ids=order_ids, order_types=order_types,
                            include_orders_this_bar=include_orders_this_bar)
        market = broker._market_state
        fields = ('prices', 'closes', 'highs', 'lows')
        saved = {name: getattr(market, name) for name in fields}
        strategy.opening_phase = True
        try:
            for name in fields:
                setattr(market, name, market.opens)
            broker.mark_account_positions(use_open=True)
            original(use_open=True, order_types={OrderType.STOP}, include_orders_this_bar=False)
            original(use_open=True, order_types={OrderType.MARKET}, include_orders_this_bar=False)
        finally:
            for name, value in saved.items():
                setattr(market, name, value)
            strategy.opening_phase = False
            broker.mark_account_positions(use_open=False)
        original(use_open=True, order_types={OrderType.STOP}, include_orders_this_bar=True)
    broker._process_orders = process


def _funding_hook(engine: Engine, events: pl.DataFrame, panel: pl.DataFrame) -> list[dict[str, Any]]:
    broker, records = engine.broker, []
    original = broker._update_time
    event_map = {}
    if events.height:
        if not {'timestamp', 'symbol', 'funding_rate', 'mark_price'} <= set(events.columns):
            raise QuantError('BLOCKED_DATA', 'Funding requires timestamp, symbol, rate and source mark')
        if events.select(pl.struct('timestamp', 'symbol').n_unique()).item() != events.height:
            raise QuantError('BLOCKED_DATA', 'Duplicate funding cashflow events')
        feed_times = set(panel['timestamp'].to_list())
        symbols = set(panel['symbol'].to_list())
        for event in events.iter_rows(named=True):
            rate, mark = event['funding_rate'], event['mark_price']
            if event['symbol'] not in symbols or event['timestamp'] not in feed_times:
                raise QuantError('BLOCKED_DATA', 'Funding event is not represented in the native event clock')
            if rate is None or not math.isfinite(rate) or mark is None or not math.isfinite(mark) or mark <= 0:
                raise QuantError('BLOCKED_DATA', 'Nonfinite funding rate or missing source mark')
            event_map.setdefault(event['timestamp'], []).append(event)
    elif panel.filter(pl.col('carry_rate') != 0).height:
        raise QuantError('BLOCKED_DATA', 'Nonzero carry requires funding event/mark sidecar')

    def update(timestamp, prices, opens, *args, **kwargs):
        original(timestamp, prices, opens, *args, **kwargs)
        for symbol, position in broker.get_positions().items():
            if abs(position.quantity) > 1e-10 and symbol not in opens:
                raise QuantError('BLOCKED_DATA', f'Open position has no tradable opening observation: {symbol}')
        # Called before native pending exits, entries, stops and strategy decisions.
        for event in event_map.get(timestamp, []):
            position = broker.get_position(event['symbol'])
            quantity = position.quantity if position is not None else 0.0
            multiplier = broker.get_multiplier(event['symbol'])
            cashflow = -quantity * multiplier * event['mark_price'] * event['funding_rate']
            before = broker.get_cash()
            broker.cash = before + cashflow
            after = broker.get_cash()
            if not math.isclose(after - before, cashflow, abs_tol=1e-7, rel_tol=1e-10):
                raise QuantError('INVALID_ACCOUNTING', 'Native cash did not reconcile to funding transfer')
            records.append({'timestamp': timestamp, 'symbol': event['symbol'], 'quantity': quantity,
                            'rate': event['funding_rate'], 'mark': event['mark_price'],
                            'cashflow': cashflow, 'cash_before': before, 'cash_after': after,
                            'mark_source': event.get('mark_source', 'provided_event_mark'),
                            'source_event_at': event.get('source_event_at', timestamp)})
    broker._update_time = update
    return records


def run_native(panel: pl.DataFrame, targets: pl.DataFrame, spec: CandidateSpec,
               *, funding: pl.DataFrame | None = None) -> NativeRun:
    if importlib.metadata.version('ml4t-backtest') != ENGINE_VERSION:
        raise QuantError('INVALID_CAPABILITY', 'Private native lifecycle adapter needs version requalification')
    prices = panel.filter(pl.col('is_tradable')).sort('symbol', 'timestamp')
    times = prices['timestamp'].unique().sort().to_list()
    if len(times) < 3:
        raise QuantError('BLOCKED_DATA', 'Native simulation needs at least three tradable timestamps')
    strategy = TargetStrategy(targets, spec, times)
    spread = spec.costs.spread_bps / 2 if not spec.costs.spread_included_in_slippage else 0.0
    config = BacktestConfig(initial_cash=spec.initial_cash, allow_short_selling=True, allow_leverage=True,
                            share_type=ShareType.FRACTIONAL, execution_mode=ExecutionMode.NEXT_BAR,
                            execution_price=ExecutionPrice.OPEN, fill_ordering=FillOrdering.EXIT_FIRST,
                            commission_type=CommissionType.PERCENTAGE,
                            commission_rate=spec.costs.commission_bps_one_way / 10000,
                            slippage_type=SlippageType.PERCENTAGE,
                            slippage_rate=(spec.costs.slippage_bps_one_way + spread) / 10000)
    feed = DataFeed(prices_df=prices.select('timestamp', 'symbol', 'open', 'high', 'low', 'close', 'volume'),
                    entity_col='symbol', timestamp_col='timestamp')
    engine = Engine(feed, strategy, config)
    old = engine.broker._fill_executor
    replacement = ProtectiveExecutor(engine.broker, account=old.account, market=old.market,
                                      orders=old.orders, risk=old.risk, journal=old.journal,
                                      record_pnl=old.record_pnl, strategy=strategy)
    replacement.fill_engine = engine.broker._fill_engine
    engine.broker._fill_engine.executor = replacement
    engine.broker._fill_executor = replacement
    funding = funding if funding is not None else pl.DataFrame()
    funding_records = _funding_hook(engine, funding, prices)
    _opening_order_hook(engine, strategy)
    result = engine.run()
    if engine.broker.get_positions():
        raise QuantError('INVALID_EXECUTION', 'End-window liquidation did not complete')
    if engine.broker.get_rejected_orders():
        raise QuantError('INVALID_EXECUTION', 'Native broker rejected one or more orders')
    equity, fills, trades = result.to_equity_dataframe(), result.to_fills_dataframe(), result.to_trades_dataframe()
    daily = (equity.with_columns(pl.col('timestamp').dt.date().alias('date'))
             .group_by('date').agg(pl.col('equity').last()).sort('date')
             .with_columns((pl.col('equity') / pl.col('equity').shift(1).fill_null(spec.initial_cash) - 1).alias('return')))
    returns = daily['return'].to_numpy()
    native_sharpe = float(sharpe_ratio(returns, periods_per_year=spec.periods_per_year)) if len(returns) > 2 else None
    if native_sharpe is not None and not math.isfinite(native_sharpe):
        native_sharpe = None
    funding_frame = pl.DataFrame(funding_records) if funding_records else pl.DataFrame()
    from .accounting_audit import audit_accounting
    audit = audit_accounting(prices, fills, funding_frame, equity, spec.initial_cash)
    metrics = {'independent_accounting': audit,'native_engine_version': ENGINE_VERSION, 'daily_sharpe': native_sharpe,
               'final_equity': float(equity['equity'][-1]), 'initial_cash': spec.initial_cash,
               'completed_trades': trades.height, 'fill_count': fills.height,
               'short_entries': strategy.short_entries, 'short_stops': strategy.short_stops,
               'short_stop_fraction': strategy.short_stops / strategy.short_entries if strategy.short_entries else None,
               'funding_total': sum(r['cashflow'] for r in funding_records),
               'funding_mark_proxy_events': sum(r['mark_source'] == 'trade_open_proxy' for r in funding_records),
               'funding_boundary_model': 'pre-opening inventory at declared modeled settlement time; not a venue latency guarantee',
               'stop_basis': 'actual episode entry fill +/- frozen decision ATR distance',
               'bar_ordering': 'prior-inventory funding; opening gap stops; opening target deltas; intrabar stops; closing marks',
               'protection_updates': strategy.protection_updates,
               'execution_model': 'native linear-notional margin account; no venue liquidation/queue model',
               'sizing_policy': 'quantities frozen from signal-close equity/prices; next-open gaps can change realized weights',
               'terminal_policy': 'predeclared liquidation at final available open'}
    return NativeRun(equity, daily, fills, trades, funding_frame, metrics, strategy.timing)
