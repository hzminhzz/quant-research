# alvarez_lqd_ief_credit_ratio_spy_timing_v1

**Status:** THESIS_CAPTURED — source evidence only; not an executable specification, handoff validation, or empirical approval.

## SOURCE_FACT
Cesar Alvarez, *Market Timing with a Canary, Gold, Copper, LQD, IEF and much more*, June 12, 2019. Primary URL: https://alvarezquanttrading.com/blog/market-timing-with-a-canary-gold-copper-lqd-ief-and-much-more/ . Source locations: *The Test*, *LQD/IEF Ratio*, *Potential Issues*, *Final Rankings & Thoughts*.

The author tests SPY long versus cash, reviewing the signal on the final US trading day of each month and entering/exiting at the next open. The LQD/IEF closing-price ratio is compared with its 200-day EMA. Five or more successive closes above (below) generate buy (sell) signals. Cash earns no interest. The article also tests other signals separately; those are not additional independent evidence for the LQD/IEF hypothesis.

## AUTHOR_REPORTED_UNVERIFIED
The historical test spans 2004-01-01 through 2018-12-31 with dividends included in SPY. LQD/IEF ranked favorably on several reported comparisons. The author explicitly warns that the approaches generated only 6–26 trades, insufficient for strong inference, and evaluated numerous timing candidates. These are author results, not independently established alpha.

## LOCAL_INFERENCE
The corporate-credit/Treasury relative-price ratio may proxy market risk tolerance. It also embeds duration, corporate bond composition and ETF pricing effects; a direct causal mechanism has not been identified.

## ADVERSE EVIDENCE
Multiple testing, sparse changes in exposure, comparison against high-beta buy-and-hold, and sensitivity to switching date. No matched-exposure after-cost test establishes an edge.

## ADAPTATION_PROPOSAL
No executable adaptation. Later research could compare identical SPY exposures and costs against equity-only timing; this is a proposed control, not the original strategy.

## UNKNOWN
Original EMA warmup/adjustments, equality handling, close data vintages, dividends across the three ETFs, exact open slippage, calendar/DST implementation, portfolio weights. Do not invent missing values.

## PORTFOLIO TAGS — HYPOTHESES ONLY
Risk driver: credit-spread / duration relative strength. Market: US credit, Treasuries and SPY equities. Horizon: monthly. Expected direction: conditional long equity beta, otherwise cash. Likely overlap: credit stress and equity risk-on timing. Overlap/correlation unmeasured.

**No market calculations, backtests, protected data, training, orders or deployment.**
