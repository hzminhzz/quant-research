# alvarez_pre_earnings_avoidance_meanrev_negative_v1

**Status:** THESIS_CAPTURED — descriptive, source-faithful negative research evidence; not research-ready or executable.

## SOURCE_FACT
Cesar Alvarez, *Avoiding Trades Before Earnings*, April 24, 2019. Primary URL: https://alvarezquanttrading.com/blog/avoiding-trades-before-earnings/ . Source locations: *A large dose of salt*, *The Base Test*, *Avoiding Earnings*, *Results Avoiding Earnings*, April 24–25 reader/author comments.

The source uses Quantopian's Q500US (500 most liquid US stocks), not historical S&P 500 constituents. Baseline entries require RSI(2) crossing below each separately tested threshold of 1, 3 or 8, a close over the 200-day moving average, and high-to-low ranking by 100-day historical volatility. Trades enter at the next trading day's 09:32 bar. Exits are RSI(2)>80 or a holding period exceeding 15 days, executed at the next 09:32 bar. The treatment excludes buys with the next known earnings event within seven days, and exits the next day if earnings are two days away.

## AUTHOR_REPORTED_UNVERIFIED
Quantopian sample 2007-01-01 through 2013-12-31. Compared with the baseline, the author reports sharply lower compound annual return in two of three versions, and worse drawdown and Sharpe for all three. He did **not** adopt the avoidance rule. These are not independent replicated results.

## ADVERSE EVIDENCE
The author explicitly cautions that his Quantopian Python implementation may contain a bug. One commenter questions surprisingly few avoided entries; author notes alternative trades could fill portfolio slots and reiterates bug uncertainty. The original platform/event data cannot be assumed reproducible today.

## LOCAL_INFERENCE
Scheduled earnings create jump and adverse-information exposure, but removing these positions can also remove recoveries and free capacity for different trades. The marginal effect is unidentified; a test must distinguish exclusion effects from portfolio substitution.

## ADAPTATION_PROPOSAL
None executed. A later paired, capacity/exposure-controlled PIT study could test the specific published treatment against the same baseline. This is not the original author's independently verified causal result.

## UNKNOWN
Historical announcement-as-of data (including scheduling updates), portfolio position limits and weights, 09:32 executable spreads/fills, Q500US historical membership and delistings, precise RSI crossing and portfolio replenishment policy. Do not invent these.

## PORTFOLIO TAGS — HYPOTHESES ONLY
Risk driver: company earnings event-gap risk. Market: US liquid equities. Horizon: several sessions to two weeks. Expected direction: conditional long equity beta, reduced earnings exposure. Likely overlap: equity mean-reversion and scheduled corporate events. No measured correlation/diversification evidence.

**No market return calculations, backtests, protected reads, ML training, broker actions or deployment.**
