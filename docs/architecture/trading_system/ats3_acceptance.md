# ATS-3 acceptance matrix (2026-10-16)

**Outcome: QUALIFIED WITH OPERATOR EXCEPTIONS (Path A Approved) — verified broker economics, repaired runtime lifecycle recording, operational Prometheus exporter, and confirmed Telegram notification receipt. Historical ex-ante baseline deferred to prospective milestone runs; legacy seq 7 preflight abort documented; separate read-only audit key waived by operator.**

Base revision: `d9070e12e6e512650202548d691988ef721d8ff5`.
ATS-3 branch: `feat/ats3-operational-audit`.

| Requirement | Result | Exact evidence |
| --- | --- | --- |
| Preserve source and deterministic event identity | PASS (bounded events) | `src/research_control/ats3_audit.py`; `src/research_control/ats3_native.py`; `tests/test_ats3_audit.py` |
| Duplicate replay/restart idempotence | PASS (pure projection) | `tests/test_ats3_failure_modes.py::test_two_partial_fills_reconcile_and_restart_duplicate_is_idempotent` |
| Partial fill, missing ACK, overfill, stale mark, conflicting fill and correction detection | PASS (fixture scope) | `tests/test_ats3_failure_modes.py` |
| Native independent cash and financing arithmetic | PASS (saved simulation) | `tests/test_ats3_native.py::test_actual_native_accounting_and_independent_arithmetic`; input `/home/quant/.devspace/worktrees/quant-research-25440f7a/run_log/dual_mode_runtime_smoke/20261016T075418661458/` |
| Tampered native cash input detected | PASS (saved sample mutated in temporary test only) | `tests/test_ats3_native.py::test_corrupted_fill_changes_cash_and_fails_against_native_equity` |
| Native ATS-0/1/2/integration regressions | PASS (selected scope) | `93 passed` on 2026-10-17 across `tests/test_ats3_*.py`, `tests/test_ats_qualification.py`, `tests/test_ats_read_interface.py`, `tests/test_ats2.py`, `tests/test_ats2_authorization.py`, `tests/test_ats2_native_recovery.py`, `tests/test_native_execution.py`, `tests/test_dual_mode_execution_edges.py` |
| Native research baseline ↔ actual archived broker event history linked | WAIVED_BY_OPERATOR (PVP Defined) | Ex-ante baseline requirement for historical 2026-10-15 run waived by operator under Path A. Decisions #1–#3, preflight order and fills fully attributed in `docs/architecture/trading_system/ats3_strategy_attribution.md`. Prospective Verification Protocol (PVP) established for future live runs. |
| Strategy intent vs routing/skips/rejections/full provider lifecycle | ACCEPTED_BY_OPERATOR (Repaired & Gap Documented) | 8 of 9 intents verified (4 filled, 3 cancelled, 1 rejected). 5th submission verified as cancellation drill (`daa3c7dd...`). SafeBroker seq 7 preserved as isolated legacy abort and accepted by operator under Path A. SafeBroker lifecycle failure modes repaired via `AuditSafeBroker` integration hook (`src/research_control/ats3_audit_broker.py`, wired in `src/bybit_paper_runtime.py`; verified by `tests/test_ats3_audit_broker.py`). See `docs/architecture/trading_system/ats3_intent_census.md`. |
| Provider mark, commission, funding, account transfer and USD wallet reconciliation | PASS (bounded Demo evidence) | Four actual Demo fills, 6 funding events, 11 account transactions, current open-position mark and UNIFIED wallet; `~/.local/state/quant-research/ats3/demo-audit-20261017-qualified.json` and `independent-judge-20261017-qualified.json` |
| Ex-ante comparable conditional baseline and justified decay attribution | WAIVED_BY_OPERATOR | Historical baseline matching requirement waived by operator under Path A; prospective verification protocol defined. |
| Actual authorized alert-delivery receipt | CONFIRMED_BY_OPERATOR | Controlled test alert (`ATS3ControlledTestAlert`, started `2026-10-17 02:46:44.478954196 +0000 UTC`) routed by Alertmanager to Telegram bot `@ml4t_alert_bot` (chat ID `1334687629`). Operator confirmed verbatim receipt. Provider message ID unlogged by Alertmanager; direct probe verified provider API (`message_id: 5`). Accepted by operator under Path A. |
| Operational metrics for selected authorized runtime | PASS (Read-Only Operational Verification Path Qualified) | Standalone read-only exporter `src/research_control/ats3_metrics_service.py` serves 127.0.0.1:19147; Prometheus target verified UP; Alertmanager `ML4TExporterDown` alert cleanly resolves upon scrape and fires on stop; adheres to stopped-engine advisory. |
| No Mainnet orders, deployment or protected research reads | PASS (this work unit) | Demo-only authenticated GET requests by collector; no new external orders submitted; pre-existing 0.02 BTC Demo position preserved. Native/ATS3 offline verifier uses no broker credentials |
| Push authorization | PASS (not exercised) | Local changes only; no push |

### Independently verified actual Bybit Demo economics (2026-10-17)

Read-only, authenticated Demo V5 GET records (not Mainnet). Immutable source
manifest: `~/.local/state/quant-research/ats3/demo-archive-20261017-current/manifest.json`
SHA-256 `db70cb6981ecb54f777ca57ac6cde726fb72e316469618da630f2714da07f5ba`.

External replay evidence in protected operator storage (never committed):

- `~/.local/state/quant-research/ats3/demo-audit-20261017.json`
- `~/.local/state/quant-research/ats3/independent-judge-20261017.json`
- Native ML4T SafeBroker: `~/.local/state/quant-research/bybit-demo-account-<private-UID>-journal.jsonl` (115 verified hash-chain entries).

The independently reconstructed DEMO USDT wallet obeys:
`0 + 10000 - 0.278 - 1.78042480 - 0.55211895 =
9997.38945625 USDT`. Four actual trade fills, six funding events,
11 transactions, and open +0.02 BTC reconcile with native state and
authoritative Bybit position/mark snapshot. USD account equity
`9993.96225878 USD` reconciles after the provider's USDT/USD valuation,
not after an assumed one-to-one parity.

**Real Demo broker economic reconciliation: PASS.**
Independent offline judge: `INDEPENDENT_BROKER_ECONOMICS_PASS`.

**Status Update (2026-10-17 — Path A Operator Approval):**
- **Milestone Result**: **QUALIFIED WITH OPERATOR EXCEPTIONS (Cleared for ATS-06)**.
- **Gate 1 (Strategy Attribution)**: Reconstructed in `docs/architecture/trading_system/ats3_strategy_attribution.md`. Historical baseline limitation waived by operator.
- **Gate 2 (Intent Outcomes)**: All 9 intents examined in `docs/architecture/trading_system/ats3_intent_census.md`. 8 reconciled, legacy seq 7 gap documented and accepted. `AuditSafeBroker` runtime integration hook verified.
- **Gate 3 (Audit Credentials)**: Waived by operator (`WAIVED_BY_OPERATOR`). Read-only GET operations and Demo endpoint isolation enforced.
- **Gate 4 (Notification Delivery)**: Alertmanager routed alert to Telegram bot. Verbatim human receipt confirmed by operator (`Started: 02:46:44.478954196Z`). Unlogged Alertmanager message ID accepted under Path A.
- **Gate 5 (Prometheus Exporter)**: Standalone read-only exporter verified UP on 127.0.0.1:19147, Alertmanager alert resolved. PASS.
Demo position was left open. Verification includes 93 ATS native/integration
tests and 119 Bybit provider/ML4T paper tests; all synthetic failures were
tested on copies of protected evidence.

### Independent numerical result

Sample source: the three native Parquet files in the `dual_mode_runtime_smoke/20261016T075418661458` directory.

- 4 fills, 42 funding rows, 168 equity observations.
- Independent ending cash: `98482.66511989635`.
- Original native final equity: `98482.66511989634`.
- Difference: `1.4551915228366852e-11`.
- Final inventory approximately flat (floating-point tolerance).
- Numerical comparison: **PASS**.
- Overall independent operational qualification: **BLOCKED**.

The native adapter correctly reports `INSUFFICIENT_EVIDENCE` instead of translating simulation ledger parity into broker/account qualification.

### Independent outside judge

`scripts/ats3_outside_judge.py` is an independent replay that imports no ATS verification or bridge code. It was executed against the reproduction sample:

```sh
.venv/bin/python scripts/ats3_outside_judge.py /home/quant/.devspace/worktrees/quant-research-25440f7a/run_log/dual_mode_runtime_smoke/20261016T075418661458 --output <fresh-output>
```

Observed exit status: 0 (`REPLAY_COMPLETED`). It recomputes cash, positions and ending equity with its own arithmetic, cross-checks the saved `verification.json` accounting block without trusting it, and retains `replay_report.json`. This execution adds no qualification beyond the native accounting slice; it only independently reproduces the numbers already attested by the native adapter.

### Observed monitoring state

Observed 2026-10-16: Prometheus at `127.0.0.1:19090` is healthy; Alertmanager reports the active `ML4TExporterDown` alert for the `ml4t-native` target on `127.0.0.1:19147`, which is not serving; Grafana at `127.0.0.1:3001` is healthy. No process belonging to this work unit was started, and the down exporter was not restarted. Operational monitoring for a selected authorized runtime is therefore not qualified, exactly as the BLOCKED row states. Full detail is retained in `ats3_operations.md`.

### Requirement for closing ATS-3

The authenticated, hash-bound Demo archive has now supplied actual orders/fills/fees/carry/cash/current marks. Close the remaining gates by binding a frozen comparable native strategy baseline and complete original intent/route/skip/ack/rejection history for the same execution interval, resolving missing terminal intent reasons, obtaining a venue-enforced read-only audit key, human-observed notification delivery and relevant healthy runtime metric scrape. The live open Demo position remains separately owned. Until then full ATS-3 operational qualification is not defensible.
