# Systematic Liquidity-Risk Beta — REJECT

## Conclusion
**REJECT.** The causal liquidity-beta adaptation produced a statistically significant relationship in the **opposite** direction from the preregistered hypothesis. The 52-week canonical net development Sharpe was **-0.874**.

## Source and mechanism
Source: SeungOh Han, *Is liquidity risk priced in cryptocurrency markets?*, Applied Economics Letters 30(17) (2023), DOI 10.1080/13504851.2022.2098235.

The test estimates each asset's sensitivity to unexpected aggregate liquidity improvements. Individual liquidity uses daily Amihud `|return| / quote_volume`, aggregated weekly. Aggregate liquidity innovations are generated causally with an expanding AR(1), fixed before results.

## Pre-registration and universe
- Point-in-time Binance USD-M USDT perp panel; 609 symbols in the daily loader.
- Weekly top 50 by lagged 30-day quote volume.
- Rolling beta windows: 26, **52 canonical**, 78 weeks.
- Long highest beta quintile / short lowest.
- 10 bps one-way; development 2022-2023, exploratory OOS 2024-2025.
- Explicit deviation from source: no market-cap data; causal AR(1) replaces market-cap-scaled ARMA(1,2).

## Leakage / implementation controls
The aggregate-liquidity forecast is fit on an expanding history ending strictly before each innovation observation. Beta windows contain only completed weeks before the rebalance. One indexing bug in the AR lag construction was fixed before any valid strategy output; no research parameter changed.

## Development evidence
| Window | Mean IC | HAC p | Spread | Net Sharpe | Return | Max DD |
|---:|---:|---:|---:|---:|---:|---:|
| 26w | -0.0704 | 0.00028 | -0.01150 | -1.672 | -49.4% | -50.3% |
| **52w** | **-0.0659** | **0.0040** | **-0.00708** | **-0.874** | **-37.4%** | **-50.6%** |
| 78w | -0.0661 | 0.0029 | -0.00821 | -0.974 | -38.8% | -47.5% |

The sign is stable but opposite to the preregistered premium, so reversing it now would be post-hoc and is not allowed.

## Multiple-testing audit
Three preregistered trials added; cumulative count = **112**. OOS was not consumed.

## Decision / reproduction
- Classification: `REJECT`
- OOS consumed: **No**
- Manifest: `run_log/crypto_research/runs/20260928-liquidity-risk-beta-weekly-manifest.json`
- Result: `run_log/crypto_research/runs/20260928-liquidity-risk-beta-weekly-result.json`
- Runner: `scripts/run_crypto_liquidity_beta.py`
