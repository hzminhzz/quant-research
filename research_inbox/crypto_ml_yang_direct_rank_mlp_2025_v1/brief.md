# Yang (2025): Direct neural rank prediction for long-only crypto portfolios

**THESIS_CAPTURED / NOT EXECUTABLE.** Source-specific limitations prevent treating this as a ready ATS strategy.

Primary author manuscript `https://arxiv.org/abs/2512.08124`. Zijiang Yang (9 December 2025). Paper HTML sections III-C, III-D and IV read directly.

## Author's exact high-level workflow

Daily 10-coin portfolio, extracting prior return, training-window volatility, Sharpe and rank correlation. Predict **next-day cross-sectional return rank** (also experimenting with ranks squared/cubed/fourth power). A two-hidden-layer MLP with 20 units per layer maps historical coin features to relative forecasts. Algorithm 1 shows 80-step trailing model window and updates every 10 steps. Outputs become normalized **long-only** weights with decay (alpha 0.7, one lag in the paper). Study reports a 1.01 Sharpe and 64.26% annualized return; those are author's own results, not independently reproduced.

## High-impact limitations

The paper explicitly chooses the **top 10 coins as of November 1, 2023** and uses them throughout a test beginning in May 2020. That is an ex-post survivorship/selection problem. A varying PIT set would also change the neural output shape, potentially invalidating fixed-universe model design. The source does not use dollar-neutral or short-legged positions. Model-prediction chronology and trading fills require more validation.

## ATS relevance

Novel *target engineering* for direct relative ranks, distinct from absolute-return regressors; technically interesting but original source is **BLOCKED_PROTOCOL** for ATS's current dollar-neutral top/bottom allocator. The problem of fair dynamic historical membership is unresolved. A separate long/short adaptation is not this paper's strategy.

No funding-rate signal, model training, performance test or protected data read. Future comparison must benchmark lagged relative momentum on identical genuinely PIT coin membership and real broker fees.
