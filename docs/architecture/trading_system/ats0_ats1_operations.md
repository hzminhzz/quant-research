# ATS-0 / ATS-1 read-only operating interface

Implementation scope: `src/research_control/agent_interface.py` and `src/research_control/job_inspector.py`.
This is an additive metadata projection over Git, the hash-chain trial ledger, stage receipts, and Linux process/tmux inspection. It is not a new trial store, permission authority, job scheduler, holdout reader, or broker adapter.

## Commands

From repository root:

```sh
.venv/bin/python -m src.research_control.agent_interface capabilities --root .
.venv/bin/python -m src.research_control.agent_interface inspect_case --root . --limit 10
.venv/bin/python -m src.research_control.agent_interface inspect_case --root . --candidate CANDIDATE_ID
.venv/bin/python -m src.research_control.agent_interface read_evidence --root . --reference dual_mode/CANDIDATE/ATTEMPT/casefile.json
.venv/bin/python -m scripts.benchmark_ats_cold_start --root . --samples 5
.venv/bin/python -m scripts.benchmark_ats_cold_start --fixture-corpus --samples 5
```

All entrypoints are strictly read-only. The evidence reader accepts only registered factory casefiles inside `run_log/dual_mode`; protected-result Casefiles (`HOLDOUT_EVALUATED` or `holdout_access: true`) are denied and redacted. Stage statuses are projected and cryptographically cross-checked against receipts, not certified as independent numerical evidence. Missing, tampered, stale, or conflicting artifacts fail closed to `BLOCKED`. Its result does not authorize deployment, development compute, broker orders, or protected-history access.

## ATS-0 authority map

| Authority | Actual location | Mechanism / Scope | Limitation |
| --- | --- | --- | --- |
| Code / dirty state | Local Git worktree | `git status --porcelain=v1 -uall`, `git rev-parse HEAD` | Tracks tracked and untracked changes in local checkout; non-atomic with filesystem |
| Current factory research | `run_log/trial_ledger.jsonl` | Cryptographic SHA-256 hash-chain verification from root `"0"*64` | Research status ledger; does not confer execution or broker authority |
| Factory Casefile | `run_log/dual_mode/<candidate>/<attempt>/casefile.json` | Streaming SHA-256 byte digest (`_integrity`) matches ledger; payload not decoded | Validates storage integrity without loading high-volume or protected arrays |
| Stage receipts & evidence | `run_log/dual_mode/<candidate>/<attempt>/stage[1-3].json` | Small JSON receipts with `receipt_hash` digest; stage evidence files SHA-verified | Cryptographic integrity only; does not recompute numerical statistics |
| v1 research Casefile | `src/research_control/casefile.py` | Compatibility adapter; read-only projection | Separate legacy entrypoint |
| Protected boundary | `src/data_vault/vault.py` | Stage 4 explicitly marked `FORBIDDEN` / `REDACTED`; holdout outcomes denied | Not opened or decrypted by ATS |
| Jobs & Processes | tmux panes + Linux `/proc/<pid>/` | Pane PID, state, `stat` start ticks, `comm`, UID match, v1 AttemptLedger lease & checkpoint | Does not infer worker completion from session existence or pane PID alone |
| Broker / live state | External connectors | Not inspected; reported `NOT_EXPOSED` / `NOT_VERIFIED` | Zero live-order or paper-trading authority |
| Approval | External human / gate authority | Static `approval: NOT_GRANTED`, `permissions: {broker_orders: False, ...}` | No ATS-0/1 ability to mint permissions |

Legacy `scripts/research.py` and native `scripts/quant.py` retain their existing status semantics. Do not interpret `FALSIFIED_STAGE_2` as a runtime failure or an unexecuted Stage 3 as a passing test.

## ATS-1 decision inspection contract

1. **Large Casefile Handling**: Large Casefiles (>256KB) are verified via streaming SHA-256 digest against the ledger without decoding their bulky JSON payload. Stage receipts (`stage1.json`, etc.) supply the verified per-stage status.
2. **Read-Budget Enforcement**: `read_evidence` enforces an explicit serialized response budget (256B to 64KB, default 16KB). Exceeding budget raises `RESPONSE_BUDGET_EXCEEDED` rather than leaking large payloads.
3. **Fail-Closed Verification**: Any discrepancy—tampered receipt, contradictory terminal stage, mtime after ledger registration (>60s), unverified worker done, missing artifact, or expired lease—sets status to `BLOCKED` with specific reason codes in `unknowns` and `unknown_summary`.
4. **Pagination & Bounded Frontier**: Both research attempts and job listings support offset-based pagination with `omitted` counts and `next_cursor`. Omitted evidence is explicitly flagged in unknowns (`OMITTED_EVIDENCE_NOT_VERIFIED`).
5. **Job Reconciliation**: Jobs observed in tmux are reconciled against v1 attempt ledger leases and SHA-verified checkpoints. Expired leases, stale checkpoints (>1800s), invalid hashes, conflicting session ownership, or unverified processes are flagged and fail closed to `BLOCKED`.

## Benchmark: first-correct-action effort

`scripts/benchmark_ats_cold_start.py` measures triage effort between the raw multi-step baseline (reading Git status, README, trial ledger, casefile, and receipts across multiple tool calls) versus the unified ATS read API (`inspect_case`):

- **Synthetic Fixture Corpus (10 cases)**:
  - Covers: clean rejection, large casefile, conflicting docs, missing artifact, corrupt artifact, contradictory stage, stale source, stale worker checkpoint, worker done without completion, holdout redaction.
  - **Managed ATS API**: 10/10 correct first actions (100%), 1 tool call per triage, ~4KB-14KB context.
  - **Baseline**: 9/10 correct (fails on large/conflicting evidence), 9-25 tool calls per triage, up to 34MB+ context.
  - Deterministic gold decisions defined before timing execution.

- **Real Repository Metadata Benchmark**:
  - Validates read-only execution against actual worktree and trial ledger.
  - Reduces tool calls from 25 to 1 and context payload from ~34.6MB to ~14.6KB.

## Qualification status: COMPLETE (ATS-0 / ATS-1)

All acceptance criteria for ATS-0 and ATS-1 are verified and qualified:

1. **Locatable Sources & Tested Tools**: `capabilities` returns explicit file existence, hashes, and tool status for Git, trial ledger, tmux process inspection, worktree metadata, and ML4T packages (`ml4t-engineer`, `ml4t-diagnostic`, `ml4t-backtest`).
2. **Zero Protected Outcome Leakage**: Protected partitions and holdouts are denied in `read_evidence` and redacted in `inspect_case`.
3. **Cryptographic Integrity Over Claims**: No stale doc or headline overrides ledger/receipt hash verification.
4. **Adversarial & Regression Test Coverage**: 42/42 passing tests in `tests/test_ats_read_interface.py`, `tests/test_ats_qualification.py`, `tests/test_casefile.py`, `tests/test_casefile_cli.py`, and `tests/test_attempts.py`.
5. **Linting & Hygiene**: Ruff clean (0 errors, 0 warnings).
6. **Benchmark Validation**: 10/10 synthetic benchmark fixtures pass (`all_critical_correct: true`).

### Explicit non-goals (deferred to ATS-2+)

- ATS-2: Bounded action and recovery contract (`prepare/start/observe/verify`), worker process launching/stopping, lease renewal.
- ATS-3: Execution evidence bridge and operational trade intent audit.
- ATS-6 / ATS-7: Broker execution, order routing, paper or live trading authority.
