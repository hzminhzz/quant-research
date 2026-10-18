# Cross-sectional sorting by historically measured factor predictability

**Status:** THESIS_CAPTURED; SOURCE_CAPTURE_ONLY. Neither simulation nor executable handoff has occurred.

**Original source:** Massimo Guidolin and Serena Ionta, *Predictive sorting of cryptocurrencies based on fundamentals and sentiment*, Journal of International Financial Markets, Institutions and Money, vol. 107 (March 2026). https://doi.org/10.1016/j.intfin.2026.102285. Read original open access publisher sections 4.3, Table 5 and Table 10, corroborated by Bocconi institutional record https://iris.unibocconi.it/handle/11565/4081736.

**What the paper actually does:** Build weekly shared-factor predictors representing chain user activity, hashrate and Google Trends attention, optionally excluding BTC from factor construction. Compute per-coin historical sequential forecasting scores R2_OOS and certainty-equivalent return. Each month rank the 40 available sample coins by the predictor's **PAST measured forecastability**, long 20 above median / short 20 below. It studies eight distinct predictors (three factors, three ex-BTC variants, BTC return, and momentum) crossed with two sorting scores for 16 different source L/S sequences. The paper does not describe an hourly signal or a prop-firm venue.

**Author findings — UNVERIFIED:** Table 10 reports positive multifactor-adjusted weekly alpha for some sorting variants (for example combined-factor R2_OOS 0.67% per week), whereas momentum R2_OOS shows -0.14% with p=0.44. These are author estimates, not independent after-cost returns or proof of trading profitability; 16 variants may involve selection bias.

**Cross-sectional mechanism:** Forecastability itself varies across coins; sorting on a predictor's *historical ability* to forecast coin returns is different from ranking today's momentum, blockchain activity or attention. Original weekly forecasts and monthly rebalances must remain source-faithful; any 5m/15m/1h translation is a new, untested proposal.

**UNKNOWN / adverse:** point-in-time chain-user and hash-rate series, Google Trends normalization/revisions and publication times, delisted universe members, full historical forecast history, truly nested score estimation, shortable instrument identity, transaction costs, financing, permitted leverage, net exposure, margin and daily prop drawdown rules. No authentic Binance 1h OHLCV-only reproduction possible; historical coin data coverage and prop account permissions unverified.

**Novelty:** Rank on historical factor-specific prediction quality rather than raw factor strength, BTC residual return or simple ML forecast. Funding/basis/carry never appear in the alpha information set. No empirical tests, protected reads, orders, deployments or ATS runner interaction.
