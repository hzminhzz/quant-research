# Mechanical Premia: Three-candidate annual ROI and ML4T tearsheet (2013–2026 YTD)

**Source:** completed research output: `docs/audit/mechanicalpremia_three_candidates_2013_2026/{summary.json,all_annual_metrics.csv,tearsheet.html,linked_roi_diagnostics.json}` in `/home/quant/dev/quant/quant-research`.

**Native evidence:** 252/252 ML4T Engine annual cells verified; C2/C3 terminal trials 7/7 completed, NOT_APPROVED. C1 original frozen prior results used as baseline.

## Instrument universes

- **C1 Original:** H1 US500/US100/DE30; D1 US500/US100/DE30/EU50
- **C2 Japan:** H1 US500/US100/JP225; D1 US500/US100/JP225/EU50
- **C3 US-only:** H1 and D1 both US500/US100

All portfolios use nominal H1 risk weight 23.36% and D1 risk weight 76.64%. The one-percent total risk budget is split equally among available assets within each sleeve. Original NY17 calendar and feature rules remain unchanged. 1x assumed direct costs: 1bp commission plus 2bps slippage **per side**.

## Annual native returns, independently reset synthetic 100k account

| Year | C1 Original | C2 JP225 | C3 US-only |
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
| 2026 YTD (through Oct 11) | +3.20% | +4.07% | +5.32% |

## Illustrative chained ROI from full-precision annual results

Formula: `ROI_linked = product(1 + each_native_year_return) - 1`.

| Metric | C1 Original | C2 JP225 | C3 US-only |
|---|---:|---:|---:|
| Linked ROI through 2025 | +23.03% | +26.49% | +42.57% |
| Linked ROI through Oct 11 2026 | +26.97% | +31.65% | +50.15% |
| Artificial final NAV from 100,000 units | 126,965.60 | 131,645.06 | 150,152.56 |
| Approx. annualized linked return | 1.75% | 2.02% | 2.99% |
| Hypothetical linked ROI at 1.5x direct costs | +13.09% | +17.66% | +32.62% |
| Hypothetical linked ROI at 2x direct costs | +0.72% | +5.16% | +17.12% |

**IMPORTANT:** These are only hypothetical links of independent annual native simulations. The backtest did not implement annual compounding, transfer/carry open positions across years, or broker-grade USD PnL accounting. These numbers **MUST NOT** be represented as a true 14-year realized portfolio ROI, CAGR, or investable strategy return.

## Native risk and trading metrics

| Metric | C1 Original | C2 JP225 | C3 US-only |
|---|---:|---:|---:|
| Average annual native return | +1.75% | +2.02% | +2.99% |
| Profitable years | 10/14 | 10/14 | 10/14 |
| Mean native annual daily-equity Sharpe | 0.50 | 0.64 | 0.66 |
| Worst native single-year max drawdown | -6.60% | -11.77% | -7.83% |
| Closed trades (all years) | 2,118 | 2,138 | 1,405 |
| Closed trade win rate | 37.8% | 39.9% | 38.9% |
| Year-end open-position occurrences | 11 | 12 | 3 |
| Mean annual net return, 2x direct costs | +0.07% | +0.39% | +1.17% |

## ML4T tearsheet: linked daily account approximation

Generated using `ml4t.diagnostic.api.PortfolioAnalysis` applied to daily-linked native equities and the ML4T tearsheet guidance. Calendar-day risk metrics annualized at 365, not the previous native annual-report 252 convention.

| Linked-proxy-only risk measure | C1 | C2 | C3 |
|---|---:|---:|---:|
| Illustrative daily Sharpe | 0.57 | 0.62 | 0.75 |
| Illustrative linked max DD | -6.60% | -11.77% | -7.83% |
| Illustrative Sortino | 0.86 | 0.92 | 1.13 |

The tearsheet includes:
- Annual verified native net returns
- Monthly heatmap of daily-linked proxy returns
- Hypothetical linked NAV and drawdown
- Native trade counts, win rate and cost sensitivity

**VPS full HTML report:**
`docs/audit/mechanicalpremia_three_candidates_2013_2026/tearsheet.html`

**Scientific interpretation:** C3 leads on synthetic profitability and shows better performance than C1 in 11/14 annual paired comparisons. But C1 had better worst single-year DD, and C3 has only 2/14 individual years with better drawdown than C1. C2/C3 selection occurred after observing historical outcomes. No fresh OOS validation remains in the 2013–2026 tested period.

**Critical qualification blockers:** Actual CFD BID/ASK spreads, rollover financing, contract multiplier/lot size, FX conversion for EUR/JPY instruments, exact broker market sessions and the H1 initial STOP placement gap. No broker-executable 14-year ROI is verified. No live orders placed.
