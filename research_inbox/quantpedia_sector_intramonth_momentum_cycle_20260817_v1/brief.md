# quantpedia_sector_intramonth_momentum_cycle_20260817_v1 — three-leg sector calendar momentum

## SOURCE_FACT
Cyril Dujava, [Quantpedia, 17 August 2026](https://quantpedia.com/sectoral-intramonth-momentum-cycle/). Universe: nine original US Select Sector SPDR ETFs; SPY is a hedge in one variant. Rank the sectors by total return over 252 trading days at each month-end; winners are top three, losers bottom three.

Source-reported schedule: prior-ranking winners-minus-losers spread from close D-10 to close D-5, new-ranking winners-minus-losers from month-end close D0 to close D+1, then **reverse the spread** from close D+1 to close D+3. D+1 is the first trading day of the new month. Alternative source variant replaces the loser short basket with short SPY.

## AUTHOR_REPORTED_UNVERIFIED
The 1998-2026 composite long/short result is reported as 5.99% annualized return, 0.55 Sharpe and -21.72% maximum drawdown. It is not an independently verified, after-cost live edge. Window selection and the reuse of one historical period require multiplicity accounting.

## LOCAL_INFERENCE
Liquidity demand by institutional month-end allocators might create a transient relative-price cycle among sectors. Counterparty and persistence are not proven.

## ADAPTATION_PROPOSAL
None in this capture. Future evaluation may compare the source's fixed calendar to identical-exposure neutral-calendar controls, but that is NOT a source-author backtest.

## UNKNOWN / ADVERSE
Exact simultaneous month-end signal/fill causality, PIT total returns, borrow/funding/spread/auction impact, independent sample, and the economic size of a feasible edge. This is **THESIS_CAPTURED**, not an ATS-qualified specification or an execution instruction.
