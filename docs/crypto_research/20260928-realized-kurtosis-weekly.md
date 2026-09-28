# Realized-Kurtosis Cross-Section — REJECT

## Conclusion
**REJECT.** The preregistered positive-kurtosis premium failed in development. The observed relationship was negative and the 14-day canonical portfolio had net Sharpe **-1.111**.

## Source and hypothesis
Source: Jia, Liu & Yan, *Higher moments, extreme returns, and cross-section of cryptocurrency returns*, Finance Research Letters 39 (2021).

Hypothesis: higher lagged intraday return kurtosis should predict higher subsequent returns.

## Pre-registration and universe
- Causal Binance USD-M USDT perp panel, 638 symbols in loaded history.
- Weekly top 50 by lagged trailing-30-day quote volume.
- Pooled hourly log-return excess kurtosis over 7, **14 canonical**, 30 prior completed days.
- Long highest-kurtosis quintile / short lowest; market-neutral.
- Monday-open to next-Monday-open; 10 bps one-way.
- Development 2022-2023; exploratory OOS 2024-2025.

## ML4T / leakage controls
Hourly moments are built from contiguous historical returns only. Rolling sums are lagged before the Monday decision. No fitted transforms or selection on future returns are used.

## Development evidence
| Window | Mean IC | HAC p | Spread | Net Sharpe | Return | Max DD |
|---:|---:|---:|---:|---:|---:|---:|
| 7d | -0.0403 | 0.0195 | -0.01021 | -1.955 | -51.5% | -52.2% |
| **14d** | **-0.0174** | **0.361** | **-0.00652** | **-1.111** | **-39.3%** | **-45.7%** |
| 30d | -0.0098 | 0.640 | -0.00208 | -0.512 | -19.9% | -39.9% |

The sign mismatch is a direct falsification of this adaptation; OOS was therefore preserved.

## Multiple-testing audit
Three preregistered trials added; cumulative count = **109**. DSR/PBO are not promoted because OOS was not used.

## Decision / reproduction
- Classification: `REJECT`
- OOS consumed: **No**
- Manifest: `run_log/crypto_research/runs/20260928-realized-kurtosis-weekly-manifest.json`
- Result: `run_log/crypto_research/runs/20260928-realized-kurtosis-weekly-result.json`
- Runner: `scripts/run_crypto_realized_kurtosis.py`
