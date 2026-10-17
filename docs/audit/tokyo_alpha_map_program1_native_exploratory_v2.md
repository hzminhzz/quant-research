# Program 1 — Native USDJPY Gotobi execution continuation v2

**Session:** `tokyo_alpha_map_program1_native_exploratory_v2`  
**Status:** EXPLORATORY / NOT_APPROVED  
**Original Program 1:** `tokyo_alpha_map_program1_v1` (frozen, unchanged)  
**Scope:** 2020-01-01 through 2026-08-31 JST; September 2026 onward protected and not read

## Executive result

This is an explicitly authorized **exploratory native execution replay**, not a reconsideration of the old statistical screening. It uses the installed `ml4t.backtest.Engine` (NEXT_BAR OPEN) for three preselected rules. Costs are unverified historical broker assumptions.

| Metric | Gotobi long 08:30–09:54 | Gotobi short 09:56–10:10 | Ordinary short 09:56–10:10 |
| --- | ---: | ---: | ---: |
| Trades | 458 | 458 | 1,143 |
| Native fills | 916 | 916 | 2,286 |
| Gross mean pips | +2.337 | +1.728 | +0.484 |
| **Net mean pips** | **+1.337** | **+0.728** | **-0.516** |
| Net win rate | 53.7% | 51.7% | 44.6% |
| Net profit factor | 1.213 | 1.226 | 0.842 |
| Closed-day USD Sharpe including flat bank days | 0.603 | 0.605 | -0.804 |
| Max closed-trade drawdown USD | -211.92 | -83.01 | -486.50 |
| Starting USD equity | 10,000.00 | 10,000.00 | 10,000.00 |
| **Net P&L USD** | **+456.94** | **+217.14** | **-450.95** |
| **Ending USD equity** | **10,456.94** | **10,217.14** | **9,549.05** |
| Cumulative USD return | +4.57% | +2.17% | -4.51% |

The percentages are **total** retrospective returns across roughly six years and eight months, not annualized, and no compounding is modeled. The reported max drawdowns are only at completed-trade endpoints, not marked-to-market or margin drawdowns.

## Why the coverage changed

The original Program 1 strict full-window screen required every 03:00–12:00 JST minute. That retained only 999 / 1,627 bank business dates and excluded all dates after 2026-04-24 because 06:01–06:03 JST was missing for May–August.

For the already declared 08:30–09:54 and 09:56–10:10 trades, **06:01–06:03 has no bearing on an order or reference label**. This continuation instead requires every minute open from 08:29 through 10:10 JST, inclusive (102 bars), with no interpolation or synthetic fills. It uses exactly the frozen seven annual Program 1 LSE snapshots and official Tokyo bank-day registry, not a refreshed vendor or a different quote source.

- Expected Tokyo bank dates: **1,627**.
- Complete trade-window dates: **1,601** (98.4%).
- Complete Gotobi dates: **458**.
- Complete ordinary dates: **1,143**.
- Missing/incomplete dates: **26**, with explicit list in data-gate artifact.
- First complete date: 2020-01-06.
- Last complete date: 2026-08-31.
- Final included Gotobi date: 2026-08-28.
- Holdout data at or after 2026-09-01 JST: **not read**.

The new sample is larger than the original 999-day exploratory study, so its results are not directly comparable as if the only difference were execution quality. Neither sample is genuinely unseen.

## Yearly net realized USD P&L

| Calendar year | Gotobi short trades | Gotobi short USD | Gotobi long USD | Ordinary short USD |
| --- | ---: | ---: | ---: | ---: |
| 2020 | 64 | -44.996 | +115.605 | -131.642 |
| 2021 | 70 | +11.429 | +102.659 | -74.566 |
| 2022 | 71 | +65.012 | +42.709 | +193.167 |
| 2023 | 70 | +66.773 | +74.392 | -59.947 |
| 2024 | 70 | +79.093 | +86.067 | -112.321 |
| 2025 | 68 | +86.311 | -14.445 | -157.853 |
| 2026 Jan–Aug | 45 | -46.483 | +49.951 | -107.789 |

The short is positive in 2021–2025 but negative in 2020 and 2026 YTD. This time instability materially weakens a production hypothesis. Gotobi H1 long is negative in 2025.

## After-cost sensitivity

Native Engine baseline cost was 0.5 pip price disadvantage per fill, 1.0 pip round trip. The following other costs are **arithmetic sensitivity on the same exact entry and exit prices** and are not separately executed native backtests:

| Arm | 0.8 pip net mean | 1.0 pip net mean | 1.4 pip net mean |
| --- | ---: | ---: | ---: |
| Gotobi pre-fix long | +1.537 | +1.337 | +0.937 |
| Gotobi post-fix short | +0.928 | +0.728 | +0.328 |
| Ordinary post-fix short | -0.316 | -0.516 | -0.916 |

The short's modest estimated edge means real spreads, commission and slippage are decisive. The LSE 1-minute OHLC observations are not executable bid/ask quotes.

## Economic identification and statistics

The new weekday/year-adjusted post-fix Gotobi premium versus ordinary Tokyo days is **+1.420 pips**, HAC 95% interval **[+0.384, +2.456]**, unadjusted p = **0.00724** on the new interval-complete cohort.

This is a **post-selection, already inspected retrospective sample**, with an unadjusted p-value. Earlier Program 1 considered a 126-test Holm family and **no Gotobi-specific incremental return survived that correction**. The new coefficient **does not reverse that conclusion** and must not be advertised as confirmed alpha. Calendar labels cannot directly observe importer/dealer order flow.

## Native implementation and independent evidence

- Starting balance: **USD 10,000** for each independent arm, and each position is a fixed USD 10,000 base notional. No compounding.
- Native engine: `ml4t.backtest.Engine`, `ExecutionMode.NEXT_BAR`, `ExecutionPrice.OPEN`.
- Calendar-only Gotobi short: submit after 09:55 JST minute; fill 09:56; submit close after 10:09; fill 10:10.
- Same ordinary-day short uses identical execution, dates classified ordinary by the original frozen BOJ-based calendar.
- Original Gotobi long: submit 08:29; fill 08:30; submit close 09:53; fill 09:54.
- Synthetic native broker accounts in JPY using 50% initial margin internally to handle changing USDJPY quote; this is **not** a verified actual USD broker-account margin. The actual strategy's economic exposure is one fixed USD 10k base position for USD 10k initial equity. USD realized P&L is recalculated per native fill using quote JPY P&L divided by contemporaneous executed exit USDJPY rate.
- Native status: **4,118/4,118 orders filled** across three arms. No unexpected overlapping positions or timing mismatch.
- Independent source-quote oracle, separate from native strategy code: **2,059/2,059 trades PASS**, 4,118 fill prices and timestamps PASS, per-trade JPY and exit-time USD conversion PASS, summed native JPY account change PASS.
- Correct closed-trade drawdown including the initial balance agrees with the reported metrics to floating-point precision.
- Research-session ledger: six declared trials completed, including data gate, three arms, fill oracle and incremental comparison.
- Focused research CLI and Tokyo alpha-map tests: **17 passed**; six existing third-party warnings.
- Python compilation: PASS. `git diff --check`: PASS.
- Full unrelated repository suite not repeated for this continuation. Prior Program 1 full-suite notebook check remained interrupted/failed.
- No live orders, commit or push. Earlier frozen session artifacts were left untouched.

## Evidence paths

- Frozen continuation spec: `config/research_sessions/tokyo_alpha_map_program1_native_exploratory_v2.yaml`
- Runner: `scripts/run_tokyo_alpha_map_native_exploratory_v2.py`
- Independent verifier: `scripts/verify_tokyo_alpha_map_native_exploratory_v2.py`
- Raw selected 1m bars: `run_log/tokyo_alpha_map_program1_native_exploratory_v2/execution_bars.parquet`
- Selected event registry: `run_log/tokyo_alpha_map_program1_native_exploratory_v2/event_panel.parquet`
- Full trade-window completeness gate: `run_log/tokyo_alpha_map_program1_native_exploratory_v2/T0_interval_data_gate/result.json`
- Gotobi short fills/metrics: `run_log/tokyo_alpha_map_program1_native_exploratory_v2/T1_gotobi_short/`
- Ordinary short fills/metrics: `run_log/tokyo_alpha_map_program1_native_exploratory_v2/T2_ordinary_short/`
- Gotobi long fills/metrics: `run_log/tokyo_alpha_map_program1_native_exploratory_v2/T3_gotobi_long_reference/`
- Independent fill oracle: `run_log/tokyo_alpha_map_program1_native_exploratory_v2/T4_independent_oracle/result.json`
- HAC comparison: `run_log/tokyo_alpha_map_program1_native_exploratory_v2/T5_comparison/result.json`
- Frozen session trial ledger: `run_log/research_sessions/tokyo_alpha_map_program1_native_exploratory_v2/`

## Decision

**Native Program 1 execution result obtained and independently reconciled. Research status remains EXPLORATORY / NOT_APPROVED.**

The pre-fix long has a larger retrospective dollar gain than the ungated short. The short shows a better Gotobi-versus-ordinary contrast but weaker stability, particularly its loss in 2026 YTD. The appropriate next experiment is a new preregistered prospective/paper-trading evaluation with real executable broker quotes and full cost accounting. Preserve the untouched September–October 2026 holdout until a controlled final-test decision has been explicitly authorized.
