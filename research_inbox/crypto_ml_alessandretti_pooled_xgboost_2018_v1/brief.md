# Alessandretti et al. (2018) Method 1: pooled XGBoost crypto return forecasts

**THESIS_CAPTURED / descriptive source only**; no model training, IC, backtesting, holdout or orders.

Source: Alessandretti, ElBahrawy, Aiello & Baronchelli, *Complexity* (2018), `https://onlinelibrary.wiley.com/doi/10.1155/2018/8983590`. Original publisher HTML methodology and portfolio construction inspected.

## What the authors actually tested

From CoinMarketCap daily histories across 1,681 coins in 2015–2018, Method 1 trains **one pooled XGBoost regressor** on each coin's lagged price, market cap, relative market share, rank, volume and ROI summaries (mean, volatility, median, last, trend). Forecast next-day coin return expressed relative to BTC. At each forecast date invest **equally in top n predicted positive-return coins, long only**, with historical parameter selection; comparison is to a simple moving-average forecast. The authors report positive BTC-denominated backtest results at several assumed transaction fee levels. Results were not independently replicated.

**Not source facts:** dollar neutrality, shorting low-ranked forecasts, 1h rebalance, Binance perpetual data, frozen end-to-end training procedure. Method 2 coin-specific XGBoost and Method 3 LSTM are separate designs and not part of this capture.

## ML improvement claim and concerns

A pooled model can learn shared conditional patterns despite sparse history per coin, but the 2016–2018 bull-era sample, historical coin-market-cap inputs, hindsight parameter adjustment and modeled execution are material limitations. Local 1h perps lack proven historical market-cap/rank fields and have different tradability.

## ATS fit and stopping

Literal original long-only design is **BLOCKED_PROTOCOL** by current ATS dollar-neutral long/short allocator. A separate local basket adaptation could be proposed, never presented as an original reproduction. Require PIT coin history, trained chronology with purged OOF forecasts, source-specific market cap fields, and a transparent linear/MA benchmark before any future scientific evaluation. Excludes funding-derived signal.
