# Hourly ML source discovery — 2026-10-19, Asia/Ho_Chi_Minh

## Authority and scope
This is a **source-only discovery record**, not ATS admission to scientific execution. Read actual VPS checkout /home/quant/dev/quant/quant-research and AGENTS.md, docs/research_inbox_operations.md, docs/research_inbox_factory_operations.md, src/engine/research_handoff.py, src/engine/thesis_ingest.py, src/workbench.py and src/models.py. Local `main` and `origin/main` are ce4eaf588608002c57e96a3e1639233df2047068; checked-out root is clean. Main inbox has 112 directories. A clean DevSpace task-owned isolated **detached worktree** is at /home/quant/.devspace/worktrees/quant-research-20d4b216, based on this exact main commit. This run does NOT invoke either historical research-capture script.

Source authority distinctions: SOURCE_FACT = directly inspected in publisher/original source; AUTHOR_TEST_UNVERIFIED = reported by authors, not locally reproduced; LOCAL_INFERENCE = a causal/economic interpretation, not proved; PROPOSED_ADAPTATION = separately permissioned later research; UNKNOWN = material facts not verified. All future execution protocols are BLOCKED_DATA / BLOCKED_PROTOCOL / REQUIRES_TRAINING_WORKFLOW unless explicitly qualified.

## Source-screening ledger (22 distinct identities)
Columns: #, author/source and first publication/known year, primary URL, classification, methodological finding. **No synthetic source identities or tested results.**

| # | Source | Primary source | Decision | Key screen |
|---|---|---|---|---|
| 1 | Kurihara & Matsumoto (10 Mar 2026), BTC/ALT 1m lag | https://doi.org/10.1007/s10690-026-09589-z | **NEW HANDOFF** | Original single-alt LightGBM entry and hold next-minute labels; distinctive ultra-short stale-price mechanism, but missing simple lag rule and execution proof. |
| 2 | Celik & Sefer (18 Apr 2025), BTC/ETH transaction motifs | https://doi.org/10.1007/s10614-025-10940-1 | **NEW HANDOFF** | Weekly transaction graph motifs + GNN/LSTM price/direction, not portfolio PnL; fundamentally distinct on-chain wallet graph information set. |
| 3 | Guidolin & Ionta (2026), blockchain/sentiment predictive sorting | https://doi.org/10.1016/j.intfin.2026.102285 | **PEER LOCAL DUPLICATE** | Previously staged as crypto_xs_predictability_sort_guidolin_ionta_20261018_v1 in multiple other isolated worktrees; do not republish. Source uses 40 crypto on-chain factors and Google attention; incremental ML over factor-mimicking sorts not demonstrated. |
| 4 | Tsoku & Makatjane (30 Jan 2026), dynamic crypto pairs cointegration | https://doi.org/10.3389/fams.2026.1749337 | **MAIN SOURCE DUPLICATE** | crypto_ml_tsoku_dynamic_coint_dwe_pairs_2026_v1; relative-value forecast already preserved. |
| 5 | Anastasopoulos et al. (2026), international crypto signed order flow | https://doi.org/10.1016/j.finmar.2026.101047 | **MAIN SOURCE DUPLICATE** | crypto_ml_anastasopoulos_world_orderflow_sgb_2026_v1; 11-fiat information missing from local simple OHLCV, not recreate with spot taker imbalance. |
| 6 | Cakici et al. (2024), cross-sectional multi-characteristic ML | https://doi.org/10.1016/j.irfa.2024.103244 | **MAIN SOURCE DUPLICATE** | crypto_ml_cakici_multicharacteristic_forecast_2024_v1. |
| 7 | Ming Che Lee (16 Jun 2025), multi-coin TFT on-chain features | https://doi.org/10.3390/systems13060474 | **MAIN SOURCE DUPLICATE** | crypto_ml_mingchelee_multicrypto_tft_onchain_2025_v1; source target next-day individual coin direction, not new rank signal. |
| 8 | Fieberg et al. (15 Jul 2025), CTREND cryptocurrency factor | https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/trend-factor-for-the-cross-section-of-cryptocurrency-returns/4C1509ACBA33D5DCAF0AC24379148178 | **MAIN SOURCE DUPLICATE** | crypto_ml_fieberg_ctrend_price_volume_factor_2025_v1; this is a factor baseline, not original new trained classifier. |
| 9 | Boyer (Jan 2026), variational latent crypto factors | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6860920 | **MAIN SOURCE DUPLICATE** | crypto_ml_boyer_factorvae_cross_sectional_2026_v1; FactorVAE forecast already staged. |
| 10 | Jia et al. (2023), seesaw cross-predictability | https://doi.org/10.1016/j.jempfin.2023.101428 | **MAIN SOURCE DUPLICATE** | crypto_ml_jia_seesaw_rolling_lasso_2023_v1; rolling Lasso intercoin forecast. |
| 11 | hamzaalisayeed-eng (2026 research repo), conditional cross-sectional meta gate | https://github.com/hamzaalisayeed-eng/QuantAlgo2 | **MAIN SOURCE DUPLICATE** | crypto_ml_hamza_cross_sectional_rs_meta_gate_2026_v1; exact authorship date UNKNOWN. |
| 12 | matthiola0 (date UNKNOWN), crypto 20-name XGBRanker robustness | https://github.com/matthiola0/ml-cross-sectional | **MAIN SOURCE DUPLICATE** | crypto_ml_matthiola_xgbranker_20usdt_2026_v1; disclosed no-purge/static-universe bias. |
| 13 | Jing, Kobayashi & Rocha (May 2025; revised Apr 2026), stable network clusters | https://arxiv.org/abs/2505.24831 | **ADVERSE / NO CAPTURE** | Source selects top-1000 as of 2022-02-22 then restricts to always-active 2017-2022; severe forward universe membership/survivorship, so predictive clustering return figures are not proof. |
| 14 | Doğan & Kurnaz (26 Sep 2026), Pearson/DTW crypto similarity | https://arxiv.org/abs/2609.32611 | **ADVERSE / NO CAPTURE** | The most cross-correlated pairs achieve peak correlation at lag 0, undercutting the notion every apparent link offers a tradeable delay. |
| 15 | Wang (6 Jun 2025), BTC/USDT LOB preprocessing vs depth | https://arxiv.org/abs/2506.05764 | **ADVERSE / NO CAPTURE** | OOS source reports careful preprocessing plus simple models matching/exceeding deep networks; no incremental complexity assumption allowed. |
| 16 | Pindza (11 Jun 2026), hierarchical crypto microstructure alpha | https://doi.org/10.3389/fbloc.2026.1811716 | **ADVERSE / NO CAPTURE** | Source five-minute LightGBM gross Sharpe 0.96 but futures net Sharpe -16.98 with retail costs; strong after-cost veto for extremely fast signals. |
| 17 | Marín & Lopes (Jan 2026), shock-triggered stochastic volatility | https://doi.org/10.1002/for.70035 | **DEFER** | BTC/Nasdaq/S&P 1- and 10-day conditional volatility/VaR; no original directional return or basket rule. |
| 18 | Xiao & Chen (5 Mar 2026), multi-scale high-order crypto interactions | https://doi.org/10.1007/s41109-026-00778-3 | **DEFER** | Crypto high-order liquidity/volatility information network, explanatory/risk structure; no forecast horizon/trade rule established. |
| 19 | Patra & Gupta (24 Jan 2025), volume-volatility structural breaks | https://doi.org/10.1080/1351847X.2025.2453732 | **DEFER** | BTC/ETH volatility prediction, not directional alpha. |
| 20 | Ko & Chen (21 Apr 2026), green-crypto/AI-token network portfolios | https://doi.org/10.3934/nhm.2026028 | **DEFER** | TVP-VAR connectedness/risk allocation; insufficient same-clock incremental supervised ML evidence vs simple risk models. |
| 21 | Zhuang & Liu (24 Aug 2026), digital/traditional market risk spillovers | https://doi.org/10.3390/e28090949 | **DEFER** | Risk transmission, no source-equivalent executable return rank. |
| 22 | Rehman et al. (30 Jan 2026), crypto quantile time-frequency networks | https://doi.org/10.1186/s40854-025-00831-7 | **DEFER** | Tail-connectedness information, no established forward directional ML improvement. |

Ledger totals: screened **22**; exact-source existing main **9**; known worktree duplicate **1**; new descriptive handoffs **2**; adverse screens **4**; other deferred **6**. Previously published research branches were inspected for target source-name/DOI; local checked-out worktrees and local/remote research refs were searched for candidate source names and DOI substrings without matches. Such searches cannot prove full semantic novelty or see unstaged untracked drafts beyond queried paths.

## Deepened new source 1: Kurihara–Matsumoto BTC-to-ALT 1-minute conditional state

**SOURCE_FACT:** Binance API 1-minute close and trade count, 369/381 coin universes analyzed in Bull/Bear macro-correlation studies, then QKC/GNO/PIVX/CITY/BIFI low-trade-count subgroup. Studies Bull 2024-02-25 to 03-25, Bear 2024-06-22 to 07-19, Sideways 2024-08-24 to 09-24, Crash 2025-01-30 to 03-01. Two LightGBM classifiers, using lagged 1-min BTC and single ALT return, predict the next 1-minute ALT return exceeding independent entry/hold thresholds. Source thresholds searched over entry {-0.0001,0,0.0001,0.0002} and hold {-0.0002,-0.0001,0,0.0001}. Per-regime first ~3 weeks train/tune, last week OOS. State is individual long/flat, **not a new cross-sectional rank basket**.

**AUTHOR_TEST_UNVERIFIED:** Authors report simulated small-alt lag strategy beating buy-and-hold, with sideways regime weaker; see publisher Eqs 4-11 and section 4.6. They charge symbolic turnover fees, not executable spread/impact/priority fills.

**LOCAL_INFERENCE:** Apparently delayed last-trade price in an illiquid altcoin could be untradable stale prints. The paper does not establish trained model advantage over a trivial threshold on last BTC move.

**PROPOSED_ADAPTATION:** Only future qualified protocol should compare LightGBM with signed-BTC one-minute rule, fixed stateful hysteresis and logistic two-feature regression under identical decision/label clocks and true quotes. Historical fee, bid/ask, next-executable fill, listing and trade-count selection must be as-of. Need fold-local preprocessing, chronological purged OOF, label availability check, and selection-budget controls. Source has one minute target; do not lengthen it to 5m/1h without separate thesis.

**UNKNOWN:** source trading market class/individual quote contract (spot vs perp), executable tick/quote timestamps, original per-altcoin model snapshots and continuous-year generalization. **BLOCKED_DATA / BLOCKED_PROTOCOL / REQUIRES_TRAINING_WORKFLOW**.

## Deepened new source 2: Celik–Sefer transaction motifs

**SOURCE_FACT:** BTC and ETH blockchain address-to-address graphs aggregated weekly from 2016-2024; daily Yahoo Finance BTC/ETH price data. Author trains motif-convolution GNN + attention-LSTM; rolling two-year fit and following one-year test, annual shift. Original compared price-only SVM, LSTM, hierarchical LSTM, GRU and other embedding models. Author online publication 2025-04-18, 2026 issue.

**AUTHOR_TEST_UNVERIFIED:** Source reports improvement in price/direction forecast metrics over stated price-only baselines. **No source-author tested exchange strategy, transaction-cost returns, or cross-sectional basket.**

**LOCAL_INFERENCE:** Changes in wallet-network motifs may contain incremental information versus a chart-only model but could collapse to simple transaction-count/volume, wallet-label leakage or future graph construction.

**PROPOSED_ADAPTATION:** First obtain causal weekly on-chain graph vintages and exact label/forecast clock. Only if data exists, compare graph + LSTM with lagged price simple model and lagged graph-count/flow Ridge at matched horizon; fold-local motif dictionary and chronological purged OOF predictions; venue execution after graph finalization. Model complexity is high, costs/data economics likely unfavorable without a quantified improvement.

**UNKNOWN:** Exact price target lead time, exchange execution identity, transaction archive/version, trade sizing and cost model. **BLOCKED_DATA / BLOCKED_PROTOCOL / REQUIRES_TRAINING_WORKFLOW**.

## Deepened rejected source: Jing et al. portfolio correlation network

**SOURCE_FACT:** Original arXiv manuscript first submitted 2025-05-30 and revised 2026-04. Uses daily 2017-11-15 to 2022-04-15. Critical data paragraph: selects top 1,000 coins by market capitalization on **2022-02-22** and retains 157 coins continuously traded since **2017-11-15**. Model uses Louvain + rolling consensus clustering with ARIMA forecast of community relationships, then a long-only portfolio; author tests short future holding horizons up to 14 days.

**ADVERSE EVIDENCE:** Source-universe membership is defined using knowledge that could not have been known before 2022-02-22, creating hindsight/survivor selection over the 2017-2022 span. Without historical tradable-universe replay and realistic transaction costs, high portfolio figures do not demonstrate source-executable forward-predictive cluster alpha. Thus no new source handoff today. A future independent formulation must preserve original portfolio long-only construction and test against no-forecast historical consensus clustering, not call it a cross-sectional short basket.

## Dedup and publication boundary
Mechanism identity is tuple (information set, target, original product, horizon, nonlinear model use, cost/clock). The current main info-delay basket is a 48-hour Binance-perp **cross-sectional** price-backlog proposal; the Kurihara source is **1-minute individually held Binance altcoin** inventory classification. Their economic theme overlaps but label, source product and model use differ. Main Peng price-graph intercoin correlations are different from Celik address-level **on-chain transaction motifs**.

Native strict parser checked directly. Each new two-file candidate passed the actual native `validate-handoff` CLI using the existing source checkout project venv (the isolated worktree has no separate .venv). Output: `HANDOFF_VALID_UNVERIFIED` / `STRUCTURE_AND_DECLARED_PROVENANCE_ONLY`. This validates envelope, source reference syntax and permissions only; **no training, OOF, SHAP, empirical tests, native stages, protected reads or orders**.

## Integrity evidence (SHA-256 of captured artifact bytes, NOT publisher document bytes)
- Kurihara thesis.yaml: `2f5bd4ea98d726d4ac6ca56115d0973789e112c2d2fce72f21231f80dc6b1ca2`
- Kurihara brief.md: `404b4c7960248337132a67679e8f675d3e80d480ab6a0be58230cfe1c10088a2`
- Celik thesis.yaml: `ea6eff2bc01ecd040a34945a09b853de8a538836d4e2d873ab5587a6cc471435`
- Celik brief.md: `955fe2ce092b8267b3c61eb1bc032517c9f882473b13339678797200dd1049b3`

Each source's HTTPS title, author, primary DOI, online publication date and exact source-market identity is recorded. Original source PDF/HTML document bytes were not independently saved or SHA-hashed, so provenance confidence is limited to verified publisher pages and text-capture identity. Artifacts are bounded safe UTF-8 regular files in isolated worktree. No future protected-data labels, prices or returns read.
