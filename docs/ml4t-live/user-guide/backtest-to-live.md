# Backtest to Live

The central promise of `ml4t-live` is that you do not rewrite strategy logic for deployment. You keep
the same `Strategy` class and move it into a live runtime with broker, feed, and safety layers around it.

## What Stays The Same

- your `Strategy` subclass
- the synchronous `on_data(timestamp, data, context, broker)` interface
- your signal logic, sizing logic, and state handling inside the strategy

## What Changes

| Backtest concept | Live equivalent |
| --- | --- |
| `Engine` | `LiveEngine` |
| historical data feed | broker-connected or replay `DataFeedProtocol` |
| simulated broker/execution | async broker wrapped by `SafeBroker` |
| backtest risk assumptions | explicit `LiveRiskConfig` limits |
| offline validation | shadow mode, paper trading, staged live rollout |

## Migration Pattern

1. Validate the strategy in `ml4t-backtest`.
2. Pick the broker and feed combination that matches your market.
3. Wrap the broker in `SafeBroker`.
4. Start in `shadow_mode=True`.
5. Promote to paper trading only after signal, inventory, and order-flow checks pass.
6. Go live with conservative limits and an explicit rollback plan.

## Minimal Port

```python
from ml4t.live import LiveEngine, LiveRiskConfig, SafeBroker

safe_broker = SafeBroker(raw_broker, LiveRiskConfig(shadow_mode=True))
engine = LiveEngine(strategy, safe_broker, live_feed)
await engine.connect()
await engine.run()
```

The important part is that `strategy` remains the same object you already validated in research.

## Where Most Divergence Comes From

Technical divergence usually comes from infrastructure, not from the strategy itself:

- different bar construction between backtest and live
- stale or mismatched data fields
- broker inventory that does not match the simulated portfolio
- order semantics that differ between the simulator and the venue
- safety rules applied in one mode but not the other

That is why `ml4t-live` separates the strategy from the runtime layers and makes the rollout policy
explicit in `LiveRiskConfig`.

## Practical Rollout Pattern

| Stage | Goal | Typical checks |
| --- | --- | --- |
| Shadow mode | Verify parity without market risk | signals, positions, kill switch, restart behavior |
| Paper trading | Verify integration with broker APIs | order lifecycle, reconciliation, timestamps |
| Small live size | Verify operational readiness | slippage, latency, monitoring, manual overrides |

## Related Pages

- [Quickstart](../getting-started/quickstart.md)
- [Brokers](brokers.md)
- [Data Feeds](feeds.md)
- [Risk Controls](risk.md)
- [API Reference](../api/index.md)

## See It In The Book

The most relevant book materials for this workflow are:

- Chapter 16 parity notebooks, especially `code/16_strategy_simulation/06_framework_parity.py`
- Chapter 25.1 and `code/25_live_trading/unified_framework_demo.py`
- Chapter 25.6 and `code/25_live_trading/pipeline_verification.py`
- Chapter 25.7 and `code/25_live_trading/safety_risk_demo.py`

Use the [Book Guide](../book-guide/index.md) for the broader chapter map.
