# Rebuild verification and acceptance boundary - 2026-10-15

## Decision

Verified partial implementation. NOT a completed repository migration, research
qualification, production release, or trading authorization. Changes are isolated
on `feat/rebuild-20261015-governed-core` at
`/home/quant/.devspace/worktrees/quant-research-25440f7a`.
Base: `9525f35667bf439781bff19edd0c9681da0b7080`.

The original checkout at `/home/quant/dev/quant/quant-research` stayed read-only.
A final SHA-256 comparison of all 505 original src/scripts/config paths against
`inventory.md` found 505 unique paths and ZERO mismatches. The original HEAD and
four previously modified tracked files are unchanged. No market-research trial,
protected-holdout inspection, broker request, order, deployment, or dependency
upgrade was performed. Statistical permutation verification used synthetic arrays,
not 500 market backtests.

## Actual implementation

- `src/strategies/base.py`: required StrategyPlugin methods and explicit native
  capability surface. `synthetic_bracket.py` is the sole registered adapter.
- `src/pipeline.py` and `scripts/research.py`: an actually executable frozen
  synthetic path through certificate, FeatureGateway, existing RunPermit,
  AttemptLedger, native ML4T engine, and independent fill audit. Existing CLI
  commands remain. Stage completion no longer implies production readiness.
- `src/data_plane/catalog.py` exposes one implementation in `certificate.py`.
  Hashes bind data, catalog, policy, schema, calendar and timezone bytes. Supported
  exchange schedules, revision clocks, as-of selection, grid checks, stale proof,
  OHLC and declared source semantics are checked on bounded in-memory frames.
  This does not migrate the entire source catalog or physically isolate I/O.
- `src/features/` preserves legacy imports and adds native FFD, explicit trade-sign
  and book-imbalance inputs, signed semivariance/jump-proxy, and availability-aware
  cross-session helpers. These are opt-in helpers, not approved FeatureGateway
  additions and not evidence of alpha.
- `src/validation/` preserves legacy imports. The development oracle uses native
  CPCV splits, interval purge/embargo, correct split/group path incidence, native
  DSR/effective-rank and PBO, and full-callback target-block permutations.
  It returns INCONCLUSIVE: ledger coverage is still caller-attested; actual OOS
  return-path distributions, joint IC/net-Sharpe endpoints and chronological
  evidence are not integrated. Diagnostic threshold pass is a separate field.
- `src/portfolio/barrier_controller.py` exposes a pure bounded sizing policy with
  residual loss reserves, fractional Kelly, floor/target taper, notional bounds,
  stale-state checks and Prague midnight handling. It is research-only, not a
  Bellman solution, order router, complete FTMO evaluator, or zero-breach guarantee.
- `src/synthesis.py` removes fabricated comparison Sharpes and the positive-single-
  trial DSR=1 shortcut. Scalar-only legacy evidence is INCONCLUSIVE.
- AGENTS documents the transition and current capabilities; CLAUDE delegates to
  AGENTS and no longer contains remote credentials.

## Supervisor corrections after worker review

1. General CPCV path construction uses (split, test-group) segments, not whole-fold
   tiling. N=5,k=2 and N=6,k=3 are tested. These remain assembly metadata until
   actual OOS returns are integrated.
2. Perfect diagnostics cannot authorize a strategy with incomplete provenance.
   A synthetic regression performs one observed callback plus 500 permutation
   callbacks and still requires INCONCLUSIVE with explicit blockers.
3. Strict p<alpha, not p<=alpha. PBO score ties are rejected rather than assigned
   potentially arbitrary success through column ordering.
4. Unsupported real-market products and escaped config/data paths are rejected
   before loading data. A regression test first failed on the old ordering and
   passed after correction.
5. Runtime source-policy enum checks reject unknown values even when a supplied
   catalog repeats those values. Type hints alone are not validation.

## Reproducible commands and observed results

Run from this worktree; do not substitute the original checkout as PYTHONPATH.

```bash
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/quant/.devspace/worktrees/quant-research-25440f7a
PY=/home/quant/dev/quant/quant-research/.venv/bin/python

$PY -B -m pytest -q -n 2 --dist worksteal -p no:cacheprovider \
  -m 'not data and not slow' \
  --ignore=tests/test_catalog.py \
  --ignore=tests/test_milkman_extended_calendar_20261014.py \
  --ignore=tests/test_milkman_native_engine_20261014.py tests

$PY -B -m marimo check notebooks/quantified_strategies_engulfing.py
git diff --check
```

Final non-data/non-slow regression: **360 passed, 12 warnings, 38.55 seconds**.
Marimo: **exit 0, no output/warnings**. Diff whitespace check: **exit 0**.
Warnings are installed SHAP/LightGBM and exchange-calendar deprecations plus the
Polars grouped-asof sortedness notice. They were disclosed, not suppressed.

An earlier focused run before the last enum/data-open regressions completed with
78 passed and 6 warnings. The final 360-test run includes the subsequent fixes.

The UNFILTERED full suite is NOT qualified. Initial collection lacked
`tests/conftest.py`. A broader earlier run excluding its consumer produced
352 passed, 2 skipped, one subsequently fixed old features.py path assertion,
and two collection errors for `src/strategies/independent_seven_data.py`.
Both support files exist only as nonignored untracked files in the original
checkout; they were inspected, not copied or silently added as rebuild work.
The three exclusions above are those known import-dependent test modules, not
suppression of new failing assertions. No protected/data tests were enabled.

## Unfinished acceptance gates

- Migrate the five strategy/vendor implementations out of research_control;
  migrate each actual strategy into the unified runner and prove native parity.
  Current real strategies and historical runners were NOT deleted.
- Complete ingestion-time schema/session-field migration and certification of
  actual catalog stores; current certifier is bounded to 100,000 supplied rows.
- Wire and approve opt-in features in FeatureGateway, and complete the requested
  new label-volatility/native uniqueness/time-decay training integrations.
  Existing models/labeling behavior was preserved, not claimed as upgraded.
- Build the derived global ledger index, verify complete candidate cohorts,
  assemble actual OOS return paths, bind both endpoints/multiplicity and attach
  chronological validation. Only then replace unconditional INCONCLUSIVE.
- Qualify actual risk integration, product-specific policies and broker behavior
  separately. No live portfolio control was installed.
- Reconcile legitimate original untracked dependencies into a reproducible base
  and pass the full regression/cutover gates before merge or deployment.

## Executor state

OpenCode completed the initial implementation and revisions, then reached its
provider usage limit. A bounded Codex fallback failed with PROVIDER_EXECUTION_ERROR.
The supervisor directly repaired the remaining approval and pre-read defects and
ran the final checks above. No implementation worker remains active. No push,
merge, issue closure, or production cutover occurred.
