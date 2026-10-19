# crypto_ml_celik_sefer_transaction_motif_btc_eth_2025_v1

**SOURCE_FACT:** Peker Celik and Emre Sefer, *Analyzing Transaction Graphs via Motif-Based Graph Representation Learning for Cryptocurrency Price Prediction*, published online 18 April 2025, journal issue 2026. Original open-access source: https://doi.org/10.1007/s10614-025-10940-1 . Source methods inspected 19 October 2026.

## Mechanism and author-tested scope
The original study builds **weekly BTC and ETH transaction-address graphs** from public blockchain data dated 2016–2024. Motif-convolution / graph-neural-network embeddings plus self-attention LSTM and Yahoo Finance daily BTC/ETH prices produce price and price-direction forecasts. Authors describe two-year training / next-year evaluation with annual rolling refits. **AUTHOR_TEST_UNVERIFIED:** The authors report better forecast error/direction metrics than price-only SVM/LSTM/HLSTM/GRU models, not execution or after-cost trading returns.

**LOCAL_INFERENCE:** Transacting wallet-network topology could capture changes in participant composition beyond simple transaction volumes. However, wealth concentration and wallet address change may drive spurious patterns. Weekly network updates are not available for trading until the corresponding source blocks are finalized and the graph snapshot computed.

**PROPOSED_ADAPTATION:** Only after as-of data availability and precise forecast horizon are resolved, compare source-informed ML against price persistence, price-only technical direction and **simple lagged weekly on-chain count/volume** at identical future price labels. Test point-in-time graph dictionary and feature preprocessing inside each training fold, chronological OOF predictions, label maturity, venue-executable fills and realistic cost sensitivity.

## Do-not-invent boundaries
**UNKNOWN:** Exact author executable label horizon, signal publication clock, trade side/threshold/size, venue product and backtested returns. No original basket or perps strategy exists. **BLOCKED_DATA:** Independent original wallet graph archives/corrections, price vintages and code unavailable. **BLOCKED_PROTOCOL / REQUIRES_TRAINING_WORKFLOW:** ATS cross-sectional IC/HAC is not a stand-in for a graph/LSTM trained model's OOF proof. This is descriptive source research, not MODEL_READY. No training, forecasts, experiments, protected reads or trading were performed.

Source document bytes not SHA-hashed; only capture-file SHA-256 evidence can be verified with the screening report.
