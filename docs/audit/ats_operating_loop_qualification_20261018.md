# ATS Post-Integration Operating Loop Qualification — 2026-10-18

**Verdict:** The ATS post-integration operating loop is **RESEARCH-QUALIFIED (development-only)**.
Live trading and external broker execution remain **BLOCKED / UNAUTHORIZED**.
Synthetic paper observation remains active under supervision and is not yet elapsed.

---

## 1. Exact Implementation & Commit Identities

- **Base commit**: `f2a6025253dc72ad531bad8968dd75bf053abb12` (`origin/main`, feat: Google Colab GPU remote trainer).
- **Task branch**: `feat/ats-operating-loop-20261018`
- **Reconciled commits**:
  - `84013226848a52a6800e0fbe7bf064dc96ff6210`: Admitted 62 nested thesis directories byte-identically from `origin/feat/ats-inbox-62-copy-20261018`.
  - Staging reconciliations: Admitted 42 additional captured flat/nested theses, completing a 112-candidate corpus with zero source tampering.
- **Touched modules & test suites**:
  - `src/research_control/casefile.py`: Added `BLOCKED_EXECUTION` next-safe action and terminal accounting.
  - `src/research_control/learning.py`: Enforced lesson retrieval strictly conditional on observed failure/error codes.
  - `src/research_control/research_inbox_queue.py`: Added `BLOCKED_EXECUTION` to `TERMINAL` and `TRIAL_TERMINAL`, version-aware reconsideration of `BLOCKED_PROTOCOL` / `BLOCKED_SPEC` / `BLOCKED_DATA` under code/data updates, and report counters.
  - `src/engine/spec_parser.py`: Added `'local_adaptation'` to `source_spec_status` enum.
  - `pyproject.toml`: Added `/home/quant/dev/trading-connector` and `.ci/trading-connector` to `pythonpath`.
  - `config/candidates/ats_crypto_xs_90d_high_anchoring_local_adaptation_20261018.yaml`: Formally declared cross-sectional candidate adaptation.

---

## 2. Capabilities Transition Matrix

| Capability | Previous Status | Current Status | Verification Proof |
| :--- | :--- | :--- | :--- |
| **Nested Thesis Intake** | `BLOCKED_HANDOFF` (schema rejection) | **ADMITTED** (62/62 nested, 111/112 corpus) | `InboxQueue.report()` confirms 111 admitted, 1 failing closed on missing brief URL anchor. |
| **Version Reconsideration** | Skipped permanently | **RECONSIDERED** | Pre-trial blocks re-evaluate when `runtime_identity()` changes. |
| **Casefile Semantics** | Collapsed into `BLOCKED_DATA` | **`BLOCKED_EXECUTION` preserved** | Casefile and trial ledger retain exact reason and stop-order remediation. |
| **Connector Import Isolation** | Broken on unexported `PYTHONPATH` | **NATIVE RESOLUTION** | Configured via `pyproject.toml` `pythonpath`. |
| **Bubblewrap Confined Worker** | Believed blocked by namespaces | **OPERATIONAL** | Direct verification: `isolated_features` and Stage 1 truncation checks execute. |
| **ATS-8 Lesson Retrieval** | Unconditional queries permitted | **FAILURE-CONDITIONAL** | Retrieval requires `error_code`, preventing instruction sprawl. |

---

## 3. Research Terminal Outcomes & Verified Evidence

Two defensible exemplars were evaluated through the native runtime without simulated shortcuts:

### A. Event Protocol Exemplar: `bta_nq_monday_bb10_atr5_cfd_v1`
- **Spec**: `config/candidates/bta_nq_monday_bb10_atr5_cfd_v1.yaml` (`BtaNqMondayEventSpec`).
- **Data**: Dukascopy `index_1h` NQ CFD proxy (`usatechidxusd`), 83,086 development rows (2012–2024).
- **Execution**: `scripts/quant.py run config/candidates/bta_nq_monday_bb10_atr5_cfd_v1.yaml --development-only`.
- **Outcome**: **`BLOCKED_EXECUTION`** (Exit Code 3).
- **Scientific Evidence**: Native `ml4t.backtest.Engine` stop-order execution adapter is unqualified for hourly Dukascopy CFD bars (intrabar quote depth and gap precedence unverified).
- **Ledger Record**: Completed trial appended to `run_log/trial_ledger.jsonl`.

### B. Cross-Sectional Exemplar: `ats_crypto_xs_90d_high_anchoring_local_adaptation_20261018`
- **Spec**: `config/candidates/ats_crypto_xs_90d_high_anchoring_local_adaptation_20261018.yaml` (`CandidateSpec`, `source_spec_status: local_adaptation`).
- **Data**: Binance hourly perpetual development panel (`[2020-04-01, 2026-01-01)`), 1,136,320 eligible rows, 3,975 periods across 484 symbols.
- **Execution**: `scripts/quant.py run config/candidates/ats_crypto_xs_90d_high_anchoring_local_adaptation_20261018.yaml --development-only`.
- **Stages Evaluated**:
  - Stage 1 (Prefix Invariance / Causal Truncation): **PASS**.
  - Stage 2 (Cross-Sectional IC & Diagnostic HAC): **`FALSIFIED_STAGE_2`** (Exit Code 0).
- **Diagnostic Metrics**:
  - Candidate 90d High-Watermark Rank: Mean IC = `+0.00510`, HAC SE = `0.02612`, HAC t-stat = `0.1951` ($p = 0.8453$). Fails minimum $t \ge 2.0$ gate.
  - Baseline 72h Momentum: Mean IC = `-0.04654`, HAC SE = `0.02150`, HAC t-stat = `-2.1645` ($p = 0.0305$).
- **Ledger Record**: Registered and completed trial appended to `run_log/trial_ledger.jsonl`. Holdout partition remained strictly sealed (`holdout_access: false`).

---

## 4. Benchmark Performance vs. Baseline

Ran `scripts/benchmark_ats8_learning.py` against 14 standard test fixtures (3 samples each = 42 total executions):

| Metric | Baseline Raw | Managed No-Learning | Managed With Learning |
| :--- | :---: | :---: | :---: |
| **All Critical Correct** | True | True | **True (14/14)** |
| **Median Tool Calls** | 107 | 18 | **33** |
| **Median Context Bytes** | 390,652 B | 56,489 B | **56,489 B** |
| **Stale Advice Rejection** | N/A | N/A | **100.0% (6/6)** |
| **Incompatible Version Rejection** | N/A | N/A | **100.0% (6/6)** |

---

## 5. Unresolved Scientific & External Dependencies

1. **Intraday CFD Stop Qualification**: Native `ml4t-backtest==0.1.7` requires an intrabar quote-depth and gap-execution adapter before single-instrument hourly stop breakout strategies (such as BTA NQ) can execute Stage 3.
2. **28-Day Paper Observation**: Background service `ats7-local-paper@observation-v1.service` (PID 300960) has run ~19 hours of its mandatory 28-day window (started 2026-10-17 06:38 UTC; earliest elapsed completion 2026-11-14 06:38 UTC).
3. **External Broker Authority**: Live trading, live account purchases, and mutating live order endpoints remain strictly barred.

---

## 6. Qualification Verdict

- **Research Qualification**: **QUALIFIED** (Four-stage factory, development-only holdout sealing, causal truncation, native diagnostic evaluation, and trial ledger append-only accounting function end-to-end).
- **Paper Qualification**: **PARTIALLY_QUALIFIED** (Local synthetic paper lifecycle qualified; external provider demo execution awaiting release authorization; 28-day continuous observation in progress).
- **Live Qualification**: **UNQUALIFIED / BLOCKED** (No live authority granted, no completed 28-day paper observation, no live broker order approval).
