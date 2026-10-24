# ATS time-series allocator vectorization — 2026-10-22

**Original PR #92 verdict (Oct 22):** merge-ready on synthetic and contract
evidence. That was the submitted-head assessment and is superseded by the
independent requalification in §8.

**Independent requalification (Oct 24):** eligible for merge review after the
collision fix in `c26d3a133c5823b2e912524c15fffe8a6856d6c2`. The broader
non-data/non-slow lane still has four unrelated collection/environment
failures, and full ATS trial throughput remains unmeasured. No merge performed.

Qualification used development partitions only, with the loaded panel ending
before the protected-window start. No protected partition, holdout, casefile,
ledger, broker or live-order path was read or written.

---

## 1. What changed

`src.engine.ts_allocator.allocate_ts` used to rebuild a Polars `DataFrame` view
and run `filter`/`partition_by` once per rebalance. For the 192×3000 synthetic
case that is 3000 small query plans and ~11 s of planner overhead.

The refactor evaluates the cadence schedule, the eligibility expression and the
output frame **once** with Polars, then walks rebalances over pre-extracted
columns. All financial arithmetic is unchanged and still runs in Python on the
same values in the same order:

* `capped_budgets` (water-filling), `_raw_budgets` and the gross/neutrality
  checks are byte-for-byte the same code, refactored to accept lists;
* `_eligible_expr` is the same predicate, evaluated once instead of per block;
* weights are looked up for **every** row of a rebalance, so a repeated
  `(timestamp, symbol)` row keeps its twin's assignment, exactly like the former
  per-symbol dict applied to the whole block;
* rebalances are traversed in first-appearance order, so error-message
  precedence matches `partition_by(maintain_order=True)` on an unsorted panel.

No ranking, eligibility, cap, stop, cost or gate rule changed.

## 2. Source identity

| Item | Value |
| --- | --- |
| Base (`origin/main` at branch point) | `9771b7372e9be950193c121708e1fd65fada6142` |
| Implementation commit | `b8dfaddc95cf6f486c52f92e0970b0630729dd01` |
| Head with contract tests | `8374aa0bf0d911600754327fccab1e3d0855adbb` |
| Original `ts_allocator.py` blob | `eeb7042ea8c1cc5d5a8db5b962135057974ee6d6` |
| Original `ts_allocator.py` sha256 | `11a1598c06203558e131ae646d1204891ba83c26123183fc526919538e0c1f1c` |
| Interpreter / libraries | Python 3.14.6, polars 1.44.2, numpy 2.5.3, `POLARS_MAX_THREADS=8`, AMD EPYC 8 vCPU |

The differential oracle asserts the original blob and sha256 before importing
it; any drift is a hard error.

## 3. Equivalence (bit-level)

`scripts/qualify_ats_ts_allocator_equivalence.py` imports the **actual original**
from git (not a re-implementation) and compares, in order: exception type,
`QuantError.status`/`reason`, ordered schema, row count, and every column as raw
IEEE-754 bits (`uint64` view) or exact timestamp ticks.

**81/81 cases bit-identical; 0 documented divergences; 0 unexplained failures.**

Coverage: all four risk methods; loose/binding/multi-round/impossible caps;
warm-up hold-flat; forecast/stop/vol extremes (null, NaN, ±inf, subnormal,
stop-distance boundary); gross scaling; cadence (hourly, 3-bar, 24-bar,
off-anchor, empty); µs/ns/naive/sub-µs timestamps; Float32/Int64 inputs;
shuffled row order; duplicate `(timestamp, symbol)` rows; cross-timestamp error
precedence; 24 seeded fuzz panels.

Two divergences existed in an earlier candidate of this refactor and were
removed rather than accepted: the ineligible duplicate twin now inherits its
twin's assignment, and error precedence follows first appearance. The oracle no
longer carries an accepted-divergence list.

Reproduce:

```
PYTHONPATH=$PWD /home/quant/dev/quant/quant-research/.venv/bin/python -B \
    scripts/qualify_ats_ts_allocator_equivalence.py --json <out>.json
```

## 4. Synthetic throughput

`scripts/benchmark_ats_allocators.py` was extended with `--allocator original-ts`
and `--subject`, so the pinned original and the worktree implementation run in
the **same interpreter, same process, same workload**. Each case: 1 warm-up +
5 timed repeats; every repeat is fingerprinted. Reports are committed as
`before.json` (original, clean tree at `b8dfaddc`) and `after.json` (head, clean
tree at `8374aa0b`).

| case | rows | before min/median ms | after min/median ms | median speedup | CV before/after | fingerprints |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| ts_small | 6 400 | 438.65 / 640.89 | 13.04 / 15.17 | **42.2×** | 16.1% / 11.6% | identical |
| ts_medium | 96 000 | 2 748.13 / 3 065.85 | 89.42 / 106.36 | **28.8×** | 11.6% / 10.2% | identical |
| ts_large | 576 000 | 10 284.10 / 10 693.17 | 556.40 / 579.13 | **18.5×** | 7.5% / 8.3% | identical |
| ts_medium_daily | 4 032 out | 83.39 / 110.09 | 10.52 / 13.12 | **8.4×** | 14.0% / 33.9% | identical |

* Fingerprints are identical for all 8 cases × 5 repeats in both blocks, and
  `repeats_identical=true` for every case.
* `signal_*` is the negative control (unchanged by this work unit). Its medians
  moved 0.3×–1.1× between blocks, so the host noise floor is large in relative
  terms; the time-series gain is far outside it.
* The measurement host was **not quiet** (load average 15.4 before, 13.1 after,
  with unrelated validation jobs on 8 vCPUs). Absolute medians are comparable
  only within this pair; treat the speedups as robust in order of magnitude, not
  as a production benchmark.
* The daily-cadence case is small in absolute time and therefore the
  noisiest (33.9% CV after).

Reproduce:

```
PYTHONPATH=$PWD POLARS_MAX_THREADS=8 <py> -B scripts/benchmark_ats_allocators.py \
    --repeats 5 --allocator original-ts --json before.json
PYTHONPATH=$PWD POLARS_MAX_THREADS=8 <py> -B scripts/benchmark_ats_allocators.py \
    --repeats 5 --json after.json
PYTHONPATH=$PWD <py> -B scripts/benchmark_ats_allocators.py \
    --compare before.json after.json
```

## 5. Checks

| Check | Result |
| --- | --- |
| `pytest tests/test_ts_allocator.py tests/test_ts_allocator_contract.py tests/test_ts_allocator_edge_contracts.py tests/test_dual_mode_core.py tests/test_signal_allocator_contract.py tests/test_ats_allocator_edge_contracts.py` | **97 passed** |
| differential oracle | **81/81 identical, 0 failures** |
| `ruff check` on the two changed production files, harness, oracle and two test modules | **passed** |
| `git diff --check` | **passed** |

## 6. Limits

* Synthetic panels only; no development vault, no pipeline composition and no
  native order simulation. Allocator share of a full trial is not re-measured
  here; PR #89 measured it at 0.72% → 0.06% on a development feature panel, and
  this change does not alter that conclusion.
* The benchmark host was shared and loaded; see §4.
* Equivalence is exact on the 81-case matrix and 24 seeded fuzz panels, not a
  formal proof for arbitrary programs.
* No protected partition was opened and no holdout claim was reserved.

## 7. Deliberately not done: scheduler concurrency, phase telemetry

**No scheduler concurrency was introduced.** The allocator is called once per
candidate inside a sequential pull queue (`InboxQueue.run` walks admitted
candidates; `--max-runtime-seconds` bounds each trial). Parallelising
rebalances inside `allocate_ts` would not remove the remaining cost, which is
the per-rebalance Python budget loop; that loop is GIL-bound, order-dependent
for compensated `sum()` and water-filling, and defines error precedence. A
thread or process pool would therefore add scheduling noise and a new
determinism surface while changing neither the declared gross exposure nor the
emitted frame. Queue-level concurrency is the credible next step, but it needs
isolated run directories, per-trial resource budgets and a trials-per-hour
acceptance metric, not an allocator microbenchmark. It is out of scope here.

**No production phase-timing API was added.** Timing hooks inside the allocator
would create a new public surface for no scientific gain; the immutable
casefile and trial ledger remain untouched. Diagnostics stay in the benchmark
harness and in `cProfile` on a development panel. If phase telemetry is later
required, add it as an explicit opt-in argument with a contract test that proves
the emitted frame and fingerprints are unchanged.

**Next benchmarks (not run here):**

1. Scale the synthetic universe to 500 symbols and 5–10 years of hourly bars to
   locate the per-rebalance Python loop's scaling knee (the current largest case
   is 192×3000).
2. Time the three phases separately on a development feature panel
   (schedule + eligibility, per-rebalance budgets, output construction) rather
   than inferring them from the end-to-end delta.
3. Measure peak memory and chunking for native 1-second panels, where row counts
   are two to three orders of magnitude larger.
4. Evaluate queue-level concurrency end to end (trials/hour, isolated run
   directories, per-trial budgets), with the allocator held fixed so the result
   is attributable to scheduling rather than to this refactor.

This work unit does **not** claim a production trials-per-hour improvement.
The independent development-panel run in §8 estimates a 2.63% reduction in the
feature-to-target component sum; the complete trial, including native
simulation and downstream gates, was not timed. PR #89 measured the
cross-sectional allocator at 0.72% of a development pipeline before its own
optimization, and this time-series allocator's share of a full trial remains
unmeasured.

## 8. Independent requalification (2026-10-24)

### Source review and compatibility fix

The submitted allocator matched the original on the documented arithmetic,
duplicate `(timestamp, symbol)` assignment behavior and first-appearance
rebalance error precedence. Independent execution found one input-compatibility
regression: `with_row_index('_row')` raised Polars `DuplicateError` when an
otherwise valid feature panel already carried an unrelated `_row` column. The
original allocator returned the expected rows. The same class of collision
could occur for `_ats_row_index` and `_ats_eligible`.

Follow-up commit `c26d3a133c5823b2e912524c15fffe8a6856d6c2` chooses internal
names absent from the scheduled input columns. Three regression cases and one
differential-oracle case cover those collisions. Financial arithmetic and
eligibility rules are unchanged.

### Correctness and regression evidence

The oracle pins the original allocator blob and SHA-256 listed in §2, imports
that source from git, and compares ordered schema, row count, exception type,
`QuantError` status/reason, exact float64 bit patterns, and exact timestamp
ticks. After adding the collision case, **82/82 cases were bit-identical**, with
zero divergences and zero failures. This includes the 24 seeded fuzz panels,
duplicate-row semantics, shuffled inputs, extreme and null values, and
rebalance-order error precedence.

The focused allocator/engine regression group passed **100 tests**, with six
SHAP deprecation warnings. All **92 allocator/engine-related cases** in the
broader non-data/non-slow lane passed. That lane reported 1,044 passed, 6
skipped, 2 failures and 2 collection errors among 1,054 cases: the collection
errors were missing `connectors` in `tests.test_ats3_audit_broker` and
`tests.test_ats7_faults`; the failures were `JOB_VISIBILITY_UNKNOWN` in two
`tests/test_managed_rebuild` cases. Those four results do not touch the
allocator, but the broad lane is not green. Ruff checks for the allocator,
oracle and edge-contract tests passed, as did `git diff --check`.

### Development-only composed workload

The benchmark used the existing `af30_s01_buy_hold_single` TimeSeriesSpec and
its index 1-hour development vault. `DataVault.load()` opened 348 development
files and produced a 146,789-row, six-instrument panel from 2020-03-31 10:00
UTC through 2024-12-31 23:00 UTC. The panel's latest timestamp was before the
spec's protected-window start; every opened file was under `/development/`.
The development manifest SHA-256 was
`8939586c7e2b39ea87f2540c12f76c8ff882d330febfc3cdbfc36dfbaaad3711`. The
schedule contained 168 target rows. The optimized result matched the pinned
original exactly.

| Component | Original | Vectorized | Evidence |
| --- | ---: | ---: | --- |
| Cold development-vault load | 1,902.79 ms | 1,902.79 ms | one observed load |
| Causal feature compile with prefix checks | 384.44 ms | 384.44 ms | one observed compile; 3 cutoffs passed |
| Allocator | 67.61 ms | 5.65 ms | median of 5 alternating calls; **11.97×** |
| Feature-to-target component sum | 2,354.84 ms | 2,292.88 ms | derived from the components above; **2.63% lower latency** |

The 2.63% result is a component-summed estimate for this pre-simulation
workload, not an observed full-trial throughput change. The corresponding
1.027× throughput ratio is a projection that assumes later trial costs remain
fixed. Native PnL, carry/execution qualification, Stage 3, holdout and trading
paths were not run; no protected data was accessed. The evidence supports a
real allocator speedup and a modest development-path reduction, but does not
establish a production trials-per-hour gain.
