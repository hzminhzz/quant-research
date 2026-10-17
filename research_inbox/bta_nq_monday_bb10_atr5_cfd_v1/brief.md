# Monday NQ lower-Bollinger ATR stop-buy — Dukascopy CFD Adaptation

**Candidate ID:** `bta_nq_monday_bb10_atr5_cfd_v1`  
**Selection family:** `bta_nq_monday_bollinger_atr_breakout`  
**Decision:** `THESIS_READY_UNVERIFIED` — descriptive research-design admission adapted to Dukascopy index CFD data. Not a frozen session, executable CandidateSpec, market-data qualification, native backtest, or trading approval.

## 1. Product Adaptation & Venue Disclosures

| Aspect | Original Published Strategy | Adapted Research Proxy |
| --- | --- | --- |
| **Instrument** | CME E-mini Nasdaq-100 (NQ) futures | Dukascopy US Tech 100 Index CFD (`usatechidxusd`, canonical `NQ`) |
| **Data Source** | CME Globex tape | Dukascopy `index_minute_NQ` (resampled to completed 60m bars) |
| **Roll Accounting** | Quarterly futures roll calendar | Not applicable (continuous cash index CFD series) |
| **Execution Reality** | Exchange order book with \$20/point tick multiplier | OTC CFD / Perpetual proxy with scalable notional |
| **Disclosure** | N/A | Cash index CFD and crypto perpetuals have distinct financing, margin, and liquidation rules; not equivalent to CME futures. |

## 2. ORIGINAL_AUTHOR_RULES vs Local Adaptation

**Primary dated source:** Breakout Trading Academy, *Steal This Monday NASDAQ Strategy (Super-simple)*, **July 16, 2026**.

- **Original Instrument**: CME E-mini Nasdaq-100 (NQ) futures, 60-minute bars.
- **Entry Reference**: Lower Bollinger Band (10 periods, 1 standard deviation) + 0.8 × ATR(5).
- **Order Mechanism**: Buy stop order at trigger level, active only in the next 60-minute bar.
- **Session**: Monday only, 00:00 to 23:00, exit at 23:00 on the same day.
- **Local Adaptation**:
  - Research session clock predeclared as `America/New_York` (00:00 to 23:00 ET).
  - Price feed adapted to Dukascopy `usatechidxusd` 60m completed bars.
  - ATR smoothing predeclared as SMA(5) on completed true ranges; band variance as sample standard deviation.

## 3. Unqualified Execution & Cost Disclosures

- **Price-Only Data**: Dukascopy `index_minute_NQ` provides completed OHLC prices, not historical execution fills, live ask/bid spreads, or broker statements.
- **Assumed Costs**: Spread (1.5 bps), commission (0.25 bps one-way), and stop slippage (1.0 bps) are research assumptions, not measured broker charges.
- **Financing / Overnight Swaps**: Strategy enters and exits within the Monday session (flat by 23:00 ET); zero overnight carry is assumed, but actual venue financing schedules remain uncertified.
- **Product Non-Equivalence**: CFD index spreads and funding differ fundamentally from crypto perpetuals (e.g. 8-hour funding rates) and futures basis. Results on CFD proxy do not certify perpetual or futures execution.

## 4. Pre-Backtest Diagnostic Protocol (Phase 3 Design)

This is a single-market event hypothesis; cross-sectional IC and portfolio dollar neutrality are not applicable.

- **Objective**: Determine whether conditional buy-stop trigger events achieve a statistically positive incremental return over an unconditional time-matched Monday long control.
- **Falsifier**: If the upper one-sided 95% confidence bound of the paired incremental event return (clustered by Monday week) is $\le 0$, the edge is falsified. If $N < 50$ or confidence interval spans zero, outcome is `INCONCLUSIVE`.
- **Holdout Boundary**: 2025-01-01 to 2026-10-01 is strictly sealed and protected. Development window is 2012-01-01 to 2025-01-01.
