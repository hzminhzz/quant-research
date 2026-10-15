# ADR 0004: Runtime causal checks over static feature-name blocks

Status: Accepted for the new dual-mode research route requested on 2026-10-15.
Scope: Research only. No broker, paper-account or live-order authority.

Numbering note: the original checkout has an unrelated, untracked
`0004-hybrid-live-execution.md`. This document does not replace it. References
must use this full filename, not the number alone.

## Context

The frozen-v1 feature gateway and run-permit path bind particular feature,
source and execution contracts. They preserve useful evidence but make a new
cross-sectional research specification depend on unrelated managed-strategy
adapters. New feature semantics were repeatedly treated as missing permission
instead of an executable function whose behavior could be tested.

The previous checkpoint added safe foundations but its executable managed
route remained synthetic-only. The current work adds a real data-source adapter,
shared feature/compiler path, native diagnostic and simulation funnel, and a
Workbench that uses those same implementations.

## Decision

New research uses `scripts/quant.py` or `src.workbench.Workbench`. Both call the
same data vault, compiler, runtime causal checks, native diagnostics and native
simulation adapter. A declarative feature marked `EXTENSION_REQUIRED` can run;
its name/status does not confer or deny qualification. Arbitrary YAML execution
is prohibited. Trusted Python functions are explicit hashed artifacts executed
inside the restricted callback worker.

The new authority chain is:

```text
source snapshot -> immutable canonical manifest -> frozen candidate JSON
-> registered attempt -> measured stage evidence -> single-use holdout claim
-> casefile / derived leaderboard
```

One append-only `trial_ledger.jsonl` is the authority for new-mode attempts in the
configured research workspace. A casefile and leaderboard are derived outputs.
Historical v1 sessions remain separate immutable history; they are not silently
converted into new trials. ADR 0001's one-authority-per-fact principle remains.
ADR 0002's static name gate and ADR 0003's manual-style preflight path no longer
apply to new-mode feature execution. Their frozen historical contracts remain
readable through the compatibility surface.

## Isolation and evidence are separate

The canonical twelve-column panel is a consumer interface, not a sufficient
bitemporal schema. Sidecars retain original funding timestamps, rates/intervals,
marks and their provenance. Manifests bind source bytes, availability assumptions,
calendar identity, ingestion snapshots and absent historical-vintage evidence.
The implementation does not fabricate an as-known historical revision archive.

Trusted ingestion writes distinct development and protected files. Development
loaders validate file bounds before decoding and never open a protected data
file. An actual Bubblewrap worker exposes only code, libraries and the supplied
frame; host raw/holdout paths and host network access are not mounted. The
filesystem owner and host notebook remain trusted. This is not a claim that a
Python API can sandbox its owner.

The Stage 1 truncation oracle compares exact feature bits, null masks, schemas,
row identity and PIT membership at seeded cutoffs. Passing is empirical evidence
for those cutoffs. It is not a mathematical proof about all inputs or about
source-universe completeness. A historically incomplete source can pass these
tests. Source coverage and prior exposure remain explicit limitations.

## Four-stage execution

Stage 1: Load certified development panels, compile PIT features and test prefix
invariance and target neutrality.

Stage 2: Use native forward labels and cross-sectional IC/HAC on train data only,
with explicit next-open label timing, outcome-end censoring and baseline checks.
A failed falsifier produces `FALSIFIED_STAGE_2`, a saved casefile and exit zero.

Stage 3: Use native candidate/baseline simulations in train and validation. Apply
native selection-aware DSR, benchmark beta and short-stop criteria. Failed gates
produce `FALSIFIED_STAGE_3`. Missing evidence remains inconclusive, not success.

Stage 4: Verify saved stage evidence, the frozen spec, code/environment identity
and source manifest. Reserve a claim with exclusive creation and durable writes
before releasing the protected data. Consume a separate read marker before the
first protected read. Renaming a candidate inside the same selection cohort
cannot obtain another claim. A crash does not restore an unused-looking claim.

The claim is a cooperative replay-control record, not an owner-proof signature.
Parts of 2026 have already been examined in this repository. New partitioning
cannot make that period globally unseen.

## Native execution seam

The installed Backtest 0.1.7 lacks the public funding API described by newer
upstream documentation. Reuse its Engine and FillExecutor, with version-pinned
adapters for pre-order cashflow, opening-order phase separation and protective
STOP quantity maintenance. Never substitute a handwritten event simulation loop.
A vectorized, independent cash/holdings audit verifies the native output.

Execution sequence is explicit: pre-event holdings pay/receive funding; gap
stops execute at the adverse opening price; scheduled opening deltas execute;
remaining intrabar stops execute; closing marks update equity. The adapter's
opening-before-intrabar regression prevents a future bar low from displacing an
opening exit. Fixed episode ATR stops survive position resizing.

Funding timestamps can have millisecond boundary jitter. The normalization
tolerance is declared, raw timestamps are retained, and modeled pre-open
settlement is not represented as guaranteed exchange ordering. Missing marks
can use an explicitly selected trade-open proxy, or remain unavailable under
`observed_only`. No proxy becomes measured venue data merely by passing tests.
CFD quote volume, broker calendars and asymmetric swaps need their own declared
semantics; one scalar carry rate cannot represent arbitrary directional swaps.

## Consequences and migration limits

A new feature no longer requires a contract-version ladder or a permit based on
its name. A run can finish successfully as research with a falsified hypothesis.
Wrong source identity, invalid input, unavailable prices, missing trial returns
and unsupported execution semantics still receive explicit terminal outcomes.

Legacy strategy implementations and runners are retained until their entry,
exit, calendar, sizing and fill behavior can be represented and reconciled. The
new target-weight contract does not automatically reproduce every old stop-entry
strategy. The migration map distinguishes replacement interfaces from completed
legacy cutovers. No original source, strategy result or frozen contract was
deleted to make the new path appear complete.

See `../architecture/dual_mode_20261015/operations.md` and
`../architecture/dual_mode_20261015/verification.md` for runnable commands,
observed tests and the exact qualification boundary.
