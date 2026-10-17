# Structural alpha mission report — 2026-10-11

## Decision

**BLOCKED / EXPLORATORY / NOT_APPROVED.** No new strategy result supports adoption. The primary S2 study stopped at its input gate. Existing S1 results are retrospective and do not qualify for live use. S3–S5 received feasibility or provenance review only, as the mission required. No protected September–October 2026 outcome was opened.

This is a completed gate review, not a completed market study. The next decisive question is whether an auditable, dated CME/CBOT contract-and-quote dataset exists for ES, ZN, ZB and UB. That dataset must include actual contract symbols, roll pairs, bid/ask, exchange sessions and costs. If it does not exist, S2 cannot proceed.

## Scope and preservation

- Inspected HEAD `c095faab89835c49f4cd6fd66d1a9ed922709039`, the mission, `docs/research_sessions.md`, `run_log/validation_status.json`, session records, and prior Gotobi reports.
- The working tree had extensive unrelated dirty and untracked work. No existing file was edited or deleted. New research artifacts use the `structural_alpha` prefix.
- No commit or push was made.
- The legacy ORB status remains `NOT_APPROVED`.

## Registered causal hypotheses

- **S1 USDJPY Gotobi:** Already registered in `gotobi_exact_paper_bridge_20261011_v1` and prior Programs 1–3. It compares the frozen 03:00 JST long through the declared 09:55 boundary with same-clock ordinary controls. Existing evidence is historical, not new OOS.
- **S2 60/40 month-end:** Registered before any new outcome analysis as `structural_alpha_eow_6040_20261011`. The frozen thesis tests whether prior equity/bond relative-return imbalance predicts month-end pressure in ES and Treasury futures beyond matched ordinary windows. The falsifier requires a corrected, stable, after-cost effect. T0 stopped the track because exact dated futures and quote inputs are missing.

The session declaration is at `config/research_sessions/structural_alpha_eow_6040_20261011.yaml`. Its frozen identity is in `run_log/research_sessions/structural_alpha_eow_6040_20261011/frozen_spec.json`. The declaration is `EXPLORATORY` and `NOT_APPROVED`.

## Seven-phase execution record

1. **Registration:** S2 was initialized before result analysis. The existing S1 registration was retained. S2 froze chronological development bounds, matched controls, candidate tests, falsifiers and cost requirements.
2. **Data audit:** `es_1m.parquet` has 651,955 rows, UTC timestamps from 2024-01-01 23:00 through 2025-12-31 21:13, and OHLCV plus symbol columns. It does not establish dated contract identity, roll prices, historical bid/ask or executable fills. The frozen ZN, ZB and UB paths are absent. Current CME product pages confirm ES is $50 × S&P 500 with a 0.25-point ($12.50) outright tick; ZN has $100,000 face value with a 1/2 of 1/32 tick ($15.625); and Treasury bond / Ultra T-Bond standard contracts use $100,000 face value and 1/32-point ticks ($31.25). These product facts do not supply dated contract history, roll pairs, delivery conversion factors, historical bid/ask, or broker/exchange fee schedules. CME Globex currently lists Treasury hours in ET; exact historical session calendars and DST treatment remain to be audited. T0 status is `failed`; the session gate is `BLOCKED`. For S1, LSE USDJPY is an OHLC proxy. The Gotobi bid/ask pilot reports only 1 of 14 required weekly quote exports verified, with the rest blocked by provider limits. Existing Programs 1–3 reports were reviewed as retrospective evidence.
3. **Structural event study:** Not run for S2. The required contract data and costs failed T0. No synthetic proxy substituted for missing futures contracts. Existing S1 controlled event studies remain historical and have weak or unstable results; they do not identify settlement flow.
4. **Native backtest:** Not run for S2 because the S2 data gate failed. No hand-built simulation was used. Prior S1 reports document native `ml4t.backtest.Engine` runs, but those use historical LSE OHLC proxies and assumed costs, not verified broker fills.
5. **Chronological validation:** Not run for S2. The registered folds and final period remain unopened. Prior Gotobi 2020–August 2026 analyses are already observed and are not fresh OOS. The protected September–October 2026 period remains unread.
6. **Refutations:** S2 registered matched ordinary windows, calendar/placebo tests, cost stress and independent audit, but none ran without T0. Prior S1 reports include ordinary controls, placebo windows, yearly/regime splits and cost sensitivities. Historical trial counts outside those ledgers remain incomplete, so full-search DSR/PBO cannot be reconstructed.
7. **Independent audit and status:** The built-in session diagnostic recorded the observed ES schema and exact file identity, and missing ZN/ZB/UB data. It computed no strategy metrics. Decision: **BLOCKED**, not adoption, rejection of the economic hypothesis, or deployment approval.

## Feasibility-only tracks

- **S3 IBA round:** No precise definition or data path for “IBA round” is present in the mission or canonical data manifest. I did not infer a meaning or run a test. Provide the source, symbols and exact date window before this audit can proceed.
- **S4 WMR EURUSD/GBPUSD:** The repository has EURUSD and GBPUSD 5-minute development/holdout partitions for a different FX study. It has no identified WMR event quote dataset or WMR-specific execution-cost source. These bars cannot establish fixing-window executable economics. Feasibility remains blocked pending event-aligned bid/ask and cost evidence.
- **S5 crypto momentum:** Existing cross-asset TSMOM replication evidence reports `THESIS_NOT_SUPPORTED_BY_FIXED_COMPOSITE`; its preregistered 4-of-5 positive and 2x-cost gates failed. This is sufficient for feasibility triage only. It is not a new trial or adoption basis.

## Evidence and hashes

- S2 frozen spec SHA256: `0df988b6770d7828ab35ef51a749ea069bad07f50adf824648727488989301ce`.
- S2 T0 audit artifact: `run_log/research_sessions/structural_alpha_eow_6040_20261011/diagnostics/T0_contract_data_gate.json`.
- S2 T0 terminal record: `run_log/research_sessions/structural_alpha_eow_6040_20261011/trials/T0_contract_data_gate.json` (`failed`).
- Full session report: `run_log/structural_alpha_eow_6040_session_report.json`.
- S1 evidence: `docs/audit/gotobi_exact_paper_bridge_20261011_v1.md`, `docs/audit/tokyo_alpha_map_program1_closure_v3_20261011.md`, `docs/audit/tokyo_fix_program2_cross_currency_20261011_v1.md`, `docs/audit/tokyo_fix_program3_ohlcv_execution_20261011_v1.md`, and `docs/audit/gotobi_lse_bidask_execution_pilot_20261011_v1.md`.
- S5 feasibility source: `run_log/cross_asset_tsmom_replication_20261007/phase2_3_summary.json`.
- Current product-spec sources checked on 2026-10-11: [CME ES contract specs](https://www.cmegroup.com/markets/equities/sp/e-mini-sandp500.contractSpecs.html), [CME ZN contract specs](https://www.cmegroup.com/markets/interest-rates/us-treasury/10-year-us-treasury-note.contractSpecs.html), [CME ZB contract specs](https://www.cmegroup.com/markets/interest-rates/us-treasury/30-year-us-treasury-bond.contractSpecs.html), and [CME Treasury futures basics](https://www.cmegroup.com/trading/interest-rates/basics-of-us-treasury-futures.html).
- Initial mission validation state remains in `run_log/validation_status.json` and was not changed.

## Methods and gates

Loaded local procedures before the market-data gate: `ml4t-continuous-futures`, `ml4t-calendar-ops`, `ml4t-point-in-time`, `ml4t-validate-data`, `ml4t-evaluate-factor`, `ml4t-run-backtest`, `ml4t-cost-model`, `ml4t-polars-patterns`, and `ml4t-lookahead-bias` from `.agents/skills/`. Their relevant invariants were: use dated contract prices and explicit roll handling; use exchange calendars and time zones; use only information available by each decision; validate schemas, timestamps and gaps; match diagnostics to the time-series/event design; use the installed event-driven engine for fills; source instrument-specific execution costs; use Polars expressions for transformations; and keep chronological validation free of future data. S2 did not pass its source gate, so no feature, event-study or backtest code was written.

The repository session gate ran `init`, `check`, `diagnose`, and `report` for S2. The diagnostic correctly limited itself to descriptive data auditing. It did not fit a model, calculate returns, or read the holdout. No test suite was run because no implementation code changed.

## Status and next step

Status: **BLOCKED**. Do not promote any track. The next action is to obtain independently verifiable dated ES/ZN/ZB/UB contracts with synchronized bid/ask, rolls, contract specs, trading calendars and dated fee assumptions. Then re-freeze a new session if the data identity or specification changes, and run the already declared T1–T5 trials chronologically. Keep the protected final period sealed.
