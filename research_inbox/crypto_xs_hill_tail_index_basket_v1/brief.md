# Research Handoff: Cross-Sectional Extreme Value Theory Hill Tail Index Risk Premium Basket

**Candidate ID:** `crypto_xs_hill_tail_index_basket_v1`  
**Selection Family:** `cross_sectional_risk_premia`  
**Status:** `THESIS_READY_UNVERIFIED`  
**Research Mode:** `THESIS_DESIGN_ONLY`  
**Created On:** 2026-10-17  

---

## 1. Executive Thesis

The Hill (1975) tail index (alpha_i) non-parametrically estimates the Pareto power-law exponent of negative return tails over trailing 30 days; altcoins with heavy Pareto tails (low alpha_i, indicating slow polynomial decay and severe extreme crash probability) impose unhedgeable gap risk on risk-averse market participants. In equilibrium, these crash-prone assets trade at deep structural valuation discounts, yielding an elevated forward risk premium during subsequent calm holding regimes. A dollar-neutral 72h basket longing low-Hill-index altcoins (Quintile 1: heavy tails, high risk discount) and shorting high-Hill-index altcoins (Quintile 5: thin tails, valuation premium) harvests this extreme value tail risk premium while neutralizing directional Bitcoin market beta.

This strategy targets Top 40 liquid perpetuals (ex-BTC) + BTCUSDT_PERP benchmark with a 72-Hour Rebalanced Basket execution cycle. Grounded in empirical asset pricing and market microstructure, the strategy harvests a persistent structural risk premium while mitigating directional market exposure.

---

## 2. Original Author, Links and Publication Details

* **Hill (1975), The Annals of Statistics**: *A Simple General Approach to Inference About the Tail of a Distribution*. [Source URL](https://projecteuclid.org/journals/annals-of-statistics/volume-3/issue-5/A-Simple-General-Approach-to-Inference-About-the-Tail/10.1214/aos/1176343247.full)
* **Kelly & Jiang (2014), The Review of Financial Studies**: *Tail Risk and Asset Prices*. [Source URL](https://ideas.repec.org/a/oup/rfinst/v27y2014i10p2841-2871.html)
* **Gabaix (2009), Annual Review of Economics**: *Power Laws in Economics and Finance*. [Source URL](https://ideas.repec.org/a/anr/reveco/v1y2009i1p255-294.html)
* **Pindza (2026), Frontiers in Blockchain**: *Microstructure alpha: hierarchical learning and cross-asset transfer in cryptocurrency markets*. [Source URL](https://www.frontiersin.org/journals/blockchain/articles/10.3389/fbloc.2026.1811716/full)

---

## 3. Original Reported Performance — Explicitly Marked as Third-Party Claims

* **Published Academic Claims:** Prior literature documents statistically significant predictive return spreads (t-statistic > 2.5) across equity or cryptocurrency cross-sections before transaction costs. *(Third-party claims; unverified on our proprietary execution environment).*
* **Current Status:** `THESIS_READY_UNVERIFIED`. No proprietary backtest or implementation has been conducted.

---

## 4. Economic Mechanism and Counterparty

* **Economic Mechanism:** Grounded in Hill (1975), Kelly & Jiang (2014), and Gabaix (2009), the Hill tail index (alpha_i = (1 / k) \* sum\_{j=1}^k ln(x\_{(j)} / x\_{(k+1)})^{-1}) measures the Pareto power-law tail thickness of an asset's left-tail return distribution; altcoins with heavy Pareto tails (low alpha_i <= 2.0) experience extreme, catastrophic crash drawdowns that inflict non-diversifiable utility penalties on risk-averse investors. To clear the market, these fat-tailed assets trade at deep structural valuation discounts, offering an elevated forward return premium during subsequent calm recovery windows. Longing fat-tailed altcoins (low Hill index / high crash discount) and shorting thin-tailed altcoins (high Hill index / tail safe havens) in a 72h dollar-neutral basket captures the extreme value theory tail risk premium while eliminating directional market beta.
* **Counterparty Payer:** Risk-averse institutional desks overpaying for thin-tailed, predictable variance assets while dumping power-law crash-prone altcoins at steep discounts.
* **Persistence Rationale:** Structural asset pricing: power-law tail risk cannot be eliminated via Gaussian diversification, ensuring an enduring equilibrium return premium for bearing extreme crash risk.

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
