# Sector Rotation Strategy: Should Trading Rules Make Sense?

Candidate: `alvarez_sector_etf_middle_rank_1m_rotation_v1`; Selection family: `us_sector_middle_rank_momentum_rotation`.
**Status: DRAFT_UNVERIFIED (native capture and remote publication pending).** No research-ready or execution authority.

**Original primary source:** Cesar Alvarez, 2023-11-15. https://alvarezquanttrading.com/blog/sector-rotation-strategy-should-trading-rules-make-sense/

**Original market / venue:** Nine US Select Sector SPDR ETFs XLB, XLE, XLF, XLI, XLK, XLP, XLU, XLV, XLY. No index-futures or CFD substitution.

## SOURCE_FACT — original author rules available publicly
- On the final NYSE trading day of each month compute trailing 1-month returns for nine named sector ETFs, rank descending (1 = highest).
- At next available open buy the ETFs ranked 4th, 5th and 6th, allocating equally.
- Liquidate or rebalance prior holdings each month at next open; no other market filter or stop specified.
- Alternative tests on the same page vary lookback between 1/2/3/4/6 months, rank starts and number of ETFs; preserve base 1-month middle-three model, do not fold other variants into original strategy.

## SOURCE_REPORTED_TEST — not independently replicated
- Author re-examined a third-party middle-rank rotation idea over 2010-01-01 to 2023-09-30; original third-party article reportedly started in 2001 but exact third-party reference not verified.
- For the one-month rank sample, the middle ranks 4,5,6 led the compared CAR choices; top ranks 1,2,3 showed substantially worse CAR and Sharpe.
- SPY buy-and-hold had slightly less CAR and Sharpe with far less activity, strongly limiting economic value.
- At 3-month and 6-month return ranks, rank 1/2/3 became competitive or best, weakening any universal middle-rank story.

## LOCAL_INFERENCE — economic mechanism and null
At a monthly horizon, sector ETFs ranked in the middle of short-term performance may avoid a temporary reversal of the strongest leaders while retaining positive sector momentum and equity beta. This is a local hypothesis, not an established mechanism.
Proposed mechanism: Top-sector 1-month returns can be susceptible to short-run reversals after concentrated inflows; middle-ranked ETFs may show less reversal. Counterparty unknown; this may be data-mined rank selection.
NULL: no incremental tradable economic payoff over source-matched controls.

## ADVERSE_EVIDENCE — prioritised independent challenge
Source examined multiple starts, lookbacks and basket sizes, and a simpler SPY hold nearly matched results. Short lookback specificity makes selection highly suspect.
Selection-family/parameter reuse must be assessed before any later empirical run.

## ADAPTATION_PROPOSAL
NONE. Preserve original instrument names and data product identity. Do not automatically substitute CFDS, perpetuals or ETFs.
Signal and execution caveats: Rank at completed last monthly exchange close; orders at next opening auction or tradable open; actual venue opening slippage not certified.
Sizing: Three sector ETFs equally weighted, no leverage specified; partial shares and capital treatments UNKNOWN.
Cost evidence: Nine ETF commissions, bid/ask opening slippage, spread, taxable turnover and funding/cash assumptions unspecified; do not assume zero trading costs.

## PRE-DECLARED FUTURE SCIENTIFIC QUESTION (NOT RUN)
Primary falsifier: Middle ranks 4-6 do not outperform top ranks 1-3 after realistic turnover costs and calendar-matched control across predeclared independent years.
Baseline: Buy top-ranked three sector ETFs on same calendar and rebalance; additionally buy-and-hold SPY, matched beta/exposure considerations.
No current Phase 3/4, market-return computations, backtests, holdout reads or optimization.

## UNKNOWN / blockers
- Original third-party source and its exact 2001 start
- ETF pre-inception and dividend handling
- Calendar-day vs trading-month total-return window convention
- Opening-auction slippage and market impact
- Full numerical drawdown/trade series from paywalled spreadsheet

## Portfolio tags (hypotheses, NOT measured correlations)
Risk driver: US sector short-term rotation and rank reversal. Market: 9 sector ETFs. Horizon: monthly. Direction/beta: fully long US equity sector beta. Overlap: stock rotation/cross-sectional momentum but distinct sector universe and middle-rank selection.
