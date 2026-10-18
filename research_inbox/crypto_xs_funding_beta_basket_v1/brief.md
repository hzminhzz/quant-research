# Research Handoff: Cross-Sectional Systematic Funding Beta & Deleveraging Risk Premium Basket

**Candidate ID:** `crypto_xs_funding_beta_basket_v1`  
**Selection Family:** `cross_sectional_risk_premia`  
**Status:** `THESIS_READY_UNVERIFIED`  
**Research Mode:** `THESIS_DESIGN_ONLY`  
**Created On:** 2026-10-17  

---

## 1. Executive Thesis

Systematic funding beta (beta^F_i = Cov(r_{i,t}, Delta F_{m,t}) / Var(Delta F_{m,t}) over trailing 30 days) non-parametrically quantifies an altcoin's price sensitivity to aggregate market leverage shocks; altcoins with elevated positive funding beta crash violently during market-wide deleveraging spirals, imposing severe collateral margin haircuts on investors. In equilibrium, rational market participants demand an elevated return premium to hold high-funding-beta assets. A dollar-neutral 72h basket longing high-funding-beta altcoins and shorting low-funding-beta altcoins captures this systematic funding liquidity risk premium while neutralizing directional Bitcoin market beta.

This strategy targets Top 40 liquid perpetuals (ex-BTC) + 660+ funding series + BTCUSDT_PERP benchmark with a 72-Hour Rebalanced Basket execution cycle. Grounded in empirical asset pricing and market microstructure, the strategy harvests a persistent structural risk premium while mitigating directional market exposure.

---

## 2. Original Author, Links and Publication Details

* **Brunnermeier & Pedersen (2009), The Review of Financial Studies**: *Market Liquidity and Funding Liquidity*. [Source URL](https://ideas.repec.org/p/nbr/nberwo/12939.html)
* **Schmeling, Schrimpf & Todorov (2023), BIS Working Papers**: *Crypto carry*. [Source URL](https://ideas.repec.org/p/bis/biswps/1087.html)
* **Adrian & Shin (2010), Journal of Financial Intermediation**: *Liquidity and leverage*. [Source URL](https://ideas.repec.org/a/eee/jfinin/v19y2010i3p418-437.html)
* **Pindza (2026), Frontiers in Blockchain**: *Microstructure alpha: hierarchical learning and cross-asset transfer in cryptocurrency markets*. [Source URL](https://www.frontiersin.org/journals/blockchain/articles/10.3389/fbloc.2026.1811716/full)

---

## 3. Original Reported Performance — Explicitly Marked as Third-Party Claims

* **Published Academic Claims:** Prior literature documents statistically significant predictive return spreads (t-statistic > 2.5) across equity or cryptocurrency cross-sections before transaction costs. *(Third-party claims; unverified on our proprietary execution environment).*
* **Current Status:** `THESIS_READY_UNVERIFIED`. No proprietary backtest or implementation has been conducted.

---

## 4. Economic Mechanism and Counterparty

* **Economic Mechanism:** Grounded in Brunnermeier & Pedersen (2009) and Schmeling, Schrimpf & Todorov (2023), market liquidity and funding liquidity are mutually reinforcing; altcoins whose price returns exhibit high positive sensitivity to market-wide funding rate shocks (systematic funding beta beta^F_i = Cov(r_i, Delta F_m) / Var(Delta F_m)) suffer severe collateral destruction and margin liquidations when market leverage contracts. Because systemic deleveraging risk is non-diversifiable within crypto perpetuals, high-funding-beta altcoins trade at deep structural valuation discounts, yielding an equilibrium risk premium during subsequent calm holding windows. Longing high-funding-beta altcoins (high deleveraging discount) and shorting low-funding-beta altcoins (leverage havens) in a 72h dollar-neutral basket captures this systematic funding liquidity risk premium while eliminating directional market beta.
* **Counterparty Payer:** Risk-averse institutional desks overpaying for low-funding-beta tokens to protect collateral margins while dumping high-funding-beta tokens at deep fire-sale discounts.
* **Persistence Rationale:** Structural asset pricing: funding liquidity risk is non-diversifiable across leveraged crypto derivatives, ensuring an enduring equilibrium return premium for bearing systemic deleveraging risk.

---

## 5. Exact Deterministic Strategy Rules

* **Universe:** Top 40 liquid perpetuals (ex-BTC) + 660+ funding series + BTCUSDT_PERP benchmark
* **Timeframe:** 1h bars + 8h funding settlements
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
