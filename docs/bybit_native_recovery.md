# Issue #46 — Native bounded recovery and fail-closed reconciliation

**Status:** credential-free deterministic fault-injection tests PASS with installed
`ml4t-live==0.1.2`. **Not** an authenticated Demo qualification or order authorization.

## Ownership and settings

- Use the existing `LiveEngine -> SafeBroker -> BybitLiveBroker` path.
  Do **not** add a retry supervisor, watchdog process, custom risk store,
  auto-flatten routine, or unmanaged direct broker fallback.
- `ReviewedPaperAccount` requires reviewed positive
  `max_recovery_attempts`, `recovery_cooldown_seconds`,
  `feed_silence_seconds`, and `max_event_age_seconds`. The factory passes
  both recovery values explicitly to native `LiveEngine`.
  Review these for each account/strategy before connection.
- For `BybitKlineFeed` (e.g. `timeframe="1m"`) the configured silence threshold
  **must exceed one complete bar period**; the operator must allow for expected
  delivery lag. A 5-second silence threshold is invalid for a 1-minute feed.
  The synthetic test overrides native health timing **only inside its fixture**
  to exercise failure branches without real-time waits.
- Native `SafeBroker` uses explicit `execution_mode="paper"`,
  `fail_on_reconciliation_mismatch=True`, and
  `fail_on_journal_error=True`. Account-scoped native state uses the same
  canonical private directory across all strategies on one account.
  `SafeBroker` has an exclusive local writer lease, **not** distributed
  cross-machine ownership.
- The Bybit adapter refuses position and pending-order reads when its
  provider is disconnected. This is important: after a failed reconciliation,
  native cleanup must **retain the last persisted snapshot** rather than
  accidentally replacing it with a snapshot from a disconnected provider.

## Native recovery path

1. The native watchdog detects `feed_silent` or `broker_disconnected`,
   or the feed terminates. It transitions to `degraded`.
2. The native engine performs reverse-order resource cleanup, emits recovery
   attempt events, waits the reviewed cooldown, then reconnects via the
   **same** `SafeBroker.connect()` and starts the same feed.
3. `SafeBroker.connect()` checks broker identity, state/journal availability,
   and persisted versus provider positions and pending orders. An unexpected
   position or order blocks the retry: `ReconciliationMismatchError`.
4. A successful native reconnect emits `engine_recovery_succeeded`. A
   cleanup error emits `engine_recovery_failed` (including cleanup results)
   and still consumes a bounded attempt.
5. When the reviewed attempt limit is reached, native
   `engine_recovery_exhausted` is emitted, the engine terminates in
   `runtime_state="failed"` with
   `terminal_failure_reason="recovery_exhausted:<reason>"`. There is no
   external infinite restart loop and no automatic position flattening.

Read-only evidence surfaces: `LiveEngine.runtime_status()`,
`LiveEngine.operational_events`, `LiveEngine.runtime_transitions`,
`SafeBroker.reconciliation_report`, and `SafeBroker.persistence_status`.
Store evidence in protected operator storage, never in Git; do not expose
identifying account/order snapshots as monitoring labels.

## Operator response to a failure

Inspect the native terminal status and broker/state reconciliation report.
**Do not** remove risk state, journals or lock files to clear a mismatch.
Preserve both provider order-intent journal and ML4T native state/audit journal.
Use authenticated **read-only** issue #44 inspection to independently determine
actual positions, pending orders, unknown submissions and a verified account
identity. A clean broker reconciliation or documented manual resolution is
required before any new paper session is authorized.

When recovery exhausts its finite budget, leave the engine stopped/failed,
capture the native recovery event sequence and the exact cleanup result, then
diagnose and explicitly restart only after the condition has been resolved.
Neither the paper runtime builder nor this test suite connects to a remote
account without a caller explicitly invoking its live methods.

## Credential-free verification

From `/home/quant/dev/quant/quant-research`:

```bash
PYTHONPATH=/home/quant/dev/trading-connector \
  .venv/bin/python -m pytest -n 0 -q \
  tests/test_bybit_native_recovery.py \
  tests/test_bybit_paper_runtime.py \
  tests/test_bybit_demo_preflight.py \
  /home/quant/dev/trading-connector/connectors/bybit/tests
.venv/bin/python -m ruff check \
  src/bybit_paper_runtime.py \
  tests/test_bybit_native_recovery.py tests/test_bybit_paper_runtime.py \
  /home/quant/dev/trading-connector/connectors/bybit/broker.py
```

**2026-10-15:** 96 tests passed; Ruff clean. Tests exercise feed silence,
broker disconnect, successful bounded reconnect, failed cleanup, restart
exhaustion, unmatched positions/orders, clean reconnection, corrupt state,
corrupt audit journal, unwritable state directory, exclusive writer lease,
unknown submission retained across reconnect, and incomplete provider snapshots. The remote create/cancel/edit transport is
mocked; no remote orders occur. Pytest reports upstream/library warnings,
including WebSockets deprecation and an existing unawaited coroutine in an
older feed test.

## Remaining separate gates

- Issue #44's authenticated Demo account preflight has not been verified.
- Issue #45's complete paper execution acceptance (including cancel/replace
  races and rejected outcomes) remains separate.
- No real Demo order/fill/cancel, production alert delivery, host fault drill
  or paper observation window has been completed. They require separate
  authorization and later issues under parent #43.
- These synthetic proofs **do not** authorize live-money trading.
