# ML4T Live Documentation Index

This directory contains the complete upstream documentation for `ml4t-live==0.1.2`.

### Core Documentation

| File | Description | Key Topics |
|---|---|---|
| [`user-guide/risk.md`](user-guide/risk.md) | **Risk Controls & SafeBroker** | `SafeBroker`, `LiveRiskConfig`, position limits, max order value, daily loss, drawdown kill switch, staleness |
| [`user-guide/backtest-to-live.md`](user-guide/backtest-to-live.md) | **Migration Guide** | Moving from `ml4t-backtest` to `ml4t-live`, `ThreadSafeBrokerWrapper`, strategy portability |
| [`user-guide/brokers.md`](user-guide/brokers.md) | **Broker Protocols** | `AsyncBrokerProtocol`, `ExecutionCapability`, live broker requirements |
| [`user-guide/feeds.md`](user-guide/feeds.md) | **Market Data Feeds** | `DataFeedProtocol`, `MarketEvent`, bar buffering and streaming |
| [`user-guide/operator-guide.md`](user-guide/operator-guide.md) | **Operator Runbook** | Staged rollout (shadow → paper → live), incident management, reconciliation |
| [`getting-started/quickstart.md`](getting-started/quickstart.md) | **Quickstart** | Minimal `LiveEngine` setup, shadow mode, connecting brokers |
| [`api.yaml`](api.yaml) | **API Specification** | Full YAML schema of all public classes, methods, and dataclass fields |
| [`DESIGN.md`](DESIGN.md) | **Architecture Design** | Internal lifecycle, state transitions, fault recovery, and invariants |
