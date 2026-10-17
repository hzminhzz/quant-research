# ATS-3 acceptance matrix (2026-10-16)

**Outcome: NOT QUALIFIED — independently validated native accounting slice, incomplete operational audit.**

Base revision: `d9070e12e6e512650202548d691988ef721d8ff5`.
ATS-3 branch: `feat/ats3-operational-audit`.

| Requirement | Result | Exact evidence |
| --- | --- | --- |
| Preserve source and deterministic event identity | PASS (bounded events) | `src/research_control/ats3_audit.py`; `src/research_control/ats3_native.py`; `tests/test_ats3_audit.py` |
| Duplicate replay/restart idempotence | PASS (pure projection) | `tests/test_ats3_failure_modes.py::test_two_partial_fills_reconcile_and_restart_duplicate_is_idempotent` |
| Partial fill, missing ACK, overfill, stale mark, conflicting fill and correction detection | PASS (fixture scope) | `tests/test_ats3_failure_modes.py` |
| Native independent cash and financing arithmetic | PASS (saved simulation) | `tests/test_ats3_native.py::test_actual_native_accounting_and_independent_arithmetic`; input `/home/quant/.devspace/worktrees/quant-research-25440f7a/run_log/dual_mode_runtime_smoke/20261016T075418661458/` |
| Tampered native cash input detected | PASS (saved sample mutated in temporary test only) | `tests/test_ats3_native.py::test_corrupted_fill_changes_cash_and_fails_against_native_equity` |
| Native ATS-0/1/2/integration regressions | PASS (selected scope) | `70 passed` across `tests/test_ats3_*.py`, `tests/test_ats_qualification.py`, `tests/test_ats_read_interface.py`, `tests/test_ats2.py`, `tests/test_ats2_authorization.py`, `tests/test_ats2_native_recovery.py`, `tests/test_native_execution.py`, `tests/test_dual_mode_execution_edges.py` |
| Native research baseline ↔ actual archived broker event history linked | BLOCKED | Inspected local `/home/quant/dev/trading-connector/.ml4t_*journal.jsonl` show `execution_mode=shadow`, `shadow_mode=true` events, not independently observed broker execution. No matching authoritative execution bundle selected |
| Strategy intent vs routing/skips/rejections/full provider lifecycle | BLOCKED | Native fills export lacks transport and intent history; broker shadow journals are separate unrelated event paths |
| Provider mark, fee, financing and owner cash attribution | BLOCKED | No matched read-only provider account statement/mark stream with stable account binding |
| Ex-ante comparable conditional baseline and justified decay attribution | BLOCKED | No matched frozen baseline and broker observation path; `INSUFFICIENT_EVIDENCE` remains required |
| Actual authorized alert-delivery receipt | BLOCKED | No auditable human-received notification receipt found in inspected `run_log` paths; no new messages sent |
| Operational metrics for selected authorized runtime | BLOCKED | No qualified selected active audit runtime, no production scrape claimed |
| No live orders/deployment/holdout reads | PASS (ATS-3 implementation scope) | Read-only Parquet adapter and isolated unit/integration tests; no broker endpoint calls |
| Push authorization | PASS (not exercised) | Local changes only; no push |

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

An authorized, read-only, hash-bound archive for the **same** strategy version and execution period must contain intent/route/skips, actual orders/acks/rejections/partial fills, authoritative fees/carry/cash/marks, account/environment identifiers and a frozen comparable native baseline. Pair it with a human-observed notification receipt and the relevant operational scrape. Until then, the full operational qualification is not defensible.
