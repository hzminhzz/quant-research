# Systemic crypto liquidity stress: predictive risk alarm, not return alpha

Candidate ID: `crypto_ml_qiu_liquidity_crowding_alarm_2025_v1`.

**Primary:** Yimeng Qiu and Feihuang Fang, *A Multi-Layer ML–Econometric Pipeline for Forecasting Market Risk: Evidence from Crypto Liquidity Spillovers*. arXiv:2510.20066v1, October 22, 2025. https://arxiv.org/html/2510.20066

**SOURCE_FACT:** The authors use an engineered 1,462-day x 74-column daily panel (2021–2025; 74 is not established as the number of distinct cryptoassets) from Yahoo Finance/CoinMarketCap, select a Granger/PageRank central network including ETH, BTC, YFI, DOT, XEM, BNB, ARK, then predict a market-wide volatility-crowding risk state. Features include liquidity, Amihud, turnover, Parkinson/GARCH volatility, and principal components. Training/validation/test: 70/15/15 by time. This is not directional or cross-sectional return alpha.

**AUTHOR_TEST_UNVERIFIED:** XGBoost PR-AUC around 0.522 vs logistic around 0.44, but logistic ROC-AUC around 0.899 vs XGB around 0.74. Persistence/HAR-type models do better on some continuous risk targets. There is no source-proven after-cost trading benefit.

**Science blocker:** Source's H=10 risk-index formula uses **trailing inputs**, and the positive risk-class target's true forward outcome clock is not unambiguously specified. This handoff does not invent a 10-day-ahead class or imply risk known before its observation.

**LOCAL_INFERENCE:** Nonlinear liquidity stress between core assets could predict later fragility; simple volatility persistence is a serious null.

**PROPOSED_ADAPTATION:** Only with subsequent authorization, test an XGBoost risk veto to an independently defined trading rule, against a same-input logistic model, HAR/persistence, and fixed realized-vol threshold. Track false alarms and profitable trades wrongly vetoed, identical action time and costs; no returns simulated here.

**Prerequisites:** Recover original artifacts and true risk label direction, ensure train-only network/PCA extraction, prevent present-day asset survivor choice, retain chronological purged OOF and source-vintage provenance. BLOCKED_PROTOCOL / REQUIRES_TRAINING_WORKFLOW. No model training, predictions, SHAP, ATS Stage 1–4, data-return analysis, protected window or orders.
