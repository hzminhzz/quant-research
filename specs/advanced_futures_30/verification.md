# Verification: Advanced Futures 30 time-series sleeve route

> Milestone `v0.1 - Advanced Futures 30 time-series sleeve research`.
> Deployment status: **NOT_APPROVED**. Nothing here authorizes live orders,
> broker credentials or a paper-trading harness.

## How to reproduce

```bash
uv run pytest -m "not data and not slow"   # standard data-free suite (CI fast-tests)
uv run pytest                              # full suite; see note below
uv run ruff check src/engine src/oracle src/data_vault src/workbench.py \
    scripts/quant.py tests/test_ts_*.py tests/test_carry_model.py \
    tests/test_cost_qualification.py tests/test_compatibility_matrix.py \
    tests/test_sleeve_specs*.py tests/test_sleeve_execution.py \
    tests/test_non_sleeve_dispositions.py tests/test_combined_portfolio.py \
    tests/test_protected_read.py tests/test_evidence_manifest.py
uv run python scripts/check_managed_features.py
git diff --check
uv run python scripts/quant.py validate config/sleeves/advanced_futures_30/af30_s06_slow_trend_long_short.yaml
uv run python scripts/quant.py run config/sleeves/advanced_futures_30/af30_s06_slow_trend_long_short.yaml \
    --development-only --run-log /tmp/afs30
```

Repository-wide `ruff check .` still reports pre-existing findings in archived
notebooks and legacy runners; the project's CI has always scoped ruff to
`src/managed_strategies` and the managed-feature AST policy. The milestone
surface listed above is clean.

The full suite has one pre-existing environment-dependent data test that fails
against the local `ml4t-data` store:
`tests/test_catalog.py::test_current_canonical_index_aliases_are_accepted_cfds`
expects US30 to resolve only through a non-canonical source, and the mounted
store no longer matches. It is unrelated to this route (`src/catalog` is
untouched), and CI skips data tests when the external store is absent. The
data-free suite passes.

## Spec acceptance criteria

| AC | Criterion | Evidence | Status |
|---|---|---|---|
| AC1 | Time-series spec form, strictly additive | `src/engine/ts_spec.py`; `tests/test_ts_spec.py` (16 tests); `quant.py validate` dispatch | VERIFIED |
| AC2 | Atomic pre-reservation failure | `tests/test_cost_qualification.py::test_rejected_qualification_writes_no_artifact_and_consumes_no_claim`; `tests/test_protected_read.py` (crash consumes the claim) | VERIFIED |
| AC3 | 25 sleeve specs and a predeclared class matrix | `config/sleeves/advanced_futures_30/af30_s*.yaml` (25); `compatibility.yaml` frozen at sha `55a2a781...`; `tests/test_compatibility_matrix.py` | VERIFIED |
| AC4 | Every book item has a terminal disposition | 25 sleeve dispositions via the runner; `non_sleeve_dispositions.yaml` for 24, 25, 28, 29, 30; `tests/test_non_sleeve_dispositions.py` | VERIFIED |
| AC5 | Sleeve casefile with proof, costs, carry, gates, disposition, hashes | `src/engine/ts_casefile.py`; `tests/test_ts_casefile.py` (9 tests) | VERIFIED |
| AC6 | Reproducible verdicts | `tests/test_ts_gates.py::test_evaluate_class_composes_and_is_deterministic`; `tests/test_ts_allocator.py::test_allocation_is_bit_identical_across_runs` | VERIFIED |
| AC7 | No pooled cross-class PnL | `tests/test_ts_gates.py::test_class_dsr_is_scoped_to_one_class`; `tests/test_combined_portfolio.py` (per-class series) | VERIFIED |
| AC8 | Per-class DSR over aligned trials | `src/engine/ts_gates.py::class_dsr`; `tests/test_ts_gates.py` (alignment, zero-variance exclusion); `dsr_inputs.parquet` columns equal ledger trials in `tests/test_sleeve_execution.py` | VERIFIED |
| AC9 | Declared costs and carry, no zero placeholders | `src/engine/carry_model.py`; `tests/test_carry_model.py` (11 tests); `tests/test_cost_qualification.py` | VERIFIED |
| AC10 | Seven qualification gates | `src/engine/ts_gates.py`; `tests/test_ts_gates.py` boundary tests (0.299/0.30, 0.49x/0.50x, 0.949/0.95, 1.99/2.0, 0.25/0.26, strict train positivity) | VERIFIED (mechanism). Real-data qualification is BLOCKED: mixed-session indices hold a symbol without an opening observation, metals lack a lease proxy, crypto panel not materialized |
| AC11 | Combined portfolio from qualified sleeves under a frozen rule | `config/sleeves/advanced_futures_30/portfolio_rule.yaml`; `src/engine/combined_portfolio.py`; `tests/test_combined_portfolio.py` (non-qualified rejection, exact weights, hashed record) | VERIFIED (mechanism). Real composition is BLOCKED because no sleeve is QUALIFIED on development data |
| AC12 | One protected read, reserved before reading | `src/engine/holdout.py`; `tests/test_protected_read.py` (reservation, success, crash, rule drift, sleeve guard) | VERIFIED (mechanism). Live read is BLOCKED: no composed portfolio and no protected partition materialized (`data/vault/markets_20261015/*/protected` absent) |
| AC13 | v1 spec and route unchanged | `tests/test_dual_mode_*.py`; v1 candidate hashes recorded in `evidence_manifest.json` and re-checked by `tests/test_evidence_manifest.py` | VERIFIED |
| AC14 | Trial accounting: variation vs new trial | `src/engine/ts_casefile.py::classify_gate_change`; `tests/test_ts_casefile.py` (post-outcome change invalidates the verdict) | VERIFIED |

## Real development execution (current checkout)

| Class | Outcome for all 25 specs | Named reason |
|---|---|---|
| indices | `BLOCKED_DATA` | a held symbol has no opening observation at a native instant; the qualified execution model forbids stale marks |
| metals | `BLOCKED_DATA` | no defensible lease-rate proxy for XAUUSD/XAGUSD; modeled carry is not zero-filled |
| crypto | `BLOCKED_DATA` | `data/vault/crypto_perps_1h` is not materialized |

The pipeline, casefile, gate and DSR mechanisms are exercised end-to-end on
synthetic development panels by `tests/test_sleeve_execution.py`, which proves
every one of the 25 variants reaches a terminal disposition, casefiles carry a
gate table, and each class's DSR input set equals the ledger's aligned trials.
No protected partition was read.

## Evidence inventory

`evidence_manifest.json` records the sha256 of every route artifact and the
spec hash of every v1 candidate; `tests/test_evidence_manifest.py` fails if any
of them drifts. The DSR inputs, portfolio series and holdout outputs are
produced under `run_log/` and are not committed.
