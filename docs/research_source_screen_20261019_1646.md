# Hourly crypto source-only discovery checkpoint — 2026-10-19, 16:46 ICT

**Authority boundary:** research source descriptions only; not Stage 1–4, IC, model training, backtests, trial/holdout reads, accounts, paper or live orders. Funding, carry and basis are excluded as signals; later economic costs must still include actual financing.

**Repository observation:** VPS checkout and latest origin/main were clean at `ce4eaf588608002c57e96a3e1639233df2047068` when isolated worktree started. Corpus on that HEAD: **112 source directories**. The earlier `37a6e5a5` merge is an ancestor, not the current main HEAD. Approximately 146 distinct candidate directories were found across tracked local/remote research refs (including those on main); branch snapshots are **not** 146 published-to-main candidates. Source-term scanning of all research refs and existing local research-inbox trees found no VFund/Abdirahmanjabdi or avi-mukesh/crypto-quant-project source identity matches. This is a scoped exact-identity check, not a proof of complete semantic novelty.

## Original sources reviewed and decisions

| # | Original source | Mechanism / original clock | Decision |
|---|---|---|---|
| 1 | [VFund TVLDivergence](https://github.com/Abdirahmanjabdi/VFund/blob/main/vfund/strategy/cross_sectional.py) | Daily TVL growth minus token-price growth, 60 observations, crypto long/short relative value | CAPTURE — distinct on-chain fundamental divergence |
| 2 | [avi-mukesh crypto-quant-project](https://github.com/avi-mukesh/crypto-quant-project) | Hourly relative tweet-attention share, reported 7-hour association (separate from price strategy) | CAPTURE — signal research only; original tweet-only trade rules absent |
| 3 | [Matias Arnal crypto momentum](https://github.com/matiasjarnal/crypto-momentum-strategy) | Daily 10/20/60d price-rank momentum, BTC regime, 35 assets | DUPLICATE — existing `crypto_xs_btc_regime_momentum_arnal_20261018_v1` |
| 4 | [Shukla et al. Granger return networks](https://arxiv.org/abs/2606.25466) | Time-varying cross-asset directional return networks | OVERLAP — existing return-transmission graph family |
| 5 | [quantsarahz BTC regime system](https://github.com/quantsarahz/btcusdt-regime-multistrategy-trading) | BTC 15m trades, 1h regime, Donchian/EMA/mean reversal | OVERLAP — established single-BTC regime/technical family |
| 6 | [djienne BTC LightGBM](https://github.com/djienne/ML_Trading_Strategy_Crypto_BTC_LightGBM_Jansen) | Single BTC 15m LightGBM directional regime system | DUPLICATE — existing `crypto_ml_djienne_15m_btc_lgbm_hysteresis_2026_v1` |
| 7 | [PatrickSebastine mean-reversion](https://github.com/PatrickSebastine/mean-reversion-trading-bot) | 15m Bollinger/RSI reversal vs EMA/volume momentum across 8 symbols | OVERLAP — generic technical reversal/momentum |
| 8 | [maxgfr adaptive reversal rules](https://github.com/maxgfr/ai-strategy-backtester) | JSON technical RSI/MACD/ADX long/short reversal | OVERLAP — generic technical indicators not a distinct information set |
| 9 | [hsingh97x crypto cross-sectional stat arb](https://github.com/hsingh97x/crypto-cross-sectional-stat-arb) | 4h 360-bar price momentum conditioned on normalized activity, long/short, daily rebalance | OVERLAP — volume-conditioned momentum, source reports material OOS decay and survivorship flaws |
| 10 | [prams2104 25-coin momentum](https://github.com/prams2104/crypto-momentum-backtest) | Daily price-rank momentum / reversal, OOS 2025-26 | ADVERSE — momentum loses OOS, reversal turnover economically destructive |
| 11 | [adensvaz sentinel Hyperliquid](https://github.com/adensvaz/sentinel-hyperliquid) | Cross-sectional market-neutral momentum | ADVERSE — author reports near-zero 5.5-year net Sharpe; funding-carry arm excluded |
| 12 | [FionaNi hourly cross-sectional validation](https://github.com/FionaNi-DS/crypto-statistical-arbitrage) | 10-coin hourly Binance spot momentum and reversal | ADVERSE — weekly momentum fails untouched 2025 period |
| 13 | [IliassSjm crypto-perps-alpha](https://github.com/IliassSjm/crypto-perps-alpha) | ML hourly dollar-neutral ranks, 411 cumulatively listed contracts | ADVERSE — source states lag-1 decay and ~1.2bps-per-side breakeven |
| 14 | [WhiteCatNa binance-strategy](https://github.com/WhiteCatNa/binance-strategy) | 1h four-major long-only regime profile | ADVERSE — weak author-reported whole-sample after-cost Sharpe, not differentiated |
| 15 | [Farzulla narrative-vs-factors](https://arxiv.org/abs/2601.20336) | Hourly token factors vs whitepaper semantic claims | ADVERSE/NULL — weak cross-sectional claims/factors alignment; not an original trade basket |
| 16 | [PravarP11 15m retest](https://github.com/PravarP11/multi-timeframe-trend-retest-strategy) | 4h EMA trend + 15m ADX/crossover/volume retest, per-symbol layered trades | DEFER — source-defined original path-dependent trend, not a cross-sectional rank; 10x leverage and selection caveats |
| 17 | [Kim and Hansen quarter-hour](https://arxiv.org/abs/2607.09426) | First 10 seconds of quarter-hour futures flow predict 4–12h return | DEFER — compelling causal clock, but no after-cost multi-coin portfolio and tick source requirements |
| 18 | [Zwydak et al. exchange trade-count anomaly](https://arxiv.org/abs/2607.13916) | Binance/Bitget/KuCoin/Kraken BTC/ETH/XRP trade-count complexity | DEFER — exchange activity-quality diagnostic, not a price-alpha mechanism |
| 19 | [tripolskypetr crowd liquidity](https://github.com/tripolskypetr/backtest-kit) | Inversion of selected social trading signals, predominantly BTC | DEFER — author selection/grid search and retrospective creator filtering, not a portable stable basket |
| 20 | [mikedconcepcion periodic order blocks](https://github.com/mikedconcepcion/momentumfx-research) | 5m clock-boundary liquidity-zone observations across FX, gold and BTC | DEFER — predominantly noncrypto, BTC sample small, no independently verified economic basket |

**Counts:** 20 screened; 7 duplicate/overlap; 6 independent adverse/null; 5 deferred; 2 captured, with flat handoff validation and publication handled separately. Mechanisms deepened: (1) daily DeFi TVL–token-price divergence, (2) 1h relative tweet attention share, (3) 15m boundary activity and 4–12h returns. The third is *not* a new candidate because complete trade rules and costs are absent.

## Source integrity and limitations

**SOURCE_FACT:** VFund's source class computes 60-observation TVL growth minus price growth and returns NaN on nonpositive historical TVL. Its cross-sectional engine is configurable; do not infer a specific experimental basket from the generic score method. The avi-mukesh README reports tweet-share feature association; its primary portfolio trades price momentum, **not** an isolated tweet strategy. Kim and Hansen describe return predictability following quarter-hour order flow; no explicit return-generating after-cost trade implementation was shown in this read.

**AUTHOR_REPORTED_TEST_UNVERIFIED:** VFund case study reports standalone IS/OOS Sharpes 1.09/0.44 for TVL divergence. avi-mukesh README reports 7-hour-lag tweet-share rank IC 0.012–0.016. No local reproduction or fresh experiment was performed.

**LOCAL_INFERENCE:** TVL feeds are revised and sometimes price-dependent; Twitter historical coverage is not necessarily as-of; shorting/capacity/spread/financing and drawdown limits could dominate both signals.

**ADAPTATION_PROPOSAL:** Any hourly crypto basket built from daily TVL or standalone Twitter attention is a new separate study requiring causal data clocks, frozen universe/weights, source-code verification and realistic costs. Do not confuse source-description validity with scientific ATS qualification.

**Native validation:** `/home/quant/dev/quant/quant-research/.venv/bin/python scripts/quant.py validate-handoff .factory_stage/<id>` returned `HANDOFF_VALID_UNVERIFIED` for both candidate pairs. This is **STRUCTURE_AND_DECLARED_PROVENANCE_ONLY**. Exactly two files per candidate, with no other files in the published candidate dirs. Byte identity between staged and published pairs is verified separately by SHA-256.

**New candidates:** `crypto_xs_tvl_price_divergence_vfund_20261019_v1` and `crypto_xs_relative_tweet_attention_avi_20261019_v1`, each with `research_inbox/<id>/thesis.yaml` and `brief.md`.

**Execution counter:** empirical analysis 0; IC 0; model training 0; ATS Stage 1–4 0; trial ledgers 0; holdout reads 0; paper/live orders 0; account changes 0. Next frontier: source-authenticated social-activity vintages and alternative DeFi adoption measures whose publication clock can be independently reconstructed.
