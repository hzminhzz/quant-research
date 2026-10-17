"""Independent timestamp-contract oracle: 30m close using 5m bar-open labels.

Under bar-open timestamp semantics, the final 5m bar of [00:00,00:30)
is stamped 00:25, and its close is observable at 00:30. Engine on_data
processes the FULL completed 00:25 bar then queues NEXT_BAR entry,
which is executed at 00:30. This tests actual fill timestamps.
"""

from datetime import datetime, timedelta, timezone

import polars as pl

from ml4t.backtest import BacktestConfig, DataFeed, Engine, ExecutionMode, OrderStatus, Strategy
from ml4t.backtest.config import ExecutionPrice

UTC=timezone.utc
T0=datetime(2024, 1, 2, tzinfo=UTC)

class MTFBoundary(Strategy):
    def __init__(self):
        self.seen=[]
        self.entry=None
    def on_data(self, timestamp,data,context,broker):
        self.seen.append(timestamp)
        if timestamp == T0+timedelta(minutes=25):
            # Completed interval [00:25,00:30), first known at 00:30.
            assert data["EURUSD"]["close"] == 1.105
            self.entry=broker.submit_order("EURUSD",1000)

def test_30m_retest_close_to_exact_next_5m_open() -> None:
    n=10
    times=[T0+timedelta(minutes=5*i) for i in range(n)]
    closes=[1.1]*n
    closes[5]=1.105
    prices=pl.DataFrame({
        "timestamp":times,
        "symbol":["EURUSD"]*n,
        "open":[1.1]*n,
        "high":[max(1.106,c) for c in closes],
        "low":[1.099]*n,
        "close":closes,
        "volume":[1000.0]*n,
    })
    strategy=MTFBoundary()
    cfg=BacktestConfig(
        execution_mode=ExecutionMode.NEXT_BAR,
        execution_price=ExecutionPrice.OPEN,
        initial_cash=100000,
    )
    Engine(DataFeed(prices_df=prices),strategy,cfg).run()
    assert strategy.entry is not None
    assert strategy.entry.status is OrderStatus.FILLED
    assert strategy.entry.created_at == T0+timedelta(minutes=25)
    assert strategy.entry.filled_at == T0+timedelta(minutes=30)
    assert strategy.entry.filled_price == 1.1
    assert all(t <= strategy.entry.created_at for t in strategy.seen[:6])
