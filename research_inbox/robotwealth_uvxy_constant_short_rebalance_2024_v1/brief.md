# Constant-dollar short UVXY with rebalancing

**Candidate:** `robotwealth_uvxy_constant_short_rebalance_2024_v1`  
**Status:** THESIS_CAPTURED, descriptive only; not executable.  
**Primary:** Kris Longmore, *Modelling UVXY trading strategies with Excel*, November 30, 2024, https://robotwealth.com/modelling-uvxy-trading-strategies-with-excel/

## SOURCE_FACT
Longmore examines shorting US-listed UVXY and periodically restoring a chosen dollar short exposure at monthly, weekly or daily intervals. UVXY tracks leveraged daily returns on a 30-day constant-maturity VIX futures index; its leverage target changed from 2x to 1.5x in 2018. The spreadsheet asks the user to select dollar exposure and rebalance frequency, not a fixed recommended setting. Original source: paragraphs under "Short that thing" and "Conclusions".

## AUTHOR_REPORTED_UNVERIFIED
In the source's monthly-rebalance simulation the short notional temporarily reached about seven times intended exposure during the February 2018 volatility event. The author says weekly/daily rebalancing controlled drift better but increases expenses. Trading and borrow costs were excluded. These are the author's claims, not independently reproduced results.

## ADVERSE EVIDENCE
Short volatility can produce extraordinary losses and margin liquidation in sudden crises. Real costs include locate, borrowing and execution. The same article separately studies a neutralized UVXY/SVXY tracking-error trade and reports that it largely stopped working after leverage reductions; that paired strategy is not this candidate.

## LOCAL_INFERENCE
Potential risk premium arises because end-investors pay to hedge equity volatility while short-volatility providers bear jump risk and costs. The risk-adjusted after-cost economics are UNKNOWN.

## ADAPTATION_PROPOSAL
NONE. Preserve ETF instrument. Do not invent fixed rebalance, position size, stop or algorithmic execution clock.

## UNKNOWN
Historical borrow rates/recalls and trade capacity, split-adjustment conventions, pricing clock, rebalancing choice, fee model, crisis execution and account margin.

## Portfolio overlap HYPOTHESES
Risk driver: short volatility and leverage compounding. Market: US listed volatility ETF. Horizon: multi-day ongoing exposure. Expected beta/direction: short volatility/short convexity. Likely overlap: volatility risk-premium and crisis correlation cluster. These are not measured correlations.

No market calculations, backtests, holdout or orders.
