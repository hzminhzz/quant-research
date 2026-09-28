# Crypto Research Run — 6h Volatility-Scaled Time-Series Momentum

## Conclusion
**REJECT.** Volatility-scaled TSMOM was strong in 2021–2023 development but decayed sharply in 2024–2025. The canonical 30-day lookback produced net OOS Sharpe **0.33**, total return **+7.3%**, and max drawdown **-42.2%**. The 14-day and 60-day neighbors reached only **0.49** and **0.54** Sharpe. At 2x base cost the canonical return turned negative.

## Source
Bui & Nguyen (2026), *Systematic Trend-Following with Adaptive Portfolio Construction: Enhancing Risk-Adjusted Alpha in Cryptocurrency Markets*: https://arxiv.org/abs/2602.11708

This candidate tests the source paper's simpler volatility-scaled TSMOM benchmark, not its full AdaptiveTrend model.

## Hypothesis
Multi-week crypto trends persist, and inverse realized-volatility weighting improves diversification enough for a liquid Binance perpetual portfolio to retain positive risk-adjusted returns at 6-hour decision intervals.

## Pre-Registered Specification
Manifest: `run_log/crypto_research/runs/20260928-volscaled-tsmom-6h-manifest.json`

Decision interval 6h; momentum lookbacks 14d / 30d canonical / 60d; lagged 30-day volatility and dollar-volume estimates; top 80% point-in-time liquidity; signal formed from completed closes before execution at current open; 1.0 gross exposure normalized by inverse volatility; 3 bps one-way base cost.

## Development
| Lookback | Net Sharpe | Total return |
|---|---:|---:|
| 14d | 1.21 | +496.7% |
| 30d | **1.57** | **+1058.6%** |
| 60d | 1.26 | +532.4% |

The development gate passed.

## OOS Results
| Lookback | Net Sharpe | Total return |
|---|---:|---:|
| 14d | 0.49 | +26.5% |
| 30d | **0.33** | **+7.3%** |
| 60d | 0.54 | +34.3% |

Canonical max drawdown: **-42.2%**.

## Cost Sensitivity
Canonical 30d: 1x cost Sharpe **0.33**, 2x **0.25**, 3x **0.16**. Total return becomes negative at 2x and 3x costs.

## Robustness
Excluding BTC/ETH reduced Sharpe to **0.28** and total return slightly below zero. A one-hour execution delay produced Sharpe **0.31**. Removing strongest contributor UNIUSDT produced Sharpe **0.26**.

## Failure Analysis
The factor remains weakly positive in recent data, but the development-to-OOS decay is large and cost/breadth robustness is insufficient. The 60-day neighboring lookback is retained as a trial but cannot be selected post hoc.

## Multiple-Testing Audit
Previous parameter trials: **18**. New trials: **3**. Cumulative: **21**. Candidate DSR probability **0.666** and haircut Sharpe **0.252**; PBO N/A for only three preregistered lookbacks.

## Decision
**REJECT**

## Reproduction
`uv run --with scipy python3 -m scripts.run_crypto_volscaled_tsmom --data /home/quant/dev/quant/ml4t-data/data/crypto/market/perps_1h.parquet`
