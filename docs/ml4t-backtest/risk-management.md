# Risk Management & Position Rules

`ml4t-backtest` provides two levels of risk controls:
1. **Position Rules (Per-position exits):** Automatically evaluated on every bar; triggers exit orders when breached.
2. **Portfolio Limits (Portfolio-wide constraints):** Aggregate checks on drawdown, exposure, leverage, and loss limits.

---

## 1. Position Rules

### Common Rules
```python
from ml4t.backtest import (
    StopLoss, TakeProfit, TrailingStop, VolatilityStop, TimeExit,
    RuleChain, AllOf, AnyOf
)

# Hard stop loss at -5% from entry price
stop_loss = StopLoss(pct=0.05)

# Take profit at +15%
take_profit = TakeProfit(pct=0.15)

# Trailing stop: 3% retrace from peak high water mark
trailing_stop = TrailingStop(pct=0.03)

# Volatility stop: 2x ATR distance
vol_stop = VolatilityStop(multiplier=2.0)

# Max holding period: exit after 20 bars
time_exit = TimeExit(max_bars=20)
```

### Rule Composition
```python
# RuleChain: First non-HOLD trigger wins (order of priority)
rules = RuleChain([
    StopLoss(pct=0.05),        # 1. Hard stop
    TakeProfit(pct=0.20),      # 2. Take profit
    TrailingStop(pct=0.03),    # 3. Trailing stop
])

# AllOf: All conditions must be true simultaneously
break_even_time = AllOf([
    TakeProfit(pct=0.0),       # At or above breakeven
    TimeExit(max_bars=5),      # Must have held for at least 5 bars
])
```

### Setting Rules in Strategy
```python
class ProtectedStrategy(Strategy):
    def on_start(self, broker):
        # Global rules applied to all assets
        broker.set_position_rules(RuleChain([
            StopLoss(pct=0.05),
            TrailingStop(pct=0.03),
        ]))

        # Per-asset override for volatile assets
        broker.set_position_rules(
            RuleChain([StopLoss(pct=0.10), TakeProfit(pct=0.25)]),
            asset="BTC",
        )
```

---

## 2. Portfolio Limits

Import from `ml4t.backtest.risk.portfolio.limits`:

```python
from ml4t.backtest.risk.portfolio.limits import (
    MaxDrawdownLimit, MaxPositionsLimit, MaxExposureLimit,
    DailyLossLimit, GrossExposureLimit, NetExposureLimit
)

# Max Drawdown: Liquidate or reduce after 20% drawdown
drawdown_limit = MaxDrawdownLimit(max_drawdown=0.20, warn_threshold=0.15, action="reduce", reduction_pct=0.50)

# Daily Loss Limit: Liquidate above 3% daily loss
daily_loss_limit = DailyLossLimit(max_daily_loss_pct=0.03, action="liquidate")

# Max Position Count
positions_limit = MaxPositionsLimit(max_positions=10)

# Gross Exposure Cap
gross_limit = GrossExposureLimit(max_gross_exposure=1.5)  # Max 150% gross
```
