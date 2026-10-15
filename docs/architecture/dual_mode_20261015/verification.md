# Dual-mode runtime verification — 2026-10-15

## Result and scope

The new dual-mode runtime is implemented in this isolated worktree. The combined
non-data/non-slow regression passed **400 tests**, with no failures. The separate
real BTC/ETH development-data regression passed **1 test**. This is not a claim
that every legacy strategy has been migrated or that the full 530-symbol matched
universe has been capacity-qualified.

Original checkout: `/home/quant/dev/quant/quant-research` (read-only).
Implementation worktree: `/home/quant/.devspace/worktrees/quant-research-25440f7a`.
Base implementation checkpoint: `bc5a595e1f9129698e8cd024ca6fa07d97e635b6`.
Branch: `feat/rebuild-20261015-governed-core`.
No broker request, trading order, deployment, push, or merge was executed.

## Commands and actual outcomes

Use the original installed interpreter without modifying its environment:

```bash
export PYTHONPATH=/home/quant/.devspace/worktrees/quant-research-25440f7a
export PYTHONDONTWRITEBYTECODE=1
PY=/home/quant/dev/quant/quant-research/.venv/bin/python
```

| Verification | Actual result |
| --- | --- |
| `uv lock --offline` | Resolved 159 packages; updated lockfile, no installation or upgrade. |
| Existing-environment `ruff check src/engine src/data_vault src/oracle src/workbench.py scripts/quant.py tests/dual_mode_fixtures.py tests/test_dual_mode_*.py` | All checks passed. |
| `$PY -B -m pytest -q -n 2 --dist worksteal -m 'not data and not slow' --junitxml=.workspace/dual-mode-20261015/fast-tests-final.xml tests` | **400 passed**, 12 warnings, 115.54 seconds. |
| `$PY -B -m pytest -q -s -n 0 --junitxml=.workspace/dual-mode-20261015/real-smoke-final.xml tests/test_dual_mode_real_store.py` | **1 passed**, 3 warnings, 3.43 seconds. |
| `$PY -B scripts/quant.py validate config/candidates/crypto_xs_funding_velocity_dislocation_basket_v1.example.yaml` | `VALID_SPEC`; explicitly `prompt_derived_example`, not the missing original candidate. |
| `git diff --check` | Passed. |
| Recompute SHA-256 for all 505 original inventory files | **505 checked; zero mismatches**. |
| Compare imported original `tests/conftest.py` and `src/strategies/independent_seven_data.py` to source bytes | Both **byte-identical**. Original copies remain unchanged. |

The fast-lane warnings were six SHAP colormap deprecations (two workers), three
SHAP/LightGBM output warnings, two exchange-calendar/NumPy warnings and one
existing `src/features/spillover.py` sortedness warning. The real smoke had the
three SHAP import warnings. No failure assertion was suppressed.

The non-data/non-slow selection excludes data-dependent and long-running legacy
research. It is not an unfiltered full-suite result or a run of protected market
history. Previously missing support files were imported byte-identically so
legacy modules now collect; the fast suite did not exclude those modules to hide
collection errors.

## New tests and what they establish

- `test_dual_mode_core.py`: native/custom feature execution, exact prefix checks,
  negative future-lag/global-normalization/future-membership checks, input-order
  invariance, neutral allocation, development-only loading, native next-open
  netting, settlement timing/sign, entry-bar stops, constant-signal rejection.
- `test_dual_mode_isolation.py`: actual Bubblewrap worker computes native features,
  cannot read a host-side protected sentinel and cannot reach the host network.
- `test_dual_mode_funnel.py`: an actual native positive four-stage synthetic run,
  repeated-claim/read rejection and tampered evidence; an actual CLI negative
  Stage 2 run exits zero without Stage 3; Workbench YAML and Python-artifact
  export/replay with tampering rejection. Positive numerical tests do not mock
  the gates into PASS.
- `test_dual_mode_ingestion.py`: consolidated raw-store discovery, timestamp jitter,
  marked funding proxies, observed-only missing marks, missing funding rejection,
  retaining earlier history when a later settlement is absent, naive-timezone
  rejection, and a New York DST CFD cash-session fixture.
- `test_dual_mode_execution_edges.py`: opening exits precede later intrabar stops,
  adverse gap-open stop fills, fixed absolute stop levels across resizing,
  missing held-symbol quotes do not silently use stale prices, and costs reconcile.
- `test_dual_mode_integrity.py`: four concurrent claim requests produce one winner;
  false validation checks are denied; failed protected reads consume the claim;
  development-to-protected manifest redirection, altered panel bytes, YAML eval
  attempts and missing manifests produce explicit outcomes. Receipt fixtures in
  this module test storage mechanics; numerical qualification is tested separately.
- `test_dual_mode_real_store.py`: actual native accounting and timing on a bounded
  historical development-data slice, not a strategy-performance claim.

## Real source regression

The canonical fixture is `data/vault/runtime_smoke_20261015_v2`.
Manifest identity:
`061e3e8c600fa20e85eacb62d2488cd1bd0b8d2d4897d22cf62f72ecf6881a00`.

Observed scope: BTCUSDT_PERP and ETHUSDT_PERP; `[2025-01-01, 2025-01-08)`;
**336 hourly price rows**, **42 funding events**, **168 native equity timestamps**,
**4 native fills**. The fixture deliberately uses simple manual targets to test
runtime mechanics, not the missing funding-velocity strategy.

Commission was 5 basis points one-way and slippage 4 basis points one-way.
Settlement marks were missing in the source slice and were explicitly labeled
trade-open proxies. Original funding timestamps had millisecond boundary jitter;
the declared 1000-ms tolerance and modeled pre-opening cashflow policy were
recorded. These are model assumptions, not measured venue execution.

Independent vectorized reconciliation found maximum equity error
`2.9103830456733704e-11`, below tolerance `1.0120620257422263e-05`, and maximum
funding cashflow error `0.0`. All timing records matched signal availability to
the next opening fill. No protected file was read.

Latest evidence from the final real run:
`run_log/dual_mode_runtime_smoke/20261015T111058974161/verification.json`.
Native fills, funding transfers and equity are saved alongside it. The failed
initial v1 fixture was retained; the successful v2 fixture did not overwrite it.

## Implementation environment

Observed: Python 3.14.6 on Linux; Polars 1.44.2; ML4T Engineer 0.1.4;
ML4T Diagnostic 0.1.6.post2; ML4T Backtest 0.1.7; Pydantic 2.13.5;
PyArrow 25.0.1; NumPy 2.5.3; SciPy 1.18.1; Cloudpickle 3.1.2;
exchange-calendars 4.13.2. The project lock binds the current dependency graph.
The native private lifecycle adapter explicitly requires Backtest 0.1.7.

The runtime source/environment identity in the final real report is
`75865529f7df7eb00e0fcd94952fad15c33cb1c9366ae89429f4dabbfd3f777b`.
Hashes identify the tested snapshot; they are not independent proof of correctness.

## Defects exposed and corrected during this work

1. Native fixed-horizon labeling rejected the final null next-opening price.
   The diagnostic now drops that censored entry, uses the actual native output
   name and restricts label construction to train history.
2. The sandbox initially launched an unresolved venv interpreter symlink.
   It now launches the real interpreter and explicitly supplies mounted packages.
3. Actual source funding timestamps did not all exactly equal bar boundaries,
   and mark prices were absent. The data adapter now records an explicit jitter
   policy and mark-proxy policy rather than silently losing events or inventing
   observed marks.
4. Native EXIT_FIRST ordering initially let a later intrabar STOP displace a
   scheduled opening market exit. The causal native phase adapter now separates
   opening gap stops, opening deltas and later intrabar stops. Its red regression
   passed after the correction.
5. The AGENTS rewrite initially removed two required legacy policy links. The
   links were restored, with a distinction between the old ResearchPhase names
   and the new factory Stage names. The tests were not weakened.
6. Naive source timestamps could otherwise be cast to UTC. Both raw-footer and
   canonical-frame checks now require an explicit source timezone.

## Remaining qualification limits

- The exact requested funding-velocity YAML was not supplied or found. The
  checked `.example.yaml` has explicit invented-for-example formulas; no exact
  original-candidate run is claimed.
- Source discovery found 864 consolidated hourly symbols and 530 matching
  funding directories. A full 530-pair compile, long-history backtest and memory/
  CPU capacity qualification were not executed.
- Old strategy-specific modules and runners remain until equivalent strategy
  adapters and behavior-parity evidence exist. The migration map is not a claim
  that those cutovers were performed.
- The current vault supplies immutable historical snapshots and provenance,
  not a reconstructed bitemporal vintage database. Source survivorship coverage
  and original historical release latency remain separate, incomplete evidence.
- Three cutoff comparisons are empirical checks, not universal mathematical
  proof. The worker is isolated; the owner and host notebook are not sandboxed.
- The positive protected evaluation used synthetic data only. No real protected
  market history was evaluated. Existing prior exposure to 2026 remains disclosed.
- DSR is selection-family scoped with available aligned returns, not an invented
  complete global correction over all legacy research histories.
- Asymmetric CFD swaps, full broker calendars, liquidation, queue priority,
  arbitrary old stop-entry strategies and live execution are not qualified by
  this implementation. Funding timestamp and mark proxy assumptions remain visible.
- Coding-agent providers were unavailable or stalled; final implementation and
  verification were performed directly through DevSpace. No independent agent
  review is claimed where a provider failed to run.
