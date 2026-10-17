"""VOLT BREAK: ML4T-native execution lifecycle adapter. Not a custom simulator.

On an ordinary NEXT_BAR entry fill, ML4T Engine normally evaluates position
rules before processing the entry. This wrapper calls native Broker risk+fill
once more immediately after a newly opened long fills; all orders, fills,
costs and cash bookkeeping remain in the native Broker.
"""
from __future__ import annotations
from ml4t.backtest import Engine
from ml4t.backtest.risk.position.protocol import PositionAction

class FixedPointStopFirst:
    def __init__(self, tp_points: float = 40.0, sl_points: float = 75.0):
        self.tp_points = tp_points
        self.sl_points = sl_points

    def evaluate(self, state):
        if not state.is_long:
            return PositionAction.hold()
        entry = float(state.entry_price)
        stop = entry - self.sl_points
        target = entry + self.tp_points
        op, hi, lo = state.bar_open, state.bar_high, state.bar_low
        if op is not None and op <= stop:
            return PositionAction.exit_full("volt_stop_gap", fill_price=float(op))
        if lo is not None and lo <= stop:
            return PositionAction.exit_full("volt_stop", fill_price=stop)
        if op is not None and op >= target:
            return PositionAction.exit_full("volt_target_gap", fill_price=float(op))
        if hi is not None and hi >= target:
            return PositionAction.exit_full("volt_target", fill_price=target)
        return PositionAction.hold()

class VoltBreakNativeEngine(Engine):
    def __init__(self, feed, strategy, config=None, *, contract_specs=None):
        super().__init__(feed, strategy, config, contract_specs=contract_specs)
        self.adapter_entry_rule_evaluations = 0
        self.adapter_entry_rule_exit_orders = 0
        self.adapter_entry_rule_exit_fills = 0
        self._adapter_in_exit_fill = False
        native_process = self.broker._process_orders
        broker = self.broker
        symbol = strategy.asset

        def process_with_entry_risk(use_open=False, *, order_types=None, order_ids=None,
                                    include_orders_this_bar=False):
            before = broker.get_position(symbol)
            before_qty = float(before.quantity) if before is not None else 0.0
            out = native_process(use_open=use_open, order_types=order_types,
                                 order_ids=order_ids,
                                 include_orders_this_bar=include_orders_this_bar)
            if (self._adapter_in_exit_fill or not use_open or order_types is not None
                    or order_ids is not None):
                return out
            after = broker.get_position(symbol)
            after_qty = float(after.quantity) if after is not None else 0.0
            if before_qty != 0 or after_qty <= 0:
                return out
            if hasattr(strategy, 'record_native_entry'):
                strategy.record_native_entry(broker.fills[-1])
            self.adapter_entry_rule_evaluations += 1
            self._adapter_in_exit_fill = True
            try:
                exits = broker.evaluate_position_rules()
                self.adapter_entry_rule_exit_orders += len(exits)
                if exits:
                    filled_before = len(broker.fills)
                    native_process(use_open=True, order_ids={o.order_id for o in exits},
                                   include_orders_this_bar=True)
                    self.adapter_entry_rule_exit_fills += len(broker.fills) - filled_before
            finally:
                self._adapter_in_exit_fill = False
            return out
        self.broker._process_orders = process_with_entry_risk
