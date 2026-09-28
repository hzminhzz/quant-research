# Crypto Research Run — Binance Perpetual Premium-Index Factor

## Conclusion
**REJECT.** The pre-registered positive-sign premium hypothesis failed in development. Canonical 5-day mean rank IC was **-0.0209** (HAC t **-2.06**, p **0.039**) and the high-minus-low next-day spread was **-0.203%**. The 3-day and 7-day neighbors were also negative. The 2024–2025 OOS portfolio was not consumed.

## Source
Pre-registered source: https://onlinelibrary.wiley.com/doi/10.1002/fut.22425

## Hypothesis
Higher recent perpetual premium-index rank predicts higher subsequent cross-sectional returns among liquid Binance perpetuals.

## Pre-Registered Specification
Manifest: `run_log/crypto_research/runs/20260928-perp-premium-basis-manifest.json`

Canonical lookback 5 days; neighbors 3/7 days; daily rebalance; point-in-time 30-day continuity and lagged dollar-volume eligibility; long high tercile / short low tercile; development 2021–2023; OOS 2024–2025 only if the development gate passes; 3 bps one-way base cost.

## Data
Prices: `/home/quant/dev/quant/ml4t-data/data/crypto/market/perps_1h.parquet`  
Premium index: `/home/quant/dev/quant/ml4t-data/data/crypto/market/premium_index_8h.parquet`

## Signal Diagnostics

| Lookback | N days | Mean IC | HAC p | High−Low |
|---|---:|---:|---:|---:|
| 3d | 1076 | -0.0273 | 0.0066 | -0.281% |
| 5d | 1068 | -0.0209 | 0.0391 | -0.203% |
| 7d | 1060 | -0.0201 | 0.0302 | -0.129% |

## Methodology
Development diagnostics were computed before any OOS portfolio construction. Because the fixed development gate failed, the primary OOS was not inspected. Flipping the sign after observing these results would be a new hypothesis and is not permitted as a rescue.

## Multiple-Testing Audit
Previous parameter trials: **6**. New trials: **3**. Cumulative trials: **9**. DSR/PBO are N/A because the OOS backtest was not consumed.

## Decision
**REJECT**

## Reproduction
`uv run --with scipy python3 scripts/run_crypto_premium_basis.py --prices /home/quant/dev/quant/ml4t-data/data/crypto/market/perps_1h.parquet --premium /home/quant/dev/quant/ml4t-data/data/crypto/market/premium_index_8h.parquet`

## Provenance
Starting SHA: `273ecd60f76ce315d577ddb5de62fe50894d656f`  
Runner SHA256: `b2ecf73843ecb6d74fb577265bda09453f21604db914d4a928f62a8857d5b166`
