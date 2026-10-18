# Han et al. (2024): Size and risk-adjusted momentum interaction in crypto factor portfolios

**THESIS_CAPTURED / descriptive source only**; no model training, IC, backtesting, holdout or orders.

Candidate: `crypto_xs_size_rmom_interaction_han_20261018_v1`
Source: Weihao Han, David Newton, Emmanouil Platanakis, Charles Sutcliffe, Xiaoxia Ye, *European Financial Management* 30(3), `https://doi.org/10.1111/eufm.12431`. Original open access journal text and tables inspected.

## What the authors actually tested

From CoinMarketCap weekly prices across 2,353 cryptocurrencies (> USD 1M market cap, 2014 to June 2021), the authors examine 29 factor portfolios. For interaction analysis, coins are split at sample median market cap into small/big, then each size group is split at 30th and 70th percentiles of risk-adjusted momentum (RMOM) across 1-, 2-, and 4-week lookbacks. Constituents are market-cap weighted within buckets, rebalanced weekly, and measured against forward one-week excess returns.

## Key limitations and risks

No uniquely pre-registered tradable combined basket; capitalization cutoff survivor bias; inability to short illiquid small-cap names; potential selection bias across 29 characteristics and multiple dominance tests.

## ATS fit and stopping

Descriptive capture only. Literal original small-cap universe is **UNAVAILABLE_DATA** on local perpetuals. A separate liquid perp adaptation would require PIT universe definition, realistic borrow/short constraints, and multiple-testing correction.
