# Hi-Lo Index as a Market Timing Indicator

Candidate: `alvarez_sp500_hilo40_breadth_mr_gate_v1`; Selection family: `us_equity_breadth_hilo_mr_gate`.
**Status: DRAFT_UNVERIFIED (native capture and remote publication pending).** No research-ready or execution authority.

**Original primary source:** Cesar Alvarez, 2015-11-11. https://alvarezquanttrading.com/blog/hi-lo-index-as-a-market-timing-indicator/

**Original market / venue:** Point-in-time S&P 500 common stocks; S&P 500 constituent breadth series; SPX as an alternative market-timing comparator. No CFD substitution.

## SOURCE_FACT — original author rules available publicly
- Source base universe: S&P 500 constituent; price > $1; 21-day mean dollar volume > $10 million; close > stock SMA(200); close in bottom 20% of own daily high-low range; stock RSI(2) < 20.
- Rank eligible stocks by 100-day historical volatility descending; at most 10 positions, 10% capital each, no margin.
- For next trading session place buy limits a further 0.25 times ATR(10) below prior close; exact brokerage order-validity conventions not given.
- Exit at next opening when RSI(2)>80 on preceding close.
- Added market gate for NEW positions only: calculate for each S&P 500 constituent if price makes a 3-month high or low, high count minus low count divided by current constituent count; simple 40-day moving average above 5% allows entries, otherwise skip new positions.

## SOURCE_REPORTED_TEST — not independently replicated
- Author used AmiBroker and Norgate, tested 2005-01-01 to 2015-09-30.
- Reported average of five worst drawdowns improved from 16.30 to 12.20 for selected Hi-Lo filter comparison, roughly 25%; not independent verification.
- Reported comparable CAR versus an SPX SMA200 gate with somewhat improved MDD and higher average trade gain; specific complete trade-level tables unavailable in accessible post.
- Author tried other Hi-Lo smoothing/threshold combinations. Compared SPX moving averages as alternative regime filters.

## LOCAL_INFERENCE — economic mechanism and null
When cross-sectional new-high participation collapses, an oversold-stock reversion strategy may have unfavorable crash-tail and clustering risk. A smoothed high-low breadth gate may reduce exposure in those states without merely replicating index SMA200 timing.
Proposed mechanism: Breadth weakening can proxy common liquidation stress and correlated stock sell-offs. Counterparty and causal mechanism NOT verified.
NULL: no incremental tradable economic payoff over source-matched controls.

## ADVERSE_EVIDENCE — prioritised independent challenge
Breadth gate trades less often, which can mechanically reduce drawdown; published small threshold and moving-average sweeps risk selection bias. PIT constituent breadth may be costly or unqualified.
Selection-family/parameter reuse must be assessed before any later empirical run.

## ADAPTATION_PROPOSAL
NONE. Preserve original instrument names and data product identity. Do not automatically substitute CFDS, perpetuals or ETFs.
Signal and execution caveats: Daily market-data signals after completed US equity close; next-session limits, next-open exit; no same-close fills. Exact order expiration and bar-level fill model UNKNOWN.
Sizing: Maximum 10 long stocks at 10% of starting allocation per position, no margin; competition among limits and capital reserve behavior UNKNOWN.
Cost evidence: Commissions, spread, impact, limits not filled and cash drag are unverified; do not imply zero cost. PIT breadth calculation is especially source-dependent.

## PRE-DECLARED FUTURE SCIENTIFIC QUESTION (NOT RUN)
Primary falsifier: No robust incremental reduction in left-tail episode loss, or no incremental risk-adjusted payoff after conditioning on exposure and SPX SMA200 gate with fixed costs.
Baseline: Same stock mean-reversion orders, rank and sizing with no breadth gate; additional comparator SPX SMA200 regime gate from source.
No current Phase 3/4, market-return computations, backtests, holdout reads or optimization.

## UNKNOWN / blockers
- PIT S&P500 constituents and delisting history
- Exact 3-month high/low rolling convention and ties
- ATR/RSI/HV computational parity and adjusted-price conventions
- Limit-order fill priority, partial fills and fees
- Survivorship, dividend timing, event availability and historical transaction costs

## Portfolio tags (hypotheses, NOT measured correlations)
Risk driver: correlated equity panic / index breadth. Market: S&P 500 common stock basket. Horizon: daily entries and short holding. Direction/beta: long equities conditional on breadth. Overlap: equity mean-reversion gate; distinguish IBS condition from separate breadth signal.
