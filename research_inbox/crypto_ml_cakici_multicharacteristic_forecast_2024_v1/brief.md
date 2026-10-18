# Cakici et al. (2024): Cross-sectional cryptocurrency ML forecasts

**Status:** THESIS_CAPTURED / source-only. No model was trained, no strategy backtested, and no native ATS stage executed.

## Source and claims

Cakici, Shahzad, Bedowska-Sojka and Zaremba, *International Review of Financial Analysis* (2024), `https://doi.org/10.1016/j.irfa.2024.103244`. Publisher abstract and readable article excerpts verified. The researchers aggregate 40 characteristics on more than 500 coins (2017–2023) using eight ML approaches. Their reported forecast-combination, value-weighted long/short strategy has approximately 2.37% mean weekly return and 1.66 annualized Sharpe **in the authors' study only**. They explicitly find simple predictors (past alpha, price, momentum, illiquidity) important and warn that the bulk of alpha comes from long illiquid micro-coins; losses/drawdowns as large as 70–80% are discussed. Costs reportedly remove over half of the payoffs.

## Local hypothesis, NOT source rule

Test whether modest-complexity, strictly PIT boosted ranking adds information to simple momentum/illiquidity ranks **after** restricting to liquid, prop-firm-tradable symbols. This restriction might remove the very alpha claimed by the source; therefore this is a stringent and likely-to-fail transfer, not a promised profitable strategy.

## ML, timing and ATS boundary

Original exact feature definitions, training split, fitted model and portfolio weights were not reproduced from full paper. OOF/walk-forward historical predictions, purging, source symbols and model-sidecar hashes would be mandatory before scientific ATS qualification. ATS's current cross-sectional rank/long-short protocol could represent a **new liquid basket adaptation** but not prove it source-equivalent. Sampled prefix tests alone cannot authenticate training split leakage. No funding-derived alpha; real swap/financing still matters in later simulation.

## Distinction and stop condition

Different from existing single-feature `crypto_xs_*` anomaly folders: this paper's mechanism is a **learned multicharacteristic forecast** with an important liquid-universe feasibility falsifier. Stop if its putative advantage disappears outside low-liquidity assets or if executable original rules would have to be fabricated.

Source type: PRIMARY_PUBLISHER_ABSTRACT_AND_EXCERPTS; source reported results are not independently verified; operational feasibility UNKNOWN.
