# Ming Che Lee (2025): On-chain + technical Temporal Fusion Transformer

**THESIS_CAPTURED — SOURCE_CAPTURE_ONLY.** Original article: https://doi.org/10.3390/systems13060474 . Inspected primary publisher paper, not trained model or historical data.

## Source-original mechanism

The paper trains a Temporal Fusion Transformer on daily cryptocurrency market, technical and on-chain/sentiment features (SOPR, TVL, active addresses, exchange flows, Realized Cap HODL Waves and Fear & Greed). It forecasts next-day closing prices and converts standardized expected returns into **buy/hold/sell directional signals**, equal weighting selected coins and resetting after one day. The five symbols are BTC, ETH, XRP, BNB and the stablecoin USDT. The author uses a fixed **0.2% round-trip fee**, **not** independently measured execution costs.

**Source-reported and unverified:** Aggregate strategy return 38.6%, Sharpe 1.06, max drawdown -22.4% over 2022–2024. TFT is compared to LSTM, GRU, SVR, XGBoost and naive momentum; the author's Sharpe annualization uses 252 days, unusual for 24/7 assets.

## Why not ATS-ready

The original strategy is not a long-top/short-bottom dollar-neutral ranking basket and cannot be silently adapted. Native return-rank ATS routing: **BLOCKED_PROTOCOL**. Current local OHLCV vault does not establish original on-chain historical releases (especially revisions and delayed publication), so **BLOCKED_DATA**. The paper executes at the same day's closing price used for the feature signal; unless earlier availability is shown, a next-open causal execution experiment changes economics. Missing frozen OOF model checkpoints and cost evidence imply **BLOCKED_SPEC**.

The paper's ~22% reported drawdown is not a plausible unchanged fit to a typical tight prop drawdown rule. Any 1h/15m crypto basket derived from these ideas is a separately labeled hypothesis, not source-original.

No funding-alpha premise, no model fitting, backtests, ATS stages, runner contact, protected reads or orders in this capture.
