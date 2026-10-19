# Plan: advanced_futures_30

Decomposes `specs/advanced_futures_30/spec.md` into one milestone: a strictly
additive time-series research route, 25 declarative sleeve specs covering book
strategies 1–23 and 26–27, per-asset-class evaluation with per-class DSR, a
cost/carry qualification layer for price-only index and metals vaults, a
combined portfolio built only from qualified sleeves, and one protected read for
that portfolio.

Gating order: the spec form and feature/allocator path (1–3) unblock all sleeve
work; carry and cost qualification (4–6) unblock native PnL on index and gold;
gates, casefiles and the frozen compatibility matrix (7–9) unblock sleeve
authoring and execution (10–13); non-sleeve dispositions (14) and the portfolio
(15–16) close the contract; docs and full regression (17) ship it.

Two spec open questions are resolved inside issue 9 under the spec's stated
decision rules, owned by the research lead: the per-variant compatibility
matrix and the per-sleeve cadence table. They must be hashed and frozen before
issue 13 runs. The gold carry-curve choice is resolved inside issue 4 under the
same rule (no defensible proxy means `BLOCKED`, never zero carry).

## Context

- v1 cross-sectional spec, `Workbench`, `funnel`, `signal_allocator`,
  `stage2_diagnostic`, `backtest_runner` and `promote/` are frozen surface.
- `ml4t-backtest==0.1.7` has no `funding_df`; the sanctioned carry seam is the
  per-instance pre-order hook in `src/engine/backtest_runner.py::_funding_hook`,
  which requires `funding_rate` and mark events. Index/metals vaults have no
  funding table, so a modeled sidecar is required.
- Vault root is `data/vault/markets_20261015/` (code default). It contains
  `development/` only today; protected partitions come from
  `quant.py materialize-markets --include-protected`.
- Engine/seam versions are pinned; any version bump requires requalification and
  is out of scope here.

## Verification policy

Every issue runs its own focused tests and `uv run ruff check` on touched files.
Issue 17 runs the full regression: `uv run pytest`, the managed feature-policy
check, `git diff --check`, and v1 spec-hash stability. No issue may open a
protected partition except issue 16.

### Milestone: `v0.1 - Advanced Futures 30 time-series sleeve research`

**Issue 1 - Additive time-series spec schema and validation**

New declarative spec kind (e.g. `src/engine/ts_spec.py`) expressing per-instrument
forecast, forecast scaling, volatility target, per-instrument risk allocation,
portfolio combination, windows, costs, carry policy and gate declarations. Parses
to a stable `spec_hash` and validates before any data access. v1 `CandidateSpec`
is untouched.

Verification: new `tests/test_ts_spec.py` covers a valid spec, each invalid case
(missing forecast, overlapping windows, undeclared class, non-additive fields
rejected), and hash stability; `uv run pytest tests/test_ts_spec.py -q` passes.
Existing v1 YAMLs still parse to their recorded hashes
(`uv run pytest tests/test_dual_mode_spec.py -q` or equivalent existing test).
Done when both hold and `uv run ruff check` is clean.

**Issue 2 - Time-series feature compilation with causal proof**

Extend the shared compiler path to the new spec (per-instrument group operations,
cross-sectional operations only where a sleeve declares them) and add the
forecast/volatility-target extension primitives the book needs that
`ml4t-engineer 0.1.4` does not supply, under ADR 0002, including audited Python
artifacts where declared. Every compiled sleeve feature set runs the existing
causal truncation proof.

Verification: `uv run pytest tests/test_ts_features.py -q` covers exact-value
checks for each new primitive, a declared Python artifact path, and three
cutoff-comparison proofs; a deliberately look-ahead expression is rejected.
A v1 feature compilation test still passes unchanged.

**Issue 3 - Time-series allocator: forecast scaling, vol target, risk allocation**

New target-weight construction for the new spec: forecast scaling, per-instrument
volatility targeting, per-instrument risk allocation and portfolio combination.
Emits the same target-weight/stop contract consumed by the native runner.
Deterministic given the same inputs.

Verification: `uv run pytest tests/test_ts_allocator.py -q` proves weights sum to
the declared gross exposure, respect per-instrument caps, are zero for
non-eligible symbols, and are bit-identical across two runs. Existing
`tests/test_dual_mode_allocator*.py` (v1) passes unchanged.

**Issue 4 - Modeled carry sidecar with explicit long/short transformation**

Materialize a per-instrument, per-settlement carry sidecar derived from the named
rate curve (`bonds_daily_US10Y`/`US2Y` or an explicitly named alternative), with
formula, tenor mapping, sign convention and source hash recorded. Positive rate
charges longs and pays shorts (`-quantity × price × rate`); instruments whose
price series already embeds financing must not receive an extra cashflow. Where
no defensible gold proxy exists, the sleeve is `BLOCKED`, never zero carry.

Verification: `uv run pytest tests/test_carry_model.py -q` covers the sign test
(long pays, short receives), double-charge rejection, missing-curve rejection,
and sidecar hash stability. A gold curve with no defensible proxy yields a
`BLOCKED` disposition, not a zero series.

**Issue 5 - Native carry integration for non-crypto sources**

Wire the modeled sidecar into the native run through the existing per-instance
pre-order hook, extending the event contract without changing v1 crypto funding
behavior. Cash movements must reconcile exactly against the native account.

Verification: `uv run pytest tests/test_ts_carry_integration.py -q` asserts
per-event cash reconciliation to within the repository's tolerance, that a
missing mark or non-finite rate raises `BLOCKED_DATA`, and that two runs produce
identical funding records. Existing crypto funding tests pass unchanged.

**Issue 6 - Cost qualification adapter for price-only index and metals vaults**

Introduce the qualification path that lets the native Stage 3 run on
`execution_qualified: false` vaults only when commission, spread and slippage
are explicitly declared and a carry sidecar is bound; the casefile records every
value as an assumption and any `UNKNOWN_NOT_MODELLED` financing blocks
qualification. The v1 price-only gate remains for v1 specs.

Verification: `uv run pytest tests/test_cost_qualification.py -q` covers: a
qualified index sleeve reaches native PnL; a sleeve with unmodeled financing is
refused with a named reason and writes no verdict; a rejected qualification
writes no artifact and consumes no claim.

**Issue 7 - Per-class gate evaluator with DSR**

Mechanical evaluator implementing the seven gates: train net Sharpe > 0,
validation net Sharpe ≥ 0.30 at 10% vol target, validation ≥ 0.5 × train,
net Sharpe > 0 at 2× costs, validation max drawdown ≤ 25%, forecast–return
rank correlation with Newey–West t ≥ 2.0 (lags = label horizon), and class-level
DSR ≥ 0.95 computed over that class's aligned trial returns including failed and
abandoned trials. DSR input sets are emitted for the casefile.

Verification: `uv run pytest tests/test_ts_gates.py -q` covers each gate's
boundary (e.g. Sharpe 0.299 fails, 0.30 passes; validation 0.49 × train fails;
DSR 0.949 fails), and proves DSR is never computed across classes and never over
unaligned series. Two evaluations of identical inputs return identical verdicts.

**Issue 8 - Sleeve casefile and trial-ledger semantics**

Casefile artifact carrying spec hash, feature proof, cost and carry assumption
records, per-class gate table, terminal disposition, and code/data/vault hashes.
Ledger records every run, failure, abandonment and retry; predeclared variation
is distinguished from a post-outcome new trial.

Verification: `uv run pytest tests/test_ts_casefile.py -q` asserts a complete
casefile validates, a missing required section is rejected, a post-outcome gate
change is recorded as a new trial that invalidates the prior verdict, and
rejected attempts append one ledger entry and no artifacts.

**Issue 9 - Freeze the compatibility matrix and cadence table**

Author the per-variant asset-class compatibility declaration for all 25 variants
(one-line economic justification each) and the per-sleeve cadence table (1h
primary, 1m where the book's horizon requires). Validate against available
symbol sets and data semantics, then hash and freeze both artifacts before any
sleeve run. Decides the spec's two open questions; owner: research lead.

Verification: `uv run pytest tests/test_compatibility_matrix.py -q` asserts
coverage of all 25 variants, a justification for every declared pair, no
undeclared pair appearing in a run manifest, and that the frozen hash is
required by the runner.

**Issue 10 - Sleeve specs: basic directional strategies 1–11**

Author the eleven declarative sleeve specs (buy-and-hold variants 1–4, trend 5–9,
carry 10, combined 11) under the frozen matrix and cadence table, each with
declared forecast, scaling, vol target, costs, carry policy and windows.

Verification: `uv run python scripts/quant.py validate <spec>` succeeds for all
eleven; `uv run pytest tests/test_sleeve_specs.py -q` proves each declares a
class pair present in the frozen matrix and that no spec uses a zero carry or
zero cost placeholder.

**Issue 11 - Sleeve specs: advanced trend and carry strategies 12–20**

Author the nine declarative sleeve specs (12–18 trend/carry refinements,
19–20 cross-sectional momentum and carry expressed within the time-series
route's declared cross-sectional mode).

Verification: same as issue 10, extended to assert that 19–20 declare their
cross-sectional operation explicitly and that class compatibility follows the
frozen matrix.

**Issue 12 - Sleeve specs: advanced directional and fast strategies 21–23, 26–27**

Author the five declarative sleeve specs (breakout, value, acceleration, fast
mean reversion, safer fast mean reversion), including the 1m cadence declaration
where required.

Verification: `uv run python scripts/quant.py validate <spec>` succeeds for all
five; `uv run pytest tests/test_sleeve_specs_fast.py -q` asserts the 1m cadence
declaration, data availability against the vault, and correct rejection when a
declared symbol or cadence is absent.

**Issue 13 - Execute the 25 sleeves development-only, per class**

Run each sleeve in each matrix-declared class against development partitions
only, producing one casefile per sleeve with per-class gate tables and terminal
dispositions. Every run appends to the ledger; failures and abandonments are
retained.

Verification: `uv run python scripts/quant.py run <spec> --development-only`
completes for each declared pair; `uv run pytest tests/test_sleeve_execution.py -q`
asserts every one of the 25 variants has a disposition, no run touched a
protected partition, and the emitted per-class DSR input set matches the
ledger's aligned trials.

**Issue 14 - Non-sleeve dispositions for strategies 24, 25, 28, 29, 30**

Produce the written disposition records: #24 diagnostic study, #25 portfolio
construction mode (documented against issue 3), #28 and #29 `BLOCKED_MULTILEG`
with evidence that the engine holds single-symbol positions, #30
`BLOCKED_NO_CONTRACT_CURVE` with evidence that vaults hold one continuous series
per symbol.

Verification: `uv run pytest tests/test_non_sleeve_dispositions.py -q` asserts
all five records exist, each cites the blocking evidence (code path or manifest
field), and none is represented as a sleeve or a failure-free exclusion.

**Issue 15 - Combined portfolio from qualified sleeves**

Implement the combined-portfolio object under an inclusion and weighting rule
frozen before composition: only sleeves with a `QUALIFIED` disposition in a class
may enter, and a non-qualified sleeve is a spec error. Produce its native
backtest evidence and its class-level DSR.

Verification: `uv run pytest tests/test_combined_portfolio.py -q` proves a
non-qualified sleeve is rejected, the frozen rule's weights reproduce exactly,
and the portfolio casefile carries its own per-class DSR and backtest hashes.

**Issue 16 - Single protected read for the combined portfolio**

Reserve the protected-read claim, then evaluate the frozen portfolio spec once
against materialized protected partitions. The claim is consumed on reservation;
a crash leaves it consumed and the failure recorded, with no retry.

Verification: `uv run pytest tests/test_protected_read.py -q` covers reservation
before read, refusal of a second read after success and after simulated crash,
and rejection of any sleeve attempt to read protected data. A live smoke run
against `data/vault/markets_20261015/*/protected` (materialized with
`--include-protected`) completes once and records the claim.

**Issue 17 - Documentation, verification summary and full regression**

Update the operations/verification docs for the new route, record the sleeve and
portfolio evidence inventory with hashes, and run the full regression: all
`tests/test_dual_mode_*.py`, promoted tests, inbox/handoff tests, the managed
feature-policy check, `ruff check`, and `git diff --check`.

Verification: `uv run pytest` passes; `uv run ruff check` passes;
`git diff --check` is clean; every v1 candidate YAML still parses to its recorded
hash; the verification summary names each criterion in the spec and the artifact
that satisfies it. Done when the summary contains no unverified criterion and no
claim of deployment approval (`NOT_APPROVED` remains).
