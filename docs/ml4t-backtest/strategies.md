# Strategy Interface & Broker API

Every strategy subclasses `Strategy` and implements `on_data`. The broker is the interface to the market for submitting orders, querying positions, and setting risk rules.

## Strategy Lifecycle Callbacks

```python
from ml4t.backtest import Strategy

class MyStrategy(Strategy):
    def on_prepare(self, broker, config=None):
        """Called once with resolved configuration before feed data. Optional."""
        pass

    def on_start(self, broker):
        """Called once before the first bar.
        Use this to set position rules, initialize state, or log configuration.
        """
        pass

    def on_data(self, timestamp, data, context, broker):
        """Called on every bar. Required.

        Args:
            timestamp: Current bar's datetime
            data: Dict of {asset: bar_dict} with open, high, low, close, volume, signals
            context: Dict of context data provided via DataFeed
            broker: Broker interface for orders and position queries
        """
        pass

    def on_end(self, broker):
        """Called once after the last bar. Final cleanup or logging."""
        pass
```

## Broker Methods

### Order Placement
```python
# Market order
broker.submit_order("AAPL", 100)

# Short sale (negative quantity)
broker.submit_order("AAPL", -100)

# Limit order
from ml4t.backtest.types import OrderType
broker.submit_order("AAPL", 100, order_type=OrderType.LIMIT, limit_price=150.0)

# Stop order
broker.submit_order("AAPL", 100, order_type=OrderType.STOP, stop_price=145.0)

# Stop-Limit order
broker.submit_order("AAPL", 100, order_type=OrderType.STOP_LIMIT, stop_price=145.0, limit_price=144.0)

# Market-On-Close order
broker.submit_order("AAPL", 100, order_type=OrderType.MOC)

# Bracket order (Entry + Take Profit + Stop Loss)
entry_order, tp_order, sl_order = broker.submit_bracket(
    asset="AAPL",
    quantity=100,
    take_profit=165.0,
    stop_loss=145.0,
)
```

### Position & Account Queries
```python
# Single position
pos = broker.get_position("AAPL")
if pos:
    print(pos.quantity, pos.entry_price, pos.bars_held)

# All positions
positions = broker.get_positions()

# Account equity and cash
equity = broker.get_account_value()
cash = broker.get_cash()

# Close position
broker.close_position("AAPL")
```

### Rebalancing to Target Weights
```python
broker.rebalance_to_weights({
    "AAPL": 0.40,
    "MSFT": 0.40,
    # Remaining 20% stays in cash
})
```
