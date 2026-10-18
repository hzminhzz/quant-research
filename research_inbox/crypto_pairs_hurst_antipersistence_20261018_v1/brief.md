# Local Hurst anti-persistence in cryptocurrency pair spreads — original-source capture

**THESIS_CAPTURED — SOURCE_CAPTURE_ONLY.** Native source-capture verification establishes document identity and provenance, not executable handoff, independent backtest, or strategy qualification.

**Source:** Mar Grande, Florentino Borondo, Juan Carlos Losada and Javier Borondo (September 2024), *Anti-Persistent Values of the Hurst Exponent Anticipate Mean Reversion in Pairs Trading: The Cryptocurrencies Market as a Case Study*, Mathematics 12(18), 2911. DOI: https://doi.org/10.3390/math12182911 . Index: https://ideas.repec.org/a/gam/jmathe/v12y2024i18p2911-d1480990.html .

## Original-source phenomenon and method
Original authors propose the local Hurst exponent as an entry signal for cryptocurrency pairs trading. Pair spreads with **H < 0.5** showed faster mean reversion in their analysis, and the authors report profitability for several pair strategies that include this signal. All performance is SOURCE_REPORTED_UNVERIFIED.

This is a long/short pair idea by design, not a retrofitted single-asset indicator. The source's studied sample uses Binance hourly observations from 2019-01-01 to 2024-06-05, on 20 coins retrospectively chosen by market capitalization as of 2024-06-06 (**survivorship warning**). Pair spread is log(P_A) minus a 30-day trailing log-return-volatility ratio times log(P_B). The proposed Hurst gate H < 0.5 precedes entry when the spread is 1–2 standard deviations from its trailing mean: short A/long B above that mean, reverse below. Source model exits on reversion, adverse 2-standard-deviation movement, or after 72 hours. The precise Hurst estimator/window variant, causal daily snapshots, executed hedge quantities, fee model and account constraints remain unresolved. These are author methodology descriptions, **not** locally validated trade rules.

## Divergence from existing corpus
A timing/anti-persistence gate differs from simple correlation/cointegration screening and the separately staged copula-conditional spread thesis. It must still be treated as the broad *pairs mean-reversion* family in diversity counts, not a wholly independent alpha generator.

## Causality / adverse tests for a future separately authorized project
A short Hurst window may be noisy and unstable, pair sample may exhibit survivorship, estimated Hurst may be contaminated by post-selection returns, and cost of two legs may eliminate apparent convergence gains. No local tests performed.

## UNKNOWN prop portability
Underlying pair symbols, allowed two-sided hedges/netting, margin, leverage, drawdown, overnight/weekend holds, swaps and venue-specific fees must be resolved per account.

**Boundary:** funding/basis alpha 0; empirical backtests 0; ATS runner actions 0; protected data reads 0; orders 0.
