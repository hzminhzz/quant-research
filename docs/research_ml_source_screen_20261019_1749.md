# Hourly ML Strategy Thesis Factory — source-only screen, 2026-10-19 17:49 Asia/Ho_Chi_Minh

**Scope:** Discovery and descriptive source publication only. No model training, feature computation on returns, SHAP, OOF predictions, IC/HAC, model selection, empirical backtest, ATS runner, protected holdout, or orders. A candidate may enter the inbox after handoff checks without any execution authority.

## Repository authority and dry smoke
- VPS-connected checkout: `/home/quant/dev/quant/quant-research` on clean `main`; actual HEAD and `git ls-remote origin refs/heads/main` both `ce4eaf588608002c57e96a3e1639233df2047068`. The formerly quoted `37a6e5a5` is not latest main.
- 112 existing source directories confirmed by `find research_inbox -mindepth 1 -maxdepth 1 -type d | wc -l`.
- Reviewed actual `AGENTS.md`, `docs/research_inbox_operations.md`, `docs/research_inbox_factory_operations.md`, `src/engine/research_handoff.py`, `src/engine/thesis_ingest.py`, `scripts/quant.py`, `src/models.py`, `src/workbench.py` and project ML4T point-in-time, purge/embargo, model validation, meta-labeling, research and cost guidance.
- Read-only ref scan covered main, `refs/heads/research` and `refs/remotes/origin/research` (63 total local/remote research ref names), plus listed task/peer worktrees and keyword inspection of local unpublished candidate dirs. No original/peer draft rewritten. Full semantic closure over every independent untracked file in all worktrees cannot be asserted.
- An isolated task-owned worktree was created from `origin/main`, with source pair staged there; no changes to main. The original checkout owns the qualified Python `.venv`; isolated worktree lacks its own venv, so native validation uses original checkout's interpreter with isolated worktree source and cwd.
- The flat native handoff validation output is `HANDOFF_VALID_UNVERIFIED` with `STRUCTURE_AND_DECLARED_PROVENANCE_ONLY` and `NO_EXECUTION_OR_TRADING_APPROVAL`. Native validator does **not** hash or certify the publisher PDF.
- Historical last automation's `research/hourly_ml_kalshi_whale_20261019` worktree still holds two staged, unpushed peer files; left untouched. This run did not merge/overwrite it.

## 20 distinct source identities screened

Screened means source title/primary abstract and its novelty/benchmark suitability were checked; only items in the next section were deepened. Duplicate means same source or the same mechanism/information/target already exists in an actual named two-file capture, not merely the same article theme. Dates below are source year unless exact dates were verified; an unlabeled year is not a claimed publication timestamp.

| # | Source and anchor | Original market/target or key evidence | Screen disposition |
|---|---|---|---|
| 01 | Lucas Dünnes & Jens Felsenstein-Eckberg, written 2026-06-26, posted 2026-07-18, [SSRN 7003998](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7003998) | Single ETH, ETH-native protocol fees/supply, forward 10–60 day ETH return, post-Dencun; nonlinear model is **not** in original test | **NEW SOURCE_CAPTURE; HANDOFF_VALID_UNVERIFIED**, future ML increment unproven |
| 02 | Farbod Ghasemlu, 2026-06-24, [SSRN 6901559](https://doi.org/10.2139/ssrn.6901559) | DeFi tokens; 12-month forward cross-sectional revenue-multiple rank fails | ADVERSE NULL; not same single-ETH fee mechanism |
| 03 | Massimo Guidolin & Serena Ionta (2026), [DOI](https://doi.org/10.1016/j.intfin.2026.102285) | 40-coin predictive factor sorting using on-chain/fundamentals/sentiment | REMOTE EXACT CAPTURE: `crypto_xs_predictability_sort_guidolin_ionta_20261018_v1`; original has no demonstrated trained nonlinear ML incremental alpha |
| 04 | Shukla, Peyyala & Chakraborty (2026), [arXiv 2606.25466](https://arxiv.org/abs/2606.25466) | High-frequency directed crypto return-influence networks, not demonstrated trade forecast | REMOTE EXACT CAPTURE: `crypto_xs_timevarying_granger_outstrength_shukla_20261018_v1` |
| 05 | Matthew Brigida (2026), [arXiv 2601.07664](https://arxiv.org/abs/2601.07664) | Latent crypto common risk-factor pricing; no frozen trade label/fill clock | DEFER: mechanism overlap with latent factor family; insufficient incremental ML |
| 06 | Anastasopoulos, Gradojevic, Liu, Maynard & Tsiakas (2026), [DOI](https://doi.org/10.1016/j.finmar.2026.101047) | 84 cryptocurrencies, 11 fiat-currency signed flows, daily forward return ranks | MAIN EXACT: `crypto_ml_anastasopoulos_world_orderflow_sgb_2026_v1` |
| 07 | Zijiang Yang (2025), [arXiv 2512.08124](https://arxiv.org/abs/2512.08124) | Fixed ten-coin daily long-only rank neural portfolio; ex-post universe caveat | MAIN EXACT: `crypto_ml_yang_direct_rank_mlp_2025_v1` |
| 08 | Boyer (2026), [SSRN 6860920](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6860920) | Cross-sectional crypto latent risk-factor model | MAIN EXACT: `crypto_ml_boyer_factorvae_cross_sectional_2026_v1` |
| 09 | Cakici et al. (2024), [DOI](https://doi.org/10.1016/j.irfa.2024.103244) | Multi-characteristic forward crypto return forecasts | MAIN EXACT: `crypto_ml_cakici_multicharacteristic_forecast_2024_v1` |
| 10 | cengizmandros (repo date not independently verified), [GitHub](https://github.com/cengizmandros/crypto-ml-trading-research) | Spot cross-sectional 3-day forecasts, HMM filter, complex ensemble; held-out losses noted in earlier screen | MAIN EXACT: `crypto_ml_cengizmandros_hmm_rank_ensemble_v1` |
| 11 | djienne (repo date not independently verified), [GitHub](https://github.com/djienne/ML_Trading_Strategy_Crypto_BTC_LightGBM_Jansen) | Single BTC 15m LightGBM, decision hysteresis | MAIN EXACT: `crypto_ml_djienne_15m_btc_lgbm_hysteresis_2026_v1` |
| 12 | Jia et al. (2023), [DOI](https://doi.org/10.1016/j.jempfin.2023.101428) | Cross-crypto adaptive Lasso/Seesaw forecasts | MAIN EXACT: `crypto_ml_jia_seesaw_rolling_lasso_2023_v1` |
| 13 | matthiola0 (repo date not independently verified), [GitHub](https://github.com/matthiola0/ml-cross-sectional) | Crypto cross-sectional learning-to-rank/XGB | MAIN EXACT: `crypto_ml_matthiola_xgbranker_20usdt_2026_v1` |
| 14 | Mingche Lee et al. (2025), [Systems 13:474](https://doi.org/10.3390/systems13060474) | Multi-crypto TFT with on-chain predictors | MAIN EXACT: `crypto_ml_mingchelee_multicrypto_tft_onchain_2025_v1` |
| 15 | Peng / CryptoGAT (2026 source family), [author repo](https://github.com/FanBroWell/CryptoGAT) | Crypto price graph-attention forecasts | MAIN EXACT: `crypto_ml_peng_cryptogat_price_graph_2026_v1` |
| 16 | Tsoku et al. (2026), [DOI](https://doi.org/10.3389/fams.2026.1749337) | Crypto pairs dynamic cointegration / deep relative value | MAIN EXACT: `crypto_ml_tsoku_dynamic_coint_dwe_pairs_2026_v1` |
| 17 | Weijia Xue & Chunyang Zhou (2026), [DOI](https://doi.org/10.1016/j.jbankfin.2026.107750) | Cross-sectional cryptocurrency 1-week image-based nonlinear ViT ranking | REMOTE EXACT CAPTURE: `crypto_ml_xue_zhou_vision_chart_xs_2026_v1` |
| 18 | GuangSen Zhai (2026-04-20 SSRN posting), [SSRN 6566940](https://doi.org/10.2139/ssrn.6566940) | Binance ETHUSDC perpetual live ML predictive models fail to deliver reported CV economics | ADVERSE REALIZED ECONOMICS; no duplicate thesis |
| 19 | Gihan M. Ali (2026), [JRFM 19:63](https://doi.org/10.3390/jrfm19010063) | Optuna/Super Learner reconstructs contemporaneous DeFi protocol valuation, not forward tradable returns | REJECT TARGET MISMATCH |
| 20 | Andrei Bysik & Robert Ślepaczuk (2026), [arXiv 2606.00060](https://arxiv.org/abs/2606.00060) | Hourly BTC/USDT forecast and cost-aware trading, claimed 2017–19 Binance futures coverage inconsistent with 2019 launch in earlier source review | ADVERSE PROVENANCE / PRIOR SCREEN, no additional capture |

Disposition counts: **1 new**, **11 exact main-source duplicates**, **3 exact remote-branch captures**, **5 adverse/deferred/target-mismatched**. The exact main IDs and remote pair paths were checked in the live checkout/ref tree. Do not count a prior offline discovery capture as remotely published.

## Deep evaluation A — Dünnes & Felsenstein-Eckberg (candidate)
**SOURCE_FACT:** Original forecast is **single ETH** with 10–60-day horizons, strongest author-reported OOS 45-day R² = 14.4%. Protocol fee-flow intensity is ETH-native fees divided by circulating supply; author methodology specifies 30-day smoothed intensity and 90-day trailing median reference, log ratio. Regime interaction plausibly starts at 2024-03-13 Dencun separation of execution and blob markets. Direct source: [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7003998); [author-owned technical methodology](https://www.majorkeycapital.com/ethereum/valuation-terminal/methodology).

**AUTHOR_TEST_UNVERIFIED:** In-sample 45-day R² up to 22.8%, expanding-window OOS R² 14.4%, author page 76.4% direction accuracy. These are not a backtest, not proven independent OOF model predictions and **do not show incremental nonlinear ML alpha**.

**PROPOSED_ADAPTATION:** One ETH future 45-calendar-day return predictor using *only historical realized* fee-intensity/lagged change/fee persistence and ETH momentum. Compare a shallow low-capacity tree to source fixed fee ratio / simple fixed rule, linear/Ridge, momentum and long/hold under identical future venue clocks/costs. Original is a *single ETH research signal*; do not convert to basket/sector-neutral pairs. Funding/basis/carry are not features.

**UNKNOWN/BLOCKED_DATA:** Daily finalized ETH fee and circulating-supply snapshots, exact historical finality/vintage, author fill/label clock, exact tradeable ETH venue/product, source PDF raw bytes, genuine market fee/spread/slippage/financing. Do not invent trade threshold or exchange. Model retraining specifics unsupported beyond the author's expanding-window claim.

**REQUIRES_TRAINING_WORKFLOW:** Future independently authorized chronological OOF fit on matured non-overlapping 45-day labels (purge at actual event endpoints), fold-local 30/90-day feature preprocessing, source-vs-adaptation identity proofs, fixed model/rule choice, estimated effective sample and significance under serial correlation. Until then **NOT MODEL_READY / NOT EXECUTABLE**. **Falsifier:** any failure of nonlinear OOF+cost improvement over the source's simple signal or failure to establish source chronology.

## Deep evaluation B — Ghasemlu (negative evidence)
**SOURCE_FACT / AUTHOR_TEST_UNVERIFIED:** One-year DeFi protocol-level token panel from DefiLlama includes 2,259 protocols and 345 with tradeable market cap; formation price/revenue does not predict 12m subsequent relative rank (Spearman rho 0.04), size/asset class adjusted regression p = 0.98; source acknowledges bear-market regime and survivor/universe conditioning. [Original SSRN](https://doi.org/10.2139/ssrn.6901559). This is not evidence that *ETH-native network fee change* fails, because the explanatory variable/asset/horizon are different. But it falsifies indiscriminate token "fee or revenue equals alpha" reasoning.

**Decision:** Negative control, not new ML strategy. Any future DeFi cross-section needs historical revenue vintage, point-in-time universe/delistings, profitability, contract identification and a simple valuation rank benchmark before nonlinear fitting. Do not transform to trade proposal.

## Deep evaluation C — Xue & Zhou (remote duplicate)
**AUTHOR_TEST_UNVERIFIED:** Chart-image Vision Transformer of crypto weekly forward cross-sectional returns reportedly delivers 2.24% weekly value-weighted long/short mean excess return and 1.89 annualized Sharpe versus CNN and characteristic sorts. Source claims pretrained nonfinancial images reduce future leakage risk, but underlying price-panel PIT, asset eligibility, chart creation, label alignment and actual after-cost short legs are not independently verified here. [Publisher DOI](https://doi.org/10.1016/j.jbankfin.2026.107750).

**Dedup:** Existing remote branch `origin/research/hourly-ml-source-xue-20261018-b12` contains exactly `research_inbox/crypto_ml_xue_zhou_vision_chart_xs_2026_v1/{thesis.yaml,brief.md}`. Thus **do not recapture**. Fair future benchmark would be same-history lagged price/volume-characteristic rank with same long/short turnover/costs and purged chronological OOF ViT refits.

## Provenance hashes and authority
- Source identity SHA-256 (UTF-8 exact ASCII-concatenated fields; **NOT publisher bytes**): `f734ab4b3ef6d3fdf2ae81850631cbda0ec68f1090b65c85c29812f1c7f6d482`, corresponding to `SSRN 7003998|Demand-Side Fee Flows and Return Predictability on Ethereum|Lucas Dunnes|Jens Felsenstein-Eckberg|2026-06-26|2026-07-18|https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7003998`.
- Capture `thesis.yaml` SHA-256 `30bfb6f381bf2bbda8be19522223266ac4f940e61221d9565e676880d752600d`.
- Capture `brief.md` SHA-256 `0827b50845589255820aad1b6186582ca801b1c6acbcc615d1f54922e32a4cca`.
- Publisher full-text-document SHA-256: **UNKNOWN / not fetched**. Hashing source identity or captured files is not a scientific source-byte provenance guarantee.
- Native flat handoff output: `{"authority":"NO_EXECUTION_OR_TRADING_APPROVAL","candidate_id":"crypto_ml_dunnes_eth_fee_demand_state_2026_v1","external_local_claims_unverified":0,"status":"HANDOFF_VALID_UNVERIFIED","validation":"STRUCTURE_AND_DECLARED_PROVENANCE_ONLY"}`.
- No source or training credential changes, no raw market data reads, no investment/execution qualifications conferred.

## Publication/readback
Source pair staged in a clean task-owned detached worktree based on current origin/main; remote publication status is determined separately from local validation. Never report a commit without matching remote SHA and two-file readback. Zero tests other than schema/Git/safety checks, and zero trading actions.
