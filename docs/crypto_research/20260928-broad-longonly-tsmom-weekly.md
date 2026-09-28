# Crypto Research Run — Broad Long-Only Vol-Scaled TSMOM

## Conclusion

**REJECT.** The preregistered broad-universe long-only trend rule failed the development gate before OOS was touched. The canonical 30-day version had development Sharpe **-0.007**, return **-37.5%**, and max drawdown **-71.1%** across 2022–2023.

## Hypothesis / Mechanism

Medium-horizon crypto trends may persist because of slow speculative-capital rotation and underreaction. Long-only exposure was intended to avoid the fragile short leg, while inverse-volatility weighting diversified risk across a point-in-time liquid universe.

## Pre-Registration

Manifest: `run_log/crypto_research/runs/20260928-broad-longonly-tsmom-weekly-manifest.json`

Pre-registration commit: `7f8ab87`

The exact lookbacks (14/30/60 days), canonical 30-day rule, weekly rebalance, top-30 causal liquidity universe, inverse-volatility weighting, 10 bps one-way base cost, development period, OOS period, and robustness checks were fixed before execution.

## Universe / Data

- Binance USD-M USDT perpetuals
- Broad local archive: **609** symbols represented in the causal daily panel
- Point-in-time top 30 by lagged trailing-30-day quote volume
- Minimum five positive-trend assets or cash
- Features use prior completed days only
- Execution at Monday open
- Missing contracts are not forward-filled

## Development Results

| Lookback | Sharpe | Total return | Max DD |
|---|---:|---:|---:|
| 14d | -0.334 | -56.1% | -78.5% |
| **30d canonical** | **-0.007** | **-37.5%** | **-71.1%** |
| 60d | -0.467 | -68.9% | -85.3% |

Canonical annual behavior was highly unstable: 2022 Sharpe **-0.91** / return **-62.1%**, followed by 2023 Sharpe **1.14** / return **+65.1%**.

## Validation Decision

The fixed development gate required canonical Sharpe >0.70, positive return, max drawdown better than -45%, and at least two of three lookbacks profitable. It failed every one of those conditions. Therefore the 2024–2025 OOS was **not consumed** and no post-hoc tuning was attempted.

## Multiple-Testing Audit

This cycle adds **3** preregistered parameter trials, increasing the durable count from **145 to 148**. DSR/PBO are not meaningful because the candidate was rejected before OOS.

## Decision

**REJECT**

## Reproduction

Runner: `scripts/run_crypto_broad_longonly_tsmom.py`
