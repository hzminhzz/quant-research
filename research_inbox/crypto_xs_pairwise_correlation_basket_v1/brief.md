# Research Handoff: Cross-Sectional Pairwise Correlation Integration & Diversification Risk Premium Basket

**Candidate ID:** `crypto_xs_pairwise_correlation_basket_v1`  
**Selection Family:** `cross_sectional_risk_premia`  
**Status:** `THESIS_READY_UNVERIFIED`  
**Research Mode:** `THESIS_DESIGN_ONLY`  
**Created On:** 2026-10-17  

---

## 1. Executive Thesis

Average pairwise return correlation across the cross-section (rho_bar_i = (1 / (N - 1)) * sum_{j != i} Corr(r_i, r_j) over trailing 30 days) measures an altcoin's systemic market integration and portfolio diversification capacity; altcoins that move in lockstep with the broad market cross-section provide zero diversification to institutional portfolios and trade at deep valuation discounts, yielding an equilibrium forward return premium during calm holding periods. Conversely, altcoins with low average correlation serve as cross-asset diversifiers and trade at persistent valuation premiums. A dollar-neutral 72h basket longing high-correlation altcoins and shorting low-correlation altcoins harvests this correlation risk premium while neutralizing market beta.

This strategy targets Top 40 liquid perpetuals (ex-BTC) + BTCUSDT_PERP benchmark with a 72-Hour Rebalanced Basket execution cycle. Grounded in empirical asset pricing and market microstructure, the strategy harvests a persistent structural risk premium while mitigating directional market exposure.

---

## 2. Original Author, Links and Publication Details

* **Pollet & Wilson (2010), The Review of Financial Studies**: *Average Correlation and Stock Market Returns*. [Source URL](https://ideas.repec.org/a/oup/rfinst/v23y2010i8p2919-2959.html)
* **Driessen, Maenhout & Vilkov (2009), The Journal of Finance**: *The Price of Correlation Risk*. [Source URL](https://ideas.repec.org/a/bla/jfinan/v64y2009i3p1371-1406.html)
* **Buraschi, Trojani & Vedolin (2014), The Review of Financial Studies**: *Economic Uncertainty, Disagreement, and Credit Markets*. [Source URL](https://ideas.repec.org/a/oup/rfinst/v27y2014i10p2807-2840.html)
* **Pindza (2026), Frontiers in Blockchain**: *Microstructure alpha: hierarchical learning and cross-asset transfer in cryptocurrency markets*. [Source URL](https://www.frontiersin.org/journals/blockchain/articles/10.3389/fbloc.2026.1811716/full)

---

## 3. Original Reported Performance — Explicitly Marked as Third-Party Claims

* **Published Academic Claims:** Prior literature documents statistically significant predictive return spreads (t-statistic > 2.5) across equity or cryptocurrency cross-sections before transaction costs. *(Third-party claims; unverified on our proprietary execution environment).*
* **Current Status:** `THESIS_READY_UNVERIFIED`. No proprietary backtest or implementation has been conducted.

---

## 4. Economic Mechanism and Counterparty

* **Economic Mechanism:** Grounded in Pollet & Wilson (2010), Driessen, Maenhout & Vilkov (2009), and Buraschi, Trojani & Vedolin (2014), an asset's average pairwise correlation with all other assets in the investment universe (rho_bar_i = (1 / (N - 1)) \* sum\_{j != i} Corr(r_i, r_j)) quantifies its systemic market integration and portfolio diversification value; altcoins exhibiting high average pairwise correlation provide zero diversification to multi-asset portfolios, acting as redundant systemic risk conduits and trading at deep structural valuation discounts. Conversely, altcoins with low average correlation provide powerful idiosyncratic diversification and trade at structural valuation premiums. Longing high-pairwise-correlation altcoins (high systemic integration discount) and shorting low-pairwise-correlation altcoins (diversification haven premium) in a 72h dollar-neutral basket captures the cross-sectional correlation risk premium while eliminating directional market beta.
* **Counterparty Payer:** Risk-averse multi-asset institutional desks overpaying for idiosyncratic diversifiers while dumping highly integrated altcoins at steep valuation haircuts.
* **Persistence Rationale:** Portfolio balance theory: correlation risk is priced because investors cannot eliminate systemic cross-asset co-movement through internal diversification alone.

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
