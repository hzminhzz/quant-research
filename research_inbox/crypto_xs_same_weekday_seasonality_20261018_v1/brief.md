# Same-weekday cross-sectional cryptocurrency return seasonality

**THESIS_CAPTURED — SOURCE_CAPTURE_ONLY**, priority MEDIUM, cross_sectional_calendar_memory. Descriptive hypothesis only, not a research/backtest/execution approval.

## Original-source evidence
Huaigang Long, Adam Zaremba, Ender Demir, Jan Jakub Szczygielski, Mikhail Vasenin (2020), original: https://repository.up.ac.za/items/14b5a5b0-4d67-43d7-b0e0-b3735b317211

### SOURCE_FACT
Relative performance on a specific weekday may persist for the same token on subsequent occurrences of that weekday, rather than general weekly momentum.

Original method: Authors study same-day-of-week past and future token returns across a cross-section and evaluate portfolio sorting and regressions; actual portfolio formation/exits/weights NOT independently extracted.

Original long logic: UNKNOWN; cannot assert source-defined cross-sectional long rankings or cutoffs.

Original short logic: UNKNOWN; cannot assert source-defined short rankings or cutoffs.

Source universe: About 151 cryptocurrencies over 2016-2019; PIT membership and venue identity UNKNOWN.

Source timing: Daily day-of-week effect, not a sourced 1h/5m rule.

Portfolio: Cross-sectional historical same-weekday score analysis; executable long/short design UNKNOWN.

### SOURCE_REPORTED_TEST — UNVERIFIED
The source reports historical empirical associations or portfolio results; these have **not** been independently replicated. We assert NO local historical profitability, Sharpe, IC, simulations or execution.

### LOCAL_INFERENCE / adverse evidence
Lukas Müller (2024), Revisiting seasonality in cryptocurrencies, finds cryptocurrency seasonality not robust in newer/broader samples: https://econpapers.repec.org/article/eeefinlet/v_3a64_3ay_3a2024_3ai_3ac_3as1544612324004598.htm

Falsifier for any later independently registered study: Same-weekday return rank effect is unstable on newer coins or after a realistic roundtrip and universe changes.

Novelty vs the 69 prior published source folders: Per-token cross-sectional recurring WEEKDAY memory differs from generic session drift or aggregate global calendar return.

### ADAPTATION_PROPOSAL — not source facts
A specific long/short basket, prediction lookback or intraday session adaptation would be NEW research not author fact.

### UNKNOWN and implementation caveats
Information-availability timestamps, exact source parameters not quoted here, execution fill clock, venue/contract identity, liquidation costs, funding as a cost, fee/impact, portfolio weights, stops, allowed leverage, hedging, margin, weekend and drawdown prop rules are UNKNOWN. Required data: Historical UTC-consistent daily closes, delisted asset coverage and PIT universe. Do not assume exchange-local trading-day boundaries. Funding/basis/premium are NOT alpha signals. No protected reads, ATS runner interactions, orders or empirical work.
