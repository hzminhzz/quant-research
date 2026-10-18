# Tsoku & Makatjane (2026): Dynamic cointegration and learned spread forecasts

**THESIS_CAPTURED — SOURCE_CAPTURE_ONLY.** Original Frontiers article https://doi.org/10.3389/fams.2026.1749337 (30 January 2026), inspected in publisher HTML. No model training, OOF, IC, ATS stage, or trades.

## Source-original economic strategy

The paper combines rolling Johansen cointegration, hedge-weighted BTC/ETH/LTC/XRP pair spreads, DNN and LSTM forecasts, and a **dynamic weighted ensemble** of forecasts to identify mean-reversion entries. The authors' methodology lists six BTC/ETH/LTC/XRP combinations and daily Yahoo Finance prices from 2018-01-02 to 2025-10-31. The abstract inconsistently includes BNB and USDT among assets; we do not infer USDT is a shortable pair leg.

The model's hypothesized advantage is adapting to changing spread equilibrium, nonlinear corrections, and temporal dependencies, not funding or spot-perp basis capture. Original outputs describe forecasting accuracy and trading signals; publisher explicitly says **transaction costs, liquidity and execution friction were not represented**. All favorable findings are unverified source claims.

## ATS fit and controls

A dynamic two-leg hedge and pair-specific stateful convergence logic cannot be faithfully represented by the existing simple rank-plus-equal-count dollar-neutral allocator: **BLOCKED_PROTOCOL**. Daily source clock and Yahoo price series are not interchangeable with Binance USD-M perps or prop-firm CFDs: **BLOCKED_DATA/BLOCKED_SPEC**. No paper Sharpe is treated as actual prop performance.

The required non-ML falsifier is a rolling train-only Johansen/z-score pair strategy with the same hedge, sizing, costs and clock. OOF snapshots must demonstrate predecision cointegration and model weight estimation; future spreads cannot determine contemporaneous pair selection. This source has no funding-alpha dependence.
