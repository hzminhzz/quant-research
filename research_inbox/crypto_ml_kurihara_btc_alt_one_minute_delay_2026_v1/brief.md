# crypto_ml_kurihara_btc_alt_one_minute_delay_2026_v1

## Source identity and boundaries
**SOURCE_FACT:** Kurihara and Matsumoto, *Price Transmission from Bitcoin to Altcoins: High-Frequency Evidence and Implications for Trading Strategy*, *Asia-Pacific Financial Markets*, published 10 March 2026, https://doi.org/10.1007/s10690-026-09589-z . Original publisher HTML inspected 2026-10-19. The source studies Binance-API **one-minute BTC-to-individual-altcoin** delayed responses with explicit focus on low-trade-count QKC, GNO, PIVX, CITY and BIFI. Product class, true real-time order prices, and historical bid/ask execution availability remain **UNKNOWN**. It is **not** a cross-sectional long/short strategy.

## Source claim versus incremental ML hypothesis
**SOURCE_FACT:** The paper supplies one-minute lagged BTC and altcoin log returns as a two-variable input to distinct LightGBM entry/hold binary classifiers. Each model predicts whether the next one-minute individual-altcoin return exceeds its threshold; when flat use entry decision, when long use hold decision. First about three regime weeks provide threshold selection, last week OOS. Author studies four dated regimes but source trading results highlight bull, sideways and crash. **AUTHOR_TEST_UNVERIFIED:** Authors report better simulated returns than buy-and-hold in low-trade-count altcoins, weakest in sideways regimes. The paper does **not** demonstrate incremental ML benefit versus a simple BTC-lag sign/threshold strategy; it charges modeled turnover fees, not audited bid/ask fills.

**LOCAL_INFERENCE:** Extremely low trade counts plausibly cause stale trade prices. The identified one-minute delayed response may be statistical but impossible to monetize without fills before the stale quote adjusts.

**PROPOSED_ADAPTATION:** Future independent scientific test, with the same source instruments/one-minute clock, would compare the paper's entry/hold LightGBM to (a) a signed BTC-lag threshold, (b) a fixed stateful long/flat hysteresis rule, and (c) regularized logistic regression on the exact same two lagged returns. Evaluate with point-in-time trade-count universe, next-executable bid/ask, costs, and continuous chronological purged OOF train/refit forecasts; do not invent a basket, long/short conversion, 5m holding horizon, source execution contract or feature cutoff.

## Scientific stop
**UNKNOWN / BLOCKED_DATA:** independent historical executable prices, Binance market/product pair IDs, same-minute bar close availability, listing universe.
**BLOCKED_PROTOCOL:** current ATS cross-sectional IC/HAC route is not a certified general inventory-sensitive entry/hold model validator. **REQUIRES_TRAINING_WORKFLOW:** fold-purged chronological OOF predictions, fold-local preprocessing and point-in-time source records are prerequisites. The native `validate-handoff` command, if passed, grants only `HANDOFF_VALID_UNVERIFIED` structural admission. No source document bytes were SHA-hashed. No training, model outputs, holdout reads, Stage 1–4, cost simulations or orders were performed.

Source-provenance anchor: https://doi.org/10.1007/s10690-026-09589-z . Research artifact SHA-256 values are recorded in the accompanying source-screening evidence file outside this two-file directory.
