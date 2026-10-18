# Source-faithful research capture — robotwealth_earnings_open_gap_intraday_drift_v1

## SOURCE_FACT
[Robot Wealth, Equity Event Studies — Post Earnings Announcement Drift](https://robotwealth.com/wp-content/uploads/2018/04/pead-analysis.nb_.html), notebook hosted in a 2018/04 archive path (**exact publication date and writer UNKNOWN**). US single-stock **out-of-hours earnings announcements**, Yahoo-scraped historical source, 1999 through May 2016. The notebook uses rolling 90 prior-session overnight standard deviation for `overnightJumpFraction = (Open/PreviousClose - 1) / trailing_overnight_std`.

**Original strategy is an exploratory hypothesis rather than a finished system.** Compare sign and magnitude of next-session opening gaps to same-session opening-to-close returns. The initial binary test separates positive from negative gaps; it then tests arbitrary standardized-gap bins and 1999-2004, 2005-2009, 2010-2014, 2015-2016 subsets. No actual order timing, sizing, stop, borrow or tradable daily turnover is defined.

## SOURCE_REPORTED_TEST — unverified
The original author says positive opening jumps were followed by weak positive average intraday return, while negative jumps had roughly -0.2% subsequent mean intraday return in the sample. Extreme standardized opening jumps often reversed; author explicitly warns that this can reflect illiquid or anomalous first prints rather than executable alpha. More persistent trends in early subsamples shifted toward more reversal in later periods. Actual precise trade counts, net costs and accepted OOS sample are not published in the excerpt.

## LOCAL_INFERENCE / plausible counterparty
Earnings information may be incorporated slowly by investors/order splitting. Non-normal volatility and spread spikes could erase the effect. It may be an asymmetric short equity beta in earnings periods rather than a unique alpha.

## Adversarial evidence
The source measures from the **same first official open** used to calculate the signal: a signal defined by that opening price cannot be filled retrospectively at that price. Results are explicitly cost-free and not yet a full trading strategy. Selection across arbitrary bins and subperiods creates multiple-testing bias. Extremes may be data errors / untradable prints. Release announcement timestamp, universe survival and earnings corrections are material sources of lookahead.

## ADAPTATION_PROPOSAL — not implemented
For a future event signed-return Phase 3, match earnings to contemporaneously published announcements, wait until a timestamped executable post-open quote after observing the open, and compare net signed close returns against matched non-earnings gaps with a single preregistered event definition and variant counts. Do not replace stocks with indices, futures or perps. Do not imply original article tested this protocol.

## UNKNOWN
Actual publication date; full historical announcement revisions, earnings released while closed, quote quality, position sizes, event crossover, transaction costs, exact opening data source, sample universe membership.

## Portfolio tags — HYPOTHESIS
Risk driver: earnings information / gap microstructure. Market: US common equity single names. Horizon: post-open to same-day close. Direction: gap-contingent long/short. Likely overlap: equity event drift and illiquidity (unmeasured).

**Status:** SOURCE_CAPTURE_ONLY, not executable, not independently validated.
