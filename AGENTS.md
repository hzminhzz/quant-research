# Agent guide: dual-mode quantitative research

## System orientation

For cross-system architecture, portfolio/routing integration, audit, recovery or
agent-interface work, read
[the operating architecture](docs/architecture/trading_system/README.md), then
only the task-specific document it selects. For implementation planning, use
[the dependency-aware rollout](docs/plans/agent_trading_system_rollout.md).
These describe target capabilities, not newly available commands or permissions.
Inspect current code and evidence before treating a target as implemented.

## Default entry points

**For new research, agents invoke only `scripts/quant.py` (factory) or
`src.workbench.Workbench` (interactive).** Do not discover or launch historic
`scripts/run_*.py` in order to bypass the common runtime; consult
`docs/architecture/dual_mode_20261015/archive_inventory.md` only for a
requested historical reproduction or compatibility investigation. An archived
script is read-only evidence, not a new workflow template.

New cross-sectional research uses `scripts/quant.py` (autonomous factory) or
`src.workbench.Workbench` (interactive research). Read
`docs/architecture/dual_mode_20261015/operations.md` before a new run. Read
`docs/architecture/dual_mode_20261015/verification.md` before making a capability
claim. The factory and Workbench share the vault, feature compiler, causal tests,
native diagnostics, allocator and native backtest adapter.

`ResearchContractV1`, old session records and `scripts/research*.py` remain
compatibility surfaces for historical work. Do not route new candidates through
v1 feature-name permits. Do not rewrite an old frozen record to make it pass.

The standing instrument/product policy remains
[`docs/architecture/market_scope_policy.md`](docs/architecture/market_scope_policy.md).
Legacy [ResearchPhase 3 signal/economic evidence](docs/research_operations.md#required-researchphase-3-decision-before-a-full-backtest)
is distinct from the new funnel's Stage 3 simulation. New factory Stage 2 provides
the pre-backtest signal decision; a Workbench experiment is not factory qualification.

## Start work

1. Inspect the actual checkout, branch, dirty changes and relevant GitHub state.
   Preserve concurrent work. The original local checkout may be ahead of GitHub.
2. Read the candidate YAML, source manifest and relevant ADRs. For a research
   handoff, use `python scripts/quant.py ingest <thesis.yaml> -o <candidate.yaml>`;
   review any explicit unmapped-choice failure instead of guessing a formula. Specify the
   economic mechanism, baseline, falsifier, instruments, windows and costs.
   When a descriptive thesis blocks with `INVALID_THESIS`, run
   `python scripts/draft_candidate_from_thesis.py <thesis.yaml>` first: it maps only
   fields that already carry their executable shape and prints every remaining gap by
   dotted path (exit 3 while gaps remain, exit 0 when complete). It never writes a
   formula, gate, window or cost that the source does not state, so a `GAPS` result is
   the authoring work list, not a partial candidate. Both thesis dialects (flat and
   nested `identity`/`markets_and_data`/... sections) are read.
   Locate the exact requested source. A similarly named strategy is not a
   replacement. Label any example or assumed formula explicitly.
3. Load the relevant ML4T skills and inspect installed signatures. Record
   package versions and source identity. Use native Engineer features/labels,
   Diagnostic statistics and Backtest Engine where their semantics fit.
4. Keep model/rule choices frozen before viewing outcomes. Register every
   explored specification, failure and retry. Export does not erase exposure.

ChatGPT supervises architecture and acceptance. Prefer a durable OpenCode
implementation session and independent native subagents for separable work.
Use Herdr for long deterministic verification when available. An agent's success
message is not independent evidence; inspect artifacts and reproduce checks.
Provider failures do not authorize unsafe fallbacks or fabricated results.

## Interactive Workbench

`Workbench(spec).load()` opens only certified development partitions and clips
its upper endpoint at `protected_test_start`. No research run permit is needed.
`features()`, `ic()`, `backtest()` and `export_yaml()` reuse factory code.
Custom Python features are archived by hash, executed in a restricted Linux
worker, and exported as an explicit sidecar with the YAML. Never deserialize an
untrusted feature artifact in the host process. Plain declarative YAML has no
`eval`, import or arbitrary execution escape hatch.

Interactive backtests are exploratory. They cannot release a holdout. Keep their
return artifacts and selection-family records for later DSR accounting.

## Autonomous four-stage factory

`python scripts/quant.py run config/candidates/<candidate>.yaml`

1. Load development-only canonical data, build the PIT universe and features,
   run exact prefix-invariance tests and verify target neutrality.
2. Run native train-only forward labels and cross-sectional IC/HAC for candidate
   and baseline. Enforce the frozen mean-IC, HAC and baseline criteria.
3. Run native candidate/baseline simulations separately in train and validation.
   Apply native selection-aware DSR, net daily-return beta and short-stop gates.
4. Only after all three stages pass, verify their saved evidence, reserve an
   exclusive cryptographic claim, consume the read and evaluate the frozen
   protected window once. No holdout-driven optimization or automatic retries.

`FALSIFIED_STAGE_2` and `FALSIFIED_STAGE_3` are valid research outcomes; save the
casefile, append the ledger and exit zero. Missing data or insufficient evidence
is `BLOCKED_*`/`INCONCLUSIVE_*` (exit 3). Invalid input or an implementation error
is a nonzero engineering result (exit 2), not evidence against the thesis.

## Runtime contracts, not name-based feature blocks

For new research, `native_status: EXTENSION_REQUIRED` is descriptive metadata,
not an execution veto. Use the native primitive or an allowlisted Polars
expression and verify its actual behavior. The compatibility bridge is
`FeatureGateway.compute_runtime`; frozen v1 `compute` retains its old semantics.

Three sampled cutoff comparisons are empirical falsification checks, not a
mathematical proof for arbitrary programs. Compare all feature columns, PIT
membership, validity masks, exact floating bits, schemas and row identities.
Keep symbol-local trailing operations separate from active-universe
cross-sectional operations. Never feed labels into the feature DAG.

A survivor-only input can pass truncation tests. Source-universe completeness,
listing history and delisted-source coverage remain separate evidence. Do not
assert those properties from a directory count or a function name.

## Data and holdout isolation

Canonical consumer schema:
`timestamp, symbol, open, high, low, close, volume, carry_rate, spread_bps,
session_id, bar_in_session, is_tradable`.

The twelve columns are not a full bitemporal warehouse. Preserve event and
availability semantics, original funding timestamps, source hashes, ingestion
snapshot identity and known vintage limitations in sidecars/manifests. Do not
invent historical recorded-at timestamps. Never overwrite a certified snapshot.

Trusted ingestion writes separate development/protected files. Development
readers check Parquet bounds before decoding and never open protected partitions.
The restricted callback worker cannot open host raw/holdout paths or use the
host network. This isolates that process; it does not restrict the filesystem
owner or turn the whole notebook into an air-gapped host.

The existing research has already examined parts of 2026. Protecting 2026 in a
new vault does not make that history unseen. Preserve this exposure disclosure.
A claim prevents cooperative replay, not tampering by the filesystem owner.

## FX and index price-only vaults

The trusted `scripts/quant.py materialize-markets` command compiles local
`forex_minute_*`, `index_minute_*`, `index_second_*`, `forex_daily_*`, and
`index_daily_*` source families into nine separate timeframe-specific vaults,
including unresampled 1m FX/indices/metals and native 1s ES/NQ. Read
`docs/architecture/dual_mode_20261015/market_materialization.md` for actual
coverage, source-alias caveats, and safe workbench reads. These are source
price panels, not CFD execution certification. Quote/tick volume is not true
exchange turnover, hourly continuity is not a broker session calendar, 1s
observations may be sparse, and these sources do not provide independently
verified directional swaps or live spreads. Keep missing 1s/1m timestamps
unfilled and load bounded second-level windows; do not load full 1s vaults
into notebook memory. Never use
zero-shaped price-only carry/spread placeholders as observed zero financing.
Do not call Stage 3 / Workbench native backtest without an explicitly qualified
cost and carry adapter. Development and protected partitions remain separate.

## Native execution and costs

Use the installed, locked ML4T version. The current adapter is qualified against
`ml4t-backtest==0.1.7`; do not silently upgrade its private lifecycle seams.
Native Engine/FillExecutor own orders, matching, positions and accounting. The
vectorized accounting audit verifies their outputs; it is not a fallback
simulator.

Model order: prior-inventory funding, opening gap stops, opening weight deltas,
intrabar protective stops, closing marks. An opening exit precedes a later
intrabar touch. A stop can gap/slip; it is not guaranteed to fill at its level.
Preserve the first-fill absolute ATR stop through an episode and resize its
quantity after netting. The current sizing policy freezes quantities from
signal-close equity/prices; opening gaps can alter realized target weights.

Apply each settlement once to pre-settlement holdings. Funding intervals are
source data, not always eight hours. Missing funding is not zero funding.
Timestamp normalization tolerance and trade-open mark proxies are explicit model
assumptions, retained in every casefile; they are not measured venue execution.
Fees/slippage fields are explicitly one-way. Do not double-charge spread.

CFD ingestion supports an explicit calendar-qualified cash-session view and
honest quote-volume semantics. It does not certify an entire broker calendar or
infer asymmetric long/short swaps from one scalar. Native execution has no
qualified liquidation, queue-priority or live broker model in this work unit.

Compute risk/statistics on continuous daily net equity returns, not annualized
trade returns. A single return series produces PSR, not multi-trial DSR. Include
available prior trials in the declared selection family; report missing or
unaligned return evidence rather than manufacture a global correction.

## Verification and delivery

Run all `tests/test_dual_mode_*.py`, relevant legacy regressions, the managed
feature-policy check, `ruff check`, and `git diff --check`. Run the explicit real
2025 smoke only when its declared canonical fixture is available. Do not read a
protected market window to make a test pass. Test positive and rejected funnels,
causal violations, funding timing/sign, opening-order precedence, stop gaps,
netting, data drift, isolation and concurrent/repeated claims.

Keep raw panels, credentials, transient worker files and bulk run artifacts out
of source commits. Commit verification summaries and hashes. Distinguish
implemented, tested, market-qualified and deployed. No research mode, passing
metric or CLI command here grants live orders, broker credentials or deployment.
