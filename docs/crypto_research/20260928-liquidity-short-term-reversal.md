# Crypto Research Run — Liquidity-Conditioned Short-Term Reversal

## Conclusion
**REJECT.** Development diagnostics passed, but untouched 2024–2025 OOS failed. The canonical 24h reversal portfolio produced net Sharpe **-0.81**, total return **-34.3%**, and max drawdown **-42.7%** at 3 bps one-way cost. The 12h and 48h neighbors were also negative.

## Source
Adam Zaremba et al., *Up or down? Short-term reversal, momentum, and liquidity effects in cryptocurrency markets*, International Review of Financial Analysis 78 (2021), DOI 10.1016/j.irfa.2021.101908.

## Hypothesis
Within the less-liquid portion of the point-in-time Binance perpetual universe, recent losers should outperform recent winners over the next day.

## Pre-Registered Specification
Manifest: `run_log/crypto_research/runs/20260928-liquidity-short-term-reversal-manifest.json`

Canonical lookback 24h; neighbors 12h and 48h; daily 00:00 UTC rebalance; bottom 60% by lagged trailing 30-day dollar volume after exact-history filtering; long loser tercile / short winner tercile; development 2021–2023; OOS 2024–2025; 3 bps one-way base cost.

## Data
`/home/quant/dev/quant/ml4t-data/data/crypto/market/perps_1h.parquet`  
SHA256: `f35452fab6b9a32ebc7e773162575ecf582e62ed5cdfaab200f6808060f5f6b8`

## Signal Diagnostics
| Lookback | Mean IC | HAC p | Long−short next-day |
|---|---:|---:|---:|
| 12h | 0.0359 | 0.00082 | +0.0319% |
| 24h | 0.0353 | 0.00070 | +0.0230% |
| 48h | 0.0457 | 0.00003 | +0.00035% |

## Results
| Lookback | Net OOS Sharpe | Total return |
|---|---:|---:|
| 12h | -0.97 | -39.4% |
| 24h | **-0.81** | **-34.3%** |
| 48h | -0.75 | -34.4% |

2024 Sharpe: **-1.12**. 2025 Sharpe: **-0.43**.

## Cost Sensitivity
| Cost | Sharpe | Return |
|---|---:|---:|
| 1x | -0.81 | -34.3% |
| 2x | -1.47 | -51.2% |
| 3x | -2.13 | -63.7% |

## Robustness
One-hour execution delay remained negative at Sharpe **-0.73**. Removing strongest contributor LINKUSDT worsened Sharpe to **-1.02**. The failure is not explained by BTC/ETH concentration.

## Failure Analysis
The factor shows a development-to-OOS regime break. Daily turnover makes friction material, but all neighboring horizons are negative even before any post-hoc selection. No parameter rescue is permitted.

## Multiple-Testing Audit
Previous trials: **9**. New trials: **3**. Cumulative: **12**. DSR probability **0.066**; haircut Sharpe **-0.886**; PBO N/A for three preregistered lookbacks.

## Decision
**REJECT**

## Reproduction
`uv run --with scipy python3 -m scripts.run_crypto_liquidity_reversal --data /home/quant/dev/quant/ml4t-data/data/crypto/market/perps_1h.parquet`

## Provenance
Runner SHA256: `2410dd1e47fda298e7ff13e7fafa0d00c483ccc930831d0b3e67d1163dd36c5b`
