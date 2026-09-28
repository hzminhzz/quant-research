# Intraday MAX lottery-demand factor — REJECT

## Conclusion

**REJECT.** The intraday MAX effect was visible in cross-sectional rank diagnostics, but a 4-hour long-low-MAX / short-high-MAX portfolio was not remotely tradable at the preregistered 10 bps one-way cost assumption. Canonical 24-hour development Sharpe was **-1.42** and total return **-64.9%**. The 2024–2025 OOS period was not consumed.

## Source

Manisha Yadav, “Intraday lottery demands in cryptocurrency market,” *Studies in Economics and Finance* 42(4), 2025, 799–835, DOI 10.1108/SEF-07-2024-0461.

The paper studies the cross-sectional MAX effect using 5-minute returns over the prior hour and an hourly forecast horizon. This repository test preregistered a coarser adaptation to the available broad 1-hour Binance panel: maximum hourly return over 12/24/48 completed hours and a 4-hour holding horizon.

## Hypothesis / mechanism

Lottery-like demand temporarily overvalues assets with unusually large recent positive intraday returns, so low-MAX assets should outperform high-MAX assets.

## Pre-registration

Manifest: `run_log/crypto_research/runs/20260928-intraday-max-lottery-4h-manifest.json`

- Lookbacks: 12h / 24h / 48h; canonical 24h.
- Universe: Binance USD-M USDT perpetuals listed by 2021-12-31, re-ranked every 4 hours; top 50 by lagged 30-day quote volume.
- Signal: negative maximum prior hourly close-to-close return.
- Portfolio: equal-weight market-neutral top/bottom quintiles.
- Execution: every 4 hours; signal data end at least one hour before entry; enter at current bar open, exit four hours later.
- Base cost: 10 bps one-way.
- Development: 2022–2023.
- OOS: 2024–2025, sealed unless development gate passes.

## Data / point-in-time handling

139 pre-2022 contracts were available. Rolling signal and liquidity inputs were lagged, exact hourly continuity was required, and rankings were formed contemporaneously. No model or scaler was fit.

## Signal diagnostics

| Lookback | Mean rank IC | HAC t | HAC p | Low-MAX minus high-MAX 4h spread |
|---:|---:|---:|---:|---:|
| 12h | 0.0533 | 16.81 | 2.23e-63 | 1.49 bp |
| **24h** | **0.0531** | **16.27** | **1.65e-59** | **2.92 bp** |
| 48h | 0.0551 | 17.41 | 6.38e-68 | 3.12 bp |

The raw relation is statistically strong, but the spread is too small for the induced turnover at the fixed cost assumption.

## Development results

| Lookback | Net Sharpe | Total return | Max DD | Turnover |
|---:|---:|---:|---:|---:|
| 12h | -3.879 | -91.96% | -91.81% | 2743.8 |
| **24h canonical** | **-1.419** | **-64.93%** | **-74.21%** | **1587.6** |
| 48h | -0.361 | -29.32% | -54.85% | 931.9 |

Canonical year split: 2022 -21.17% (Sharpe -0.42), 2023 -55.52% (Sharpe -2.97).

## Failure analysis

The anomaly survives as a diagnostic signal but not as an implementable 4-hour portfolio under realistic costs. This is a useful negative result: statistical IC alone is insufficient when turnover is extreme. The failure is broad across all three preregistered lookbacks, so OOS was not opened.

## Multiple-testing audit

Previous counted trials: 151. New preregistered trials: 3. Cumulative trials: **154**. DSR/PBO are not meaningful because the candidate failed before OOS.

## Decision

**REJECT.** No confirmation or deployment action.

## Reproduction

`uv run python scripts/run_crypto_intraday_max_factor.py --root /home/quant/dev/quant/ml4t-data/.data/store/crypto_futures_ohlcv_1h_BINANCE_UM_PERP`

## Provenance

Pre-registration commit: `1a64342`. Result produced 2026-09-28.
