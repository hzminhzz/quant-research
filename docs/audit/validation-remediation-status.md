# Validation Remediation Status

**Strategy:** `multi_asset_eow_orb_meta_gate`  
**Current status:** `NOT_APPROVED`  
**Scope:** validation remediation for the flagship ORB research artifacts

## Decision

The existing backtest, whitepaper, notebook, dashboard, and trial summaries are historical research artifacts only. They are **not independently validated** and must not be used as evidence of live readiness or production approval.

The machine-readable source of truth is [`run_log/validation_status.json`](../../run_log/validation_status.json). Reports must preserve `NOT_APPROVED` while any blocking gate remains.

## Blocking gates

- The prospective legacy trial ledger remains incomplete, so DSR is `DSR_UNREPRODUCIBLE`.
- Development CPCV completed, but the selected development trades returned -4.04% net with -0.917 annualized Sharpe; this is not an economic pass.
- Final OOS completed with only seven selected trades. The observed +3.76% return and 2.087 annualized Sharpe are too small-sample to establish strategy robustness; the strategy remains `NOT_APPROVED`.
- BTC/USD retains month-scale gaps in July and December 2024. BTC is outside this run's configured DE30/JP225 dependencies, so that warning was preserved as nonblocking evidence rather than hiding it or incorrectly blocking this scoped run.

## Corrected validation run

- Run: `orb-validated-20260924T040530Z` (`run_log/validated/orb-validated-20260924T040530Z/`).
- Development: 88 events, 28 CPCV folds, zero failed folds, complete OOF coverage, and zero train/test interval overlaps. Mean fold AUC was 0.5965.
- Final OOS: once-only evaluation from 2026-08-01 through 2026-09-22, seven selected trades, +3.758% net-return sum, 2.087 annualized Sharpe, and -2.198% max drawdown. Treat as descriptive only given the seven-trade sample.
- The global claim, completion record, run commit, metrics, and resume receipt were read back and hash-checked. The resume path did not refit or retune on final labels.
- Development net-return sum was -4.043% and annualized Sharpe -0.917. Final OOS does not erase this adverse development evidence.
- Overall status remains `NOT_APPROVED`; no NQ/MNQ simple-breakout result is represented by this run.

## Security containment

Tracked provider credential literals were removed from downloader and notebook sources. The validated path now requires the environment variable `LSE_API_KEY`; missing credentials fail closed through the environment lookup. No credential value is stored in this document or repository.

The exposed credential must be revoked and rotated with the provider outside this repository. Git history cleanup is a separate destructive operation and has not been performed; it requires explicit approval and a separate backup/recovery plan. The audit scan found 50 historical credential-shaped pattern hits; values are intentionally not reproduced here.

## Deterministic remediation completed in this checkout

- Added `src/market_time.py` with explicit open/close bar semantics, UTC normalization, DST-aware session windows, duplicate/ordering checks, and fail-closed naive timestamp handling.
- Added `src/validation.py` with global event ordering, event-interval purging, elapsed-time embargo, fold-local uniqueness weights, final-OOS gating, and OOF coverage checks.
- Added point-in-time feature availability/as-of join helpers and append-future regression tests.
- Added a timestamp-window ORB builder path that records decision time and uses the next tradable bar open for execution.
- Added `scripts/run_validated_orb.py`; its data-less preflight emits structured `BLOCKED` output rather than metrics.
- Added an append-only trial-ledger audit; the current mixed legacy ledger is explicitly `DSR_UNREPRODUCIBLE`.
- Added regression coverage for DST, half-hour sessions, next-bar execution, interval overlap, fold-local weights, final-OOS absence, OOF coverage, and validated-path Kelly rejection.

## Evidence boundary

- Existing metrics and rendered artifacts remain immutable historical evidence.
- Corrected reruns must use a versioned run directory and newly available data.
- A green unit-test suite does not approve the strategy; approval requires every validation, data, final-OOS, and reproducibility gate.
- If source data or timestamp metadata is unavailable, the final result remains `FINAL_OOS_PENDING_DATA` and overall status remains `NOT_APPROVED`.

## Last audited repository state

- Audited head recorded by the handoff: `3b73b93`.
- `data/processed/_manifest.json` now records seven UTC-aware Parquet inputs and post-boundary rows through 2026-09-22.
- The manifest was regenerated from all seven on-disk Parquet files after targeted re-fetches. DE30 and JP225 inputs passed the canonical audit; BTC/USD remains flagged for vendor-empty July and December 2024 intervals and is outside this run's dependencies.
- The corrected run used the uncommitted worktree at this head; `validated_commit` remains null. See the run's `frozen_spec.json` for config, data, model, and source fingerprints.
- The exposed credential must be revoked. The acquisition operator reports that a rotated key was used; its value is not retained here.
