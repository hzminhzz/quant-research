# SPY month-end to first-day close exposure

Candidate: `quantinsti_spy_monthturn_one_day_v1`. Classification: **THESIS_CAPTURED only**. No backtest/approval/permission.
Original source: QuantInsti / Quantra (course co-author Quantpedia), UNKNOWN. https://quantra.quantinsti.com/glossary/-Trading-the-Turn-of-the-Month-Effect

**Product:** SPY US-listed equity ETF, NOT ES future / US500 CFD. **Horizon:** one trading session.

## SOURCE_FACT: Source-described original rules
- Buy SPY at final trading day's CLOSE of each calendar month.
- Sell SPY at first trading day's CLOSE the next calendar month.
- Separate enhancement tests a 200-session simple moving-average trend rule; filter is an AUTHOR VARIANT, not part of base strategy.

## SOURCE_REPORTED_TEST: Original claims, not replicated
- Original author states backtest uses SPY ETF history from 1993 through 2023.
- Reports 2.87% CAGR and 11.97% max drawdown for unfiltered base.
- Reports filtered CAGR 2.71% and max drawdown 5.56%, but exact execution and calculation of filter on closing bar not qualified.

## LOCAL_INFERENCE and economic hypothesis
Scheduled cash inflows around month end may induce temporary index demand into the first trading day; market-closed-to-market-closed calendar edge could appear in unhedged SPY ETF returns.
No independent alpha established; counterparty UNKNOWN. Null: No incremental tradable net advantage over source-matched control. Proposed baseline: SPY buy-hold calendar-matched windows and equal number of randomly or systematically matched adjacent sessions

## Independent adverse evidence
- Closing signal could create lookahead if same closing price treated as both realized signal and fill.
- Filter tested on same sample reduces annual returns despite drawdown improvement; no independent time validation.
- Potential strong overlap with broader stock month-end seasonal factors; not DAX-specific mean reversion.

## ADAPTATION_PROPOSAL
NONE. Do not map original ETF/futures into CFDs/perpetuals or invent missing rules. Signal and earliest valid fill: Last trading session closing auction to first next-month closing auction, schedule known ahead of time; if rule uses final close to decide same-close purchase then timing is invalid.
Source sizing: Original weight/position sizing detail UNKNOWN; typical long-when-window only is an INFERENCE, not new constraint.
Source costs: Unreported; US-listed ETF spread, commissions and market-close auction fill must be qualified.

## Future scientific falsifier (NOT RUN)
First-of-month close-to-close after-cost exposure provides no incremental mean signed return against matched non-month-boundary closes.
No Phase 3/4 tests, market-return computation, optimization or holdout access. Require instrument-specific PIT and fill reconciliation, real spreads/commissions/financing, product calendar, full source semantics, false-discovery accounting.

## UNKNOWN / unresolved blockers
- Closing auction executable decision timing when end-of-month close is only final bar value
- Original capital/cash assumptions and dividends, exact annualization
- SPY corporate action total-return data and original quoted costs
- Exact source publication date and underlying author empirical data source

## Descriptive portfolio tags (hypotheses; NOT measured diversification)
Risk driver: calendar cashflow/portfolio rebalancing. Market: SPY US-listed equity ETF, NOT ES future / US500 CFD. Horizon: one trading session. Beta/direction: long S&P 500. Overlap family: us_etf_one_day_month_boundary.
