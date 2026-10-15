# ML4T Backtest

Event-driven backtesting engine with configurable execution semantics, validated against four independent frameworks (VectorBT, Backtrader, Zipline, LEAN).

## Overview

`ml4t-backtest` is the simulation layer in the ML4T stack:
- `ml4t-data`: prepares canonical market datasets
- `ml4t-engineer`: produces labels and features
- `ml4t-diagnostic`: validates signals, models, and portfolio behavior
- `ml4t-backtest`: simulates execution with explicit, configurable semantics
- `ml4t-live`: reuses the same strategy surface for paper and live rollout

## Quick Example

```python
import polars as pl
from ml4t.backtest import BacktestConfig, DataFeed, Engine, Strategy
from ml4t.backtest.types import OrderSide

class SmaCrossStrategy(Strategy):
    def on_data(self, timestamp, data, context, broker):
        bar = data.get("AAPL")
        if not bar:
            return
        pos = broker.get_position("AAPL")
        if pos is None:
            broker.submit_order("AAPL", 100, side=OrderSide.BUY)

prices = pl.read_parquet("aapl_daily.parquet")
engine = Engine(
    DataFeed(prices_df=prices),
    SmaCrossStrategy(),
    BacktestConfig(initial_cash=100_000),
)
result = engine.run()
print(f"Fills: {len(result.fills)}, Final Value: ${result.metrics['final_value']:.2f}")
```

## Key Capabilities

1. **Configurable Execution Semantics:** Support for `NEXT_BAR` (default for realistic simulation) and `SAME_BAR` execution modes.
2. **Quote-Aware Execution:** Feed can cache bid, ask, midpoint, and quote sizes for side-aware fills and separate mark pricing.
3. **Framework Parity Validation:** Pinned parity profiles matching VectorBT, Backtrader, Zipline, and LEAN.
4. **Rich Output Persistence:** Direct export of trades, fills, equity curves, portfolio state, and daily P&L.
