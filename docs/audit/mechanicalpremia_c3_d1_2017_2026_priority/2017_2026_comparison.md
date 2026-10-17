# C3 D1 pullback relaxation: Native ML4T, 2017–2026 YTD

**Status: VERIFIED 30/30 native annual variant cells and 12/12 2x cost stress cells (plus baseline).**
**Rules:** US500/US100 H1 breakout unchanged; D1 low ATR + Bollinger percent-B cutoff only 0.35,0.50,0.80. Original D1 cutoff 0.20 is baseline. All other source rules/costs/nominal risk weights fixed.
**Method:** One independent native ML4T Engine $100k synthetic account per year. Past warmup, next-minute fill. 2026 scored only through October 11.

## Portfolio annual net returns, 1x modeled direct cost

| Year | C3-original | ATR+%B<0.35 | ATR+%B<0.50 | ATR+%B<0.80 |
|---|---:|---:|---:|---:|
| 2017 | -0.41% | -0.41% | -0.41% | -0.41% |
| 2018 | +0.88% | +0.95% | +0.37% | -0.56% |
| 2019 | +2.39% | +5.06% | +7.13% | +10.70% |
| 2020 | +2.48% | -3.59% | +0.05% | +5.08% |
| 2021 | +9.44% | +8.96% | +11.09% | +11.46% |
| 2022 | -0.01% | -1.41% | -2.50% | -3.94% |
| 2023 | +3.42% | +3.88% | +4.81% | +7.48% |
| 2024 | +4.74% | +8.80% | +11.62% | +8.55% |
| 2025 | +5.89% | +5.89% | +5.44% | +7.56% |
| 2026 YTD | +5.32% | +6.40% | +6.21% | +5.31% |

## Closed D1 trades per annual combined portfolio

| Year | C3-original | ATR+%B<0.35 | ATR+%B<0.50 | ATR+%B<0.80 |
|---|---:|---:|---:|---:|
| 2017 | 0 | 0 | 0 | 0 |
| 2018 | 3 | 3 | 3 | 3 |
| 2019 | 5 | 8 | 12 | 23 |
| 2020 | 3 | 6 | 13 | 28 |
| 2021 | 9 | 11 | 15 | 20 |
| 2022 | 2 | 4 | 4 | 8 |
| 2023 | 8 | 11 | 14 | 21 |
| 2024 | 3 | 9 | 13 | 22 |
| 2025 | 5 | 5 | 7 | 14 |
| 2026 | 6 | 8 | 9 | 13 |

## Matched-year aggregate

| Variant | D1 trades | D1 PF | D1 win % | Mean annual return | Mean annual Sharpe | Worst-year DD | Better-return years vs baseline | 2x mean return (4 stress years) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| C3-original | 44 | 6.30 | 84.1% | +3.41% | 0.80 | -6.89% | 0/10 | +4.46% |
| ATR+%B<0.35 | 65 | 2.91 | 80.0% | +3.45% | 0.70 | -16.95% | 5/10 | +5.56% |
| ATR+%B<0.50 | 90 | 3.04 | 78.9% | +4.38% | 0.69 | -16.95% | 5/10 | +6.55% |
| ATR+%B<0.80 | 152 | 2.82 | 84.2% | +5.12% | 0.57 | -16.86% | 6/10 | +6.06% |

## Interpretation limits

- 2017–2026 has already been examined in earlier studies; all results are exploratory, not fresh out-of-sample.
- Win rate and profit factor above are for actual closed D1 positions inside the combined portfolio, not a standalone D1 with a different risk budget.
- 2026 ends Oct11; no exposures are carried across separate year-end resets.
- Expected costs: 1 bp commission and 2 bps slippage PER SIDE. True CFD ASK/broker spread, overnight financing and contract point value are not modeled.
- H1 first-minute protective stop gap remains unresolved. No candidate is production approved.
- A hypothetical product of annual returns is present in the JSON for illustration only; it is **not** a verified continuous multi-year backtest.
- The original ten-rule trial ledger remains complete or pending independently; do not discard negative trials.
