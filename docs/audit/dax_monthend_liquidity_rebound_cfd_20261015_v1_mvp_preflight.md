# DAX month-end CFD — MVP source/feasibility decision (2026-10-15)

**Candidate:** `dax_monthend_liquidity_rebound_cfd_20261015_v1`  
**MVP conclusion:** **INCONCLUSIVE — BLOCKED_DATA before Phase 3 outcome evaluation.** This is not a REJECT or VALIDATE finding, and no net backtest or trading execution occurred.

## Frozen user-supplied thesis
- Original YAML: `config/research_sessions/dax_monthend_liquidity_rebound_cfd_20261015_v1_gemini_source.yaml` SHA-256 `61a96451146f486bb6112472a0ccfec806aaff683d7c4a88ba44ab5359c6fc27`.
- Original brief: `docs/audit/dax_monthend_liquidity_rebound_cfd_20261015_v1_gemini_brief.md` SHA-256 `2fe825eaa1fcc097cdf2479197621b7d79f6e46b6b6157785b44253ce72453cf`.
- Calendar long candidate: Xetra month-end T, 09:10 Berlin signal, next legal 09:11 buy; T+3 17:10 signal, next legal 17:11 sell.
- Paired control: T-10 09:11 buy to T-7 17:11 sell. Same-entry-weekday restriction. No rule tuning; 1.0x initial EUR NAV notional. Development at most January 2018–November 2024. No access to 2025+ research returns or protected holdout.
- Falsifier after full qualification: standalone candidate net mean <= 0 or monthly paired candidate-minus-control net mean <= 0, with at least 60 complete independent pairs and six years. A positive effect requires paired HAC(3) 95% lower confidence bound > 0 to justify separate validation.

## Evidence directly inspected
1. Existing DevSpace workspace `ws_f6cd0671bf`, checkout `/home/quant/dev/quant/quant-research`, branch `local-first-main-sync-20261014`, initial HEAD `9525f35`, 899 pre-existing dirty/untracked changes. Those are preserved.
2. Referenced `docs/prompts/gemini_to_ml4t_mvp.md` **does not exist** in this checkout. Applicable replacement authority inspected: `AGENTS.md`, `docs/research_operations.md`, `docs/research_sessions.md`, `docs/architecture/market_scope_policy.md`, and `docs/phase3_signal_evaluation_template.md`.
3. Actual canonical dataset `/home/quant/dev/quant/ml4t-data/.data/store/index_minute_DAX` exists. Partition counts by year 2018–2024: 290, 312, 312, 310, 310, 306, 313 respectively. These are **partition counts**, not verified complete Xetra sessions. A November 2024 partition has `timestamp` of Polars Datetime(time_zone=UTC), symbol `DAX`, and numeric OHLCV; timestamps begin at 00:00 UTC. **Bar-start convention, individual clock coverage and true execution prices remain unproved.**
4. Existing repository source notes describe `index_minute_DAX` as **Dukascopy `deuidxeur` historical BID-only CFD price proxy** (`config/research_sessions/mechanicalpremia-original-four-2013-2024-v1.yaml`). `scripts/pilot_b0_dax_dukascopy_source_20261012.py` separately names the official public `DEUIDXEUR` `BID_candles_min_1.bi5` feed. These support likely symbol provenance, not historical executable ASK/bid parity, contract details, or dividend mapping.
5. Installed libraries: `ml4t-backtest 0.1.7`, `ml4t-engineer 0.1.4`; native `Strategy`, `Engine`, `DataFeed` and `BacktestConfig` are importable. XETR calendar resolves through installed `exchange_calendars`. A calendar-only preflight for the frozen 83 months gives **73 matching entry weekdays and 10 unmatched**. This is theoretical calendar eligibility only, **not 73 valid/executable paired trades**. Historical early-close and official effective-dated calendar parity have not been audited.

## Predeclared ResearchPhase 3: **INCONCLUSIVE**
The feature is deterministic calendar scheduling; no technical indicator, cross-sectional IC or ML model is needed. The matched fixed-horizon gross event-price screen is conceptually applicable, but the actual price source/clock must first be qualified. **No return observation was read or computed, no Phase 3 score was produced, and no full native execution was started.** It would be methodologically invalid to call Phase 3 PASS or FAIL. This is a **pre-outcome source audit**, not a completed performance diagnostic.

## Hard blockers to executable qualification
- Bid-only proxy contains no observed **historical ask** for long entries. Cannot invent spread, infer ask from bid OHLC, or treat the bid-only close/open as executable buy prices.
- Missing independently effective-dated Dukascopy **overnight/weekend financing, commission tiers, dividend cash adjustments**, DAX price/performance variant mapping, slippage and contract multiplier/minimum lots. The thesis explicitly prohibits using unqualified current fees as historical costs.
- Need explicit vendor bar-open timing, exact required 09:11/17:11 source and broker quote completeness, Xetra holidays/early closes, broker hours and DST checks without conditioning prior entries on later quote coverage.
- Confirm repo-wide protected research boundary. Do not infer that overlapping already-observed 2018–2024 studies provide unseen validation.

## Decision and next permissible action
**INCONCLUSIVE (BLOCKED_DATA).** Preserve this one fixed thesis, source hashes and negative/blocked evidence. Do not backfill fictional costs, change instrument, generate a custom PnL simulator, score bid-only gross patterns as net return, register an executable permit, read protected holdout, or promote. A future attempt requires actual effective-dated broker/quote/financing/dividend and lot evidence, then a separate preregistered Phase 3 screen and native `ml4t.backtest.Engine` only if the gates pass.

**Scope:** No live orders, no performance optimization, no commit/push, and no modifications to unrelated files. The source YAML is a discovery handoff, not a valid executable ResearchSessionSpecV1; do not falsely register a frozen execution session without verified sources/costs.
