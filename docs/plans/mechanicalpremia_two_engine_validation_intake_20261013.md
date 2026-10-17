# Mechanical Premia — Validation Intake and Conditional Plan (2026-10-13)

## Authority and current disposition
Research session: `mechanicalpremia-two-engine-mvp-20261013`.
This is an **intake / conditional plan**, NOT an active Validation session or a frozen validation trial ledger. No OOS or native validation has run. The existing MVP SessionSpecV1 is immutable.

Evidence inspected:
- Frozen spec: `run_log/research_sessions/mechanicalpremia-two-engine-mvp-20261013/frozen_spec.json`, frozen 2026-10-13T11:25:27.717637+00:00.
- Existing plan: `docs/plans/mechanicalpremia_two_engine_mvp_20261013.md`.
- Source identity note: `docs/plans/mechanicalpremia_two_engine_mvp_source_archive_20261013.md`.
- Read-only derived Casefile: `IN_PROGRESS`, reason `TRIALS_PENDING`, zero attempts, next safe action `Obtain a new verified RunPermit for the next declared development trial`. Generated with `scripts/research.py casefile --root /home/quant/dev/quant/quant-research --session mechanicalpremia-two-engine-mvp-20261013` from existing worktree revision `fa4abd0`, because the dirty main checkout at `98d5949` lacks that read-only command.
- MVP trial ledger: SOURCE-PARITY, DATA-ELIGIBILITY, H1-ONLY, D1-ONLY, PORTFOLIO-EQUAL-RISK, PORTFOLIO-SOURCE-RISK: **0 complete / 0 failed / 6 pending**.
- No Mechanical Premia tmux session or current Codex execution found at intake. Existing unrelated processes and dirty files untouched.
- Protected final test: `[2025-01-01T00:00:00Z, +infinity)` under the frozen session declaration. DO NOT open.
- Original article source was historically available, but full local MQL5 archive, source fidelity verification, source mapping and broker execution provenance are not yet qualified.

## Gate: do not run validation yet
Required MVP evidence before any separate validation session:
1. Complete source parity (including actual MQL5 iBands buffers, D1 no-hard-stop vs ghost-size, H1 1-minute-aware trailing semantics).
2. Qualify canonical ES/NQ CFD research proxies: vendor, instrument identity, timestamp/bar semantics, session hours and DST, contract/lot/multiplier, bid/ask and financing assumptions. A CFD proxy is not CME futures and not automatically executable at a named broker.
3. Obtain proof for the required engineer features or parity-certified extensions, **native** ml4t.backtest orders/fills, cash/positions/equity, conservative gaps and fees, and all six trial records with hashes.
4. Independently check that the predeclared MVP source-risk combination has positive stress-cost net expectancy and improves BOTH daily-equity Sharpe and max drawdown versus each frozen comparator across eligible development subperiods. If it fails, REJECT without validation. If unknown, mark INCONCLUSIVE; do not treat missing trades as zero-return evidence.
5. Resolve any observed past uses of the proposed validation interval; a previously examined period is NOT fresh OOS merely because a new session name is assigned. Published-source selection exposure is a limitation.

## Conditional, bounded validation design (not executed)
**Candidate:** unchanged source-risk D1/H1 portfolio using ES_PROXY/NQ_PROXY. No new features, sizing optimization, instrument additions, or stops.

**Chronological partition proposal, only if data proven eligible and the time segment remains unobserved for local model selection:**
- MVP/development: `[2017-01-01, 2022-01-01)`, with predeclared warmup and broker-session-aware aggregation.
- Candidate validation: `[2022-01-01, 2025-01-01)`, NEVER including 2025-01-01 onward.
- Before freezing validation, compare actual earlier trial footprints. If the MVP already evaluated 2022–2024, label the interval *observed robustness*, not OOS; acquire separately authorized virgin data below 2025 cutoff if available, or conclude validation BLOCKED. Do not use a different cut motivated by profits.
- This proposal does not alter the existing frozen MVP evaluation boundary. A different candidate selection/evaluation rule requires a separately registered, prospective session before the affected outcomes are observed.

**Conditional preregistration plan (formal registrations ONLY after the MVP gate):**
- `VAL-CHRONO-1`: one unchanged, native-engine chronological validation of H1-only, D1-only, equal-risk combination and fixed 76.64% D1 / 23.36% H1 portfolio on identical calendar/clock. Compare daily equity Sharpe, Calmar, max DD, net PnL, trades, win rate, expectancy, exposure and portfolio beta; ledger every attempt.
- `VAL-COST-1`: fixed source-risk portfolio with **1.0x / 1.5x / 2.0x** the qualified per-side commission + spread + slippage schedule; account separately for overnight financing at documented broker charge/holding schedule. No optimizing the stress or a retrospective "typical" spread to rescue performance. Record native executions and fill gaps.
- `VAL-AUDIT-1`: independent re-computation of key daily-equity accounting, point-in-time features, fill clocks, stop gaps, cost deductions, cash + marked positions = equity, and per-year 2022/2023/2024 returns; where sample adequate, paired 20-session moving block bootstrap (2,000 draws, fixed seed 20261013) for difference in portfolio vs comparator daily equity Sharpe and net returns. If insufficient, mark uncertainty undefined. No new economic parameter search.

**Falsifier:** preserve the original registered portfolio falsifier and MVP acceptance thresholds, with additional validation constraint that apparent benefit cannot disappear at 2x costs, cannot depend only on one calendar subperiod, and must satisfy all native execution/source data gates. This plan does not replace the frozen falsifier.

**Possible decisions AFTER evidence:** REJECT (invalid or negative), REVISE AS NEW TRIAL (substantive change needs new thesis/session), PROMOTION CANDIDATE (auditable positive results; final test still sealed; not trading approval).

## Current action and prohibition
Next lawful work is finishing already declared MVP development trials, starting with SOURCE-PARITY and DATA-ELIGIBILITY, with fresh verified RunPermit. Do not register or run the conditional validation trials now. Do not modify the original frozen MVP spec, run protected final test, place live orders, or touch unrelated working-tree files.
