# Issue #45 — Native ML4T paper execution and risk configuration

**Status:** credential-free implementation and synthetic tests only. **NOT AUTHORIZED for Demo/network orders or Mainnet.** Issue #44 authenticated Demo read-only preflight remains unverified.

## Contract
- One pre-existing `ml4t.backtest.Strategy` object is passed unchanged to native `LiveEngine`. No separate live strategy implementation.
- Native `LiveEngine -> SafeBroker -> BybitLiveBroker` owns lifecycle, risk, order validation and persistence; no new gateway, portfolio risk service or custom execution loop.
- `src/bybit_paper_runtime.py` exposes only `ReviewedPaperAccount`, `make_native_risk()` and `build_native_paper_engine()`. They configure but **do not connect**, run or submit anything.
- All numeric limits, a reviewed strategy identifier, Bybit Demo UID, venue-qualified asset allowlist, and durable private state directory are required. No material `LiveRiskConfig` default is silently accepted.
- An account-scoped native risk-state file (`bybit-demo-account-<UID>.json`) is shared by all strategies on the same account. `SafeBroker` obtains the exclusive native writer lease: a second simultaneous owner fails. Preserve the state and journal, do not delete them to bypass a lock or reconciliation mismatch. This is per-path local locking; it **does not** coordinate different VPS machines or protect against manually choosing a different state directory. Operators must provide one canonical state directory per broker account.
- Demo identity, dedicated credentials and expected UID are checked on construction; **only** `BybitClient` authenticated Demo checks at connect can prove the selected account. Mainnet and read-only connector modes are rejected for execution construction.
- `execution_mode="paper"`, native strict reconciliation/journal safeguards, feed-silence threshold and native bounded recovery are set. No flatten on disconnect.

## Qualification protocol
1. Independently complete [issue #44 read-only preflight](bybit_demo_preflight.md) on the identified Demo account. No orders.
2. Have the operator explicitly review every field in `ReviewedPaperAccount` for a specific qualified strategy, intended symbols and account. A `reviewed=True` flag is an operator assertion, not proof of authorization.
3. Provision an existing 0700 private canonical state directory **outside both repositories**, preserving audit state. Never commit UID, keys, balances, or journal files.
4. Run only synthetic tests under `quant-research/.venv` for this issue:

```bash
cd /home/quant/dev/quant/quant-research
PYTHONPATH=/home/quant/dev/trading-connector \
  .venv/bin/python -m pytest -n 0 -q \
  tests/test_bybit_paper_runtime.py tests/test_bybit_demo_preflight.py \
  /home/quant/dev/trading-connector/connectors/bybit/tests
```

## Verification boundary
Tests create synthetic paper orders **only against mocked provider methods** and assert native strategy callback delivery, risk rejection, duplicate protection, Mainnet denial and account writer exclusivity. They do not prove authenticated Bybit Demo connectivity, remote fills, cancel/replace/restart recovery or paper account qualification. Real order/fill/cancel drills are independently gated by issue #43 and are not authorized under issue #45.
