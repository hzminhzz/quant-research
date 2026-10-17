# Independent ATS-0–8 cutover and legacy compatibility audit — 2026-10-17

## Scope, identity, and verdict

**Verdict: CONDITIONAL** for an **additive, reviewed merge only**. An ATS-8 branch replacement or any merge dropping qualified ATS-3/4/5/6/7 paths is **BLOCKED**. This report does **not** authorize a legacy retirement, research approval, provider execution, production deployment, or live trading.

Read-only inspection of the live repository (excluding creation of this report and its isolated worktree) found:

| Ref | Inspected commit |
| --- | --- |
| origin/main | `fbfc2ed2288ec12f9ed07e6de191dfb9fde36d9d` |
| feat/ats-integration-20261017 | `769ef9807b9823bfe3127cacbd4db05568fd4ddc` |
| feat/ats7-release-qualification | `8f114c76985721cd690fcd514d190b717f94c660` |
| feat/ats8-learning-benchmark | `14f515218ab63cd32e7db6879dbb282bb906b106` |
| ATS-7 / ATS-8 merge base | `368d8f00beb5e51ac1f0e5215a339c770198c1ee` |

Audit worktree: `audit/ats-cutover-20261017`, started clean at `origin/main`. The original checkout at `/home/quant/dev/quant/quant-research` is on `local-first-main-sync-20261014` at `9525f356`, with modified tracked files and many untracked research artifacts; **none were modified by this audit**. Multiple parallel ATS worktrees exist. Ref identities are observations, not immutable future release coordinates. No push, merge, data movement, execution or provider call was performed.

**Evidence boundary:** inspected Git trees/diffs, migration/archive documents, qualification narratives and source/test path inventories. Did **not** run a combined-tree regression suite or verify live process health, raw artifact checksums, provider orders or actual holdout state. These are explicit unverified gates, not implied passes.

## Prioritized findings

### C-01 — BLOCKER: ATS-8 branch is not a replacement for ATS-7

- **Source/evidence:** `src/research_control/learning.py`, `src/shadow_router.py`, `src/release_runtime.py`, `src/research_control/ats3_bybit_replay.py`, `tests/test_ats6_shadow_router.py`, `tests/test_ats7_release.py`, `tests/test_ats8_learning.py`. Read-only `git diff --name-only feat/ats7-release-qualification feat/ats8-learning-benchmark` shows ATS-8 gains learning code while dropping ATS-3 audit/replay, ATS-4 evidence, ATS-6 router, ATS-7 runtime and their tests relative to ATS-7. The common base is `368d8f0`.
- **Risk:** a branch replacement or careless conflict resolution discards qualified functionality, while ATS-8 tests can still pass on its own branch.
- **Correction:** Sessions A/B must integrate ATS-8 learning **additively** on the ATS-0–7 result. Preserve ATS-3/4/5/6/7 source, tests, security boundaries, and evidence. Do not accept a diff with unexplained module/test deletion.
- **Verification:** post-integration `git diff --name-status origin/main..HEAD`, compare `git ls-tree -r --name-only` against ATS-7 for essential source/test paths; run the full ATS-2 through ATS-8 regression/independent acceptance suites on the exact merged SHA. Fail on removals or behavioral drift.

### C-02 — BLOCKER if unresolved: mainline preservation is not established by branch-local tests

- **Source/evidence:** `scripts/quant.py`, `src/workbench.py`, `src/engine/funnel.py`, `src/engine/backtest_runner.py`, `src/research_control/attempts.py`, `src/data_vault/panel_builder.py`, `AGENTS.md`, `docs/research_operations.md`. These are modified in the ATS integration relative to `origin/main`; parallel mainline work and dirty local checkout also exist. The inspected ATS integration diff covers 140 files, >16,000 added lines.
- **Risk:** conflict resolution may silently overwrite current native research contracts, cli semantics, import paths, scientific gates, or newer bug fixes.
- **Correction:** use current fetched main as base; review changed shared files semantically, not by blanket ours/theirs. Preserve both dual-mode and additive ATS contracts; do not merge unrelated dirty work.
- **Verification:** exact merged SHA; `git diff --check`; mainline/native and ATS suites for CLI, ingestion, panel timing, funnel, accounting, worker recovery, and research Casefiles. Run API/import smoke tests for both legacy and new-mode entry points. Re-review main if origin/main advances.

### C-03 — COMPATIBILITY_RISK: archival move is not native strategy migration

- **Source/evidence:** `docs/architecture/dual_mode_20261015/archive_inventory.md`, `migration.md`, `tests/test_legacy_archive_safety.py`. ATS integration relocates 29 tracked files with R100 Git renames: 14 one-off scripts and 15 frozen YAMLs. Migration explicitly states ORB, EOW, specialized Dukascopy and M8 strategy parity is **not** established.
- **Risk:** external shell commands, importers, frozen paths, downstream tests, documentation and research replay lose old paths; an apparently generic native backtest silently changes fills or signal timing.
- **Correction:** retain all archived bytes and immutable identities; provide explicit compatibility entry paths or migration mappings to every actual consumer. Never claim parity from an archive rename or synthetic factory test. Do not retire a strategy until matched sources, calendar, entry/exit events, native fills, costs and account ledger are independently compared.
- **Verification:** `tests/test_legacy_archive_safety.py`; hash comparison against original inventory; frozen config loader and CLI resolution smoke tests; strategy-by-strategy event/equity parity where retirement is proposed.

### C-04 — COMPATIBILITY_RISK: scientific authority must survive cutover

- **Source/evidence:** `src/research_session.py`, `src/research_control/attempts.py`, `src/oracle/stage3_falsifier.py`, `src/engine/funnel.py`, `src/data_vault/panel_builder.py`, `docs/architecture/dual_mode_20261015/phase2_cutover_verification.md`; existing `run_log/eow_rebuild/_final_holdout_claims/`, `docs/audit/m8_agent_qualification.md` and frozen M8 specifications. Migration says legacy contracts/attempts are compatibility authority, not converted history. Phase-2 report records a *FALSIFIED_STAGE_2* economic result rather than unconditional success.
- **Risk:** a replayed or reconstructed registry drops negative trials, selection-family exposure, development/protected boundaries, single-use claims, source hashes, or clocks; engineering failure is mislabeled economic falsification.
- **Correction:** preserve append-only historical attempts, manifest bytes/IDs, freeze receipts, family/trial exposure and consumed protected claims. Keep data availability <= decision <= fill time, native ML4T events/accounting, and outcome taxonomy: valid economic failure vs infrastructure/unknown. Treat missing evidence as INCONCLUSIVE.
- **Verification:** immutable snapshot/hash comparison before/after merge; synthetic protected-access cross-window, issuer, consumption and replay tests; selection-family ledger reconstruction; prefix-invariant PIT signal tests; matched native event/fill/equity audit; terminal status regression with induced engineering failure.

### C-05 — QUALIFICATION_LIMITATION: isolated ATS-6/7 signatures do not certify a new merge tree

- **Source/evidence:** `docs/audit/ats6_qualification_20261017.md`, `docs/audit/ats7_qualification_20261017.md`, `src/shadow_router.py`, `src/release_runtime.py`. ATS-7 reports ATS-6 artifact identity verification (211 hashes, 31 SQLite databases), scoped synthetic qualifications, and a separately operating observation. Its report explicitly denies full external provider execution qualification and live approval.
- **Risk:** integrations altering callers, schemas, policies, manifests, or dependency versions invalidate assumptions without changing historical reports.
- **Correction:** retain historical reports unmodified; record new merged SHA, dependency lock, source/evidence identities and fresh qualification delta. Do not rewrite old certificates as though they were produced on new tree.
- **Verification:** ATS-2/3/4/6/7 cross-module acceptance plus independent oracle on merged SHA; checksum and schema/compatibility audit; exact identity comparison and fresh release authority test.

### C-06 — QUALIFICATION_LIMITATION: ATS-7 observation remains distinct

- **Source/evidence:** `docs/audit/ats7_qualification_20261017.md`, `docs/architecture/trading_system/ats7_release_boundary.md`, `src/bybit_paper_runtime.py`. Report says a separate synthetic PAPER_RUNNING observation began **2026-10-17 06:38:25 UTC**; earliest elapsed four weeks **2026-11-14 06:38:25 UTC**. Research release eligibility and live authorization blocked; fresh provider Demo order scenarios not qualified.
- **Risk:** integration accidentally stops/changes the process or describes elapsed observation as complete provider qualification.
- **Correction:** no operations against that running process/state; maintain separate deployment identity. Explicit fresh authorization and provider evidence for any later real provider test.
- **Verification:** external read-only service/deployment inspection by observation owner, process identity and heartbeat before/after merge; verify unchanged journal and that no new order permission is inferred.

### C-07 — QUALIFICATION_LIMITATION: ATS-8 benefit is not proven by benchmark

- **Source/evidence:** `docs/architecture/trading_system/ats8_operations.md`, `src/research_control/learning.py`, `tests/test_ats8_learning.py`. 14-fixture reported benchmark: 18 median tool calls without learning, 33 with learning; 0/0 remedy-resolvable benchmark fixtures; 11 retained raw traces, 3 lost during cleanup.
- **Risk:** advertising superior efficiency or full evidence completeness is unsupported; stale lessons might become authoritative if their scope guard weakens in integration.
- **Correction:** expose ATS-8 as optional, advisory, version-filtered evidence; no authority over permits, trading, source manifests or trial outcomes. State benchmark limitation; do not optimize claimed outcomes using observed protected evidence.
- **Verification:** no-learning baseline and with-learning ablation on merged SHA; stale lesson/source/code/version rejection tests; forbidden-side-effects tests; remedy-positive independent fixture before asserting practical improvement.

### C-08 — COMPATIBILITY_RISK: archived CLI entry points need consumer-level testing

- **Source/evidence:** renamed `archive/legacy_v1/scripts/run_orb_*.py`, `run_eow_rebuild.py`, `run_ftmo_challenge_simulation.py`, `run_pipeline.py`, `audit_milkman_*.py`; relocated `archive/legacy_v1/config/research_sessions/*.yaml`. Nine candidates retained at original paths per inventory because of executable consumers.
- **Risk:** users and unattended jobs invoking historical `python scripts/run_...` or `config/research_sessions/...` paths now fail despite R100 content preservation. Imports inside relocated scripts may depend on original module execution context.
- **Correction:** identify all external cron/systemd/docs/config consumers; either preserve wrappers at old locations or document and validate executable `python -m`/explicit archived-path replay. Historical reports remain immutable.
- **Verification:** smoke tests from repository root and archived path, frozen YAML reopening, historical runner imports with no provider/holdout side effects, systemd/cron inventory by operations owner.

## Legacy preservation matrix

| Family | Example authority | Status at ATS integration | Retirement |
| --- | --- | --- | --- |
| EOW | `src/eow_rebuild.py`, archived `run_eow_rebuild.py`, `run_log/eow_rebuild/` | Historical compatibility, native strategy parity not proven | **NO** |
| ORB raw/ML/validated | `src/orb_raw_optimization.py`, `src/orb_ml_research.py`, `src/validated_orb_pipeline.py`, archived `run_orb_*.py` | Historical compatibility, specialized fills/calendar not ported | **NO** |
| CFD and Dukascopy | `src/research_control/dukascopy_native.py`, Milkman scripts, source-to-CFD configs | Legacy specialized execution; generic vault not exact fill parity | **NO** |
| M8 cash/N8 | `scripts/run_m8_n8.py`, `scripts/run_m8_cash_session.py`, archived frozen M8 YAMLs, M8 audit | Existing dedicated runners and frozen case/recovery evidence | **NO** |
| Prop / FTMO | archived `run_ftmo_challenge_simulation.py`, existing prop evidence | Historical simulation only; no validated generic prop account equivalence | **NO** |
| Research sessions | `src/research_session.py`, `src/research_control/attempts.py`, `run_log/research_sessions/` | Legacy authoritative history with additive new-mode path | **NO** |
| One-off runners | archived `run_pipeline.py`, `run_full_10y_backtest.py`, Milkman auditors | Byte-preserved forensic tools; execution compatibility must be tested | **NO** |
| New thesis factory | `scripts/quant.py`, `src/workbench.py`, `src/engine/funnel.py` | New native ML4T research path; not old-strategy substitute | N/A |

## Release acceptance checklist and handoff

1. Sessions A/B produce an exact integrated SHA and prove all ATS-3/4/5/6/7 modules and tests survive ATS-8 integration; any unexplained removal is a **blocker**.
2. Resolve shared mainline differences with semantic code review and run native dual-mode + ATS-0–8 regressions on **that SHA**, not only historical branch SHAs.
3. Demonstrate archived-path consumer compatibility and immutable source/trial/holdout identity before cutting over default commands; do **not** retire old engines.
4. Publish merged-SHA qualification delta and preserve ATS-7 observation identity independently; never substitute synthetic/local-paper testing for fresh provider qualification.
5. Keep ATS-8 learning advisory, document measured efficiency regression, and record all remaining unknowns.

**Final:** `CONDITIONAL`. An additive code merge is acceptable **only after** C-01 and C-02 release gates demonstrably pass. Direct ATS-8 replacement, lost legacy authority, lost qualified ATS path, or unreviewed merged-tree regression means `BLOCKED`. Neither result grants provider, paper-duration, or live authority.
