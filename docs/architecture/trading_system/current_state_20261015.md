# Evidence snapshot for the architecture revision

**Observed on 2026-10-15.** This is a dated, read-only inspection record, not a
live status service. Reinspect before implementation. Sources are current code,
Git/GitHub metadata, repository evidence reports and two bounded specialist
reviews. No market experiment, protected history or account mutation was run
for this architecture task.

## Repository identity and concurrent work

Original checkout: `/home/quant/dev/quant/quant-research`, workspace
`ws_8cc0b9965d`, branch `local-first-main-sync-20261014`, observed HEAD
`9525f35667bf439781bff19edd0c9681da0b7080`. It contains extensive legitimate local
research and tracked dirty changes. It is not the documentation write target.

Active rebuild worktree: `/home/quant/.devspace/worktrees/quant-research-25440f7a`,
workspace `ws_cea0c4794f`, branch `feat/rebuild-20261015-governed-core`, inspected
HEAD `601e26ad6514487b424ca92f4b80996bca76699e`. This follows the prior response's
`971d991` checkpoint. The remote branch matched `601e26a` when queried; remote
main was `fbfc2ed2288ec12f9ed07e6de191dfb9fde36d9d` at that query.

GitHub PR #59, titled "feat(research): add tested dual-mode runtime and native
funnel", was reported MERGED at `2026-10-15T11:55:22Z`. A merged earlier PR does
not prove that every later branch commit or local file is on main.

Concurrent, task-unowned work appeared in `scripts/quant.py`,
`src/engine/funnel.py`, `src/workbench.py`, `src/data_vault/market_materializer.py`
and `tests/test_dual_mode_market_materializer.py`. This documentation task does not
modify or stage them. Their working bytes may advance independently. Active
worker and tmux sessions were inspected without killing or restarting them.

## Verified code facts versus recorded qualification

| Capability or claim | Evidence and interpretation |
| --- | --- |
| Shared factory/Workbench | `scripts/quant.py`, `src/workbench.py`, `src/engine/funnel.py`; implemented interfaces, not arbitrary strategy compatibility |
| Cross-sectional gate assumptions | `funnel.py` calls neutrality, `stage2` and `stage3`; current protocol cannot be declared universal for ORB/event rules |
| New-mode ledger and Casefile | `src/engine/common.py`, `funnel.py`; append-only history and derived result views exist |
| Protected read | `funnel.py` invokes `DataVault.unlock_holdout` after Stage 3 and identity checks; `src/data_vault/vault.py` supplies cooperative claims. Distinct external authorization is a target gap |
| Recovery | Monthly ingestion receipts support reuse. They do not establish universal same-attempt factory recovery or crash equivalence at every boundary |
| Pure prop risk policy | `src/portfolio/policy.py` computes a research-only proposal from supplied marks; `barrier_controller.py` re-exports it. No atomic account/global reservation or order router is established by these functions |
| Latest recorded cutover | `../dual_mode_20261015/phase2_cutover_verification.md` records the full matched-source build and real negative Stage 2 outcome |
| Earlier tests | `../dual_mode_20261015/verification.md` records 400 fast tests plus one bounded real-data smoke at its tested identity. Those tests were not rerun as part of this docs-only revision |
| Legacy paths | `../dual_mode_20261015/migration.md` distinguishes actual file relocation from strategy parity. Do not interpret a migration map as completed porting |
| Connector scope | Read-only specialist inspected `/home/quant/dev/trading-connector/AGENTS.md`, `docs/architecture.md` and policy-related sources. Transport/bridge behavior and runtime qualification remain provider-specific |
| Monitoring | The preceding response directly observed VPS metrics UP and ML4T target DOWN. This document task did not repeat that live endpoint check; do not report those observations as fresh runtime health |
| Cross-system operating interface | Casefile/action projection, transactional router, attribution audit, reviewed rulebook loop and benchmark in the new design are proposed; not implemented by these edits |

## Updated research boundary

The phase-two cutover report records 530 matched source symbols in the union of
development/protected partitions, with 484 development symbols and 8,296,320
development price rows. It records Stage 1 PASS and `FALSIFIED_STAGE_2` for an
explicitly prompt-derived example. Stage 3 was not executed and real protected
outcomes were not opened by that run. These are reported artifact facts, not a
new independent full-market rerun in this architecture session.

The previous response's "full 530-symbol compile not executed" limitation has
therefore been superseded by the later cutover report for ingestion and negative
Stage 2 qualification only. It has not become proof of profitable native Stage
3/4 execution or general live readiness.

## Independent bounded design reviews

Two read-only DevSpace/Codex reviews completed: `agt_f1d5eb6e` (research/control
interfaces) and `agt_47a46b77` (risk/routing/audit failure modes). They made no
implementation changes and did not use credentials or broker endpoints.

Their findings informed the target: explicit protocol selection; separate
permission and integrity claims; truthful compact status; identity-bound recovery;
atomic risk reservations; multi-leg intent ownership; unknown-ack reconciliation;
account-specific rule applicability; intraday equity-path evidence; and separation
of actual payout cash from counterfactual losses. ChatGPT inspected the core funnel
and current documentation directly; the reviews are architectural evidence, not
proof that proposed controls already pass runtime tests.

## Treatment of the videos and uploaded examples

The user's summaries provide the motivating operating model. Their firm counts,
routing reconciliation, speed and ROI claims are not independently verified here.
Drawdown-only grouping, a universal 0.5 threshold and independence-based losing-
month arithmetic are not adopted as established production rules.

The uploaded Shannon `portfolio.py` describes a daily return/weight overlay with
free daily rebalancing; it does not implement a multi-account intraday router.
Its return matrix cannot by itself prove account-rule survival. The target keeps
this distinction without replacing the uploaded source or claiming its results
were independently reproduced in this task.

## Interpretation

The architecture changes are recommendations grounded in these observations.
Source statements, inference, target decisions and implementation status remain
separate. Dated verification reports are preserved unchanged. This snapshot
expires as operational status when code, rules, accounts or runtime state change.

## Documentation revision verification

The revision creates eight design/plan documents and updates eleven existing
entrypoint/glossary/design files. Relative-link validation checked 19 documents
and 105 local links with no missing target paths. `git diff --check` passed for
task-owned documentation. No application test-suite pass is claimed: this was a
documentation-only change, and concurrent application edits belong to another
workstream. Historical verification reports and frozen research records remain
unchanged.

The first research/control reviewer also reviewed the completed document set.
Its final findings required explicit forged/mis-scoped authorization tests,
stale-writer fencing after lease takeover, and removal of an unscoped historical
backtest badge. These corrections were applied to the rollout and README; the
same reviewer then confirmed all three findings were addressed in a bounded
read-only closure check. That confirms the documentation fixes, not runtime tests.
No runtime implementation, broker action, protected-data read, commit, staging
or push was performed by this documentation task.
