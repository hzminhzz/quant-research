# Hourly ML source discovery — 2026-10-19 18:46 Asia/Ho_Chi_Minh

**Scope:** source-only. No training, predictions, SHAP, empirical IC/HAC, backtest, ATS Stage 1–4, market-return panel/holdout reads or orders.

**Repository verification:** Main/origin/main `ce4eaf588608002c57e96a3e1639233df2047068`, 112 two-file handoffs, clean checkout. Local research worktrees and remote research refs enumerated. Task branch based on origin/main: `research/hourly_ml_crossmodal_20261019_b11` in independent managed worktree. Strict native validation `scripts/quant.py validate-handoff` is structural only. Former `research_capture.py` interfaces absent and not invoked. Native current ATS cross-sectional factory does not train model artifacts or independently qualify general event/risk classifiers.

## 20 source identities screened and classified

Classes: NEW_DESCRIPTIVE is a **candidate**, not an independent alpha replication; MAIN_DUP means mechanism/source already captured on main; REMOTE_DUP means source captured in separate branch; DEFER includes insufficient incremental ML mechanism, thin source economics, adverse cost evidence, or unrealistic source data.

| # | Source (URL, author/year) | Decision and evidence |
|---|---|---|
| 1 | Li et al. (2026), https://doi.org/10.1016/j.pacfin.2025.103033 | NEW_DESCRIPTIVE. Cross-sectional return ranking, MVRV x address-adoption nonlinear interactions; journal abstract only, full methods unavailable. |
| 2 | Sak (2026), https://dergipark.org.tr/en/pub/joeep/article/1837177 | NEW_DESCRIPTIVE. BTC whale-attention event interactions, original event study NOT ML/trading. |
| 3 | Qiu/Fang (2025), https://arxiv.org/html/2510.20066 | NEW_DESCRIPTIVE. Cross-asset liquidity-vol risk alarm, original **not return alpha**; trailing H=10 risk-label clock unresolved. |
| 4 | Guidolin/Ionta (2026), https://doi.org/10.1016/j.intfin.2026.102285 | REMOTE_DUP. `origin/research/crypto-source-intake-20261018-run11`, captured predictability-sort thesis. |
| 5 | Anastasopoulos et al. (2026), https://doi.org/10.1016/j.finmar.2026.101047 | MAIN_DUP. International multi-fiat signed order-flow ML crypto rank. |
| 6 | Mercik et al. (2025), https://doi.org/10.1016/j.irfa.2024.103809 | MAIN_DUP. Non-additive crypto past-return/liquidity/risk interactions. |
| 7 | Cakici et al. (2024), https://doi.org/10.1016/j.irfa.2024.103244 | MAIN_DUP. Crypto cross-sectional multi-characteristic ML. |
| 8 | Tsoku/Makatjane (2026), https://doi.org/10.3389/fams.2026.1749337 | MAIN_DUP. Dynamic cointegration ML-pairs relative value. |
| 9 | Pindza (2026), https://doi.org/10.3389/fbloc.2026.1811716 | DEFER_ADVERSE. Five-minute microstructure model gross-vs-net costs; no new credible incremental tradable ML thesis. |
| 10 | Pindza/Mba (2026), https://link.springer.com/article/10.1007/s10690-026-09637-8 | DEFER. Risk contagion Hawkes/DCC, overlaps risk-only family; no independently verified incremental basket outcome. |
| 11 | Bieganowski/Ślepaczuk (2026), https://arxiv.org/abs/2602.00776 | DEFER. Second-resolution order book forecasting, incompatible source data/timing and costs. |
| 12 | Zwydak et al. (2026), https://arxiv.org/abs/2607.13916 | DEFER. Trade count anomaly, source data integrity not new return predictor. |
| 13 | Shynkevich (2026), https://doi.org/10.1002/fut.70089 | DEFER. Seasonality, insufficient incremental ML economic mechanism. |
| 14 | Kroner et al. (2026), https://doi.org/10.2139/ssrn.6447644 | DEFER. Fast macro news crypto response, clock and fill parity unresolved. |
| 15 | Xue/Zhou (2026), https://doi.org/10.1016/j.jbankfin.2026.107750 | REMOTE_DUP. `origin/research/hourly-ml-source-xue-20261018-b12` contains source-matching two-file thesis. |
| 16 | Benedetti et al. (2026), https://doi.org/10.1016/j.iref.2026.104912 | DEFER. Stablecoin/return connectedness; no source-proven incrementally trained return basket. |
| 17 | Xiao/Chen (2026), https://link.springer.com/article/10.1007/s41109-026-00778-3 | DEFER. Information network, insufficient tradable baseline parity. |
| 18 | Wang/Xiao et al. (2026), https://doi.org/10.3390/math14081286 | DEFER. Cross-chain zero-shot forecasts, limited after-cost portfolio evidence. |
| 19 | Wang/Huang (2026), https://doi.org/10.1080/08839514.2026.2612793 | DEFER. Hybrid SVR forecasting lacks verified as-of venue and cost advantage. |
| 20 | CoinQuant practitioner (2026), https://www.coinquant.ai/blog/best-crypto-trading-strategy-in-2026-backtested-and-ranked | DEFER/BENCHMARK. BTC simple strategy baselines only; not incremental model evidence. |

**Counts:** 20 screened = 3 new descriptive, 4 main duplicates, 2 remote duplicates, 11 deferred/adverse. Source URLs are provenance **identifiers**; full original publisher documents were not byte-hashed. Remote branch matches were checked from Git refs, while untracked concurrent local research drafts cannot be declared exhaustively absent. No result of a new experiment is claimed.

## Deepening and decision contract

**Li et al.:** Original cross-sectional multi-coin forecasting (horizon/venue/weights UNKNOWN from abstract), not a fictional top-K perps basket. SOURCE_FACT 12 models, on-chain MVRV/address inputs; AUTHOR_TEST_UNVERIFIED RF best forecast but NN highest portfolio cumulative return. LOCAL_INFERENCE nonlinear interaction; PROPOSED shallow RF versus MVRV-only return ranks and same-feature Ridge; requires PIT address/MVRV vintages, recovered original label/fill/fit clocks, survivor-free universe, cost-matched basket and matured-label OOF.

**Sak:** Original BTC-only observational event study, horizons 1/7/14/28 calendar days, 2018–2025. AUTHOR_TEST_UNVERIFIED whale/attention return differences; no executable PnL. PROPOSED future event meta-label with fixed whale-only/Google-only and logistic interaction baseline. No basket; BLOCKED_DATA/PROTOCOL. Need historical top-100 wallet membership, Trends refresh revisions, actual event and trade clocks, and event-purged OOF.

**Qiu/Fang:** Original daily crypto **market-wide risk** and liquidity-crowding alarm; engineered 1462x74 **columns** not established 74 distinct assets. AUTHOR_TEST_UNVERIFIED XGB PR-AUC 0.522 vs logistic ~0.44; logistic higher ROC and F1, persistence superior in some levels. Published ten-day risk index formula uses TRAILING features, true prospective forecast target not reconstructed. PROPOSED optional veto to an independent base strategy only; compare same-input logistic, HAR/persistence and volatility threshold with missed-opportunity costs; NOT return alpha. BLOCKED_PROTOCOL until label clock and train-only network/PCA proven.

## Scientific and publication controls

No funding, basis, or carry as alpha feature. These are **HANDOFF_VALID_UNVERIFIED** only after native validation, otherwise source captures. Full native model training, OOF predictions, preprocessing provenance and chronological purging are independent future prerequisites. At source level, `SOURCE_FACT`, `AUTHOR_TEST_UNVERIFIED`, `LOCAL_INFERENCE`, `PROPOSED_ADAPTATION` and `UNKNOWN` are not interchangeable. File SHA-256 proves only artifact bytes, not primary publisher bytes, source methodology parity or economic viability. Not MODEL_READY. No protected data touched and no trading authority.
