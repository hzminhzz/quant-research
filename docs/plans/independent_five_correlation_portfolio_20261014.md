# Independent five: correlation and diversified portfolio assessment

Date: 2026-10-14. State: PRE-RESULT ANALYSIS PLAN.
Source: user-provided `portfolio.py` from the Shannon-20 package.
These five independent strategies are NOT Shannon components.

## Research question
Can five independently executed native ML4T strategy returns form a
diversified portfolio, without choosing the highest absolute-return sleeve?

Frozen five (no selection changes): pivot-breakout-btc, donchian-btc,
three-red-spy, slope-hook, rsi-30-50.

## Evidence and alignment
Read only verified native engine `equity.csv`, `summary.json` and
`manifest.json` under `run_log/independent_five_full_history_20261014/`.
Do not rebuild prices or alter standalone strategies. Verify file hashes,
native final account equity, and timestamp chronology.

Use 2020-01-01 through the latest common ES completed session, strictly
before 2026-10-12 protected boundary. Derive percentage returns from
native equity, NOT dollar PnL or equity levels.

Primary calendar = business days (as in supplied Shannon `portfolio.py`).
BTC Saturday/Sunday net equity changes are compounded into the next
business day (not dropped or simply summed). ES missing calendar weekdays
are zero-return/unchanged sleeve equity, flagged as assumptions.
Use all business days for unconditional pairwise correlation.
Also report both-active-day correlations where count is adequate, and
co-activity rate and 252-business-day rolling correlations.
Secondary robustness: full UTC calendar-day correlations with weekends
retained for BTC, ES held flat. Daily BTC and New York ES session close
clock are different; calendar alignment is a proxy, not synchronized PnL.

## Portfolio comparison
Use final native after-cost daily sleeve returns. This is downstream
`ml4t.diagnostic.api.PortfolioAnalysis` diagnostics, NOT an additional
broker execution simulation or live combined margin account. No
transaction-cost-free backtest claim.

Freeze these non-return-optimized allocations before examining correlation:
- EW-5: 20% each of all five sleeves
- Market-bucket equal: 50% BTC split 25%/25%, 50% ES split 1/6 each
- Market-bucket inverse-vol: 50% BTC group and 50% ES group.
  Within each group allocate inverse realized standard deviation from
  2020-2022 development only; deterministic max 35% per sleeve,
  redistribute any excess within the same group.
- RSI only: reference benchmark, not portfolio recommendation.

Daily weighted-return aggregation emulates the Shannon file's DAILY
REBALANCE rule with no portfolio-layer rebalancing cost. Report this
explicitly as a *gross-of-extra-rebalancing-cost analytical overlay*,
although all underlying strategy returns are native after modeled
per-strategy fees. Overlay allocations are not native broker-run proof
and may require more turnover, financing, and capital than represented.
Compare static initial-capital sleeve ownership separately if practical.

Score total/common-sample and chronologically 2020-22 versus 2023-25
versus 2026 YTD (already observed, NOT untouched OOS); report
Sharpe, CAGR, MDD, CVaR95, Calmar, positive months and
2020-22 trained weights and risk contributions. Also calculate
same-market factor concentration and outcome under removing a sleeve
as exploratory diagnostics, but do not reselect after seeing output.

## Post-initial diagnostic addition (exploratory; not pre-registered)

The initial equal-capital portfolio revealed ~92% of variance from
two BTC sleeves. The positive Sharpe comparison should not be treated
as a risk-diversified solution. Additional fixed-rule candidate:
- **Market-group inverse-vol risk**: within BTC equally weight the
  two sleeves and within ES equally weight the three sleeves. Compute
  the **two group portfolio volatilities** from ONLY 2020–2022.
  Allocate capital inverse to group volatilities, then divide equally
  inside the group. No Sharpe, returns, or future covariance used
  to choose weights. Maximum 35% sleeve cap; reject infeasible.
  This is a *post-observation exploratory sensitivity*, not
  prospective confirmation.

Report the risk share and native-analysis metrics for this variant,
alongside a static initial capital comparison that does not need
daily cross-sleeve rebalancing.

## Post-initial cost sensitivity (exploratory, not preregistered)

The five prior standalone stress results indicate Three Red and Slope
are cost-sensitive. The balanced allocation has high ES capital weight.
For interpretability, rerun all five **native Engines**, with the exact
frozen prices, signals and strategy classes, at 2x and 3x the original
commission and slippage. Keep baseline portfolio weights unchanged.
Combine each scenario's *native stressed sleeve equity returns* using
the same business-day calendar. Compare EW-5 and group-risk-balanced
portfolio overlays (daily rebalanced and static initial capital).
Portfolio-rebalance extra execution fees remain unmodelled.
Record every cost trial including adverse outcomes.
This is explicitly AFTER initial portfolio analysis.

## Completion gates
- Five inputs, complete joint calendar and zero silent missing returns
- Correct compounded BTC weekend mapping and separate UTC-calendar audit
- All metrics via native ML4T PortfolioAnalysis where supported
- Matrix symmetric, diagonal = 1, nonzero exposure/activity counts
- 2020-22 inputs only for inverse-vol weights; weights frozen later
- Portfolio daily overlay return = sum(weights * signed sleeve returns)
- Saved correlation/weights/portfolios/summary + independently checkable tests
- No promotion or claim of statistically confirmed diversification

Known caveats: All five were pre-selected by 2020-2022 Sharpe.
Two strategies trade BTCUSDT perps, three trade the same ES proxy
rather than actual SPY. Funding, CFD financing, ETF dividends
and combined account interaction are absent.
