# Nearness-to-52-Week-High Anchoring — REJECT

## Conclusion
**REJECT.** The preregistered 364-day canonical factor failed the development gate, so 2024-2025 exploratory OOS was not consumed.

## Source and hypothesis
Source: Jia et al., *Psychological anchoring effect and cross section of cryptocurrency returns*, Journal of Banking & Finance 182 (2026), DOI 10.1016/j.jbankfin.2025.107592.

Hypothesis: assets trading nearer their trailing high should outperform assets far below it because anchoring slows information incorporation.

## Pre-registration and universe
- Point-in-time Binance USD-M USDT perpetual universe.
- Each Monday: top 50 by lagged trailing-30-day quote volume among contracts with exact history.
- Lookbacks: 182, **364 canonical**, 546 days.
- Long highest-nearness quintile / short lowest quintile; 0.5 gross each side.
- Monday-open to next-Monday-open; 10 bps one-way base cost.
- Development: 2022-2023. Exploratory OOS: 2024-2025.

## ML4T / leakage controls
The factor was implemented directly in Polars because it is a single transparent causal transform; no catalog sweep or fitted preprocessing was used. Rolling highs and liquidity end before the decision timestamp. Cross-sectional ranking is contemporaneous. Forward returns are used only as labels/portfolio outcomes.

## Development evidence
| Lookback | Mean IC | HAC p | Spread | Net Sharpe | Return | Max DD |
|---:|---:|---:|---:|---:|---:|---:|
| 182d | 0.0239 | 0.263 | 0.00354 | 0.247 | 6.1% | -31.5% |
| **364d** | **0.0085** | **0.717** | **-0.00179** | **-0.304** | **-16.2%** | **-39.5%** |
| 546d | -0.0087 | 0.695 | -0.01283 | -1.760 | -52.2% | -52.7% |

The canonical relationship is economically and statistically absent. No post-hoc switch to the 182-day neighbor is allowed.

## Multiple-testing audit
Three preregistered parameter trials were added: cumulative crypto strategy parameter trials = **103**. DSR/PBO are not meaningful because the development gate stopped the candidate before OOS.

## Decision / reproduction
- Classification: `REJECT`
- OOS consumed: **No**
- Manifest: `run_log/crypto_research/runs/20260928-nearness52-anchoring-weekly-manifest.json`
- Result: `run_log/crypto_research/runs/20260928-nearness52-anchoring-weekly-result.json`
- Runner: `scripts/run_crypto_nearness52.py`
