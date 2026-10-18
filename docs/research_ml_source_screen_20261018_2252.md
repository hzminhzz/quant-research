# ML source-discovery screening — 2026-10-18 22:52 ICT

**Authority:** source-only. Sources reviewed at title/abstract/README depth unless explicitly noted; no empirical runs or user market history read. Actual Git observations: remote main `37a6e5a5b21edd5d306f58914e454b0f097450cd` with 112 tracked thesis pairs; local main `49c0d70f21518e0963780b6b3c93f0ec7afe93e0` is ahead three commits and has unrelated untracked candidate (left untouched). The isolated source worktree started detached at `37a6e5a5`. The historical `research_capture.py` interfaces are absent; the current two-file `quant.py validate-handoff` is used. Other local and remote research branch refs were inventoried.

## Screened source identities (22)

Each item is independently identifiable; screening does not imply a full-paper replication.

| No. | Original source | Mechanism / decision |
|---|---|---|
| 1 | Saidane & Ben Mohamed (2026), [Wiley](https://doi.org/10.1002/for.70159) | **CAPTURE:** joint six-coin regime-conditional VaR/ES; after-cost risk-averse allocation SOURCE_REPORTED_UNVERIFIED. Not return alpha; BLOCKED_PROTOCOL. |
| 2 | Guo, Sang, Tu & Wang (2021), [SMU](https://ink.library.smu.edu.sg/lkcsb_research/6901/) | DEFER/DUPLICATE_FAMILY: Binance minute lagged cross-coin returns, adaptive LASSO/PCA; source reports 2.16% average daily net OOS (unverified). Substantial prediction target, model and information-set overlap with already captured Jia rolling LASSO and crypto spillover family. Distinct sign cannot be inferred without full paper; avoid cloning. |
| 3 | Jia, Wu, Yan & Liu (2023), [publisher](https://doi.org/10.1016/j.jempfin.2023.101428) | DUPLICATE existing `crypto_ml_jia_seesaw_rolling_lasso_2023_v1`. Large-to-small negative lead-lag. |
| 4 | Cakici et al. (2024), [publisher](https://doi.org/10.1016/j.irfa.2024.103244) | DUPLICATE existing multi-characteristic ML cross-section; paper finds simpler models competitive and illiquid-asset concentration. |
| 5 | Zijiang Yang (2025), [arXiv](https://arxiv.org/abs/2512.08124) | DUPLICATE existing neural direct return ranking; long-only original, not short basket. |
| 6 | Yicheng Yang (2026), [GitHub](https://github.com/YichengYang-Ethan/crypto-return-prediction-kaggle) | DUPLICATE existing HKU LightGBM 24h forecast family. |
| 7 | IliassSjm (2026), [GitHub](https://github.com/IliassSjm/crypto-perps-alpha) | PRIOR SCREENED/OVERLAP: hourly cross-sectional Ridge/XGB, short-lived high-turnover edge, execution cost defeat and opaque external feature provenance. |
| 8 | cengizmandros (2026), [GitHub](https://github.com/cengizmandros/crypto-ml-trading-research) | DUPLICATE existing HMM-conditioned ensemble/return-rank family, with adverse final holdout evidence. |
| 9 | Anastasopoulos et al. (2026), [publisher](https://doi.org/10.1016/j.finmar.2026.101047) | DUPLICATE existing world order-flow ML source; original international flows cannot be replaced by made-up Binance taker-flow proxy. |
| 10 | Bieganowski & Ślepaczuk (2026), [arXiv](https://arxiv.org/abs/2602.00776) | PRIOR CAPTURE/STAGED family: 3-second L2 CatBoost, protocol/cost mismatch. |
| 11 | Fabre & Muni Toke (2024/25), [arXiv](https://arxiv.org/abs/2401.09361) | REJECT trade alpha: neural Hawkes estimates event-rate excitation and causal network; no tradable return-position mapping established. |
| 12 | Shukla, Peyyala & Chakraborty (2026), [arXiv](https://arxiv.org/abs/2606.25466) | REJECT trade alpha: high-frequency Granger influence network, not a trained return or risk-utility trading model. |
| 13 | Korkusuz & Sahiner (2025), [publisher](https://doi.org/10.1186/s40854-025-00881-x) | ADVERSE: conventional HAR volatility forecasts reportedly outperform ML in most tested cases. |
| 14 | Qiu & Fang (2025), [arXiv](https://arxiv.org/abs/2510.20066) | DEFER: layered crypto liquidity spillovers forecast market-wide risk; insufficient native conditional trading/economic evaluation. |
| 15 | Garcia Seuma (2026), [arXiv](https://arxiv.org/abs/2607.27070) | ADVERSE: liquidation-cascade precursors heterogeneous across seven episodes, not reliable individual alarms. |
| 16 | Grobys & Shahzad (2025), [publisher](https://doi.org/10.1002/ijfe.70036) | ADVERSE: momentum factor variances appear power-law/heavy-tailed; Sharpe-based guarantees fragile. |
| 17 | Gbadebo (2026), [journal](https://doi.org/10.15388/batp.2026.1) | REJECT non-ML: EMA momentum portfolio comparisons. |
| 18 | Lindroos (2025), [Aalto](https://aaltodoc.aalto.fi/items/a6253508-55f9-4548-9f42-fa0ee3e49815) | REJECT non-ML: PoW/PoS momentum and factor exposure analysis. |
| 19 | Guidolin & Ionta (2026), [publisher](https://doi.org/10.1016/j.intfin.2026.102285) | REJECT incremental ML: rolling factor portfolios from blockchain/search sentiment rather than a separately trained learner with incremental predictive mechanism. |
| 20 | Ji & Zhang (2022), [journal](https://francis-press.com/papers/6399) | DEFER: crypto residual LightGBM return prediction; model-versus-simple-net utility and original venue not established in accessible summary. |
| 21 | Islas Anguiano & García-Medina (2025), [arXiv](https://arxiv.org/abs/2511.00665) | DEFER: BTC-only LightGBM/LSTM vs EMA, insufficient novel multiasset mechanism and source cost/parity evidence. |
| 22 | Hybrid Heston–LSTM with on-chain inputs (2026), [publisher](https://doi.org/10.1007/s44257-025-00046-1) | DEFER: one-minute single-BTC volatility forecast, short observation span and incompatible ATS return ranking; inspect source claims critically before borrowing any reported Sharpe. |

**Counts:** 22 distinct source identities; 1 candidate captured; 9 duplicate/overlap/prior-capture; 12 rejected, adverse or deferred. Two seriously deepened: Saidane and Guo. No incentive to manufacture 3-6 captures.

## Capture and scientific triage

Candidate: `research_staging/crypto_ml_saidane_mhmfa_sixasset_tailrisk_2026_v1/` containing exactly `thesis.yaml` and `brief.md`. The published-source DOI is an identifier, **not** a local hash of full original paper bytes; the source is an abstract-level claim and no full PDF copy was certified.

The model's incremental hypothesis is that time-varying regime and non-Gaussian cross-crypto tail dependence improve calibrated VaR/ES relative to rolling empirical risk estimates, not that it predicts relative returns. Simple benchmark: rolling empirical VaR/ES or static Gaussian covariance with the same portfolio, horizon, OOS dates and transaction costs. The paper reports strong out-of-sample joint-score and cost-aware allocation results; these are **AUTHOR_TEST_UNVERIFIED**, not ATS evaluations.

**Protocol:** `BLOCKED_PROTOCOL` for joint-risk forecasts and conditional sizing; `REQUIRES_TRAINING_WORKFLOW` for chronological risk predictions and EM regime artifacts. Future qualification needs historical six-symbol identity, end-of-bar/publication clocks, purge/label overlap governance, fold-local preprocessing, fixed retraining rules, reproducible model and feature hashes, calibration/tail-risk scoring, an independent accounting/cost rulebook, broker-product short/financing/prop restrictions, and economic parity against a simple risk rule. Exact forecast horizon and ticker list remain UNKNOWN.

No local real market returns, predictors, holdout, models, labels or execution/evaluation services were opened. Model training=0; empirical IC/backtests=0; runner interactions=0; protected reads=0; orders=0.
