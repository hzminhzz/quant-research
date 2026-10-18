# January tax-loss-loser rebound basket

Candidate: `alvarez_january_losers_rebound_v1`. Classification: **THESIS_CAPTURED only**. No backtest/approval/permission.
Original source: Cesar Alvarez, 2021-12-22. https://alvarezquanttrading.com/blog/january-effect-on-stocks/

**Product:** Index constituent common stocks from S&P 500, NASDAQ 100, Russell 3000 and Russell 2000. **Horizon:** one calendar month.

## SOURCE_FACT: Source-described original rules
- At last trading day of December rank each index's constituents on calendar-year-to-date price performance ascending.
- Buy worst-performing 10 stocks at OPEN of first exchange trading day in January, using last-year data already known.
- Exit at OPEN of first trading day in February; compare buying ten best year-to-date stocks as the published baseline.

## SOURCE_REPORTED_TEST: Original claims, not replicated
- AmiBroker + Norgate original test spans 2007-01-01 through 2020-12-31.
- Worst-ten basket outperformed best-ten in 8/14 observed years, not every year.
- For DIFFERENT longer exit variant S&P 500 December exit, author reports 5.1% CAR and 85% max drawdown. This is NOT evidence about the January-only return/drawdown.
- Author finds a Russell 2000 long-hold result driven by 2 extremely large stock gains; exclusion destroys purported average edge.

## LOCAL_INFERENCE and economic hypothesis
Year-end tax-loss selling may leave extreme losers temporarily depressed, followed by early January buying and liquidity normalization; relative performance vs prior winners is the testable component.
No independent alpha established; counterparty UNKNOWN. Null: No incremental tradable net advantage over source-matched control. Proposed baseline: Same universe, buy prior calendar-year best-ten, identical rebalancing and stock availability

## Independent adverse evidence
- Benefit only appears 8 of 14 years in original source.
- Small-cap results materially affected by extreme winners; strong selection risk across four universes and varying holding months.
- The 85% drawdown pertains to a different December exit portfolio, not original one-month hold.

## ADAPTATION_PROPOSAL
NONE. Do not map original ETF/futures into CFDs/perpetuals or invent missing rules. Signal and earliest valid fill: Rank as of last Dec exchange session close; enter Jan first-day open; exit February first-day open.
Source sizing: Ten names within each source universe; author precise portfolio weights not established.
Source costs: No executable spread/impact/fee numbers supplied; opening liquidity on distressed prior losers likely material.

## Future scientific falsifier (NOT RUN)
Worst-ten minus best-ten net January basket expectancy is nonpositive after tradable liquidity, PIT constituents and market/size/distress exposure control.
No Phase 3/4 tests, market-return computation, optimization or holdout access. Require instrument-specific PIT and fill reconciliation, real spreads/commissions/financing, product calendar, full source semantics, false-discovery accounting.

## UNKNOWN / unresolved blockers
- PIT universe mapping, delistings, pre-January market caps and actual stock split conventions
- Initial capital distribution and intra-month rebalancing not published
- Bid/ask open slippage, borrow/carry assumptions, commission, taxes
- Price ranking conventions including adjusted dividend/reinvestment choice

## Descriptive portfolio tags (hypotheses; NOT measured diversification)
Risk driver: tax-loss / calendar microstructure. Market: Index constituent common stocks from S&P 500, NASDAQ 100, Russell 3000 and Russell 2000. Horizon: one calendar month. Beta/direction: long annual loser stocks, market beta and size/distress. Overlap family: equity_tax_loss_reversal_year_turn.
