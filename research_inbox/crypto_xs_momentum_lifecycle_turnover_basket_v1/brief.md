# Research Handoff: Cross-Sectional Momentum Life Cycle & Volume Turnover Exhaustion Basket

**Candidate ID:** `crypto_xs_momentum_lifecycle_turnover_basket_v1`  
**Selection Family:** `cross_sectional_risk_premia`  
**Status:** `THESIS_READY_UNVERIFIED`  
**Research Mode:** `THESIS_DESIGN_ONLY`  
**Created On:** 2026-10-16  

---

## 1. Executive Thesis

Price momentum accompanied by abnormally high trading turnover reflects retail attention saturation and liquidity exhaustion prone to sharp reversals, whereas momentum accompanied by low turnover reflects stealth institutional accumulation that continues to drift; longing low-turnover winners and shorting high-turnover winners in a dollar-neutral 72h basket captures the momentum lifecycle premium.

This strategy targets Top 40 liquid perpetuals (ex-BTC) + BTCUSDT_PERP benchmark with a 72-Hour Rebalanced Basket execution cycle. Grounded in empirical asset pricing and market microstructure, the strategy harvests a persistent structural risk premium while mitigating directional market exposure.

---

## 2. Original Author, Links and Publication Details

* **Lee & Swaminathan (2000), The Journal of Finance**: *Price Momentum and Trading Volume*. [Source URL](https://ideas.repec.org/a/bla/jfinan/v55y2000i5p2017-2069.html)
* **Campbell, Grossman & Wang (1993), The Quarterly Journal of Economics**: *Trading Volume and Serial Correlation in Stock Returns*. [Source URL](https://ideas.repec.org/a/oup/qjecon/v108y1993i4p905-39.html)
* **Pindza (2026), Frontiers in Blockchain**: *Deep reinforcement learning for cryptocurrency trading*. [Source URL](https://www.frontiersin.org/journals/blockchain/articles/10.3389/fbloc.2026.1811716/full)

---

## 3. Original Reported Performance — Explicitly Marked as Third-Party Claims

* **Published Academic Claims:** Prior literature documents statistically significant predictive return spreads (t-statistic > 2.5) across equity or cryptocurrency cross-sections before transaction costs. *(Third-party claims; unverified on our proprietary execution environment).*
* **Current Status:** `THESIS_READY_UNVERIFIED`. No proprietary backtest or implementation has been conducted.

---

## 4. Economic Mechanism and Counterparty

* **Economic Mechanism:** Grounded in Lee & Swaminathan (2000) and Campbell, Grossman & Wang (1993), trading volume reveals the stage of an asset's speculative momentum lifecycle; longing low-turnover early-stage winners (quiet institutional accumulation) and shorting high-turnover late-stage winners (retail mania blow-off tops) in a 72h dollar-neutral basket captures post-exhaustion momentum rotation alpha.
* **Counterparty Payer:** Late-stage retail momentum buyers chasing high-volume breakout hype and liquidity-constrained traders forced to unwind crowded positions.
* **Persistence Rationale:** Attention dynamics: institutional accumulation deliberately minimizes market impact and volume footprint, while retail herds generate explosive volume spikes right before buyer exhaustion.

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
