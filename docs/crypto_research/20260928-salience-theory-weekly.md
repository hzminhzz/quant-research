# Salience-Theory Cross-Section — REJECT

## Conclusion
**REJECT.** The salience signal was directionally strong in rank diagnostics, but the fixed 7-day canonical net development Sharpe was **0.646**, below the preregistered >0.70 gate. OOS remained sealed.

## Source and mechanism
Source: Cai & Zhao, *Salience theory and cryptocurrency returns*, Journal of Banking & Finance 159 (2024), DOI 10.1016/j.jbankfin.2023.107052.

The implementation fixes the paper-inspired salience function before results: daily state salience compares each asset return with the contemporaneous cross-sectional market return; states are decision-weighted by salience rank. The trading signal is negative salience-theory excess return, so downside-salient assets rank higher.

## Pre-registration and universe
- Point-in-time Binance USD-M USDT perpetuals; 638 symbols present in the loaded history.
- Weekly top 50 by lagged 30-day quote volume.
- Windows: 5, **7 canonical**, 14 completed days.
- `theta=0.1`, `delta=0.7`.
- Long top signal quintile / short bottom; 0.5 gross each side.
- 10 bps one-way cost; development 2022-2023; exploratory OOS 2024-2025.

## ML4T / leakage controls
Direct first-principles implementation was used rather than feature-catalog search. All return states and liquidity inputs end before Monday open. No full-sample scaling/model fitting occurs. Universe membership is reconstructed at each rebalance.

## Development evidence
| Window | Mean IC | HAC p | Spread | Net Sharpe | Return | Max DD |
|---:|---:|---:|---:|---:|---:|---:|
| 5d | 0.0512 | 0.0042 | 0.00386 | 0.102 | 0.3% | -23.8% |
| **7d** | **0.0762** | **7.7e-6** | **0.00814** | **0.646** | **24.9%** | **-18.4%** |
| 14d | 0.0959 | 1.1e-7 | 0.00681 | 0.535 | 20.7% | -22.0% |

The signal predicts the cross section but does not clear the transaction-cost-aware canonical portfolio threshold. Selecting another window after observing the surface would be post-hoc tuning.

## Multiple-testing audit
Three preregistered trials added; cumulative count = **106**. OOS was not consumed, so no success-gate DSR/PBO claim is made.

## Decision / reproduction
- Classification: `REJECT`
- OOS consumed: **No**
- Manifest: `run_log/crypto_research/runs/20260928-salience-theory-weekly-manifest.json`
- Result: `run_log/crypto_research/runs/20260928-salience-theory-weekly-result.json`
- Runner: `scripts/run_crypto_salience.py`
