# qoppac_futures_longlookback_skew_absolute_v1

## SOURCE_FACT
Rob Carver, *Skew and Kurtosis as trading rules*, January 13, 2020. Primary URL: https://qoppac.blogspot.com/2020/01/skew-and-kurtosis-as-trading-rules.html (sections "The trading rules", "Checking behaviour, correlation and costs", "Performance", "Some thoughts on fitting").

Original product: diversified exchange-traded futures. Original experiment: use trailing daily-return skew over 7, 14, 30, 90, 180 and 365 days, de-mean absolute, historical, cross-sectional, or within asset class, normalize by the robust volatility of the factor, then smooth an EWMA with span ceil(lookback_days/10). Standalone skew forecasts use negative skew. Author screened out 7-day lookback after cost diagnostics.

## SOURCE_REPORTED_TEST
Author reports about 0.33 Sharpe for a one-year absolute-skew factor and about 0.35 for slow relative-value skew. He reports only approximately 0.07 increase in overall system Sharpe after adding skew. These are author claims; no independent reproduction was performed.

## LOCAL_INFERENCE
A slowly varying negative-skew characteristic may price convexity or hedging demand, but precise counterparty and causal mechanism remain UNKNOWN. Baseline for future study: risk- and cost-matched futures trend-plus-carry portfolio without skew forecasts.

## ADVERSE EVIDENCE
Fast lookbacks underperformed and incurred heavy costs, the original sweep covered 72 rule permutations, and the author explicitly warned about selection bias. Skew estimates are unstable under isolated extremes, especially around crises.

## ADAPTATION_PROPOSAL
No futures-to-ETF/CFD/perpetual conversion and no selected best lookback. Do not fabricate weights or a new threshold. Original author's ensemble and instrument-risk rules need independent parity.

## UNKNOWN / FUTURE SCIENTIFIC GATES
Contract universe, historical raw data/roll construction, factor robust_vol_calc and forecast scaling, fill convention, risk weights, bid/ask cost and future OOS window. Freeze a selection family before any trial. Primary falsifier: no post-cost benefit over a matched futures trend-plus-carry baseline after full selection accounting.

Descriptive portfolio tags (HYPOTHESIS): diversified futures, slow skew/tail asymmetry, mixed sign, months, overlap cluster slow distributional premium. No Phase 3/4 or protected reads were executed. This is not research-ready, executable, or approved.
