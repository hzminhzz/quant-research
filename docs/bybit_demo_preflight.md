# Bybit Demo read-only ML4T preflight (issue #44)

**Scope:** operator-controlled **read-only** Bybit Demo account inspection. This is not
a paper-trading qualification, order authorization, or deployment of a trading engine.
The authoritative implementation uses installed `ml4t-live==0.1.2` and
`SafeBroker.preflight_async()`; Bybit transport belongs to `trading-connector`.

## Prerequisites

1. In Bybit **Demo Trading**, identify the Demo account's UID independently
   from its account UI. It is **not** the Mainnet UID or Bybit Testnet UID.
2. Create a separate Demo API key and secret **in Demo Trading**, preferably
   with read-only permissions. Keep all credentials in your local environment or
   secure operator secret store, never in this repository or command-line flags.
3. Set `BYBIT_ENVIRONMENT=demo`, `BYBIT_MODE=read_only`,
   `BYBIT_DEMO_API_KEY`, `BYBIT_DEMO_API_SECRET`, and
   `BYBIT_DEMO_EXPECTED_UID` to the independently observed Demo UID.
   The command will not fall back to `BYBIT_API_KEY/SECRET`.
4. Choose the durable, exclusive ML4T native risk-state path for this account.
   Put it **outside both source repositories**, on protected storage. Preserve
   the state and its accompanying audit journal; do not delete/reinitialize
   state to bypass a reconciliation mismatch.
5. Run against the checked `ml4t-live==0.1.2` virtual environment in
   `quant-research/.venv`. The two VPS checkouts must be present.

## Run

From `/home/quant/dev/quant/quant-research`, with the Demo environment
variables supplied **outside git**:

```bash
umask 077
PYTHONPATH=/home/quant/dev/trading-connector \
  .venv/bin/python -m scripts.bybit_demo_preflight \
  --state-file /home/quant/.local/state/quant-research/bybit-demo-risk.json \
  --evidence-file /home/quant/.local/state/quant-research/bybit-demo-preflight-001.json
```

This runs **native `SafeBroker.preflight_async()`** in
`execution_mode="paper"`, `fail_on_reconciliation_mismatch=True`,
`fail_on_journal_error=True`, with a `BybitLiveBroker` and a *READ_ONLY*
Bybit client. It reads authenticated key/account information, UNIFIED wallet
totals, all supported position/order pages and native reconciliation/persistence
status, then disconnects. No strategy, engine, remote order creation, amendment,
cancellation, flattening or test order runs.

Outputs a JSON status to stdout. Optional local evidence JSON is created once,
mode `0600`; it contains only a whitelisted identity/endpoint attestation,
USD account equity and available balance, position/pending counts,
reconciliation discrepancy counts, persistence statuses, and no UID, key, order
ID, symbols, or raw broker response. **USD totals remain private financial
information**, so do not commit/upload this file; the operator must secure it.
An existing evidence filename is not overwritten.

`PASS` (exit 0) means the *read-only snapshot* was authenticated against the
explicit Demo UID, native preflight returned clean reconciliation, and persistence
and unknown-intent checks did not block. It is **not** evidence that remote orders
work and **never grants live-money authorization**.

`BLOCKED` (exit 2) means no valid read-only preflight was established.
Missing dedicated Demo key/secret/UID, Mainnet/Testnet identity, incorrect
endpoint, missing/unsupported V5 fields, active unsupported instruments/hedge
positions/orders, nonempty broker exposure absent from persisted state, unknown
intents, and state/journal failures are blockers. Do not work around them by
switching environment or resetting state. The report shows discrepancy counts
without exposing account identifiers. Detailed exceptions are redacted.

## Contract and bounds

- **Private Demo REST:** `https://api-demo.bybit.com`; authenticated
  `GET /v5/user/query-api`, `/v5/account/info`,
  `/v5/account/wallet-balance?accountType=UNIFIED`,
  `/v5/position/list`, and `/v5/order/realtime?openOnly=0`.
- **Public market data:** Mainnet (separate `BybitKlineFeed`);
  no market-data feed is required for this preflight.
- **Account equity:** `totalEquity` USD; available balance:
  `totalAvailableBalance` USD (margin availability, **not withdrawable cash**).
  Do not sum coin balances to represent UNIFIED equity.
- **Position/order coverage:** paginated linear USDT/USDC swaps. Other active
  derivatives, spot/options/inverse orders and hedge/conditional orders cannot
  silently disappear into an empty snapshot: unsupported or malformed active
  records **BLOCK**. If an endpoint is unsupported in the selected Demo account,
  this is a **BLOCKED** result, not evidence of zero positions/orders.
- **Read-only boundaries:** operator configuration requires `read_only`, and
  the Bybit connector disallows remote mutation for both read-only and shadow
  modes. The native preflight does not invoke remote order mutation methods.
  Even if a key has trading permissions, this command has no order path.
- **Credentials:** the provided Demo key and expected UID must agree with the
  authenticated API-key response on the Demo host; only boolean match evidence
  is printed. Testnet is not a substitute for Demo.

Bybit official sources: [Demo Trading](https://bybit-exchange.github.io/docs/v5/demo),
[API-key info](https://bybit-exchange.github.io/docs/v5/user/apikey-info),
[Wallet Balance](https://bybit-exchange.github.io/docs/v5/account/wallet-balance),
[Positions](https://bybit-exchange.github.io/docs/v5/position),
[Open Orders](https://bybit-exchange.github.io/docs/v5/order/open-order).

## Verify without credentials

```bash
cd /home/quant/dev/quant/quant-research
PYTHONPATH=/home/quant/dev/trading-connector \
  .venv/bin/python -m pytest -q \
  /home/quant/dev/trading-connector/connectors/bybit/tests \
  tests/test_bybit_demo_preflight.py
```

All fixtures are synthetic. They cover Demo/Testnet/Mainnet isolation,
Bybit V5 shape/field validation, native `AsyncBrokerProtocol` and
`SafeBroker.preflight_async()`, reconciliation mismatch and no remote mutation.
These tests do **not** prove a real Demo key/account works.

**VPS verification, 2026-10-15:** the original 43 provider tests still pass;
combined Bybit provider + operator tests: **63 passed** (two warnings:
upstream WebSockets deprecation and an existing feed-test unawaited coroutine).
Ruff reports **all checks passed** for the new/modified Python files.
Credential-free operator invocation with empty Demo variables returns the
expected JSON `BLOCKED` and `submitted_orders: 0`.

**Authenticated Demo preflight (2026-10-15):** authenticated Demo connectivity,
account identity validation, V5 UNIFIED wallet balance, position and pending order
snapshots, and native broker reconciliation were executed using dedicated Demo
credentials (`~/.config/trading-connector/bybit-demo.env`, mode `0600`).
The preflight returned **PASS** (`broker_connected_during_preflight: true`,
`clean: true`, `positions: 0`, `pending_orders: 0`, `submitted_orders: 0`).
Redacted execution records are preserved in `/home/quant/.local/state/quant-research/bybit-demo-preflight-001.json`
and `002.json` (mode `0600`) outside both repositories.
