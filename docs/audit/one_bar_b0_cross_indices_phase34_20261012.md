# B0 cross-index replication — ML4T Phase 3 and Phase 4 (12 October 2026)

**Decision: exploratory evidence of transfer to Nikkei and pre-2024 DAX, not to ES.** The DAX source becomes scale-corrupted in 2024; all DAX 2024–2026 native results are retained but **invalid for strategy inference**. Hang Seng is blocked without comparable 1-minute data. Nothing is approved for live execution.

## Frozen research design

The original promoted B0 entry, exit and protective stop have not changed. The native ML4T Strategy uses previous **50 fully completed 30-minute high/low bars** as buy/sell STOP entry levels (opposing orders intended OCO), a **50 raw index-point** protective STOP, and an exit at the **immediately following 30-minute opening**, with at most **two entries per Chicago session** (17:00 America/Chicago extended-session anchor). Both long and short are included. No ATR, new filter, percent stop, instrument-specific tuning or contract-size adjustment was introduced.

Every trial uses canonical 1-minute index proxy prices observed up to 2026-07-14, the native **ml4t.backtest.Engine**, one **synthetic index unit**, the literal 0.25 point B0 tick grid, and either zero cost or an **illustrative** 2.50 synthetic currency units plus 0.25 price points adverse slippage per side. The native Engine must use a synthetic $20-per-index-point contract to reuse the original broker. This is a mechanical implementation detail: **all cross-index results are reported in index points and R, NOT tradable futures dollars.** Define **1R = 50 price points** before execution costs.

## Main comparable outcomes — costed, before the DAX corruption

| Index | Closed trades | Net R | Win rate | Profit factor | Daily Sharpe | Calmar* | Max DD* |
|---|---:|---:|---:|---:|---:|---:|---:|
| NQ (frozen original) | 4,392 | +119.4 | 47.2% | 1.31 | 1.50 | 0.49 | −21.21R |
| DAX (2013–2023 only) | 2,805 | +112.9 | 50.3% | 1.22 | 0.98 | 0.83 | −13.18R |
| Nikkei 225 | 1,682 | +78.9 | 46.0% | 1.13 | 0.47 | 0.20 | −38.45R |
| ES proxy | 4,036 | −18.4 | 39.0% | 0.85 | −0.85 | −0.07 | −23.77R |

Sharpe uses daily **realized trade PnL assigned to UTC entry date**, including flat calendar days and annualizing by sqrt(365.25). Calmar assumes a fixed, hypothetical starting balance of 1000R; it is not a true marked-to-market futures capital curve.

## 2026 stress — already observed January 1 through July 14

| Index | Trades | Net R | Win rate | Profit factor | Daily Sharpe | Max realized DD |
|---|---:|---:|---:|---:|---:|---:|
| NQ | 238 | −14.17 | 47.48% | 0.81 | −1.83 | 16.61R |
| Nikkei 225 | 251 | **+64.11** | 35.86% | 1.39 | **2.40** | 18.97R |
| ES | 241 | −7.69 | 40.25% | 0.59 | −3.49 | 8.79R |
| DAX | 21 | −479.15 | 23.81% | 0.00 | invalid | INVALID SOURCE |

Nikkei's 2026 win rate is low. Its positive native result depends on larger winners rather than frequent wins. Critically, **91 of 251 2026 trades (36.3%)** cross their entry and protective stop within the same minute. Replacing those ambiguous outcomes with a pessimistic -1R stop-out plus illustrative costs changes the 2026 result from **+64.11R to -19.78R**. Therefore 2026 is **INCONCLUSIVE** without higher-resolution or independently verified execution paths. The full historical Nikkei +178.28R changes to +74.84R under the same non-native sensitivity. The source is sparse and synthetic.

## Data forensics: DAX source unusable after 2023

The read-only source integrity audit detected **1,000 changes above 25% between adjacent observed prices** on DAX: **447 in 2024, 334 in 2025 and 219 in January–July 2026**. Many switch between around 800–900 and 20,000–25,000 index points. In one native 2026 trade a short entry at 889 exited at 24,835.3, creating a **spurious roughly −479R** result. Such moves are feed/scale contamination, not genuine breakout alpha or stop performance.

Before the 2024 corruption, the DAX 2013–2023 trial yielded **+112.85R, 50.3% wins, profit factor 1.22, realized-daily Sharpe 0.98, and hypothetical Calmar 0.83**. This is preliminary evidence worth replicating after the data source is repaired. **Do not filter the corrupted bars after observing PnL and label the resulting returns validated**; replacement prices and source provenance must be verified first.

The same >25% adjacent-observation discontinuity screen found **zero** such jumps for ES, Nikkei and NQ. That absence does not prove their execution bars or calendars are perfect. In Phase 2, observed complete 30-minute bars were only 69.7% for ES and 62.2% for Nikkei. Missing scheduled opening prints and non-atomic native OCO remain material uncertainties.

## Phase 3 causal event study

Completed 15 event sets: ES, DAX and Nikkei × 2018, 2022, 2024, 2025, 2026. The price thresholds come only from previous **fully completed** 30-minute bars and are available no earlier than the next minute. Polars vectorized 30-minute OHLC from the **future** interval is used only as a retrospective label, never as a signal or an execution fill.

For 2026, fully observed next-30m intervals numbered **ES 7,104**, **DAX 5,890**, **Nikkei 6,575**. Incomplete or absent next intervals were **370, 662 and 741**, respectively. Missing future intervals were not filled with invented prices. A touched threshold in the event study does **not** imply a trade or a favorable fill.

## Monte Carlo and selection uncertainty

The final JSON records **2,000 reproducible paired moving-block bootstrap repetitions** for both 5-day and 20-day blocks, on synchronized zero-inclusive UTC daily realized R paths. It includes terminal R distributions, daily Sharpe differences to the frozen NQ control and maximum drawdowns. The contaminated 2024–2026 DAX path is excluded from valid full-period bootstrap comparisons; the clean **2013–2023** window includes DAX.

In the 2013–2023 5-day bootstrap, positive ending-R frequency was **100% for DAX, 95.2% for Nikkei and 0.4% for ES**. However, the probability of a **higher bootstrapped Sharpe than NQ** was only **9.9% for DAX** and **1.1% for Nikkei**. This is resampling of already-observed outcomes, not the true future probability of profits. These instruments are multiple research trials; no out-of-sample or live approval follows.

## Technical evidence and limits

- All **14 annual native ML4T backtest shards** completed for ES, DAX and Nikkei, in both zero-cost and illustrative-cost conditions (**84 final annual scenario results**). The originally failing Nikkei 2014 warmup was retried with older **historical-only** context; its failed attempt was preserved.
- An independent audit reconciled annual native evaluation-trade PnL and trade counts, enforced the two-filled-entries-per-Chicago-day invariant, and confirmed the frozen NQ control's **5,462 trades / +166.10792R**. NQ signal levels were also checked against the original source.
- The **real product identities, currency multipliers, spreads, historic FX, market-impact assumptions, contract rolls and margin** are not yet certified. The literal Chicago session can be unnatural for Asian/European trading. Comparisons are only structural.
- The native broker has no atomic OCO, while 1-minute OHLC cannot establish event order within a minute. Native annual Engine accounts reset and cannot be stitched into a validated portfolio equity curve. No protected or previously unseen final test was opened.
- Hang Seng remains **blocked for 1-minute replay**. A separate 172,108-row HK33/HKD **five-minute** proxy exists, but was not substituted into the one-minute simulator.
- No Git commit, push or live orders occurred. Original promote/one_bar_nq_30m remains untouched.

## Evidence paths (relative to repository root)

- Registered frozen protocol: run_log/one_bar_b0_cross_indices_20261012/phase34_frozen_spec.json
- Phase 3 events: run_log/one_bar_b0_cross_indices_20261012/phase34/phase3_event_diagnostics.json
- Native annual ledgers: run_log/one_bar_b0_cross_indices_20261012/phase34/{ES,DAX,NIKKEI225}/YYYY/
- Source anomalies: run_log/one_bar_b0_cross_indices_20261012/phase34/extreme_price_jump_audit.json
- Final comparison and paired bootstrap: run_log/one_bar_b0_cross_indices_20261012/phase34/final_research_metrics.json
- Native replay: scripts/run_one_bar_cross_indices_native_20261012.py
- Event study: scripts/study_one_bar_cross_indices_events_20261012.py
- Risk and bootstrap: scripts/report_one_bar_cross_indices_20261012.py

**Research decision:** retain NQ B0 as promoted; prioritize a verified DAX source repair and a realistic Nikkei contract/session-cost validation before any portfolio or production decision. ES is negative under the identical structural rules and illustrative costs. Do not search for a better index-specific lookback or stop in this registered trial.
