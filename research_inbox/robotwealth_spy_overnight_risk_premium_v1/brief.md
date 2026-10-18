# Source-faithful research capture — robotwealth_spy_overnight_risk_premium_v1

## SOURCE_FACT
Kris Longmore, Robot Wealth, **2024-05-31**, [Revisiting Overnight vs Intraday Equity Returns](https://robotwealth.com/revisiting-overnight-vs-intraday-equity-returns/). Original product **SPY ETF**; US regular cash sessions; daily bars. The author supplies R code using Yahoo SPY prices from 2000-01-01 through the latest May 2024 rows. This is descriptive segment analysis, not an independent trading-system qualification.

**Original illustration:** hold SPY from market close to next market open, compared with buying at open and selling at close. The code computes intraday = Close/Open - 1 and overnight = Open/lag(Close) - 1, with a separately adjusted-price comparison. No discretionary signal, stop, account sizing, margin or executable order protocol is specified. The article's sentence describing the formula in prose appears to mix terms; the shown R formula is the authoritative internal reference and must be checked against source data, not silently repaired.

## SOURCE_REPORTED_TEST (not independently reproduced)
The author reports that most historical price returns come from overnight holdings, while the largest negative returns also cluster overnight. The retrospective 2024 revisit suggests persistence of the observation since the original 2020 analysis. No tradable after-fee Sharpe, fill diary, executable spread, or independent prospective confirmation is published here.

## LOCAL_INFERENCE / hypothesis
Compensation for unhedgeable gap-news risk is a plausible explanation. This is not demonstrated arbitrage alpha: an investor already holding SPY bears the risk, and added auction turnovers could swamp incremental economics. More importantly, a non-predictive exposure schedule is not proof that a positive conditional predictor exists.

## Adversarial evidence
Overnight gains coincide with overnight crash tails; auction prices from retrospective OHLC can be unfillable at the signal decision time. The dividend-adjustment method requires exact distribution-date parity. Continuous overnight-only participation may incur an excessive two-trade-per-day cost burden. Capital-at-risk and interval duration differ from buy-and-hold.

## ADAPTATION_PROPOSAL (not performed)
Pre-register a pure descriptive close-to-next-open schedule versus matched ETF intraday and passive exposure. Do not substitute US500 CFD, ES or NQ. Require independently sourced opening/closing auction execution assumptions and distributions before any economics. The primary falsifier is no positive compensation net of realistic turnover/frictions after matched risk assessment. No Phase 3/4 research has been run.

## UNKNOWN
Live fill quality, risk-adjusted net returns, source price corrections, exact order submissions, distributions, capital constraints, financing, holidays and eligible electronic order clock.

## Descriptive overlap tags (HYPOTHESES)
Risk driver: equity beta and overnight gap risk. Market: SPY ETF. Horizon: one night. Direction: long. Likely overlap cluster: equity overnight risk premium; NOT measured correlations.

**Status:** SOURCE_CAPTURE_ONLY. Not executable, not scientifically qualified, not authorized for orders.
