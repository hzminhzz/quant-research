# Research Handoff: Cross-Sectional Amihud Illiquidity Innovation Shock & Liquidity Momentum Basket

**Candidate ID:** `crypto_xs_illiquidity_innovation_basket_v1`  
**Selection Family:** `cross_sectional_risk_premia`  
**Status:** `THESIS_READY_UNVERIFIED`  
**Research Mode:** `THESIS_DESIGN_ONLY`  
**Created On:** 2026-10-17  

---

## 1. Executive Thesis

Asset pricing reacts primarily to unanticipated innovations in liquidity rather than static illiquidity levels; altcoins experiencing an acute positive illiquidity shock (Delta_Illiq_i,t = (Illiq_7d - Illiq_30d) / sigma_30d >= +1.5) suffer severe forced institutional selling into thin order books, depressing prices below fair value. As quotes are replenished and order books normalize, these discounted tokens experience persistent upward mean-reverting drift. Conversely, altcoins experiencing rapid liquidity deepening attract retail crowding and trade at a premium. A dollar-neutral 72h basket longing acute illiquidity shock altcoins and shorting liquidity deepening altcoins captures this recovery premium while eliminating market beta.

This strategy targets Top 40 liquid perpetuals (ex-BTC) + BTCUSDT_PERP benchmark with a 72-Hour Rebalanced Basket execution cycle. Grounded in empirical asset pricing and market microstructure, the strategy harvests a persistent structural risk premium while mitigating directional market exposure.

---

## 2. Original Author, Links and Publication Details

* **Acharya & Pedersen (2005), Journal of Financial Economics**: *Asset pricing with liquidity risk*. [Source URL](https://ideas.repec.org/a/eee/jfinec/v77y2005i2p375-410.html)
* **Chordia, Roll & Subrahmanyam (2001), The Journal of Finance**: *Market Liquidity and Trading Activity*. [Source URL](https://ideas.repec.org/a/bla/jfinan/v56y2001i2p501-530.html)
* **Goyenko, Holden & Trzcinka (2009), Journal of Financial Economics**: *Do liquidity measures measure liquidity?*. [Source URL](https://ideas.repec.org/a/eee/jfinec/v92y2009i2p153-181.html)
* **Pindza (2026), Frontiers in Blockchain**: *Microstructure alpha: hierarchical learning and cross-asset transfer in cryptocurrency markets*. [Source URL](https://www.frontiersin.org/journals/blockchain/articles/10.3389/fbloc.2026.1811716/full)

---

## 3. Original Reported Performance — Explicitly Marked as Third-Party Claims

* **Published Academic Claims:** Prior literature documents statistically significant predictive return spreads (t-statistic > 2.5) across equity or cryptocurrency cross-sections before transaction costs. *(Third-party claims; unverified on our proprietary execution environment).*
* **Current Status:** `THESIS_READY_UNVERIFIED`. No proprietary backtest or implementation has been conducted.

---

## 4. Economic Mechanism and Counterparty

* **Economic Mechanism:** Grounded in Acharya & Pedersen (2005) and Chordia, Roll & Subrahmanyam (2001), asset prices react strongly to unanticipated liquidity innovations rather than static levels; altcoins suffering an acute unexpected illiquidity shock (trailing 7-day average Amihud ratio surging far above trailing 30-day baseline, standardized by illiquidity volatility: Delta_Illiq = (Illiq_7d - Illiq_30d) / sigma(Illiq_30d) >= +1.5) face forced institutional risk-reduction liquidations into dry books, depressing market price to a severe fire-sale discount. Once stabilized, market makers replenish quotes, generating robust upward recovery drift. Longing acute illiquidity shock altcoins (high recovery discount) and shorting liquidity deepening altcoins (overbought havens) in a 72h dollar-neutral basket captures this liquidity shock recovery premium while eliminating directional market beta.
* **Counterparty Payer:** Distressed institutional sellers dumping positions into illiquid books and retail momentum chasers overpaying for temporarily liquid, crowded tokens.
* **Persistence Rationale:** Capital friction and risk limits: designated market makers do not instantaneously restore deep quote depth across mid-cap crypto perpetuals, allowing price recovery to drift over 72 hours.

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
