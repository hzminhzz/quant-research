# qoppac_futures_relative_carry_within_assetclass_v1

## SOURCE_FACT
Primary: Rob Carver, *Some more trading rules*, June 22, 2017, https://qoppac.blogspot.com/2017/06/some-more-trading-rules.html . Original section **Relative carry**; article text provides the 90-business-day smoothing and subtraction of the within-class median.

Original product is a multi-asset-class portfolio of exchange-traded futures. This is not an ETF, FX-spot, CFD or perpetual study. Within each asset class, author defines relative carry as a smoothed futures-carry forecast minus contemporaneous median smoothed carry of that class. The raw carry construction, scaling, universe and exact execution clock depend on the referenced pysystemtrade/books and are **UNKNOWN** in this capture.

## SOURCE_REPORTED_TEST — NOT INDEPENDENTLY VERIFIED
The author reports that standalone relative carry underperformed absolute carry and that their signals had around 0.6 correlation. Combining them changed author's annualized Sharpe from 0.508 to 0.524 and the 2-predictor weight optimization gave the relative signal about 40% weight. This is a small, model-dependent improvement, not independently established alpha. Locate these claims in the **Relative carry** paragraph.

## LOCAL_INFERENCE / HYPOTHESIS
Hedging pressure and curve inventory economics could reward cross-market carry differences. A median-demeaned relative forecast might reduce outright duration/market trend beta, but neutrality is not automatic. Counterparty: unknown.

## ORIGINAL_AUTHOR_RULES
90-business-day smoothing of carry signal; within-class median subtraction; use signed relative forecast within systematic futures risk allocation. The author explicitly cautions against rescaling very small cross-sectional carry dispersion to force unit variance. Contract, roll and fill rules are **UNKNOWN**, so no complete stand-alone long/short strategy is claimed.

## ADAPTATION_PROPOSAL
None adopted. Study on original futures first; neither CFDs nor crypto funding is automatically equivalent.

## Scientific protocol / primary falsifier
After pre-registering original carry definitions and eligible contracts, compare risk/cost-matched absolute carry versus absolute-plus-relative carry on **only development data**. Use actual cross-sectional signed-carry ranks for an IC diagnostic if a later research design calls for one. Falsifier: nonpositive incremental post-cost contribution after class and roll control. Do not run it during capture.

## Adverse evidence and blockers
- Relative carry was worse than absolute carry by itself; the combined Sharpe change was small.
- Parameter weights are estimated and likely exposed to multiple-testing and in-sample instrument choice.
- Requires PIT futures curve chain, roll dates, point-in-time class membership, multipliers, fees, margin, spread/slippage and comparable daily settlement timestamps.

Portfolio tags (HYPOTHESIS, not measured): risk driver term-structure / hedger pressure; market diversified futures; horizon multiweek; beta mixed with potential long-short within class; overlap cluster **futures carry / relative value**.
