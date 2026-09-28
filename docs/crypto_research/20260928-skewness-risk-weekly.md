# 20260928 Skewness Risk Weekly

## Conclusion

**REJECT.** The source-inspired low-skewness cross-sectional effect was statistically strong in development, but the preregistered canonical 30-day portfolio missed the fixed development Sharpe gate. The 2024-2025 OOS period was not consumed.

## Source

Liu & Chen, *Skewness risk and the cross-section of cryptocurrency returns*, International Review of Financial Analysis 96 (2024), DOI 10.1016/j.irfa.2024.103626.

## Hypothesis / mechanism

Lower lagged return asymmetry risk should command higher subsequent expected returns. The implementation ranks contemporaneously eligible Binance USD-M USDT perpetuals by negative lagged realized skewness.

## Pre-Registration

- Windows: 14 / **30 canonical** / 60 completed days.
- Rebalance: Monday 00:00 UTC using information through the prior completed day.
- Universe: top 50 by lagged trailing-30-day quote volume at each rebalance.
- Portfolio: market-neutral long lowest-skewness quintile / short highest-skewness quintile, 0.5 gross each side.
- Cost: 10 bps one-way base; 2x/3x reserved for OOS if the development gate passed.
- Development: 2022-2023.
- Exploratory OOS: 2024-2025, sealed unless development gate passed.
- Gate: canonical IC > 0.02 with HAC p < 0.05, positive quintile spread, canonical net Sharpe > 0.70 and total return > 0, at least 2/3 windows profitable.

## Data / universe

609 Binance USD-M USDT perpetual symbols were available in the point-in-time loader. Eligibility used only lagged history and liquidity; no asset was selected for historical strategy performance.

## Signal diagnostics

| Window | Mean rank IC | HAC p | Low-minus-high skew return spread |
|---|---:|---:|---:|
| 14d | 0.0652 | 4.36e-08 | 0.7886% |
| **30d** | **0.0777** | **7.20e-09** | **0.6441%** |
| 60d | 0.0879 | 3.55e-11 | 1.0540% |

The predictive relation itself was strong and stable.

## Development portfolio results

| Window | Net Sharpe | Total return | Max DD | Turnover |
|---|---:|---:|---:|---:|
| 14d | 0.678 | 27.2% | -12.9% | 126.4 |
| **30d** | **0.679** | **24.1%** | **-13.8%** | **84.7** |
| 60d | 1.462 | 58.6% | -12.4% | 57.6 |

The 60-day neighbor was materially stronger, but switching to it after observing results would violate the preregistration and count as post-hoc tuning.

## Robustness / failure analysis

The canonical 30-day implementation failed only the fixed portfolio-Sharpe gate: 0.679 < 0.70. Because the gate was fixed before results, OOS was preserved. No OOS cost sensitivity, contributor-removal, or BTC/ETH ablation was run.

## Multiple-testing audit

This candidate adds three parameter trials, taking the cumulative research count from 90 to **93**. DSR/PBO are not meaningful for this rejected candidate because OOS was not consumed.

## Decision

Classification: `REJECT`. Do not promote the 60-day neighbor within this hypothesis. Move to a materially different mechanism.

## Reproduction

`PYTHONPATH=. uv run python scripts/run_crypto_skewness_risk.py --root /home/quant/dev/quant/ml4t-data/.data/store/crypto_futures_ohlcv_1h_BINANCE_UM_PERP`

## Provenance

Manifest: `run_log/crypto_research/runs/20260928-skewness-risk-weekly-manifest.json`
Structured result: `run_log/crypto_research/runs/20260928-skewness-risk-weekly-result.json`
