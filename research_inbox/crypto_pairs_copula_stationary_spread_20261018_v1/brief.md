# Copula mispricing of cointegrated cryptocurrency futures pairs

**THESIS_CAPTURED — SOURCE_CAPTURE_ONLY; not executable.**

## Original source
Masood Tadi and Jiří Witzany (2023), [*Copula-Based Trading of Cointegrated Cryptocurrency Pairs*](https://arxiv.org/abs/2305.06961).

## SOURCE_FACT
The research explores crypto relative-value positions formed by cointegration testing and copula-based conditional mispricing. Original exchange/instruments: approximately 20 Binance USDT-margined futures, with hourly and five-minute historical observations. It forms BTCUSDT-reference log spreads for altcoins, screens Engle-Granger and nonlinear KSS cointegration, ranks correlations using Kendall tau, and trades two selected altcoin legs in opposing directions; BTC is the **reference**, not an executable third leg. The source uses approximately three-week formation and one-week trading windows, conditional copula signals at the hourly observation clock, entry alpha1 in {10%, 15%, 20%}, exit alpha2 10%, and closes at trading-week end. The reported initial leg notionals are roughly 20,000 USDT each, fixed in quantity within the week; dollar neutrality may drift. This is a source summary, not a verified executable specification: precise conditional-probability sign-to-order mapping, PIT universe, actual order fills, financing, and effective spread/slippage remain unverified.

## SOURCE_REPORTED_TEST
The authors publish backtest comparisons; statistical/economic outcomes are **UNVERIFIED** independently. No local backtest, IC or trading activity.

## LOCAL_INFERENCE / adverse evidence
Cointegration may fail after regime shifts; fitted copulas are vulnerable to lookahead in pair selection and conditional model fitting, and simultaneous two-leg fills may be impractical. Fil and Kristoufek (2020), https://doi.org/10.1109/access.2020.3024619, report poor after-fee performance of traditional crypto pairs trading, providing adverse but not decisive evidence for this distinct copula model. Most direct falsifier: OOS non-stationary spreads or disappearing economic conditional reversion after friction.

## Novelty
Conditional copula *nonlinear* spread dislocation is distinct from the existing return-correlation and information-delay captures. No substitute z-score pairs rule is allowed as an alleged source strategy.

## UNKNOWN / prop transfer
As-of universe/delisting, quote execution, short/hedge permission, gross leverage, risk cap, margin, weekend treatment and financing: **UNKNOWN**. Cost accounting in any future separately authorized simulation is not funding-based alpha. Source-only capture; no ATS interaction or scientific stage work.
