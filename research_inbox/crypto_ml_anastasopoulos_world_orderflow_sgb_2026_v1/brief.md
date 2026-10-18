# Anastasopoulos et al. (2026): International order-flow ML crypto return ranks

**THESIS_CAPTURED — SOURCE_CAPTURE_ONLY.** Original open-access journal article: https://doi.org/10.1016/j.finmar.2026.101047 . Reviewed author methodology and reported economics, not their original data or code. All results below are **SOURCE_REPORTED_UNVERIFIED**.

## Original strategy and economic thesis

Global order flow is defined using buyer- versus seller-initiated trading volumes in **11 fiat currencies**, reflecting geographically heterogeneous information arrival and persistent price discovery. The authors use cross-sectional daily crypto data and forecast next-day returns with nonlinear ML (RF, stochastic gradient boosting, neural nets), plus linear variants and forecast combinations. Their portfolios are **long top predicted-return quintile and short bottom quintile**, with a long-only alternative. Their original sample contains 84 cryptoassets; source describes a 2020–2022 forecasting OOS window.

The paper attributes incremental predictability to international order-flow patterns beyond lagged returns/fundamentals. It reports SGB OOS R2 near 0.39%, long-short annualized Sharpe 3.68 (nonlinear combination 3.61), and meaningful turnover/cost limits. None of these figures are verified local performance, actual prop-firm returns or an independently reproduced after-cost strategy.

## ATS/ML scientific boundary

**Most promising original-source long/short ML candidate of this batch, but BLOCKED_DATA for exact replication.** The local Binance USD-M OHLCV panel does not contain 11-currency historically time-stamped initiated-trade flows. Substituting a one-exchange taker-volume proxy changes the economic mechanism and must be labeled a new adaptation. A frozen model requires train-only scaling, chronological fitted-model snapshots and prediction-time availability. Same-data training IC is not scientific OOF evidence.

Current ATS supports return ranks and fixed long/short baskets but not source-equivalent data/execution by assumption. Source's daily quintiles, contract identity, prop-firm shorts, financing, spreads and trader account constraints require explicit future verification. No funding-alpha dependency.

**Falsifier if separately authorized:** conditional international order-flow nonlinear forecasts do not improve PIT ranking and after-cost economics over a linear flow model and lagged-return baseline. No training, testing, optimizer or ATS runner interaction occurred.
