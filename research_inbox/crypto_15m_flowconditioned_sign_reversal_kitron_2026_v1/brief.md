# 15-minute flow-conditioned directional reversal — source evidence, cost-negative

**Candidate:** `crypto_15m_flowconditioned_sign_reversal_kitron_2026_v1`
**Status:** THESIS_CAPTURED; SOURCE_CAPTURE_ONLY; NOT EXECUTABLE.

**Primary source (SOURCE_FACT):** Nadav A. Kitron and Jonathan M. Wengrowicz, 22 August 2026, *Short-horizon mean reversion in cryptocurrency markets: a matched cross-market measurement*. Original author HTML: https://arxiv.org/html/2608.21888. The paper itself identifies https://github.com/nadav2/short-horizon-reversion as its replication package; repository code not audited here.

## Original, not adapted

The source studies 183 Binance USDT **spot** pairs on adjacent **15-minute bars** over 2025-01-01 to 2026-02-11 (with matched US equity controls), and supplements that work with a separate forward continuation through August 2026 and other market feeds. A trailing price-sign reversal and a constrained logit are measurement rules, not published multi-coin target weights. Aggressive taker-flow price pressure conditions the phenomenon but extra lagged flow did not improve the original OOS sign model.

**AUTHOR_REPORTED_TEST_UNVERIFIED:** About 90% of source crypto pairs exhibit detectable directional reversal; the largest gross per-trade edge is around 1.3 bp. Crucially, **none clears the paper's 5-bp round-trip maker spot-cost benchmark**; higher taker fees worsen it. This is adverse economic evidence, not a profitable strategy. A 5-minute alternative has still smaller gross edge. The paper treats the mechanism as consistent with liquidity provision rather than identifying it causally.

## Separation from proposed portfolio

**ADAPTATION_PROPOSAL:** A hypothetical neutral basket ranks completed 15-minute price pressure across coins, with flow agreement as context. **LOCAL_INFERENCE:** Different coin-specific pressure relief might leave a relative-value effect that is not established by the source. No side, size, rank cutoff, hedge ratio, stop, gross exposure or rebalance rule is source-defined. Never claim the original source traded a neutral basket.

A causal test must wait for **fully closed** signal candles and an executable subsequent quote. Missing/delisted source members, post-sample high-volume selection, maker queue priority, shortability, prop-firm restrictions, and financing for any derivative adaptation remain unresolved. Do not use funding, carry, or basis as predictive signals. No empirical research, ATS ingest, training, or order activity occurred.
