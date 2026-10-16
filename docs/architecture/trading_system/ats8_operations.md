# ATS-8 Continuous Learning and Operating Benchmark

Implementation scope: `src/research_control/learning.py` and `scripts/benchmark_ats8_learning.py`.
Provides version-aware research lesson retrieval, fail-closed protocol and scope invalidation, and independent benchmark measurement over existing authorities.
Adheres to `ml4t-agent-state-memory`, `ml4t-agent-tool-contracts`, and `ml4t-agent-governance`.

## 1. Operating Commands

From repository root:

```sh
# Validate cryptographic digests of all registered lessons
.venv/bin/python -m src.research_control.learning validate --root .

# List all registered active lessons
.venv/bin/python -m src.research_control.learning list --root .

# Deterministic query by error code, scope, or protocol
.venv/bin/python -m src.research_control.learning query --root . --error-code EVIDENCE_TOO_LARGE
.venv/bin/python -m src.research_control.learning query --root . --scope-path src/research_control/action_worker.py
.venv/bin/python -m src.research_control.learning query --root . --protocol native_bracket_v1

# Run the independent 3-way continuous learning operating benchmark (samples=3)
.venv/bin/python -m scripts.benchmark_ats8_learning --samples 3
```

All entrypoints are strictly read-only and advisory. A lesson retrieval match provides a verified recipe and associated regression test; **it never mints permissions, authorizes execution, or certifies that the present environment is healthy** (adhering to `ml4t-agent-governance`).

---

## 2. Authority & Governance Boundaries

| Entity | Actual Authority | Invalidation / Rejection Policy |
| :--- | :--- | :--- |
| **Lesson Record** | `docs/lessons/<lesson_id>.json` | Tampered digest fails `verify_digest()`; unverified file rejected |
| **Protocol Scope** | `protocol` field | Conflicting target protocol fails closed (`PROTOCOL_MISMATCH`) before relevance scoring |
| **File Scope** | `affected_scope` field | Unmatched scope path fails closed (`SCOPE_MISMATCH`) before scoring |
| **Version Bounds** | `version_bounds` field | Missing environment versions or numeric semver lower than bound fails closed (`VERSION_INCOMPATIBLE`) |
| **Code / Data Drift** | `bound_code_hashes`, `bound_data_hashes` | Changed code or data SHA-256 fails closed (`CODE_DRIFT` / `DATA_DRIFT`) |
| **Supersession** | `superseded_by` field | Obsolete lessons excluded by default; reported as `SUPERSEDED` when inspected |
| **Environment Invalidation** | `invalidated_by` field | Matching environment flags immediately set validity to `INVALIDATED` |

---

## 3. Canonical Lessons Grounded in Git History

1. **`LSN-20261015-OVERSIZE-CASEFILE-STREAM`**
   - **Trigger:** `EVIDENCE_TOO_LARGE` when parsing large factory Casefile JSON (>256KB).
   - **Root Cause:** Eager JSON deserialization of high-volume bulk exclusion arrays overflows memory and response context budgets.
   - **Verified Remedy:** Stream SHA-256 byte digest (`_integrity`) against ledger hash without decoding full JSON; inspect small stage receipts (`stage1.json`, etc.) for per-stage status.
   - **Evidence Ref:** `commit 260b14e5af7f56ccd21c2879c363c0867b89512c` (`src/research_control/agent_interface.py`).
   - **Regression Test:** `tests/test_ats_qualification.py::test_large_casefile_stream_hash_and_receipts_without_json_decode`.
   - **Demonstrated Sensitivity:** Executing the historical pre-fix reader triggers `AssertionError` under the regression guard; the verified remedy passes cleanly (`test_real_historical_failure_and_verified_remedy_cycle`).

2. **`LSN-20261016-CGROUP-V2-MEMORY-CONTAINMENT`**
   - **Trigger:** Kernel-enforced resident memory capping for isolated native research workers.
   - **Root Cause:** 64-bit Rust/Polars (jemalloc) maps ~2.3GB virtual address space at startup. In-process `RLIMIT_AS` panics thread creation (`os error 11`), while parent periodic RSS polling permits burst spikes.
   - **Verified Remedy:** Use Linux cgroup v2 / systemd user scopes (`systemd-run --user --scope -p MemoryMax=... -p MemorySwapMax=0`) wrapped in `src/research_control/resource_cgroup.py`.
   - **Evidence Ref:** `commit 368d8f00beb5e51ac1f0e5215a339c770198c1ee` (`src/research_control/resource_cgroup.py`).
   - **Regression Test:** `tests/test_ats2_resource_limits.py::test_unavailable_cgroup_does_not_consume_admission`.

3. **`LSN-20261016-PARENT-RSS-POLLING-UNENFORCED` (Superseded)**
   - **Trigger:** Attempting in-process `RLIMIT_AS` or parent periodic RSS polling for worker memory limits.
   - **Result:** Failed supervisor final gate 4 (`final_gates.md:26`).
   - **Superseded By:** `LSN-20261016-CGROUP-V2-MEMORY-CONTAINMENT`.

4. **`LSN-20261016-TZ-AWARE-UTC-NORMALIZATION`**
   - **Trigger:** Comparison failure or silent drift when comparing ISO timestamps with explicit timezone offsets.
   - **Root Cause:** Using `.replace(tzinfo=None)` strips timezone offsets without converting to UTC.
   - **Verified Remedy:** Normalize timestamps using `.astimezone(UTC).replace(tzinfo=None)`.
   - **Evidence Ref:** `commit 16d56a3e144a36f9870425c2759e66ff4d84f9cf` (`src/research_control/ats2_raw_audit.py`).

5. **`LSN-20261010-LEGACY-V1-PERMIT-OVERRIDE` (Superseded)**
   - **Trigger:** Feature permit manual override for v1 research contracts.
   - **Root Cause:** Manual permit overrides caused schema drift.
   - **Superseded By:** `LSN-20261015-DUAL-MODE-RUNTIME` (commit `827731d`).

---

## 4. Operating Benchmark Ablation & Tradeoff Analysis

Evaluated across 14 predeclared fixtures (3 samples each) comparing three operator arms:
1. `baseline_raw`: Multi-source independent queries (Git, README, trial ledger, raw casefile).
2. `managed_no_learning`: Unified `inspect_case` without lesson retrieval.
3. `managed_with_learning`: Unified `inspect_case` with deterministic `LessonStore` query.

### Measured Ablation Results

| Metric | Baseline Raw | Managed (No Learning) | Managed (With ATS-8 Learning) | Measured Finding |
| :--- | :---: | :---: | :---: | :--- |
| **Critical Invariants Correct** | 100% | 100% | **100%** | Zero forbidden side effects, zero order permissions across all arms. |
| **Median Tool Calls** | 107 | 18 | **33** | **Negative efficiency on call count:** Querying store adds +1 tool call per evaluated error (+83% calls). |
| **Median Context Bytes** | 390,652 B | 56,489 B | **56,489 B** | Zero net context increase on medians (compact JSON lesson records). |
| **Diagnostic Remedy on Errors** | 0% (unassisted) | 0% (blind `inspect_evidence`) | **NOT_EXERCISED (0/0 in benchmark)** | Benchmark matrix had 0 remedy-resolvable fixtures; verified remedy demonstrated in unit test only. |
| **Stale Advice Rejection Rate** | N/A | N/A | **100.0% (6/6 measured)** | Evaluated opportunities for superseded or incompatible lessons rejected fail-closed. |
| **Mutation Sensitivity** | N/A | N/A | **Verified Sensitive** | Disabling filtering in `test_benchmark_mutation_disabling_compatibility_filtering_fails` causes benchmark failure (exit code 1). |
| **Raw Trace Persistence** | No | No | **Partial (11 runs retained)** | 11 runs persisted in `run_log/ats8/benchmark/`; 3 early runs unrecoverable after intermediate cleanup. |

### Measured Ablation Finding
In this 14-fixture benchmark matrix, enabling lesson retrieval incurred a **net efficiency cost** (+15 tool calls, 33 vs 18) without altering terminal action correctness (both reached the same action). The operating benchmark did not demonstrate a positive remedy gain across these fixtures; remedy recovery was demonstrated exclusively in unit regression `test_real_historical_failure_and_verified_remedy_cycle`.

---

## 5. Ongoing Integration Boundary

ATS-8 provides a small, decoupled interface (`LessonStore.query()`, `AgentLearningState`) ready for future ATS-4 (scientific protocol validation) and ATS-5 (account rulebook replay) consumers without modifying concurrent worktrees or rewriting `AGENTS.md`.

---

## 6. Qualification Status: PARTIALLY QUALIFIED

- **Qualified:** Schema-validated lesson store (`LessonRecordV1`), fail-closed protocol and scope gates, numeric semver bounds (`1.10` > `1.9`), cryptographic digest verification, real historical regression execution, and mutation sensitivity.
- **Unresolved / Limitation:** The end-to-end operating benchmark demonstrated a negative efficiency ablation (+15 calls) and did not exercise a positive remedy gain in the 14-case matrix (0/0 remedy opportunities). Three early benchmark runs were unrecoverable after cleanup.
