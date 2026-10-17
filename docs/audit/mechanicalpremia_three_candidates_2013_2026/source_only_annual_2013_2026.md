# Mechanical Premia: complete 2013–2026 YTD source-weighted comparison

**Method:** Native ml4t.backtest.Engine; one independent $100,000 synthetic price-unit account per calendar year. NOT continuous CAGR, broker USD PnL, or fresh OOS.
**Costs:** 1 bp commission and 2 bps slippage per side; no ASK spread, financing or FX conversion.
**Windows:** 2013–2025 full years; 2026 Jan 1–Oct 11 inclusive. EU50 D1 enters the C1/C2 eligible universe only after June 2014; 2013 portfolios have three D1 indices.

| Year | C1 DE30/EU50 | C2 JP225/EU50 | C3 US500/US100 |
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

| Candidate | Mean year return | Positive years | Mean yearly daily Sharpe | Worst within-year DD | Closed trades | Win rate |
|---|---:|---:|---:|---:|---:|---:|
| C1_DE30 | +1.75% | 10/14 | 0.50 | -6.60% | 2118 | 37.8% |
| C2_JP225 | +2.02% | 10/14 | 0.64 | -11.77% | 2138 | 39.9% |
| C3_US_ONLY | +2.99% | 10/14 | 0.66 | -7.83% | 1405 | 38.9% |

## Paired-year comparison vs original C1 (bootstrap descriptive only; variants were post-selected)

| Candidate | Years higher return | 2013-25 mean annual return delta | 95% bootstrap CI (pp) |
|---|---:|---:|---:|
| C2_JP225 | 8/14 | +0.22 pp | [-0.63, +1.07] |
| C3_US_ONLY | 11/14 | +1.17 pp | [+0.35, +2.03] |

**Limitations:** currency-mixed synthetic units for C1/C2, native stop initial-minute gap, undocumented broker sessions, omitted real financing and ASK spread. Year-end marked positions not carried. These data were already observed before C2/C3 selection.
