# Crude oil channel extremes: follow or fade according to ADX slope

Candidate: `davey_cl_adx_slope_breakout_fade_2010_v1`. **THESIS_CAPTURED only; no empirical research / ATS approval**.

**Primary author-hosted original document:** Kevin J. Davey, *Refining crude-oil breakouts*, *Active Trader*, March 2010, print pp. 30–35: https://kjtradingsystems.com/Act/davey0310.pdf . Read all six pages; source claims mapped below. No available TradeStation source-code download was examined.

## SOURCE_FACT: original rule and market — print page 30; setup on p. 32
**Market:** CL crude oil futures, not CFDs/perpetuals. 30-minute bars limited to approximately 9:00–14:30 Eastern (source p. 32), allowing overnight price gaps. Source conditions are checked on the current closed bar and filled at **next bar open**, not the source bar close.

For a signal bar closing at its x-bar **highest closing price**, go LONG if 11-bar ADX is greater than or equal to its value Y bars back; instead go SHORT if 11-bar ADX is lower. For a bar closing at the x-bar **lowest closing price**, go SHORT if ADX is non-falling; instead go LONG if ADX fell. Opposite-direction signals close and reverse existing positions (p. 30). Exact channel inclusion-of-current-bar and same-session first eligible fill require TradeStation parity before executing.

The author optimized channel lengths **10–50** and compared two ADX comparison lags (2 and 10), selecting **x=34**, **Y=10**. ADX itself is an **11-bar** indicator. Later the author searched a delay of 2–11 bars after prior exit before a next entry and chose **8 bars**; that is a separately tuned addition, not an original unoptimized requirement (pp. 34–35).

## AUTHOR_REPORTED_UNVERIFIED: p. 34, Tables 1–3
TradeStation author tests: in-sample 2003-11-01–2008-11-01; held-out year 2008-11-01–2009-11-01. Reported simulation charges **$45 round trip** for commissions/slippage. For the selected 8-bar delayed-entry variant Table 3 reports **115 out-of-sample trades, +$16,325 net, 1.15 profit factor and -$19,320 max drawdown**. These amounts are reported by the author, not recomputed or endorsed.

## Adverse evidence and LOCAL_INFERENCE
The paper reports long flat-to-losing stretches, large drawdowns and disappointing results from the walk-forward and volatility-adaptive alternatives. Table 1 shows walk-forward -$42,155 intraday drawdown versus baseline -$35,035. The delayed-entry parameter was itself selected on observed returns; out-of-sample performance was substantially weaker than the training period. This limits confidence in persistence. A possible mechanism is that falling ADX makes an extreme more likely to reverse while non-falling ADX supports continuation. **That economic interpretation is an unverified hypothesis**, not an observed risk-premium explanation.

## ADAPTATION_PROPOSAL
**NONE.** Keep original CL futures, directional signal and stop/reversal mechanics. Do not silently change to CFD or perpetual, invent modern fees, stop distances or position sizing. A future test must preregister whether the author's final 8-bar delay is part of the primary rule, and count the searched variants.

## UNKNOWN and verification blockers
Source TradeStation implementation, complete contract size, rollover, close-high tie semantics, ADX smoothing conventions, holiday/DST timing, delay effect on an existing stop-and-reverse position, benchmark/null specification and executable contemporary spreads are **UNKNOWN**. The source's simulation is not executable evidence.

## Future falsifier — NOT RUN
Conditional switch has no incremental net performance relative to pure channel trend-following and pure channel fade controls after real CL costs and the complete strategy-search history.

**Portfolio tags (hypotheses, no measured correlation):** risk driver CL commodity price trends vs failed breakouts; market US energy futures; horizon 30-minute intraday signals with possible overnight holding; beta/direction dynamic long/short commodity; overlap cluster commodity breakout / short-term reversal.
