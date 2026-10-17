# Tokyo Fix / Gotobi Alpha Map — Program 1 v3 Closure Audit

**Date:** 2026-10-11 JST  
**Status:** RESEARCH PROGRAM COMPLETE / EXPLORATORY / NOT_APPROVED  
**Repository:** `/home/quant/dev/quant/quant-research` at inspected HEAD `c095faa`  
**Frozen session:** `tokyo_alpha_map_program1_closure_v3`  
**Legacy**: `tokyo_alpha_map_program1_v1`, `tokyo_alpha_map_program1_native_exploratory_v2`

## Outcome and limits

The mission's A–D research diagnostics, native event-driven backtest, audit ledger, and independent fill checks now have saved evidence. The v3 study repaired overrestrictive full-window *sample selection* by testing contiguous minute completeness independently for each preregistered interval. **It did not fill or alter source prices**. It did not relax or silently replace the original Program 1 frozen statistical acceptance gate.

The complete 2020–August 2026 retrospective history was already investigated. All claims remain exploratory and not independent OOS. No September–October 2026 price outcomes were read. USD/JPY prices are LSE OHLC proxies without historical executable broker bid/ask or validated commissions.

**No live/deployment candidate qualified.** Results are not proof of an exploitable fixing-flow strategy.

## Sources and calendar

- Original Program 1 BOJ/Cabinet-Office holiday-based bank registry, 1,627 Tokyo bank business dates, 2020-01-01 through 2026-08-31. Weekend/holiday Gotobi rollback is an assumption, not verified corporate settlement flow.
- Seven previously frozen annual LSE 1-minute USDJPY source snapshots under `data/processed/tokyo_alpha_map_program1_v1/`. SHA256 of each is saved in `T1_window_coverage/result.json`.
- Data are UTC minute **open** bars, transformed to `Asia/Tokyo`.
- A window passes only if **every open minute timestamp** from its specified start through exit is present, unique and valid. No price interpolation or broker quote fabrication.
- Full 03:00–12:00 JST complete cohort: **999/1,627** (61.4%); remaining complete outcome data end April 24, 2026.
- Pre-fix 08:30–09:54 complete cohort: **1,602/1,627** (98.5%).
- Post-fix 09:56–10:10, 09:56–10:30, and 09:56–11:00 cohorts: **1,625/1,627** (99.9%, Gotobi n=468, ordinary n=1,157), with August 2026 included.
- Earlier 03:00–09:54 long: **999/1,627** (61.4%), too incomplete to generalize; 07:00–09:54 long: **1,414/1,627** (86.9%).
- The full gap by year/weekday and excluded dates is saved per window in `T1_window_coverage/result.json`.

## A — Pre-fix pressure and alpha map

Price profiles are visualized at each JST minute relative to the 09:55 **open** using only available date/time pairs. Each minute has its own recorded eligible sample count; different minute samples are not a fixed-cohort cumulative investment path. Pointwise 95% HAC intervals do not establish simultaneous statistical confidence.

- 07:00–08:30 long Gotobi gross mean **+1.474 pips** (n=415 Gotobi; n=1,418 total), weekday/year controlled Gotobi increment **+2.715 pips**, HAC interval **[+0.973, +4.458]**.
- In the **new 18-test window-increment family**, adjusted Holm p = **0.0386** for this interval. However, the original Program 1 included 126 declared tests and failed the broader correction. The already inspected historical sample and changed window-specific selection invalidate treating the new result as an independently confirmed discovery.
- 08:30–09:54 long Gotobi gross mean **+2.329 pips** (n=459 Gotobi), adjusted calendar premium **+0.602 pips**, HAC interval **[-1.658, +2.862]**: no significant controlled premium.
- 03:00–09:54 long retained only 61.4% of eligible bank sessions and cannot support broad claims about earlier-day drift.

**Decision:** 07:00–08:30 is a new exploratory research lead, not an approved entry time. There is no verified start time for structural flow.

## B — Post-fix reversal, all preregistered horizons

All B horizons use their own complete interval. Figures below are hypothetical net mean pips after 1.0 pip round-trip execution cost, *not all native broker fills*.

| 09:56 short exit JST | B0 ordinary (n=1,157) | B1 Gotobi (n=468) | B2 month-end (n=80) | B3 pre-fix extension gate (n=37) |
|---|---:|---:|---:|---:|
| 10:10 | -0.524 | **+0.702** | +0.774 | -1.616 |
| 10:30 | -0.377 | **+0.956** | +2.381 | -2.214 |
| 11:00 | -0.112 | **+1.058** | +3.108 | -1.784 |

Month-end overlaps Gotobi and ordinary dates and is not an independent event count. B3 uses the previously frozen pre-fix extension gate based exclusively on prior session observations. Its 37 observations are below the minimum strategy sample and it is negative after assumed costs at all three horizons.

Gotobi-minus-ordinary, weekday/year controlled return premiums:

| Exit | Estimated difference in pips | HAC 95% CI | Raw p |
|---|---:|---|---:|
| 10:10 | +1.420 | [+0.397, +2.442] | 0.0065 |
| 10:30 | +1.649 | [+0.199, +3.099] | 0.0259 |
| 11:00 | +1.616 | [-0.262, +3.494] | 0.0916 |

These comparisons did **not** survive the v3 18-test Holm correction (adjusted 10:10 p=0.104; 10:30 p=0.362), nor the earlier full Program 1 corrections. Ordinary-day short has negative net mean across all horizons at assumed costs.

The outcome patterns are unstable across years. The 09:56–10:10 B1 short has **-1.57 net pips/trade for Jan–Aug 2026**, despite a positive full-sample net average.

**Decision:** Ungated post-fix reversal is a viable question for genuinely new data, but it remains *unapproved*.

## C — Corrected settlement-date analysis

A calendar coding error was detected during verification: the original v3 `nominal_5` expression used substring matching and included nominal 15th and 25th. That invalid artifact remains preserved for audit, and **must not be cited as a valid calendar test**. The versioned correction `T4_calendar/nominal_exact_token_erratum.json` uses exact semicolon-delimited tokens and six independent string-fixture tests, including 30;5 collision handling.

The corrected joint model includes nominal 5/10/15/20/25/30, rolled days, month/quarter end, weekday and year. Baseline and overlap conventions are recorded in the erratum.

- The pre-fix nominal fifth coefficient is -4.41 pips with CI [-9.15,+0.34]; **not significant**.
- In the 09:56–10:30 post-fix short, nominal 20th is +3.24 pips (raw p=0.0468), nominal 25th +2.98 pips (raw p=0.0274). They were inspected alongside multiple calendar tests and are **not corrected-significance or predictive strategy evidence**.
- Quarter-end has only 26 observations under the relevant outcome cohort; it is below the min 30 category requirement.

**Decision:** No settlement-day category is established as predictively superior.

## D — Refutation and robustness

- Pre-fix matched 09:30–09:54 versus 11:30–11:54 placebo difference adjusted Gotobi premium **+0.451 pips**, CI [-1.096,+1.998].
- Matched four-minute short 09:56–10:00 versus 11:56–12:00 placebo difference adjusted Gotobi premium **+0.754 pips**, CI [+0.013,+1.495], unadjusted p=0.046. It was one of many tests; not confirmatory and does not validate longer horizons.
- The source snapshot ends 12:00 JST; a 14/34/64-minute post-11:55 placebo is **not available in that immutable source**. Do not substitute the four-minute placebo as proof for those horizons.
- Negative-control dates (2/7/12/17/22/27) were examined. Calendar assumptions, date overlap and small interaction cells limit causal interpretation.
- HAC 5 and year/weekday controls used. The v3 18-test Holm set is supplementary. It does not supersede the prior 126-test family or account for untracked historical experimentation.

## Native ML4T backtests — verified implementation

The previously completed native `ml4t.backtest.Engine` replay used next-bar open fills, a fixed **$10,000 starting USD equity**, fixed **$10,000 base USD position**, no compounding and a hypothetical 1.0 pip round-trip price disadvantage. The native JPY quote-currency cash ledger was translated to USD using contemporaneous executed exit FX prices.

| Executed arm | Trades | Net pips/trade | USD net P&L | Final USD equity |
|---|---:|---:|---:|---:|
| Gotobi pre-fix long 08:30–09:54 | 458 | +1.337 | +456.94 | 10,456.94 |
| Gotobi post-fix short 09:56–10:10 | 458 | +0.728 | +217.14 | 10,217.14 |
| Ordinary short 09:56–10:10 | 1,143 | -0.516 | -450.95 | 9,549.05 |

**Verification:** 2,059 completed trade records / **4,118 independent order fills** all matched native timestamp and source-bar price, the assumed half-pip adverse fill difference, JPY P&L and USD conversion. Full records and test evidence remain in `run_log/tokyo_alpha_map_program1_native_exploratory_v2/`.

These native execution outcomes use the earlier 08:29–10:10 **joint** completeness cohort (1,601 days), which is slightly narrower than v3's independent 09:56–10:10 cohort (1,625 days). Do not treat different sample means as exact engine/diagnostic replication. The additional v3 B2/B3 and 10:30/11:00 horizon results are event markouts rather than native fills; they were retained as factor diagnostics because no candidate passed the frozen qualification gate.

The 0.8 and 1.4 pip alternative costs are deterministic markout sensitivity, not independent native runs. There is no verified broker spread/commission history, and maximum closed-trade drawdown is not full intratrade marked-to-market drawdown.

## Acceptance and verification

- Phase 1 frozen specification: `config/research_sessions/tokyo_alpha_map_program1_closure_v3.yaml`.
- v3 trial ledger: all six declared diagnostic/verification trials recorded (T4 points to corrected calendar erratum).
- Native v2 trial ledger: all six prior trials recorded and independently reconciled.
- Focused tests: 22 passed, six third-party SHAP deprecation warnings.
- Python compilation and `git diff --check`: **PASS** in the final audit on HEAD `c095faa`.
- Original Program 1 full repository suite was previously interrupted after notebook-related failures; a full-suite pass is **not** claimed here.
- No commits, pushes, real orders or holdout analysis.

## Final disposition

**Program 1 research and exploratory engine evaluation are delivered with explicit data, execution and statistical limits. Strategy deployment: NOT_APPROVED.**

Next research ideas are (1) 07:00–08:30 pre-fix increment on a genuinely unobserved sample and (2) unconditional 09:56–10:10 reversal with broker executable quotes. The v3 expanded development results are retrospective and cannot become a clean holdout by reclassification.

### Artifact index

- `run_log/tokyo_alpha_map_program1_closure_v3/T1_window_coverage/result.json`
- `run_log/tokyo_alpha_map_program1_closure_v3/T2_alpha_windows/result.json`
- `run_log/tokyo_alpha_map_program1_closure_v3/T2_alpha_windows/coverage_corrected_cumulative_map.png`
- `run_log/tokyo_alpha_map_program1_closure_v3/T2_alpha_windows/coverage_corrected_curves.csv`
- `run_log/tokyo_alpha_map_program1_closure_v3/T3_postfix/result.json`
- `run_log/tokyo_alpha_map_program1_closure_v3/T4_calendar/nominal_exact_token_erratum.json`
- `run_log/tokyo_alpha_map_program1_closure_v3/T5_refutation/result.json`
- `run_log/tokyo_alpha_map_program1_closure_v3/T6_reconciliation/result.json`
- `run_log/tokyo_alpha_map_program1_native_exploratory_v2/T1_gotobi_short/trades.parquet`
- `run_log/tokyo_alpha_map_program1_native_exploratory_v2/T4_independent_oracle/result.json`
