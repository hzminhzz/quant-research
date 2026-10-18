# What Friday's VIX Action Hinted At

**Candidate:** `hanna_spx_vix_corise_friday_reversal_v1`
**Capture status:** THESIS_CAPTURED, descriptive only.
**Primary:** Rob Hanna, 2012-02-27, https://quantifiableedges.com/what-fridays-vix-action-hinted-at/
**Original market/timeframe:** S&P 500 index (SPX) signal with VIX index observation; execution product not specified; Friday close to following sessions; exact exit UNKNOWN.

## SOURCE_FACT — Original tested or described rules
- Source studies Fridays when both SPX and VIX close higher than their preceding respective closes.
- A long-term uptrend filter was included, but public text does not specify its exact lookback/threshold.
- Author describes downside tendency over the next few days, not a complete order-entry/exit system.

## SOURCE_REPORTED_TEST — Not independently verified
- Original author reports a short-term downside tendency even in an uptrend; results occur in a graphic without a publicly readable numeric trade/sample table.

## LOCAL_INFERENCE — Economic hypothesis and null
When SPX and VIX both advance on a Friday despite their usual inverse relationship, demand for downside insurance may anticipate equity weakness over the next few sessions; this is a testable interpretation, not demonstrated causation.

Possible mechanism: Friday options hedging and volatility demand can diverge from rising index price, potentially foreshadowing short-horizon risk repricing.

Null: the conditional opportunity has no incremental advantage after baseline and costs. Proposed baseline: Other uptrend Fridays without simultaneous SPX/VIX advances, matched on realized volatility and prior SPX return.

## ADVERSE EVIDENCE AND SELECTION RISK
- Graph data, trade count, drawdown, exact trend filter and costs are not disclosed in accessible text.
- SPX and VIX closing positive could simply reflect regime and measurement effects; Friday-specific selection risks multiple testing.

## ORIGINAL vs LOCAL ADAPTATION
Original product and source rules above are preserved. No product substitution, parameter repair, local backtest or deployment is authorized; **ADAPTATION_PROPOSAL: NONE**. The author's cited results are source claims, not reproduced alpha.

## SCIENTIFIC DEEPENING — NOT PERFORMED
Original decision/fill clock: Friday official SPX/VIX closing values; first feasible transaction is no earlier than next liquid session; original source does not identify tradable fill.

Causal features: Friday indicator; lagged SPX/VIX close-to-close signs; source long-term trend filter UNKNOWN.

Original sizing: UNKNOWN in source; source describes signal study, not executable position policy.

Costs: UNKNOWN; must identify an authorized executable SPX proxy first.

Primary falsifier: Conditional forward signed SPX proxy return after the Friday co-rise event is not lower than matched Fridays under the identical qualified trend filter, net of specified frictions.

No Phase 3/4 analysis, holdout access, or price-return calculation was performed. PIT availability, exchange calendar, original data provenance, explicit cost oracle and next-executable-fill semantics must be qualified separately.

## UNKNOWN / BLOCKERS
- Exact trend filter/decision cutoffs, source study horizon and measured dates
- Execution instrument: SPX itself is a non-tradable index; any ETF/CFD/future is a new study
- Weekend calendar, price availability, returns measurement, source costs and sample count

## Portfolio overlap HYPOTHESES (not measured correlations)
- Risk driver: volatility-demand divergence / weekend hedging
- Market: US equity index and options-implied volatility
- Horizon: short swing
- Expected exposure: potential short SPX / equity downside
- Likely overlap cluster: equity event reversals, VIX divergence
