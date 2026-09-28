# Crypto Research Run — Weekly Low Realized Variance

## Conclusion
**REJECT.** The low-variance rank showed positive development IC, but the pre-registered tradable extreme-tercile spread was negative for all three formation windows. The canonical 168h signal had mean rank IC **0.0919** (HAC p **0.0026**) while its low-minus-high subsequent-week spread was **-0.0369%**. Because the development gate required both predictive rank information and a positive tradable spread, the 2024-05 through 2025 OOS was not consumed.

## Source
*Variance Decomposition and Cryptocurrency Return Prediction*, Journal of Financial and Quantitative Analysis (2024): https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/variance-decomposition-and-cryptocurrency-return-prediction/9995E58095453CB44A3BC3C9C111969F

## Hypothesis
Cryptocurrencies with lower recent realized variance outperform higher-variance peers over the subsequent week.

## Pre-Registered Specification
Manifest: `run_log/crypto_research/runs/20260928-low-realized-variance-weekly-manifest.json`

Canonical 168h realized-variance formation; neighbors 72h and 336h; weekly Monday 00:00 UTC rebalance; 30-day exact-history filter; top 80% by lagged trailing dollar volume; long low-variance tercile / short high-variance tercile; development 2021–2023; OOS begins 2024-05-01 and is only consumed after the development gate; 3 bps one-way base cost.

## Data
`/home/quant/dev/quant/ml4t-data/data/crypto/market/perps_1h.parquet`  
SHA256: `f35452fab6b9a32ebc7e773162575ecf582e62ed5cdfaab200f6808060f5f6b8`

## Signal Diagnostics

| Lookback | Weeks | Mean IC | HAC p | Low−High next-week |
|---|---:|---:|---:|---:|
| 72h | 155 | 0.0826 | 0.0097 | -0.327% |
| 168h | 155 | 0.0919 | 0.0026 | -0.0369% |
| 336h | 155 | 0.0849 | 0.0079 | -0.493% |

The positive IC did not translate to the pre-registered long-short extremes. This is exactly the kind of diagnostic disagreement that should stop a portfolio backtest rather than invite post-hoc construction changes.

## Methodology
The factor is negative lagged realized variance, computed as the lagged rolling sum of squared hourly log returns. Liquidity and history filters are causal. OOS portfolio construction is gated behind the fixed development criteria.

## Results
No OOS portfolio result was produced because the pre-registered development gate failed.

## Failure Analysis
The signal contains rank information in development, but the extreme tercile construction is not directionally profitable. Selecting a different quantile cut or changing sign now would be a new trial and is not permitted as a rescue.

## Multiple-Testing Audit
Previous parameter trials: **12**. New trials: **3**. Cumulative trials: **15**. DSR/PBO are N/A because OOS was not consumed.

## Decision
**REJECT**

## Reproduction
`uv run --with scipy python3 -m scripts.run_crypto_low_variance --data /home/quant/dev/quant/ml4t-data/data/crypto/market/perps_1h.parquet`

## Provenance
Result: `run_log/crypto_research/runs/20260928-low-realized-variance-weekly-result.json`
