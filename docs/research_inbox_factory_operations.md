# ATS Research Inbox Factory — Development-only operator runbook

**Scope:** bounded autonomous development research. **Not authorized:** protected holdout,
paper/live trading, orders, deployment, portfolio allocation, new trial rules, or
rewriting frozen outcomes. This is a thin queue over ATS handoff admission,
the native ML4T research factory, the existing trial ledger and Casefiles.

## Commands (repository root)

Use the qualified project Python environment; examples assume it is active.

```sh
python scripts/quant.py validate-handoff
python scripts/quant.py validate-handoff research_inbox/<candidate_id>
python scripts/research_inbox_queue.py inspect
python scripts/research_inbox_queue.py start
python scripts/research_inbox_queue.py resume
python scripts/research_inbox_queue.py report
```

Use `--inbox PATH` and `--run-log PATH` for isolated fixture testing.
`--max-candidates N` limits how many queue entries a CLI invocation visits;
`--max-runtime-seconds N` bounds each qualified native trial (default 3600).
`start` and `resume` are idempotent entrypoints for the same queue reconciliation.
`inspect` and `report` are read-only and work during a native run.

```sh
# A direct native research trial MUST use this restriction when run in development:
python scripts/quant.py run <fully-frozen-candidate.yaml> --development-only
```

The default `quant.py run` **does not have this restriction** for historical
ATS workflows; **never** call it without `--development-only` in this queue.

## Authority and workflow

1. Reconcile source branches before ingesting. Never overwrite a candidate's
   `research_inbox/<candidate_id>/thesis.yaml` and `brief.md`. Source identity is
   exact SHA-256; semantic identity includes the hypothesis, instruments, rules,
   clock, features, size, costs, baseline and source provenance. Two different
   variants citing one article are not duplicates merely because of the source.
2. `validate-handoff` uses `src.engine.research_handoff.validate_handoff`.
   `HANDOFF_VALID_UNVERIFIED` proves bounded syntax and declared references,
   **not** verified economics, actual provenance, data suitability or executability.
   A source URL is not proof its contents agree with the adaptation.
3. Classification uses explicit structured basket membership and rules. Only
   a fully specified cross-sectional thesis can use the native existing
   cross-sectional factory. General single-instrument event and path-dependent
   protocols are **BLOCKED_PROTOCOL** until qualified native typed adapters and
   independent event/fill/accounting oracles exist. The frozen M8 N8 case is not
   a universal event protocol. Never route these theses into IC/neutrality gates.
4. The conversion path reuses `src.engine.thesis_ingest.convert_thesis`, then
   `parse_spec`. Required source rules, economic falsifier, baseline,
   instrument identity, causal clock, sizing and costs must be explicit.
   Declared `unresolved_blockers` veto execution. No invented fees, RSI,
   bar timing, stop behavior, data source, null model or trial variants.
5. For an executable candidate, freeze the candidate spec hash, source bytes,
   code dependency identity, data manifest SHA-256, development windows and
   protected *start metadata*, one-trial budget, baseline and declared cost
   model. The queue does not build/download substitute data.
6. The worker invokes **only** `quant.py run ... --development-only`.
   `ResearchFunnel.run(..., development_only=True)` stops after Stage 3
   (including a PASS) **before** `unlock_holdout` and `load_holdout`.
   Stage 1 prefix/cutoff leakage checks and Stage 3's existing independent
   native cash/equity accounting must pass their native gates. Stage receipts,
   hashes, source/spec/code identity, ledger chain, and saved Casefile are
   rechecked before a terminal native result is accepted. This verifier
   authenticates internal native evidence, **not** an independent full
   numerical replication by an outside research auditor.
7. A falsified hypothesis is a terminal valid trial; failures and inconclusive
   trials remain in their native ATS trial ledger. Pre-execution blocks do not
   fabricate native trial ledger entries. Every admission/block is recorded
   in the append-only queue journal with source references.

## Durable state and crash policy

- `run_log/inbox_factory/candidates/<id>/events/000001.json` etc. form a
  hash-chained, exclusive-created, fsynced event log. `state.json` is an
  atomic projection, recoverable from that log.
- `attempts/<timestamp-id>/stdout.log` and `stderr.log` preserve native
  process output. The native factory writes its own
  `run_log/dual_mode/<candidate_id>/<attempt>/casefile.json`,
  Stage receipts, Parquet evidence and `run_log/trial_ledger.jsonl`.
- One nonblocking OS file lock is the integration owner. Two `start` or
  `resume` invocations cannot double-admit the same queue. Read-only
  `report` does not acquire the writer lock.
- Terminal verified work is skipped without another backtest. A changed
  thesis source -> `BLOCKED_DRIFT` (previous trial history retained).
  Journal corruption -> `BROKEN_EVIDENCE` and fail closed.
- A crash after append-only event fsync but before state projection publication
  reconstructs the latest state from events.
- A process left in `RUNNING` after a crash -> `BLOCKED_RECOVERY`; do not
  launch a duplicate native attempt automatically. First reconcile running
  tmux/processes, native trial ledger, saved Casefiles and partial outputs.
  After verified manual review, create an explicitly linked successor trial
  under native attempt/recovery policy. This conservative behavior lets the
  batch continue with the *other* eligible candidates.
- Statuses: `ADMITTED`, `EXECUTABLE`, `RUNNING`,
  `DEVELOPMENT_QUALIFIED`, `FALSIFIED`, `INCONCLUSIVE`,
  `BLOCKED_HANDOFF`, `BLOCKED_SPEC`, `BLOCKED_PROTOCOL`,
  `BLOCKED_DATA`, `BLOCKED_EVIDENCE`, `BLOCKED_DRIFT`,
  `BLOCKED_RECOVERY`, `BLOCKED_SECURITY`, `ENGINEERING_ERROR`,
  and `DUPLICATE`. These are queue states, not new ATS/ML4T result labels.
  `DEVELOPMENT_QUALIFIED` is not promotion or holdout evaluation.

## 2026-10-17 initial available candidate coverage

Source branch: `research/inbox-handoff-20261017` (same handoff commit
`2fa13c03` as `research/gemini-62-inbox-20261017`), based on ATS-integrated
main `041477be`. The checkout had no research inbox; seven original
two-file handoffs were copied without rewriting the rules.

| Coverage | Verified count |
|---|---:|
| Two-file handoffs validated | 7 |
| Admitted as descriptive handoffs | 7 |
| Classified single-instrument event | 7 |
| Executable native cross-sectional candidates | 0 |
| Executable native generalized event candidates | 0 |
| General path-dependent candidates in this batch | 0 |
| Blocked by native protocol | 7 |
| Real research trial executions | 0 |
| Verified native results in this batch | 0 |

Each `BLOCKED_PROTOCOL` record carries exact original
`unresolved_blockers` as `required_adaptations`. In addition to a
general event adapter, these candidates require different as-of calendar
sources, broker executable quote/carry/contract identity, and bar/DST
parity proofs. Do not confuse paper research instruments with broker CFD
contracts. Original source claims must be verified before their economic
results can be trusted.

The full 62-thesis ZIP/archive was not found in the inspected VPS paths.
Do not manufacture the remaining 55 candidates or describe them as blocked
in the executed seven-candidate queue; they are **not admitted**.

## Verification and scientific limitations

```sh
PYTHONPATH=. python -m pytest -q -n 0 \
  tests/test_research_handoff.py tests/test_research_inbox_queue.py \
  tests/test_research_inbox_dev_guard.py
ruff check src/research_control/research_inbox_queue.py \
  scripts/research_inbox_queue.py scripts/quant.py src/engine/funnel.py
git diff --check
```

The positive development-only safety fixture exercises a synthetic native
Stage 3 PASS (with a disclosed synthetic-only DSR test stub), monkeypatching
the protected claim/read functions to fail if called. It is **not** a genuine
candidate backtest or evidence of economic alpha. A real end-to-end
development-only thesis run is conditional on one complete compatible
candidate and qualified native data. No such eligible candidate was present
in the initial seven. Do not weaken native gates just to produce a positive
test or describe unsupported handoffs as falsified.

## Nested source admission and triage (2026-10-18)

The queue accepts the original flat ATS handoff format and the captured nested
format (`identity`, `economic_thesis`, `markets_and_data`,
`deterministic_strategy_specification`, `research_evaluation`,
`scientific_integrity`). Nested admission verifies bounded regular files,
unique YAML keys, directory/source identity, declared source anchors, and
SHA-256 identities for both files. It records source-preserving, typed field
aliases with exact YAML paths and a digest of each value. Those aliases are
triage evidence only; they are never converted to `CandidateSpec`.

`quant.py validate-handoff` remains strict and flat. Nested sources enter queue
state as `THESIS_CAPTURED` then `SOURCE_ADMITTED`, followed by explicit triage.
Reason codes include `UNRESOLVED_SOURCE` (a URL or bibliography is not verified
evidence), `CONTRADICTORY_RULES` (including hourly next-bar/00:01),
`UNAVAILABLE_DATA` (no declared development vault with a manifest), and
`UNQUALIFIED_PROTOCOL`. A newer source after `BLOCKED_HANDOFF` appends a linked
revision event; the earlier event is retained. Other terminal evidence remains
frozen.

Reports distinguish captured and admitted sources, queue trial starts, native
evidence runs, Stage 1–4 receipts, and reason-code counts. `native_runs` counts
verified ATS Casefiles, not inbox rows. Stage 4 is absent from this
development-only queue.

### 2026-10-18 source-corpus reproduction

On `origin/main` `4693f96a`, the pre-existing 69-source baseline was 62 nested
sources rejected by the flat envelope and seven admitted event handoffs blocked
by protocol, with zero native trials. The BTA handoff on `main` adds one more
legacy flat event source, making 70 sources after reconciliation. The 62 source
directories were imported from the published Git commit without rewriting
their files; the seven existing handoffs and BTA source also retain their
committed bytes.

The development-only queue pass recorded 70 captured, 70 admitted, 62
`BLOCKED_SPEC`, eight `BLOCKED_PROTOCOL`, zero executable specs, zero trial
starts, zero native runs, zero Stage 1/2/3/4 receipts, and zero holdout reads.
All 62 nested items carry explicit source, data, and protocol reasons. The
hourly next-bar/00:01 conflict was detected from nested clock declarations.
Each nested source has one count for each of `UNRESOLVED_SOURCE`,
`CONTRADICTORY_RULES`, `UNAVAILABLE_DATA`, and `UNQUALIFIED_PROTOCOL`; per-item
codes remain in the evidence journal. The eight flat event items retain their
declared protocol adaptations. In
particular, BTA remains `BLOCKED_PROTOCOL`: its preserved ATS-4 adapter reports
hourly CFD stop-order matching and session/cost evidence are not qualified. No
Stage 1–3 real-market candidate was compatible with the admitted sources and
current data/protocol contracts, so none was started.

The inbox regression also exercises synthetic positive native development-only
Stage 3 and negative Stage 2 fixtures. They establish the no-Stage-4 boundary
and are not economic evidence for any inbox source. Data materialization was
disabled for the corpus reproduction.
