"""Synthetic engineering probe. No economic strategy or deployment approval."""
from ml4t.backtest import Strategy


class SyntheticCycle(Strategy):
    """Use identical native Strategy code in replay and local live simulation."""

    def __init__(self, asset="BTC/USDT:USDT", quantity=0.001):
        super().__init__()
        self.asset = asset
        self.quantity = quantity

    def on_data(self, timestamp, data, context, broker):
        if self.asset not in data:
            return
        position = broker.get_position(self.asset)
        if timestamp.minute % 2 == 0 and (position is None or position.quantity == 0):
            broker.submit_order(self.asset, self.quantity)
        elif timestamp.minute % 2 == 1 and position is not None and position.quantity > 0:
            broker.close_position(self.asset)
