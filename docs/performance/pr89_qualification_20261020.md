# PR #89 qualification — ATS cross-sectional allocator vectorization

**Date:** 2026-10-20
**Repository:** `hzminhzz/quant-research`
**PR:** #89 `perf(ats): benchmark and vectorize cross-sectional allocation`
**Branch:** `perf/ats-throughput-measured-20261019`
**Scope:** development-only allocator equivalence, benchmark and development-data
pipeline evidence. No protected partition was read, no holdout claim was reserved,
no factory gate was changed, no broker or live-order path was touched.

---

## 1. Verdict

**MERGE_READY** — no blocking defect found. The three documented behaviour
differences in §12 are listed for explicit supervisor acceptance rather than
silently absorbed, and this work unit does not merge.

Blocking reasons would have been: an unexplained allocator divergence, a failing
gate that is not reproducible on the baseline, or a nondeterministic repeated
output. None of those occurred.

---

## 2. Source identity

| Item | Value |
| --- | --- |
| `origin/main` at fetch (also PR merge-base) | `1e8d0cc33f5f3469eb83a78fcc2b79505bff8e9b` |
| PR head at start of qualification | `ffe2c258d4cf3ea45e9f3039ed09292a0f6261d8` |
| Final head (this commit) | see `git log -1` on the branch; recorded in §12 |
| Original `signal_allocator.py` git blob | `956fd849cf6b7b70ff49caf46167c7fdbfe9fb7e` |
| Original `signal_allocator.py` sha256 | `820a2abfae50d9a29d0a05665b746bd36a1ced6d04870e09f4ad1d53f4c00c5f` |
| Qualified `src/engine/signal_allocator.py` sha256 | `3d8668f06458355ad614f231c2a0c6f0b140e8dd45595fc5b3fa13dc21db3498` |
| Qualified `scripts/benchmark_ats_allocators.py` sha256 | `dc358f26036d515b603ec7ee3049676b10623ae4acc7f142a8cd21787a178c47` |

`origin/main` was already an ancestor of the PR head, so no integration merge was
required; nothing was force-pushed. The local `main` checkout carries two
unpushed research commits (`36e8c88f`, `33f7ce38`) that touch only AF30 research
manifests and logs — unrelated to this PR and deliberately left untouched.

Interpreter and libraries for every number below: Python 3.14.6, `polars`
1.44.2, `numpy` 2.5.3, `ml4t-backtest` 0.1.7 (locked), AMD EPYC (8 vCPU),
`POLARS_MAX_THREADS=8`.

---

## 3. What was inspected before changing anything

* PR state: open, not draft, `mergeable=MERGEABLE`, `mergeStateStatus=CLEAN`,
  zero reviews, zero review comments, zero issue comments, four successful checks
  (`Managed feature policy`, `Fast tests`, `Full tests`, `GitGuardian`).
* PR body claimed a 20-test pass, an identical small-case fingerprint and
  "before medians 600–1004 ms, after 23.52 ms". The stored artifacts in the PR
  worktree (`.workspace/perf/before_small.json`, `after_small.json`) actually say
  1108 ms → 8.8 ms, and the "after" artifact was produced with a dirty tree at
  commit `3bdf20f1` — i.e. the body's numbers were not reproducible from its own
  evidence. That inconsistency is what the benchmark work below replaces.
* Worktree `/home/quant/.devspace/worktrees/quant-research-0174c48b` was clean at
  head `ffe2c258`, so it was used as instructed; `main` was not disturbed.
* A concurrent qualification session was operating in the same worktree and had
  already created `tests/test_signal_allocator_contract.py` and its own perf JSONs
  under `.workspace/perf/pr89-qualification/`. That work was preserved: this
  change adds only the non-duplicated edge regressions
  (`tests/test_ats_allocator_edge_contracts.py`) and its evidence is consolidated
  in §6 and §9 rather than duplicated.

---

## 4. Differential oracle against the *actual* original (acceptance 1)

`scripts/qualify_ats_allocator_equivalence.py` does **not** re-implement the old
allocator. It reads `src/engine/signal_allocator.py` out of git at the pinned
merge-base, asserts both the blob object id and the sha256 against recorded
constants, rewrites exactly two package-relative import lines (verified: exactly
two lines differ from the pinned bytes), then imports and runs it.

Comparison is exact, not approximate:

* exception type, then `QuantError.status`, then `QuantError.reason`;
* schema as an ordered `(name, dtype)` list;
* row count;
* `Float64` columns compared as raw IEEE-754 **bit patterns** (`uint64` view);
* timestamps compared as exact integer ticks plus dtype;
* strings compared verbatim.

Result: **81 of 84 cases bit-identical; 3 documented divergences; 0 unexplained**
(`.workspace/pr89/oracle.json`).

| Area | Cases |
| --- | --- |
| Balanced/unequal baskets, gross 1.0/1.5, exactly-at-minimum, insufficient eligibility | 8 |
| Ranking ties: head boundary, tail boundary, fully tied, basket overlap via `minimum_assets` | 4 |
| Boolean nulls (`in_pit_universe`, `is_tradable`) | 1 |
| Signal null/NaN/±inf/zero; ATR null/NaN/±inf/zero/negative/subnormal | 2 |
| Stop-distance boundary (at/just below/just above 1.0) and rejection | 2 |
| Close edge values (0, negative, null, `1e-300`) | 1 |
| Empty frame; no scheduled timestamp | 2 |
| Cadence: hourly, daily (24 bars), 15-minute bars with off-cadence start, anchor-before-data | 4 |
| Timezone/time-unit: `us`, `ns`, naive, sub-microsecond | 4 |
| Signal override argument | 1 |
| Duplicate symbols: equal signal, unequal signal, head+tail, ineligible twin, neutrality | 5 |
| Dtypes: `Int64`, `Float32`, `Float32` near the eligibility boundary | 3 |
| Name aliases: `atr_feature == signal`, `atr_feature == close`, `signal == close` | 3 |
| Error precedence across timestamps | 1 |
| Mixed multi-timestamp sections, shuffled physical row order | 3 |
| Seeded random fuzz (ties, duplicates, nulls, ineligibility, mixed parameters) | 40 |

Seven of the 84 cases are *rejected* inputs; both implementations raise
`QuantError` with the same status in all but the documented cases below.

---

## 5. Regressions found and fixed

Each was reproduced on the unfixed PR head `ffe2c258` and passes after the fix.

**R1 — Float32 panels changed the published schema and the stop-distance
precision.** With `Float32` feature columns the vectorized projection inherited
`Float32`, so `stop_loss_dist_pct` came back as `Float32` *and* the distance was
computed in single precision, while the former loop read Python floats (exact
Float32 → Float64 widening) and always emitted `Float64`.
Fix: cast the projection operands to `Float64` and cast the emitted column
explicitly. Eligibility arithmetic is deliberately left in the original column
dtype, because the former loop also evaluated the eligibility filter in Polars.
Evidence: `test_float32_stop_distance_uses_double_precision`,
`test_non_float64_feature_dtypes_keep_the_target_contract[Float32]`,
`test_target_schema_is_stable_for_float32_feature_columns`.

**R2 — a legal feature alias crashed the allocator.** `allocation.atr_feature:
close` is accepted by `CandidateSpec` validation (it only requires the name to be
a declared feature output), but the new projection selected `close` twice and
raised `polars.exceptions.DuplicateError`; the former loop allocated normally and
returned a flat section. Fix: alias the projection inputs (`_close`, `_atr`) so
no output name can collide.
Evidence: `test_atr_feature_named_close_collision_allocates`.

**R3 — benchmark realism: the synthetic clock contradicted its own spec.** The
harness generated timestamps from the Unix epoch while `signal_spec()` declares
`windows.train.start = 2025-01-01T00:00:00Z`, which is also the anchor the
allocator uses for cadence. The timestamps are now anchored at `START` and the
panel builder asserts it, so a timing row can no longer describe a panel that the
declared spec could never produce.

**R4 — the harness fingerprinted only the last repeat.** `_run` returned one
`sha256` from the final repeat, so a nondeterministic implementation would have
been timed as if stable. Every repeat is now fingerprinted, per-case
`repeats_identical` is recorded, and a differing repeat marks the case as a
failure. `--compare` prints matched-case medians, speedups and fingerprint
agreement so the table in §6 is reproducible from the saved JSON.

Scope discipline: no change to `allocate_ts`, execution, gates, costs, holdout,
trial ledger, or the allocator's ranking/eligibility rules. The only production
edit is the Float64 projection and the non-colliding aliases.

---

## 6. Benchmarks (acceptance 2)

Method: the pinned original is extracted from git and imported into the *same*
interpreter as the worktree implementation, so the two sides differ only by the
allocator module. Two interleaved blocks; per block, 5 timed repeats after 1
warm-up per case, `POLARS_MAX_THREADS=8`, identical `PYTHONPATH` and interpreter.
`allocate_ts` is unchanged by the PR and is reported as a negative control.

Workloads: `small` 16×400, `medium` 64×1500, `large` 192×3000, `medium_daily`
64×1500 at cadence 24. Every synthetic panel starts at `2025-01-01T00:00:00Z`.

### Block 1 (original → head)

| case | before ms | after ms | speedup | before CV | after CV | fingerprints |
| --- | --- | --- | --- | --- | --- | --- |
| signal_small | 640.64 | 16.20 | 39.5× | 10.9% | 13.0% | identical |
| signal_medium | 2811.59 | 26.07 | 107.8× | 7.2% | 7.5% | identical |
| signal_large | 6859.78 | 107.47 | 63.8× | 6.7% | 20.3% | identical |
| signal_medium_daily | 82.19 | 23.25 | 3.5× | 20.6% | 24.6% | identical |
| ts_small (control) | 578.29 | 544.20 | 1.1× | 15.7% | 19.1% | identical |
| ts_medium (control) | 2459.62 | 2440.96 | 1.0× | 11.6% | 5.0% | identical |
| ts_large (control) | 8002.27 | 8768.76 | 0.9× | 3.8% | 11.1% | identical |
| ts_medium_daily (control) | 97.68 | 133.00 | 0.7× | 24.1% | 116.4% | identical |

### Block 2 (original → head)

| case | before ms | after ms | speedup | before CV | after CV | fingerprints |
| --- | --- | --- | --- | --- | --- | --- |
| signal_small | 600.88 | 11.23 | 53.5× | 16.8% | 19.0% | identical |
| signal_medium | 2391.48 | 36.66 | 65.2× | 18.0% | 15.1% | identical |
| signal_large | 7927.36 | 88.98 | 89.1× | 10.4% | 13.1% | identical |
| signal_medium_daily | 145.86 | 14.77 | 9.9× | 11.9% | 24.3% | identical |
| ts_small (control) | 498.79 | 574.13 | 0.9× | 13.4% | 17.6% | identical |
| ts_medium (control) | 2703.45 | 3006.83 | 0.9× | 6.2% | 4.5% | identical |
| ts_large (control) | 10777.25 | 10314.40 | 1.0× | 10.6% | 10.9% | identical |
| ts_medium_daily (control) | 136.69 | 125.33 | 1.1× | 8.7% | 8.3% | identical |

**Determinism:** 8 cases × 2 implementations × 2 blocks × 5 repeats = 160 timed
runs. Every repeat of every case produced the same fingerprint, and the original
and optimized implementations produced the same fingerprint for every case
including the unchanged timeseries control.

**Honest reading of the numbers.** The measurement host was *not* quiet: load
average was 10–15 on 8 vCPUs for most of the run because other sessions were
compiling and benchmarking concurrently. The unchanged `allocate_ts` control
therefore moves by −8% to +36% between the paired runs; that is the noise floor of
this environment. Within that floor the conclusion is stable and large: hourly
cadence allocation is **≈40–108× faster** and the daily-cadence case **≈3.5–9.9×**
faster. Absolute medians are only comparable *within* a block; the `medium_daily`
speedup range is wide because that case is small in absolute terms (14–146 ms) and
therefore noise-sensitive. An independent session's epoch-clocked run of the
earlier harness (`before` 6843–7046 ms → `after` 77–88 ms on `large`) agrees on
the order of magnitude.

---

## 7. Test suite (acceptance 3)

Local independently reproduced checks (2026-10-20, Python 3.14.6):

| Check | Result | Evidence and limit |
| --- | --- | --- |
| `python -m pytest -q -o addopts= tests/test_signal_allocator_contract.py tests/test_ats_allocator_edge_contracts.py` | **19 passed** | Target-specific Float32, alias, ranking, eligibility, cadence and duplicates. |
| `python -m pytest -q -o addopts= tests/test_dual_mode_*.py` | **52 passed, 1 skipped** | Reproduced by independent supervisor on this branch. |
| `python -B scripts/qualify_ats_allocator_equivalence.py` | **81 exact; 3 documented; 0 unexplained** | The three intentional differences are *only* on malformed duplicate-symbol input that upstream rejects. The harness asserts the exact difference shape; it fails on new or changed differences. |
| Ruff check on the two changed production/benchmark files and four new harness/test modules | **Passed** | `/home/quant/dev/quant/quant-research/.venv/bin/ruff check` on those six files. |
| `git diff --check` | **Passed** | No whitespace errors. |
| Local repository-wide tests | **Environment-limited** | The local environment lacks the separately released pinned `trading-connector` checkout needed by `tests/test_ats3_audit_broker.py` and `tests/test_ats7_faults.py` (`ModuleNotFoundError: connectors`); those two errors were reproduced on PR base `1e8d0cc3` and are not caused by this change. CI explicitly checks out connector commit `8b82d597e36e9f95dba2446b7d0d43c6819207ab` before running the entire suite. |

GitHub Actions was 4/4 green for the **previous** committed PR head `ffe2c258` (Fast tests, Full tests, Managed feature policy, GitGuardian). The updated PR head must receive **fresh green checks after push**; prior CI is not evidence for the new commit. The CI suite is authoritative for repository-wide verification on Python 3.13 with the pinned connector, while local coverage independently tests the allocator contract. No unqualified production throughput or live-trading claims are made.

---

## 8. Real development-data pipeline (acceptance 4)

Harness: `scripts/qualify_ats_pipeline_devdata.py`. It drives the shared
`Workbench` code path (`DataVault.load` → `compile_and_verify` → `stage2` →
`allocate`) on certified development partitions of
`full_530_20261015` (`manifest_hash 69ed952e…`, `protected_test_start
2026-01-01T00:00:00Z`, so every read is clamped below the protected window),
bounded to `2023-10-01 … 2024-04-01`.

| Item | Value |
| --- | --- |
| Panel | 786 860 rows, 201 symbols, 2023-10-01 → 2024-03-31 hourly |
| Input panel sha256 | `7ca8889481b297d2b3b5aabe53ef624907997230815fa81d87fa705b602013c0` |
| Feature panel sha256 | `2ac7a1d95583c97b9c30ff7baf525c42d2138badb9b925ef39a1789efaf77c60` (18 columns) |
| Candidate | `config/candidates/crypto_xs_funding_velocity_dislocation_basket_v1.example.yaml`, only `panel_root` overridden |
| Allocation | 5 long / 5 short, gross 1.0, rebalance every 48 bars, 3× ATR stop (unchanged) |
| Scheduled sections | 91 (4380 hourly bars ÷ 48) |
| Target rows / weighted rows / symbols weighted | 16 294 / 760 / 84 |
| Max abs section weight sum | 2.78e-17 |

### Measured phases

| Phase | ms |
| --- | --- |
| Vault load (development only) | 5 271.98 |
| Feature compile incl. three prefix-invariance checks | 22 995.72 |
| Stage-2 diagnostics | 172.59 |
| `allocate` — original (5 repeats, median) | 206.61 |
| `allocate` — head (5 repeats, median) | 16.66 |

Allocator A/B on the real feature panel: **12.4×** faster (206.6 → 16.7 ms),
all ten repeat fingerprints identical within and across implementations
(`e31a01c6…`), `outputs_identical=true`, `stable=true`. Stage 2 reports
`FALSIFIED_STAGE_2` for this example candidate, which is a valid research outcome
and irrelevant to throughput here.

### Composed estimate — not a measured run

Adding the once-measured phases to the allocator median gives 28 646.9 ms
(original) vs 28 456.9 ms (head). **This is an arithmetic composition, not a
measured end-to-end A/B and not a throughput figure:** load, features and
diagnostics were measured once each, so their single-run sampling error is not
quantified here. Its only use is to size the allocator's share.

**Allocator share of the authorized pipeline: 0.72% → 0.06%.** The measured
allocator gain therefore moves total pipeline time by ≈0.66%
(≈190 ms of ≈28.6 s). Feature compilation with prefix-invariance checks is ~80% of
the pipeline. That is the honest ceiling on any throughput claim from this PR.

**Blocked, not proxied:** native order simulation was **not** run. These vaults
carry no execution-qualified cost/carry adapter (`quality_summary` is absent and
the sibling crypto vaults report `execution_qualified: false`), and the repository
forbids running a native backtest on a price-only source. The native-simulation
and execution phases are therefore unmeasured here, and they are the part of the
funnel this PR does not accelerate.

---

## 9. Standards and Spec review

**Provider deviation, stated explicitly:** both review subagents and the fallback
review agents were refused by the model provider
("free models aren't available from your current network…"), so *no independent
agent review is claimed*. The two axes were performed directly against the pinned
diff, following the `code-review` procedure (fixed point = merge-base `1e8d0cc3`,
three-dot diff, two separate axes, findings not re-ranked). This mirrors the
repository's own precedent in
`docs/architecture/dual_mode_20261015/verification.md` ("No independent agent
review is claimed where a provider failed to run").

### Standards axis

Sources: `AGENTS.md`, `CLAUDE.md`, `CONTEXT.md`, `pyproject.toml` (pytest markers,
no `[tool.ruff]` section, so ruff defaults), `.github/workflows/ci.yml`,
`docs/architecture/dual_mode_20261015/verification.md`.

Hard violations before this change: **none found.** Judgement calls, all now
addressed or explicitly out of scope:

1. *Comment asserted an unverified equivalence claim.* "rank/order are the same
   [signal desc, symbol asc] contract as the former per-timestamp Python sort" was
   a claim with no test behind it. It is now verified by 84 differential cases;
   the comment stands.
2. *Comment described an unreachable mechanism.* "then short weights override on a
   repeated symbol" describes head/tail overlap, which `max(minimum_assets,
   long + short)` makes structurally impossible for distinct symbols, and which
   for duplicate rows always breaks the neutrality sum. Comment tightened to say
   what is actually reachable.
3. *Dead constant* `FORBIDDEN_ROOTS = ('/',)` in the benchmark harness — unused,
   removed (Speculative Generality).
4. *Duplicated magic tolerance*: `1e-12` now appears both as
   `_NEUTRALITY_TOLERANCE` here and literally in `src/engine/funnel.py`. Pre-existing
   cross-module duplication; not changed in this PR (out of scope, tracked).
5. *Module docstring claimed "the fingerprint is the equivalence contract"* while
   only the last repeat was fingerprinted. Now enforced per repeat.

### Spec axis

Against the PR body and the supervisor's acceptance criteria, at PR head:

* Original-vs-new equivalence: **missing** (no oracle, no bit-level comparison,
  one small synthetic case only). → added.
* Coverage of ties, dtypes, aliases, duplicates, cadence, timezone, empty inputs:
  **partial**. → added.
* Four benchmark sizes with 5 repeats, environment and workload identity, negative
  control, per-repeat fingerprints: **missing** (one case, two repeats, last-repeat
  fingerprint only). → added.
* Realism defect (epoch clock vs 2025 train start): **present** and fixed.
* Report: **missing**. → this document.
* Scope creep: none found — the diff touches only the allocator and its harness.

---

## 10. Does this change production throughput?

No — not by itself, and the report must not be read as a claim that it does.

* The allocator is one phase of a funnel dominated by data load, feature
  compilation with prefix-invariance checks, diagnostics and the native
  simulation (see §8).
* The hourly ATS runner is a *pull* CLI: `scripts/research_inbox_queue.py
  start|resume` walks candidates **sequentially** (`InboxQueue.run` iterates the
  admitted list, no worker pool), each trial bounded by
  `--max-runtime-seconds` (default 3600) and intake bounded by `--max-candidates`.
  Realized throughput per hour is therefore set by queue invocations, candidate
  arrival in the inbox, and the per-trial budget — not by allocator speed.
* Allocator speedup must not be converted into "strategies per hour": a 40–108×
  allocator gain on a phase that is a sub-percent share of a trial changes
  end-to-end trial time by roughly that share. §8 quantifies the share honestly.

---

## 11. Limitations

* Host noise: load average 10–15 during benchmarking; control drift up to +36%.
* The development vault used for §8 is price-only and carries **no**
  execution-qualified cost/carry adapter, so native execution was not run; the
  repository forbids it and it is reported as blocked rather than proxied.
* Three documented allocator divergences remain (§12). None changes a successful
  allocation; all are on malformed (duplicate-symbol) inputs.
* Fuzz coverage is 40 seeded panels, not an exhaustive proof of equivalence.
* `tests/test_dual_mode_*.py` and the wider suite depend on an external pinned
  connector checkout that is absent locally; those results are reported as
  environment-blocked with a baseline reproduction, not silently skipped.

---

## 12. Documented divergences (exact, asserted, not xfail)

These are asserted *exactly*: the harness fails if the observed difference is not
precisely the recorded one, so a new change cannot hide behind these entries.

| Case | Exact expected difference | Why it is acceptable |
| --- | --- | --- |
| `duplicate_symbol_ineligible_twin` | `EXC_TYPE`: `TypeError` → `QuantError(INVALID_ALLOCATION)` | The former loop crashed dividing a float by a `None` ATR for a weighted duplicate row; the pipeline raises the module's own domain error. Both abort; the duplicate row is already an upstream contract violation. |
| `duplicate_symbol_weighted_null_close` | `EXC_TYPE`: `TypeError` → `QuantError(INVALID_ALLOCATION)` | Same class change for a `None` close. |
| `error_precedence_across_timestamps` | `EXC_MESSAGE`: `Non-positive or unrepresentable ATR stop` → `Market-neutral target failed`, same `INVALID_ALLOCATION` status | The former loop interleaved the stop check with the per-timestamp neutrality check; the vectorized path checks neutrality globally first. Only reachable through duplicate symbols (the eligibility filter makes an out-of-range stop unreachable for a well-formed section). |

---

## 13. Merge conditions

* All §7 gates pass or are reproduced as pre-existing/blocked on the baseline.
* Final head re-verified after the commit (differential oracle + edge-contract
  tests re-run on the committed tree).
* Supervisor acceptance of the three documented divergences in §12.
* No merge is performed by this work unit.
