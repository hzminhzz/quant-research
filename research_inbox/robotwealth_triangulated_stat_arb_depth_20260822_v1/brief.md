# Robot Wealth triangulated stock statistical arbitrage — source capture

Candidate: robotwealth_triangulated_stat_arb_depth_20260822_v1. Classification: **THESIS_CAPTURED only**; no executable order, ATS Stage trial, or performance qualification.

Original author pages: https://robotwealth.com/when-is-a-mispricing-not-a-mispricing/ (June 1, 2026);
https://edgealchemy.robotwealth.com/p/the-wisdom-of-very-small-crowds (Aug 22, 2026);
https://edgealchemy.robotwealth.com/p/the-metamorphosis (Feb 2, 2026).

## SOURCE_FACT: Original mechanism and direction
- Original instruments: individual equities in economically related pairs, not perpetuals, futures or CFD symbols.
- Use relative-value spreads as evidence about individual stocks: each stock receives rich/cheap votes from pairs in which it appears. Long those judged cheap across several relations; short those judged rich. This is **not** ordinary simultaneous pair-by-pair two-leg trading.
- A public author example calculates consistency = abs(mean(sign(votes))). The August follow-up discusses multiplying that consistency by sqrt(pair network depth). Treat actual spread normalization and signal-to-weight conversion as UNKNOWN.
- The follow-up says the author refreshes selected pairs monthly; **it does not establish that every position is held one month**.

## AUTHOR_REPORTED_UNVERIFIED
- The author's June 2026 cross-factor cumulative-return graphics explicitly **lack costs and frictions and are not executable backtests**.
- His Aug 2026 update describes roughly 2.7 **simulated after-cost** Sharpe using 80 stocks with favorable broker costs, versus roughly 1.2 at 150 names after admitting lower-depth tickers. This is not an independent reproduction.
- He reports live Sharpe above 3 over about ten months while cautioning that it is a brief favorable sample. No live trade ledger was audited.
- He highlights high turnover and market impact/borrow sensitivity. Pair selection is described as the largest driver of performance.

## LOCAL_INFERENCE and null
Temporary price-insensitive flow may cause transitory apparent stock mispricings. True earnings-driven repricing **must not** be mistaken for mean-reverting mispricing. Counterparty not established per trade.

Null: network depth/consistency adds no after-cost advantage over same-universe traditional two-leg pairs, unweighted flattening or randomized related-stock networks.

## Adverse evidence / limits
- Pair votes are correlated by construction; a pure independent-binomial intuition overstates evidence.
- Author describes failure cases from real earnings surprises and missing vendor stocks; network screens cannot alone identify news.
- Earnings feed, corporate actions, PIT universe, active borrow and valid quote timestamps required. Quote links are not economic verification.

## ADAPTATION_PROPOSAL
None. No substitution to CFD or crypto baskets, no guessed signal thresholds. Exact pair-selection, z-score estimation, fills, stops, weights and clock remain UNKNOWN. Market is the author's common stocks.

**Boundary:** descriptive evidence capture only. No stage qualification, model training, backtests or protected-data access.
