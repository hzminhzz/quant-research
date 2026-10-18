# ATS Post-Integration Operating Loop Qualification — 2026-10-18

**Verdict:** The ATS post-integration operating loop is **RESEARCH-QUALIFIED (development-only)**,
including a real source-to-native terminal decision driven entirely through the research inbox.
Live trading and external broker execution remain **BLOCKED / UNAUTHORIZED**.
The 28-day synthetic paper observation was interrupted by an external cgroup OOM kill and its
clock is reset to zero (see `docs/audit/ats7_incident_20261018.md`).

---

## 1. Exact Implementation & Commit Identities

- **Base commit**: `f2a6025253dc72ad531bad8968dd75bf053abb12` (`origin/main`, feat: Google Colab GPU remote trainer).
- **Task branch**: `feat/ats-operating-loop-20261018`
- **Reconciled commits**:
  - `84013226848a52a6800e0fbe7bf064dc96ff6210`: Admitted 62 nested thesis directories byte-identically from `origin/feat/ats-inbox-62-copy-20261018`.
  - `f06c0705`: Supervisor-review resolution (ATS-7 incident, `BLOCKED_EXECUTION` read model, stricter learning, portable `pythonpath`).
  - Staging reconciliations: Admitted 42 additional captured flat/nested theses, completing a 112-candidate corpus with zero source tampering.
- **Touched modules & test suites**:
  - `src/research_control/casefile.py`: Added `BLOCKED_EXECUTION` next-safe action and terminal accounting.
  - `src/research_control/learning.py`: Enforced lesson retrieval strictly conditional on observed failure/error codes.
  - `src/research_control/research_inbox_queue.py`: `BLOCKED_EXECUTION` terminal accounting; capability-aware `_preflight`
    (qualified cross-sectional specs/adaptations execute, unqualified single-instrument events fail closed); discovery of
    source-hash-bound `local_adaptation` specs through an injected `candidates_dir`; version-aware reconsideration including
    `BLOCKED_EVIDENCE`; ledger reconciliation that adopts a completed trial **only** under the same frozen code identity and
    blocks duplicate re-registration while an interrupted registration is unreconciled; exact native exit/signal recording.
  - `src/engine/isolation.py`: Worker termination diagnostics now carry the exit status / POSIX signal; worker Polars threads bounded to 2.
  - `src/engine/funnel.py`: Event Casefiles carry the mandatory `development_only` flag.
  - `src/engine/spec_parser.py`: Added `'local_adaptation'` to `source_spec_status` enum.
  - `src/connectors_bootstrap.py`: Portable sibling-repository connector resolution (no machine-specific absolute paths).
  - `pyproject.toml`: Relative `pythonpath` entries only.
  - `scripts/triage_inbox_theses.py`: Non-executing full-corpus triage audit generator.
  - `config/candidates/ats_crypto_xs_90d_high_anchoring_local_adaptation_20261018.yaml`: Formally declared cross-sectional candidate adaptation.

---

## 2. Capabilities Transition Matrix

| Capability | Previous Status | Current Status | Verification Proof |
| :--- | :--- | :--- | :--- |
| **Nested Thesis Intake** | `BLOCKED_HANDOFF` (schema rejection) | **ADMITTED** (62/62 nested, 111/112 corpus) | `InboxQueue.report()` confirms 111 admitted, 1 failing closed on missing brief URL anchor. |
| **Capability-Aware Preflight** | Blanket `BLOCKED_PROTOCOL` for every non-XS protocol | **REAL ROUTING** | Qualified cross-sectional specs/adaptations execute; unqualified single-instrument events fail closed with `UNSUPPORTED_EVENT`. |
| **Version Reconsideration** | Skipped permanently | **RECONSIDERED** | Pre-trial blocks (incl. `BLOCKED_EVIDENCE`) re-evaluate when `runtime_identity()` changes; advances through exactly one authorized run. |
| **Duplicate/Interrupted Protection** | Health: unverified | **ENFORCED** | Unreconciled `registered` ledger entries without `completed` fail closed as `BLOCKED_RECOVERY`; identical completed trials are adopted only under the same frozen code hash. |
| **Casefile Semantics** | Collapsed into `BLOCKED_DATA` | **`BLOCKED_EXECUTION` preserved** | Casefile and trial ledger retain exact reason and stop-order remediation. |
| **ATS-1 Read Model** | Crashed on `BLOCKED_EXECUTION` | **INTEGRITY VERIFIED** | `inspect_case` maps `BLOCKED_EXECUTION` with cryptographic verification. |
| **Connector Import Isolation** | Broken on unexported `PYTHONPATH` | **PORTABLE BOOTSTRAP** | `src/connectors_bootstrap.py` + relative `pythonpath`; `python -m scripts.ats7_observation --help` resolves. |
| **Unmocked Inbox Research** | Zero native trials through inbox | **REAL PILOT QUALIFIED** | Two adaptations reached independent terminal `FALSIFIED_STAGE_2` decisions through the inbox CLI, with verified receipts, Casefile and ledger. |
| **ATS-8 Lesson Retrieval** | Unconditional queries permitted | **FAILURE-CONDITIONAL** | Retrieval requires `error_code`/`protocol`, preventing instruction sprawl; median 2 calls per case vs 9 baseline; 100% stale/incompatible rejection. |

---

## 3. Real Inbox-to-Native Pilot (primary acceptance evidence)

**Command (exactly as an operator would run it):**

```
.venv/bin/python -m scripts.research_inbox_queue start --max-candidates 2
```

**Canonical development panel** (deterministic rebuild from the local raw store, no downloads, no protected read):
`/tmp/ats-crypto-xs-90d-high-anchoring-development`, manifest hash `e77f793b45527cb4…`,
23,112 development entries, `bar_seconds=3600`, `protected_test_start=2026-01-01T00:00:00Z`,
window `[2020-03-02, 2026-01-01)` (30-day warm-up before the declared 2020-04-01 train start).
*This manifest hash is volatile: the panel root is a `/tmp` path declared by the frozen adaptation, so the
panel is reproducible from the raw store but not durable. Recorded as a known limitation, not a qualified vault.*

| Inbox thesis | Frozen adaptation `spec_hash` | Native attempt | Stage 1 | Stage 2 | Inbox terminal | Evidence status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `crypto_xs_90d_high_anchoring_basket_v1` | `5c0a84740912ea9d…` | `20261018T065829-34b51977ce` | PASS (as recorded) | `FALSIFIED_STAGE_2` | `FALSIFIED` | **UNVERIFIED** — Stage-1 receipt destroyed by an operator tamper test (see incident below) |
| `crypto_xs_funding_velocity_dislocation_basket_v1` | `d72a053d93894eb6…` | `20261018T070027-f5500f3ce1` | **PASS** | `FALSIFIED_STAGE_2` | `FALSIFIED` | **VERIFIED end-to-end** |

Stage 1 evidence: 8,278,172 feature rows, exact prefix invariance at three recorded cutoffs, PIT membership
`in_pit_universe` present in both feature sets. Stage 2 (train-only labels, cross-sectional IC, Newey–West HAC):

| Thesis | Arm | Mean IC | HAC SE | HAC t | p | n periods |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| 90d high anchoring | `high_watermark_rank` (candidate) | +0.005096 | 0.026120 | **+0.1951** | 0.8453 | 3,975 |
| 90d high anchoring | `momentum_72h_baseline` | −0.046542 | 0.021502 | −2.1645 | 0.0305 | 3,975 |
| Funding velocity | `velocity_reversal_score` (candidate) | +0.004875 | 0.003774 | **+1.2917** | 0.1965 | 28,360 |
| Funding velocity | `static_funding_level_basket` | +0.021773 | 0.005728 | +3.8011 | 0.00014 | 28,360 |

Both candidates fail the frozen `minimum_hac_t = 2.0` gate; funding velocity additionally fails
`require_baseline_ic_improvement` (its own baseline has the stronger IC). These are **valid scientific
falsifications**, not engineering failures.

### Independent reproduction (separate process, not the funnel)

| Check | Result |
| :--- | :--- |
| Casefile bytes vs recorded `casefile_sha256` | **match** (both) |
| Frozen spec re-parsed and `spec_hash` re-derived | **match** (both) |
| `thesis.yaml` / `brief.md` bytes vs `source_files_sha256` | **match** (both) |
| Casefile `candidate_id` / `spec_hash` vs inbox state | **match** (both) |
| `development_only` / `holdout_access` / `holdout_claim` | `True` / `False` / `None` (both) |
| Stage 1 & 2 receipt digests + all artifact hashes | **verified** for funding velocity; 90d Stage-1 receipt destroyed by the incident below |
| Trial ledger hash chain (55 records) | **intact** |
| Ledger `completed` record for the native attempt, same Casefile SHA-256 | **found** (both) |
| Ledger `holdout_access` | `False` |
| Recomputed mean IC from `stage2_ic.parquet` | **bit-identical** to the reported value |
| Recomputed Newey–West HAC SE and t | agree to `1e-12` once the reported convention (sample `n-1` covariance, Bartlett taper `1 - l/(L+1)`) is used |
| Second `start` invocation | no additional trial registered (idempotent) |

### Evidence-integrity incident (disclosed, not reconstructed)

While proving that the verifier rejects a receipt pointing outside the attempt directory, the tamper test
overwrote `stage1.json` in the **live** 90d attempt directory: `state.json` records an absolute Casefile path, so
copying the run log did not isolate the test. Everything else in that attempt is intact
(`casefile.json`, `spec.json`, `stage1_evidence.json`, `stage2.json`, `stage2_evidence.json`, `stage2_ic.parquet`),
and the candidate's `FALSIFIED_STAGE_2` decision stands as recorded — but its Stage-1 causal proof can no longer be
verified from bytes, so it is reported **UNVERIFIED** rather than quietly rebuilt. The receipt was deliberately
**not** reconstructed: a receipt written after the fact is self-attestation, not evidence.
Incident record: `run_log/dual_mode/ats_crypto_xs_90d_high_anchoring_local_adaptation_20261018/EVIDENCE_INTEGRITY_INCIDENT.md`.

Consequence for the acceptance claim: the fully verified real pilot is
`crypto_xs_funding_velocity_dislocation_basket_v1`. `docs/audit/ats_inbox_pilot_verification_20261018.json`
therefore reports `verified_count: 1`, `unverifiable_count: 1` and the verifier exits 2 — a partial pass is
published as a partial pass.

**Committed reproduction:** `scripts/inbox_pilot_evidence.py` (read-only; never executes a strategy, never writes
into the run log, never touches a protected partition). It re-derives every hash above from recorded bytes and
recomputes the Stage 2 mean IC and Newey–West HAC statistics, agreeing with the native diagnostic to
`1e-12` (sample `n-1` covariance, Bartlett taper `1 - l/(L+1)`). Its machine-readable output is
`docs/audit/ats_inbox_pilot_verification_20261018.json`:

```
.venv/bin/python scripts/inbox_pilot_evidence.py \
  --output docs/audit/ats_inbox_pilot_verification_20261018.json   # exit 0 = verified
```

Its own guards are regression-tested in `tests/test_inbox_pilot_verifier.py` (HAC convention, ledger tamper
detection, fail-closed exit when nothing verifiable exists).

### Independent adversarial review and its outcomes

Two independent reviewer subagents (no authorship of this change) attacked the claims above. Accepted findings,
and the code changes made in response:

| Finding | Severity | Resolution |
| :--- | :--- | :--- |
| Verifier hashed stage-receipt artifact paths without containment, so a crafted receipt could make it read outside the attempt directory | P1 | Rejected: absolute paths, symlinks and any path whose `resolve()` escapes the attempt directory now fail closed. Proof attempted against an `/etc/hostname` escape — which also caused the disclosed incident below. |
| `_execute` could adopt an existing `completed` ledger record with the same spec + current code hash, which a *direct* `quant.py` run would also satisfy | P2 | The adoption branch was deleted. An interrupted registration now always fails closed as `BLOCKED_RECOVERY` for operator reconciliation. Regression: `test_completed_direct_run_evidence_is_never_adopted_as_an_inbox_result`. |
| Verifier compared code/spec identities only to recorded state instead of re-deriving them | P2 | The verifier now re-parses the frozen spec and re-derives `spec_hash`, and re-hashes `thesis.yaml`/`brief.md`. It reports `code_identity_is_current_runtime` instead of silently assuming it. |
| `_preflight` blocked every `single_instrument_event` before looking up a spec, so the two listed qualified event adapters were unreachable | P2 | The gate now consults `QUALIFIED_EVENT_ADAPTERS`; everything else still fails closed. |
| A `local_adaptation` was selected by substring mention of a hash and candidate id | P1 | Binding is now the parsed `assumptions`: an exact `SOURCE_SHA256` of this thesis **and** a `SOURCE_ID` ending in `research_inbox/<candidate>/thesis.yaml`. Regression: `test_adaptation_must_declare_the_matching_source_identity`. |
| A symlink at `<candidate_id>.yaml` could point outside `candidates_dir` | P2 | Rejected by `_inside_candidates`. Regression: `test_adaptation_symlink_escaping_candidates_dir_is_rejected`. |
| Inbox `attempt_id` differed from the native ledger attempt id with no cross-reference | P2 | State now records `native_attempt_id` from the Casefile and reports it. |

Not accepted as defects, with reasons:

- *"Verifier restates the same HAC convention, so reproduction is not independent-method."* True and now stated plainly:
  the verifier computes the statistic with its own numpy implementation and agrees with the native
  `ml4t.diagnostic` path to `1e-12`; it is an independent *implementation*, not an independent *estimator*.
- *"Whitespace-only receipt edits are accepted."* Receipts are content-addressed over parsed JSON (the production
  convention); the verifier deliberately matches production so a pass means the same thing in both.
- *"The vertical slice failed during review."* It failed because `src/engine/funnel.py` was being edited by
  concurrent work in the same checkout, so `runtime_identity()` changed mid-run and the fail-closed drift check
  fired. That is the guard working. The suite passes (43 passed) on a stable tree.

### Code identity of the pilot

The pilot executed under frozen runtime identity `3b8d3440c34d5e77…`. The committed tree now reports a different
identity because concurrent work in the same checkout modified `src/engine/funnel.py` after the run. The pilot
evidence is bound to `3b8d3440…` and is **not** re-labelled; `docs/audit/ats_inbox_pilot_verification_20261018.json`
records `code_identity_is_current_runtime: false` for both cases. Any future run under the current code is a new trial.

### Full-corpus frontier

`python -m scripts.triage_inbox_theses` regenerated `docs/audit/ats_inbox_full_corpus_triage_20261018.md`:
112 theses inspected, 111 admitted, 1 structurally blocked handoff, 8 unqualified single-instrument events,
103 descriptive specifications blocked on explicit missing data/parameters. Only the two source-hash-bound
cross-sectional adaptations were executable, and both have now reached terminal decisions.

---

## 4. Earlier Direct-Run Exemplars (historical, not inbox-driven)

These were executed in a prior session by invoking `scripts/quant.py run` directly. They remain valid
scientific evidence but are **not** the inbox acceptance proof; Section 3 supersedes them for that purpose.

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

### C. Cross-Sectional Factor Exemplar: `ats_crypto_xs_funding_velocity_local_adaptation_20261018`
- **Spec**: `config/candidates/ats_crypto_xs_funding_velocity_local_adaptation_20261018.yaml` (`CandidateSpec`, `source_spec_status: local_adaptation`).
- **Data**: Binance hourly perpetual development panel (`[2020-04-01, 2026-01-01)`), 1,136,320 eligible rows, 28,360 periods across 484 symbols.
- **Execution**: `scripts/quant.py run config/candidates/ats_crypto_xs_funding_velocity_local_adaptation_20261018.yaml --development-only`.
- **Stages Evaluated**:
  - Stage 1 (Prefix Invariance / Causal Truncation): **PASS**.
  - Stage 2 (Cross-Sectional IC & Diagnostic HAC): **`FALSIFIED_STAGE_2`** (Exit Code 0).
- **Diagnostic Metrics**:
  - Candidate Funding Velocity Reversal: Mean IC = `+0.00487`, HAC SE = `0.00377`, HAC t-stat = `1.2917` ($p = 0.1965$). Fails minimum $t \ge 2.0$ gate and fails baseline increment.
  - Baseline Static Funding Carry: Mean IC = `+0.021773`, HAC SE = `0.005728`, HAC t-stat = `3.8011` ($p = 0.000144$).
- **Ledger Record**: Registered and completed trial appended to `run_log/trial_ledger.jsonl`. Holdout partition remained strictly sealed (`holdout_access: false`).

---

## 5. Benchmark Performance vs. Baseline (ATS-8)

Ran `scripts/benchmark_ats8_learning.py` against 15 test fixtures (3 samples each = 45 total executions), including the remedy-eligible `remedy_eligible_isolation_unavailable` fixture and verified lesson `LSN-20261016-ISOLATION-UNAVAILABLE-REMEDY`:

| Metric | Baseline Raw | Managed No-Learning | Managed With Learning |
| :--- | :---: | :---: | :---: |
| **All Critical Correct** | True | True | **True (15/15)** |
| **Total Tool Calls (15 cases)** | 116 | 19 | **37** |
| **Median Tool Calls Per Case** | 9 | 1 | **2** |
| **Median Context Bytes** | 395,712 B | 61,019 B | **61,915 B** |
| **Remedy-Eligible Coverage** | 0/0 | 0/0 | **100.0% (1/1)** |
| **Stale Advice Rejection** | N/A | N/A | **100.0% (6/6)** |
| **Incompatible Version Rejection** | N/A | N/A | **100.0% (6/6)** |
| **Trace Artifact** | — | — | `run_log/ats8/benchmark/20261018T045927Z-5abd7866/report.json` |

---

## 6. Unresolved Scientific & External Dependencies

1. **Intraday CFD Stop Qualification**: Native `ml4t-backtest==0.1.7` requires an intrabar quote-depth and gap-execution adapter before single-instrument hourly stop breakout strategies (such as BTA NQ) can execute Stage 3.
2. **ATS-7 Operational Incident & Observation Reset**: As audited in `docs/audit/ats7_incident_20261018.md`, `ats7-local-paper@observation-v1.service` suffered a cgroup OOM kill (status 137) and burst restart loop under host memory pressure at 05:06 CEST, latching the kill switch. Total accepted observation was 77,782.79 s (~21.6 hours) across 1,229 completed bars (94.83% coverage). The unbroken 28-day window is **NOT SATISFIED** and requires an observation clock reset to `observation-v2` after swap/cgroup memory remediation.
3. **Volatile panel root**: both frozen adaptations declare `panel_root: /tmp/ats-crypto-xs-90d-high-anchoring-development`.
   The panel is deterministically rebuildable from the raw store (~13 min) but is not durable and its manifest hash
   changes on rebuild. Moving to a certified vault requires a new spec identity and a new trial, not a rewrite.
4. **Host memory**: the full 1.13M-row panel plus concurrent agent workloads exhausted host swap; the isolated
   feature worker was repeatedly killed. Worker Polars threads are now bounded to 2 and termination now reports
   exit status/signal. A dedicated larger host or a reduced universe remains the real fix for routine operation.
5. **External Broker Authority**: Live trading, live account purchases, and mutating live order endpoints remain strictly barred.

---

## 7. Qualification Verdict

- **Research Qualification**: **QUALIFIED** — a real thesis from `research_inbox/` advanced through source verification,
  frozen source-hash-bound adaptation, capability-aware preflight, canonical development data, native Stage 1 + Stage 2,
  independent receipt/Casefile/ledger verification and a terminal decision, driven solely by the inbox CLI.
  This is development qualification only: no protected partition was read, and neither candidate's source-level
  gates (annualised Sharpe, drawdown, low-liquidity-regime falsification) are encoded by the native factory.
- **Paper Qualification**: **INTERRUPTED / RESET REQUIRED** (Local synthetic paper lifecycle qualified; 28-day continuous observation interrupted by cgroup OOM kill at ~21.6 hours; observation reset required; external provider demo execution awaiting release authorization).
- **Live Qualification**: **UNQUALIFIED / BLOCKED** (No live authority granted, 28-day paper observation broken, no live broker order approval).
