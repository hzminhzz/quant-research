# YichengYang-Ethan: 355-crypto LightGBM 24h return decile spread

**SOURCE_CAPTURE_ONLY / THESIS_CAPTURED.** Original public code and methods: https://github.com/YichengYang-Ethan/crypto-return-prediction-kaggle ; notebook: https://github.com/YichengYang-Ethan/crypto-return-prediction-kaggle/blob/main/crypto_return_prediction.ipynb . Original repository README and file manifest inspected 2026-10-18. No dataset, notebook execution, fitted model or locally verified score.

## Exact author's approach
The Avenir HKU Web3 Quant competition project forecasts 24h forward returns across 355 cryptoassets using a LightGBM regression_L1 model with technical lagged momentum/volatility/volume features (RSI, MACD, ROC, bands, ATR, OBV, 1–5 bar lag returns). Five chronological TimeSeriesSplit fold models are averaged. The source README describes an **illustrative equal-weight long top-decile, short bottom-decile** predicted-return simulation; it compares forecast MAE against always-zero and last-return persistence baselines.

## Economic and validation caveats
The author says ML improves MAE; exact results require the original competition data, which the README explicitly says are not redistributable. Lower MAE is not after-cost alpha. Native source coin universe selection (including delistings), actual instrument type, feature bar sampling, prediction-to-fill clock, fees, spread, short availability, model calibration and correct historical fold-model snapshot replay are unknown. The 5-fold final ensemble must NOT be presumed OOF at all historical timestamps.

## ATS status
This source's actual decile long/short design is closer to the existing ATS scalar cross-sectional rank protocol than the other batch mechanisms, but only **descriptively**: data/label clock and executable specification are not established. Future comparison should fix the same PIT universe, rebalance, risk and execution costs and test a simple lagged-return rank baseline. Status **BLOCKED_SPEC** until source ambiguity resolved; no funding-alpha trading. Prop-firm contract set and daily-loss rules UNKNOWN.
