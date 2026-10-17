# Research Inbox Factory qualification — 2026-10-17

**Decision:** SOFTWARE_READY_FOR_REVIEW, **not** real-strategy or execution qualification.

## Authority and isolation

- Source repository: `hzminhzz/quant-research`.
- Baseline: `origin/main` at `041477bec24eb4936ed65214c20227b747f3b0c3`.
- Task branch: `feat/ats-research-inbox-factory-20261017`.
- Task worktree: `/home/quant/.devspace/worktrees/quant-research-0b051635`.
- The primary checkout had unrelated dirty work, left untouched.
- No main merge, paper/live order, broker interaction, or protected holdout read was authorized or attempted.

## What was built and qualified

1. Imported the 7 exact two-file descriptive handoffs from
   `research/inbox-handoff-20261017` and restored the existing strict
   `validate-handoff` path. Source Git blob identities were verified identical
   to that branch. `research/gemini-62-inbox-20261017` points to the same published
   source commit `2fa13c03`.
2. Added a thin CLI `scripts/research_inbox_queue.py` with
   `inspect`, `start`, `resume`, and `report`.
3. Added source/logic deduplication, event-vs-cross-sectional-vs-path-dependent
   classification, explicit `BLOCKED_PROTOCOL` details, preserved source
   references and unresolved prerequisite lists, and idempotent terminal state.
4. Added fsynced append-only hash-chained per-candidate events, atomic state
   projection, single owner lock, per-attempt logs, frozen spec/data/source/code
   identities, native Casefile/receipt/trial ledger verification, and a
   fail-closed crashed-RUNNING disposition of `BLOCKED_RECOVERY`.
5. Implemented and tested `quant.py run --development-only`, a native
   `ResearchFunnel` branch that exits after Stage 3 PASS and cannot claim/read
   protected Stage 4. Direct development-only event requests are rejected before
   the frozen event runner. The regular historical `quant.py run` path remains
   compatible with existing behavior.
6. Added human runbook at `docs/research_inbox_factory_operations.md`.

## Evidence

- `PYTHONPATH=. python -m pytest -q -n 0`: **36 passed**, three
  third-party deprecation warnings. Exact scope: `tests/test_research_handoff.py`,
  `tests/test_research_inbox_queue.py`, `tests/test_research_inbox_dev_guard.py`,
  and two pre-existing development/falsification regression tests in
  `tests/test_dual_mode_funnel.py`.
- After additional event fail-closed and spec-digest checks:
  **3 targeted tests passed**, 0 failed.
- Scoped `ruff check`: PASS.
- `git diff --check`: PASS.
- Durable local qualification log:
  `run_log/inbox_factory/qualification_tests.log`.
- Machine-readable queue evidence:
  `run_log/inbox_factory/candidates/<candidate_id>/events/*.json` and
  `state.json`. Files belong to the isolated local worktree; this repository
  does not treat machine-specific queue runtime state as portable source code.
- `validate-handoff`: 7/7 `HANDOFF_VALID_UNVERIFIED` (structure/provenance
  declarations only, not source verification).

## Candidate outcome (seven available published handoffs)

| Category | Count |
| --- | ---: |
| Discovered two-file handoffs | 7 |
| Structurally admitted | 7 |
| Source/logic duplicates | 0 |
| Classified single-instrument event | 7 |
| Classified cross-sectional | 0 |
| Classified path-dependent | 0 |
| Executable frozen native specifications | 0 |
| `BLOCKED_PROTOCOL` | 7 |
| Native economic falsifications | 0 |
| Native inconclusives | 0 |
| Independently verified economic candidates | 0 |
| Real end-to-end development-strategy backtests | 0 |
| Protected-holdout reads | 0 |
| Paper/live orders | 0 |

Every candidate requires a general qualified single-instrument event adapter,
causal session/next-fill rules, and independent order/fill/cash checks. Their
distinct, source-declared missing broker/product/price, DST, macro timing,
transaction cost and carry evidence is retained in the queue as
`required_adaptations`. None can correctly be forced through the existing
cross-sectional IC/neutrality factory, and the frozen M8 N8 adapter is not
a universal event engine.

The full `ats_theses_all_62_cycles.zip` collection was **not present** in
inspected VPS repo/worktrees, nor in the current container's mounted uploads.
The other 55 theses were not invented, marked falsified, or counted as ingested.

## Independent PR #63 review addendum (2026-10-17)

The separate merge review expanded verification beyond the original delivery:

- The ATS-4 plus dual-mode and inbox regression selection ran **98 tests,
  zero failures** on the original feature head, with only existing third-party
  warnings. Repo-local log: `run_log/inbox_factory/merge_review_regression.log`.
- Review found and corrected three integration risks: malformed directory
  names no longer terminate the queue or escape its state root; deduplication
  now differentiates data, train/validation windows, falsifiers and unresolved
  prerequisites without treating another citation as a new trial; fixed seven-
  candidate test fixtures no longer prevent future inbox expansion.
- Added tests for invalid directory containment, concurrent source mutation,
  false deduplication across research windows/cost-related prerequisites, and
  fixture independence. A fresh post-fix queue suite passed **19 tests**.
- The first required GitHub CI pass found a real ATS-4 compatibility regression:
  the ordinary `quant.py run` path had begun passing a new optional keyword
  to historical caller stubs. The CLI now preserves its original one-argument
  factory invocation by default and passes `development_only=True` only on
  explicit development-only requests. The affected ATS-4 and development-only
  regressions passed **6 tests** after this correction.
- Scoped Ruff and staged diff checks passed. These tests do not promote the
  seven unsupported event theses or claim a genuine real-market backtest.
- Merge authorization and protected GitHub CI are separate release gates;
  do not bypass main-branch protection.

## Limitations and release gate

- The positive native development-only Stage 3 test uses an openly declared
  **synthetic DSR stub**, not a real trading strategy or a measured edge.
- Native trial accounting and Stage 1 leakage checks run on compatible
  executable specifications, but none of the seven handoffs is currently
  compatible. Consequently, independent economic validation remains **zero**.
- Queue verification authenticates native source/spec/receipt hashes and
  recorded native independent accounting outputs; it is not a separate
  source-independent reproduction of each possible strategy.
- Crash recovery fails closed with `BLOCKED_RECOVERY` when worker completion
  cannot be verified; the remaining candidates continue, while the uncertain
  attempt requires ledger/process reconciliation rather than unsafe automatic
  replay.
- This is a feature branch for review, not a main cutover, ATS protocol
  generalization, protected-data approval or deployment authorization.
