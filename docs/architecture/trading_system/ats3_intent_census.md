# ATS-3 Gate 2: Intent & Lifecycle Disposition Census

## 1. Intent Census (All 9 Historical SafeBroker Intents)

| SafeBroker Sequence | Causal Timestamp (UTC) | Asset & Order Parameters | SQLite Intent ID & Timestamp | Status / Outcome | Verified Disposition |
|:---:|:---:|:---|:---|:---|:---|
| **seq 4** | 2026-10-15 06:14:04.150 | BTC/USDT:USDT Buy 0.001 Limit @ 50000.0 | `01M4Z34H3TSP14Y7S25XH51F47` (06:14:04.154) | Exchange Rejected | **REJECTED** (`Insufficient funds: InsufficientFunds` prior to account transfer) |
| **seq 7** | 2026-10-15 06:16:46.177 | BTC/USDT:USDT Buy 0.001 Limit @ 50000.0 | *None in SQLite* | Engine restart / pre-check abort | **UNKNOWN** (Isolated historical incident: aborted before SQLite intent persistence; preserved as unverified) |
| **seq 10** | 2026-10-15 06:20:20.798 | BTC/USDT:USDT Buy 0.001 Limit @ 50000.0 | `01M4Z3G0Y29F99FYD2N6NV8X8B` (06:20:20.802) | Provider Order `95e6c7cd...` | **CANCELLED** (Verified cancelled on Bybit Demo via SQLite audit seq 6) |
| **seq 13** | 2026-10-15 06:21:46.172 | BTC/USDT:USDT Buy 0.001 Limit @ 50000.0 | `01M4Z3JMA1HFJMSAZGMCEWGQWP` (06:21:46.177) | Provider Order `39044a7b...` | **CANCELLED_ON_PROVIDER** (Verified cancelled on Bybit Demo via SQLite audit seq 9) |
| **seq 16** | 2026-10-15 06:25:35.089 | BTC/USDT:USDT Buy 0.001 Limit @ 50000.0 | `01M4Z3SKVP4KVQBRZFMM3AZY8K` (06:25:35.094) | Submission #1 (seq 17): `daa3c7dd...` | **DRILL_ORDER_CANCELLED** (Scripted order cancel drill, cancelled seq 19, reconciled seq 23) |
| **seq 93** | 2026-10-15 07:11:05.345 | BTC/USDT:USDT Buy 0.01 Market | `01M4Z6CY4856JA4GYTQE6YECN8` (07:11:05.352) | Submission #2 (seq 94): `a98518a2...` | **FILLED** (Preflight order filled @ 80,882.3 USDT) |
| **seq 108** | 2026-10-15 07:12:05.670 | BTC/USDT:USDT Sell 0.01 Market | `01M4Z6ES1E6CWM4SGY4RKHZ4QH` (07:12:05.678) | Submission #3 (seq 109): `5cb2ac55...` | **FILLED** (Decision #1 filled @ 80,854.5 USDT) |
| **seq 110** | 2026-10-15 07:16:05.197 | BTC/USDT:USDT Buy 0.01 Market | `01M4Z6P2YHMJ6STXK0BFH7MFWX` (07:16:05.201) | Submission #4 (seq 111): `5af29df4...` | **FILLED** (Decision #2 filled @ 80,978.8 USDT) |
| **seq 112** | 2026-10-15 07:17:05.706 | BTC/USDT:USDT Buy 0.01 Market | `01M4Z6QY1M3YP180CWTGWD411A` (07:17:05.716) | Submission #5 (seq 113): `a7619836...` | **FILLED** (Decision #3 filled @ 80,998.0 USDT) |

---

## 2. Submission Census (All 5 Historical SafeBroker Submissions)

1. **Submission #1 (`daa3c7dd-c40c-450d-b2f6-5f291e36bfd1`)**:
   - Order type: Buy 0.001 BTC Limit @ 50,000.0 USDT
   - Role: Scripted Order Cancellation Lifecycle Drill (`bybit-demo-order-lifecycle-drill-evidence.json`)
   - Lifecycle: Submitted seq 17 -> Cancel Requested seq 18/19 -> Reconciled cleanly seq 23
   - Explanation of Absence from Provider History: Bybit V5 linear order history API does not retain cancelled limit orders with 0 fills in standard multi-day queries. Its cancellation was confirmed in the session drill log.
2. **Submission #2 (`a98518a2-3b5b-40b1-bd5c-155026998bae`)**:
   - Buy 0.01 Market -> Filled @ 80,882.3 USDT. Present in Bybit `orders.json`.
3. **Submission #3 (`5cb2ac55-1af9-4a9b-8c56-3ddead79a708`)**:
   - Sell 0.01 Market -> Filled @ 80,854.5 USDT. Present in Bybit `orders.json`.
4. **Submission #4 (`5af29df4-16d8-47a6-a05e-adca2da666c9`)**:
   - Buy 0.01 Market -> Filled @ 80,978.8 USDT. Present in Bybit `orders.json`.
5. **Submission #5 (`a7619836-8d58-4026-89d6-906bfdc3aff5`)**:
   - Buy 0.01 Market -> Filled @ 80,998.0 USDT. Present in Bybit `orders.json`.

---

## 3. Lifecycle Recording Repair

To prevent future unrecorded terminal outcomes:
1. `BybitIntentJournal.mark_rejected(intent_id, reason)` added to persist explicit rejection states and audit events.
2. `BybitLiveBroker.submit_order_async` updated to distinguish clear rejections (insufficient funds, invalid parameters, permission errors) from ambiguous network drops. It calls `mark_rejected` immediately rather than leaving intents hanging in an unrecorded state.
3. `AuditSafeBroker` runtime integration hook implemented in `src/research_control/ats3_audit_broker.py` and wired into `src/bybit_paper_runtime.py`:
   - Pre-send risk and validation errors classified as `TERMINAL_REJECTION`.
   - Venue acceptance with persistence confirmation failure (`AcceptedOrderPersistenceError`) classified as `ACCEPTED_BUT_UNPERSISTED_DO_NOT_RETRY`.
   - Transport timeouts, in-flight exceptions, and task cancellations default strictly to `UNKNOWN_OUTCOME` (as orders may have executed on venue).
4. Verified by dedicated test suite `tests/test_ats3_audit_broker.py` (5 passing tests).
---

## 4. Causal Proximity & Historical Incident Accounting

- **Anti-Pattern Refuted**: Naive parameter matching would falsely allow `01M4Z3SK...` (06:25:35 drill intent) to explain seq 7 (06:16:46).
- **Causal Constraint**: Replay enforces strict 1-to-1 consumption and sub-2-second causal timestamp alignment.
- **Auditable Verdict**: Seq 7 is left genuinely **UNKNOWN** (`INTENT_TERMINAL_REASON_NOT_RECORDED`), preserving historical integrity.
- **Gate 2 Result**: **PARTIAL / EXPLAINED WITH PRESERVED HISTORICAL INCIDENT** (Every monitored trading session intent is accounted for; the preflight restart incident at 06:16:46 is retained as an unrecorded event).
