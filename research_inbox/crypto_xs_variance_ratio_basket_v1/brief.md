# Research Handoff: Cross-Sectional Lo-MacKinlay Variance Ratio & Multi-Scale Autocorrelation Persistence Basket

**Candidate ID:** `crypto_xs_variance_ratio_basket_v1`  
**Selection Family:** `cross_sectional_risk_premia`  
**Status:** `THESIS_READY_UNVERIFIED`  
**Research Mode:** `THESIS_DESIGN_ONLY`  
**Created On:** 2026-10-17  

---

## 1. Executive Thesis

The Lo-MacKinlay Variance Ratio (VR_i(24) = Var(r_{24h}) / (24 * Var(r_{1h})) over trailing 14 days) non-parametrically diagnoses deviations from random walks and quantifies multi-scale serial autocorrelation; altcoins with VR(24) > 1.0 are driven by persistent, autocorrelated institutional execution algorithms that produce multi-day drift continuation, whereas tokens with VR(24) < 1.0 are dominated by transient noise trader whipsaws and mean-reverting bid-ask bounce. A dollar-neutral 72h basket longing high-VR altcoins and shorting low-VR altcoins captures the autocorrelation persistence premium while neutralizing directional market beta.

This strategy targets Top 40 liquid perpetuals (ex-BTC) + BTCUSDT_PERP benchmark with a 72-Hour Rebalanced Basket execution cycle. Grounded in empirical asset pricing and market microstructure, the strategy harvests a persistent structural risk premium while mitigating directional market exposure.

---

## 2. Original Author, Links and Publication Details

* **Lo & MacKinlay (1988), The Review of Financial Studies**: *Stock Market Prices Do Not Follow Random Walks: Evidence from a Simple Specification Test*. [Source URL](https://ideas.repec.org/a/oup/rfinst/v1y1988i1p41-66.html)
* **Campbell, Lo & MacKinlay (1997), Princeton University Press**: *The Econometrics of Financial Markets*. [Source URL](https://ideas.repec.org/a/bla/jfinan/v52y1997i5p2139-2144.html)
* **Charles & Darné (2009), Journal of Banking & Finance**: *The Random Walk Hypothesis for Hedge Funds*. [Source URL](https://ideas.repec.org/a/eee/jfinec/v33y2009i1p69-89.html)
* **Pindza (2026), Frontiers in Blockchain**: *Microstructure alpha: hierarchical learning and cross-asset transfer in cryptocurrency markets*. [Source URL](https://www.frontiersin.org/journals/blockchain/articles/10.3389/fbloc.2026.1811716/full)

---

## 3. Original Reported Performance — Explicitly Marked as Third-Party Claims

* **Published Academic Claims:** Prior literature documents statistically significant predictive return spreads (t-statistic > 2.5) across equity or cryptocurrency cross-sections before transaction costs. *(Third-party claims; unverified on our proprietary execution environment).*
* **Current Status:** `THESIS_READY_UNVERIFIED`. No proprietary backtest or implementation has been conducted.

---

## 4. Economic Mechanism and Counterparty

* **Economic Mechanism:** Grounded in Lo & MacKinlay (1988) and Campbell, Lo & MacKinlay (1997), the Variance Ratio (VR_i(q) = Var(r\_{i,t}(q)) / (q \* Var(r\_{i,t}(1)))) tests for deviations from a random walk and measures multi-scale serial return autocorrelation; altcoins exhibiting high VR(24) (> 1.2 over trailing 14 days) reflect persistent, autocorrelated institutional order flow execution and continuous trend efficiency, whereas altcoins exhibiting low VR(24) (< 0.8) are dominated by non-informational retail whipsaws and mean-reverting bid-ask bounce. Longing high-VR altcoins (persistent institutional drift) and shorting low-VR altcoins (mean-reverting noise churn) in a 72h dollar-neutral basket captures multi-scale autocorrelation alpha while eliminating directional market beta.
* **Counterparty Payer:** Noise traders betting on reversals in persistent institutional trends and momentum traders caught in mean-reverting whipsaw chop.
* **Persistence Rationale:** Execution mechanics: institutional parent order execution extends across days, generating positive serial autocorrelation that cannot be erased by high-frequency market makers.

---

## 5. Exact Deterministic Strategy Rules

* **Universe:** Top 40 liquid perpetuals (ex-BTC) + BTCUSDT_PERP benchmark
* **Timeframe:** 1h bars
* **Signal Computation:** Evaluated at closed bar boundary.
* **Execution Timing:** NEXT_BAR open using net weight-delta trading to minimize turnover.
* **Holding Horizon:** 72-Hour Rebalanced Basket
* **Risk Management & Stops:** Frozen catastrophic bracket stop at `entry_price * (1 +/- 3.0 * ATR_1h_24)`.

---

## 6. Market and Dataset Requirements

* **Target Venue:** `BINANCE_UM_PERP`
* **Workstation Store Location:** `/home/quant/dev/quant/ml4t-data/.data/store/`
* **Data Loader:** Polars `pl.scan_parquet(sorted(store_dir.rglob("*.parquet"))).collect()`.
* **Warmup Requirements:** Continuous historical bars covering the full lookback formation window prior to initial signal generation.

---

## 7. Execution Assumptions and Estimated Costs

* **Taker Fee:** 5.0 bps per leg.
* **Slippage:** 4.0 bps per leg.
* **Total Round-Trip Friction:** 18.0 bps per leg.
* **Turnover Management:** Net weight-delta rebalancing minimizes redundant transaction churn.
* **Funding Settlement:** Point-in-time 8-hour funding cash transfers tracked directly in simulation.

---

## 8. Baseline and Primary Falsifier

* **Comparable Baseline:** Equal-weighted universe basket and standard benchmark buy-and-hold.
* **Primary Economic Falsifier:** The strategy is falsified if the return spread collapses when controlling for market beta or during low-volatility regimes.

---

## 9. Contradictory Evidence and Likely Failure Modes

* **Market-Wide Cascade Shocks:** Severe liquidity cascades can widen spreads and trigger intrabar bracket stops across multiple positions simultaneously.
* **Lookback Sensitivity:** Sub-optimal formation window lengths may capture noise rather than structural economic premiums.

---

## 10. Recommended Native ML4T Research Protocol

1. **Stage 1 (`ml4t.engineer`):** Construct feature pipeline via `create_dataset_builder` with zero lookahead.
2. **Stage 2 (`ml4t.diagnostic`):** Evaluate rank IC via `compute_ic_hac_stats` on train window (2019–2023) and apply `deflated_sharpe_ratio` multiple-testing adjustment.
3. **Stage 3 (`ml4t.backtest`):** Simulate portfolio in `Engine` with 18.0 bps round-trip friction and frozen 3.0x ATR bracket stops.

---

## 11. Implementation-Critical Unknowns

* **Unknown 1:** What is the optimal lookback smoothing window across varying macro volatility regimes?
* **Unknown 2:** Does volume-weighting or volatility-weighting portfolio legs improve risk-adjusted Sharpe over equal-weighted legs?

---

## 12. Smallest Decisive Research Experiment

* **Experiment:** Compute the factor ranking across the active liquid universe over 2019–2023. Run Fama-MacBeth cross-sectional regressions against forward returns.
* **Decisive Hurdle:** Factor risk premium coefficient must remain positive and statistically significant (HAC t-statistic > 2.0) after controlling for market beta.
