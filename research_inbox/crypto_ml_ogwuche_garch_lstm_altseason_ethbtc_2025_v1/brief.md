# Ogwuche, Liew and YLim ee: GARCH-attention-LSTM ETH/BTC pair and regime filter

**SOURCE_CAPTURE_ONLY · THESIS_CAPTURED.** Primary indexed abstract https://ssrn.com/abstract=6554918; written June 30, 2025 and SSRN listing posted April 20, 2026. Source abstract examined; not a full-paper replication.

The source proposes a long/short ETH/BTC pair-trading model combining GARCH/EGARCH volatility dynamics, an attention LSTM and an Altcoin Season Index regime-switching filter. The mechanism is time-varying correlations/volatility and conditional mean-reversion or divergence. It is **not** a fixed top/bottom crypto rank, does not explicitly use funding as alpha, and it is not source-proven profitable.

### Novelty and sharp blockers
Different from the previously captured Tsoku multi-asset Johansen-cointegration DNN/LSTM ensemble: this method centers on ETH/BTC conditional variance and explicit season-regime conditioning. However, it shares the pairs-trading family and is low priority until exact hedge/time/entry rules are available. The historical Altcoin Season Index methodology/timestamp is an extra point-in-time data blocker. Generic ATS cross-sectional IC/ATR stops cannot represent the stateful pair.

### Future tests (not run)
Reconstruct actual source rules and compare to a causal rolling ratio-z-score pair with matched costs; test train-only GARCH/LSTM fitting and temporal filters, two-leg execution, weekend/prop limits. Source provides no verified after-cost Sharpe or exact threshold; no model training, simulator, runner or protected data reads occurred.
