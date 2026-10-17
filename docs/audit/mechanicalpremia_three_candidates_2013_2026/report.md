# Mechanical Premia three-candidate comparison | 2013-2026 YTD

**Evidence:** 252/252 native annual cells independently reconciled, no order rejections. Annual separate resets, not continuous equity.
**Qualification:** synthetic price-unit only; cannot call real PnL without broker point value, currency conversion, ASK spread and overnight financing.
**Selection:** all dates are observed exploratory data, not pristine OOS.

## Source-weighted H1 + D1 annual net returns (1x assumed costs)

| Year | C1 DE30 + EU50 | C2 JP225 + EU50 | C3 US500/US100 |
|---|---:|---:|---:|
| 2013 | +2.97% | +5.39% | +5.98% |
| 2014 | +1.29% | +1.70% | +3.34% |
| 2015 | -1.00% | -0.87% | -0.89% |
| 2016 | -0.60% | +0.84% | -0.75% |
| 2017 | +1.17% | -0.30% | -0.41% |
| 2018 | +0.12% | +2.40% | +0.88% |
| 2019 | +3.41% | +1.49% | +2.39% |
| 2020 | -1.41% | -2.99% | +2.48% |
| 2021 | +7.04% | +5.84% | +9.44% |
| 2022 | -0.91% | -1.42% | -0.01% |
| 2023 | +2.67% | +4.45% | +3.42% |
| 2024 | +2.08% | +4.30% | +4.74% |
| 2025 | +4.43% | +3.34% | +5.89% |
| 2026 YTD | +3.20% | +4.07% | +5.32% |

## Aggregate of independent annual native runs (NOT continuous CAGR)

| Candidate | Mean annual return | Positive years | Closed trades | Win rate | Mean yearly Sharpe | Worst year DD | 2x mean annual return |
|---|---:|---:|---:|---:|---:|---:|---:|
| C1_DE30 | +1.75% | 10/14 | 2118 | 37.8% | 0.50 | -6.60% | +0.07% |
| C2_JP225 | +2.02% | 10/14 | 2138 | 39.9% | 0.64 | -11.77% | +0.39% |
| C3_US_ONLY | +2.99% | 10/14 | 1405 | 38.9% | 0.66 | -7.83% | +1.17% |

## Paired-year diagnostics vs C1

| Challenger | Return better (years) | Mean return delta (pp) | Sharpe better (years) | Drawdown better (years) |
|---|---:|---:|---:|---:|
| C2_JP225 | 8/14 | +0.27 | 9/14 | 4/14 |
| C3_US_ONLY | 11/14 | +1.24 | 11/14 | 2/14 |

## Limitations
- All three variants are exploratory selected/observed data.
- 2026 ends October 11; partial year.
- Broker ASK and spread, overnight CFD financing, lot/multiplier and FX conversion missing.
- H1 initial protective stop submitted after entry-minute callback; not source MT5 stop parity.
- Year-end open trades are marked, not carried into subsequent separate annual runs.
- For each year/candidate/sleeve and cost, consult all_annual_metrics.csv and source native fill/trade/equity Parquet.
- Annual reset Sharpe/Calmar means are descriptive and not global 2013-2026 risk metrics.
