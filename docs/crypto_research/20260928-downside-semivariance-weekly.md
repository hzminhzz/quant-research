# 20260928 Downside Semivariance Weekly

## Conclusion
**REJECT.** The canonical 14-day downside-semivariance factor produced development Sharpe **0.602**, below the fixed 0.70 gate, while rank IC was significantly negative (**-0.0709**, HAC p=0.0019).

## Source and Hypothesis
Zhang et al. (2021), *Downside risk and the cross-section of cryptocurrency returns*. The preregistered hypothesis was a positive downside-risk premium.

## Universe and Method
Frozen ex-ante set of 139 Binance USD-M perpetuals already listed by 2021-12-31, with weekly point-in-time top-50 liquidity selection. Feature windows 7/14/30 completed UTC days, canonical 14. Weekly Monday-open execution; base cost 10 bps one way.

## Results
The 14-day variant returned **+28.7%** in 2022-2023 with max drawdown **-23.7%**, but failed both the Sharpe and signal-direction gates. The 7-day and 30-day neighbors were not robust.

## Decision
OOS remained sealed. Cumulative trial count: **121**.
