# ADR 0004 — Prefer native ML4T live execution over custom orchestration

**Status:** Accepted; architecture grill CLOSED on 2026-10-15. Operational qualification and deployment remain separate, not approved by this ADR.
**Date:** 2026-10-15.

## Context

The desired operating model is independently understandable strategies with coordinated account safety. A previous design proposed a new shared execution gateway, portfolio-risk service, cross-strategy netting system and capital-allocation infrastructure. The user explicitly rejected additional code and services when native ML4T capabilities suffice.

The authoritative runtime is `ml4t-live==0.1.2` installed in `/home/quant/dev/quant/quant-research/.venv`. `/home/quant/dev/trading-connector` owns optional provider adapters for that runtime, not a replacement trading engine. The old standalone `ml4t-live` checkout is stale.

## Decision

- **Native first:** Reuse `ml4t-live.LiveEngine`, `SafeBroker`, `LiveRiskConfig`, `ThreadSafeBrokerWrapper`, its broker/feed protocols, lifecycle, journal, persistence, order checks, and reconciliation. Add no new gateway, risk service, order netter, scheduler or capital allocator by default.
- **Provider integration only:** Keep vendor-specific translation in the `trading-connector` adapters, matching the actually installed `ml4t-live` protocol. No strategy or allocation logic in connector adapters.
- **One native owner per broker account:** The first deployment uses one ML4T execution/risk owner per account. Multiple strategies may use separate accounts or run sequentially, but concurrent independent `LiveEngine`/`SafeBroker` instances must not trade the same account. This is the user's approved operational choice (option A).
- **Fail closed on unsupported shared-account concurrency:** Installed `SafeBroker` locking and persistence are per instance and do not establish cross-instance atomic risk enforcement. Keep shared-account multi-engine execution out of scope; do not build custom coordination solely to achieve the earlier aspirational hybrid design.
- **Observability is read-only:** Expose native runtime health, broker connection, risk/reconciliation state, order events and VPS resources in Grafana/Prometheus. Do not build a custom portfolio analytics stack or use monitoring to submit orders or own risk authority.
- **Initial validation stage: paper trading:** Start with a verified simulated trading account rather than requiring another shadow-mode phase. Bybit **Demo Trading** is a main-platform simulated account, whereas Bybit **Testnet** is a separate environment; they have different API addresses, credentials and market-data characteristics. `SafeBroker(execution_mode="paper")` requires the connector to attest to the actual configured simulated environment. Connector tests alone cannot establish that attestation for a different environment.
- **Native bounded recovery:** Use `LiveEngine(auto_recover=True)` for `feed_silent` and `broker_disconnected`, with a configured feed-silence threshold and its native bounded attempts. Reconnection must pass existing broker identity, reconciliation and persistence checks. When attempts are exhausted, leave the engine stopped/failed and surface an operator alert rather than adding a custom retry supervisor.
- **Fail-closed reconciliation:** Set native `LiveRiskConfig(fail_on_reconciliation_mismatch=True)` for paper and future live execution. After restart or reconnect, any detected position/order mismatch blocks the engine from reconnecting to active strategy execution until reconciliation is clean or an operator resolves it. Native automatic recovery cannot bypass this check. Do not automatically flatten or pretend mismatches are resolved.
- **Evidence-based paper qualification:** Consider live deployment only after predeclared paper observation criteria are satisfied, including order/fill accounting, broker reconciliation, restart and failure-recovery drills, and risk-limit checks. Specify the observation duration and measurable pass/fail criteria before collecting qualification evidence; no arbitrary duration or performance threshold is implied here. An independent live-authorization decision is still required.
- **Explicit native risk budgets:** Every strategy/account pair uses an explicitly reviewed `LiveRiskConfig` with suitable order limits, position/exposure limits, loss/drawdown limits, data-staleness settings and account semantics. Do not rely blindly on library default dollar limits or add a separate risk service.

## Alternatives rejected

- **Custom shared execution gateway + portfolio-risk microservice:** Adds operational and correctness burden before proving a gap that requires solving.
- **Independent engines with independent `SafeBroker` instances accessing the same account:** Does not prove aggregate risk correctness or single-writer coordination.
- **Assume shared portfolio features exist because the backtest engine supports portfolios:** Research and live execution guarantees are distinct.

## Consequences

- The minimal first deployment uses the native `LiveEngine -> SafeBroker -> trading-connector adapter -> broker` path.
- Check official installed APIs and exercised tests before declaring any native feature supported.
- Treat same-account multi-strategy capital allocation, internal netting, and centralized execution as explicitly out of scope for the initial deployment, not implementation commitments.
- Keep research authorization, deployment permission, and account execution state separate.

## Approved initial operating choices

- Q2: One native ML4T execution/risk owner per broker account; no concurrent engines on the same account.
- Q3: Begin with a verified simulated paper account rather than requiring another shadow-mode phase. This is approval of the validation *mode*, not authorization to place orders from this research discussion.
- Q4: Monitor native ML4T runtime/risk/reconciliation/order health and VPS health through Grafana/Prometheus. Defer custom performance analytics.
- Q5: Enable ML4T's own bounded recovery for feed silence/disconnects. The installed default is up to three attempts separated by five seconds of recovery cooldown; `feed_silence_seconds` must be configured for feed-silence detection. Exhaustion stops the runtime; it must not trigger uncontrolled external restarts.
- Q7: **A** — fail closed on broker-versus-persisted-state reconciliation mismatch. Set `fail_on_reconciliation_mismatch=True`, which is **not** enabled by default in installed 0.1.2. Require a clean snapshot or documented operator resolution before resuming orders, including after native recovery.
- Q8: **A** — require independently verifiable paper-trading execution evidence and a predeclared observation window/gates before considering live promotion. This approval sets qualification policy, not the specific observation duration, pass thresholds or any live-order permission.
- Q9: **A** — configure native `LiveRiskConfig` limits explicitly for each strategy and account. Defaults are not an approved universal risk budget; size/cost/venue-specific values are chosen when a particular strategy is prepared for paper deployment.

**Provider qualification and Bybit correction (official API docs verified 2026-10-15):** Bybit Demo Trading uses `https://api-demo.bybit.com` and private `wss://stream-demo.bybit.com`; public market data is mainnet. Bybit Testnet instead uses `https://api-testnet.bybit.com`. The Bybit connector has since been updated to support explicit `DEMO` settings, separate Demo credentials, CCXT `enable_demo_trading(True)`, and ML4T paper assertions. The 43 credential-free Bybit connector tests pass on 2026-10-15, but authenticated Demo connectivity and actual Demo order lifecycle remain unverified. The earlier proposal to substitute Bybit Testnet for Bybit Demo was incorrect. Hyperliquid's paper assertion targets its testnet. Propr explicitly rejects `assert_paper_trading()` because its challenge accounts cannot be considered paper-only. Any selected venue/account requires verified identity, supported API paths, preflight, risk configuration and feed semantics. No network order placement is authorized by this ADR.

Official references: https://bybit-exchange.github.io/docs/v5/demo ; https://bybit-exchange.github.io/docs/faq ; https://www.bybit.com/en/help-center/article/FAQ-Demo-Trading .

## Architecture closeout; deployment qualification remains open

No further architecture-decision nodes remain in this grill. The initially proposed custom execution gateway, cross-strategy netting service, and centralized risk microservice are explicitly out of scope. The accepted design is native `LiveEngine -> SafeBroker -> trading-connector adapter -> broker`, one owner per account.

The selected first validation environment is Bybit Demo Trading. Its connector supports Demo configuration in code and has passed credential-free tests, but operational qualification remains **UNVERIFIED** until an authenticated read-only preflight, account/position/order reconciliation, complete Demo order/fill/cancel evidence, and bounded recovery/risk drills have been observed. The paper observation window and numerical strategy-specific native risk limits are operating-plan parameters to freeze before validation; they are not a reason to reopen the architecture grill.

No change to this ADR alone grants permission to place Demo or real-money orders, makes the connector production-ready, or establishes that Grafana/Prometheus has been deployed.

Related: [research glossary](../../CONTEXT.md), [run permits](0003-research-run-permit.md), [market scope](../architecture/market_scope_policy.md).
