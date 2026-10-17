# Four promoted strategies — shared-portfolio evidence reconciliation (2026-10-17)

**Research finding: VERIFIED EXPLORATORY PORTFOLIO FEASIBILITY.** This reconciles the four-stream October 17 candidate-specific execution audit with the earlier October 14 capital-allocation experiment. It does **not** issue paper/live trading clearance, certify a prop account, or rerun the strategies.

## Earlier evidence that must not be overlooked

The original checkout already contains:
- `docs/audit/allocation_b0_continuous_20261014.md`: continuous 2013-2024 **native Engine** B0 account and marked equity, not solely its older annually reset reports. Still lacks atomic OCO and intraminute price path.
- `docs/audit/allocation_c3_continuous_20261014.md`: continuous 2013-2024 **native Engine** C3 account, carrying cross-year open positions. Still lacks broker spread, financing and contract translation.
- `docs/audit/allocation_btc_funding_resolve_20261014.md`: signed 2019-2024 BTC funding fixed-fill overlay, mostly price-proxy settlements, not native funding-aware execution.
- `docs/audit/multi_strategy_allocation_development_report_20261014.md`: preregistered four-strategy allocator research using 64 actual observed month marks, 63 intervals, and 36 chronological 2022-2024 evaluation months. No 2025-2026 allocator test opened.

This **supersedes any blanket claim** that no continuous-account B0 or C3 replay exists. The narrower October 17 statement remains true: the historical **promoted packages** themselves are not fully broker-grade, and neither the existing continuous paths nor the portfolio experiment grant ATS7/B0/CFD/prop-firm execution authorization.

## Saved native-development portfolio outcomes, 2022-2024

| Allocation | Net Sharpe | Monthly-mark maximum drawdown | Net compound return | Annualized volatility |
| --- | ---: | ---: | ---: | ---: |
| Monthly equal-weight 25%/sleeve | 0.969 | -5.09% | +24.95% | 8.00% |
| Inverse-vol (40% per-sleeve cap) | 1.787 | -1.02% | +8.94% | 1.61% |
| ML4T linear (one preregistered fit family) | 0.941 | -5.49% | +25.10% | 8.31% |

The preregistered linear allocator **failed** versus equal-weight: net Sharpe difference -0.028 and 0.40 percentage points deeper monthly mark DD. That is NOT a finding against the profitability of all four source strategies or a rejection of diversified portfolios.

## Independent descriptive covariance recheck

Recomputed directly from the immutable, observed `monthly_observed_panel.csv` in the original checkout; 36 monthly returns for 2022-2024. This is a covariance diagnostic on published return observations, not a replacement backtest.

| Pair | Monthly Pearson correlation |
| --- | ---: |
| B0 / C3 | -0.009 |
| B0 / BTC | +0.191 |
| B0 / RSI | -0.179 |
| C3 / BTC | +0.158 |
| C3 / RSI | +0.569 |
| BTC / RSI | -0.110 |

**Important concentration:** with 25% capital in each strategy, BTC contributes approximately **96.3%** of portfolio return variance (C3 2.6%, B0 0.8%, RSI 0.3%). The inverse-vol baseline actually assigns **0% capital to BTC in all 36 evaluation months**, with mean allocations B0 40.0%, C3 32.2%, RSI 27.8%. Its lower drawdown is therefore substantially an exposure-removal result, not proof of diversified returns across all four strategies. The sample has only 36 observed monthly results, and correlations may increase in joint stress.

Maximum drawdowns here are based on **monthly observed portfolio marks**; they cannot establish an intraday/daily account-loss maximum or prop-firm survival. Source account valuations, actual spread, funding settlement proxy, CFD swaps, collateral and portfolio capital-transfer execution remain caveated.

## Independent verification performed October 17

- Independently reran `tests/test_allocation_development_20261014.py`, `tests/test_allocation_b0_continuous_20261014.py`, and `tests/test_allocation_c3_continuous_20261014.py` from the original checkout with installed Python and without writing bytecode or pytest cache: **22 passed**.
- Recomputed pairwise Pearson correlation, monthly realized volatility, inverse-vol mean weights and equal-capital variance contributions from the existing 2019-2024 panel and 2022-2024 allocation ledger, using **only recorded pre-2025 development returns**.
- No new source-strategy re-optimization, new allocator configuration, shadow orders, broker orders, or protected 2025-2026 allocator outcomes.

**Decision:** All four retain `PROMOTED_FOR_FURTHER_RESEARCH`. Their **portfolio-level diversification is a verified exploratory research finding**. The next qualification should target a frozen **shared-account, intraday risk and true cost study** with existing native features/engine, not another Sharpe-optimized model. Candidate ATS2/4/5/6/7 trading-release status stays separately blocked/inconclusive as documented.
