# Research Handoff: Volatility-Managed Time-Series Momentum

**Candidate ID:** `crypto_vol_managed_tsmom_v1`  
**Selection Family:** `time_series_trend_momentum`  
**Status:** `THESIS_READY_UNVERIFIED`  
**Research Mode:** `THESIS_DESIGN_ONLY`  
**Created On:** 2026-10-15  

---

## 1. Executive Thesis

Scaling 20-day trend exposure out during high-volatility spikes eliminates momentum crash tails while participating in steady macro bull runs.

This strategy targets BTCUSDT_PERP (resampled daily) with a Multi-Day Swing (5 to 20 days) execution cycle. Grounded in empirical asset pricing and market microstructure, the strategy harvests a persistent structural risk premium while mitigating directional market exposure.

---

## 2. Original Author, Links and Publication Details

* **Moreira & Muir (2017), Barroso & Santa-Clara (2015), Daniel & Moskowitz (2016)**: *Volatility-Managed Portfolios*. [Source URL](https://www.researchgate.net/publication/315972283_Volatility-Managed_Portfolios)

---

## 3. Original Reported Performance — Explicitly Marked as Third-Party Claims

* **Published Academic Claims:** Prior literature documents statistically significant predictive return spreads (t-statistic > 2.5) across equity or cryptocurrency cross-sections before transaction costs. *(Third-party claims; unverified on our proprietary execution environment).*
* **Current Status:** `THESIS_READY_UNVERIFIED`. No proprietary backtest or implementation has been conducted.

---

## 4. Economic Mechanism and Counterparty

* **Economic Mechanism:** 20-day time-series momentum scaled inversely by trailing realized volatility to eliminate momentum crash tails.
* **Counterparty Payer:** Risk-averse hedgers, noise traders, and forced margin liquidators.
* **Persistence Rationale:** Structural market frictions, margin limits to arbitrage, and non-diversifiable risk constraints.

---

## 5. Exact Deterministic Strategy Rules

* **Universe:** BTCUSDT_PERP (resampled daily)
* **Timeframe:** 1h bars
* **Signal Computation:** Evaluated at closed bar boundary.
* **Execution Timing:** NEXT_BAR open using net weight-delta trading to minimize turnover.
* **Holding Horizon:** Multi-Day Swing (5 to 20 days)
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
* **Total Round-Trip Friction:** 14.0 bps per leg.
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
3. **Stage 3 (`ml4t.backtest`):** Simulate portfolio in `Engine` with 14.0 bps round-trip friction and frozen 3.0x ATR bracket stops.

---

## 11. Implementation-Critical Unknowns

* **Unknown 1:** What is the optimal lookback smoothing window across varying macro volatility regimes?
* **Unknown 2:** Does volume-weighting or volatility-weighting portfolio legs improve risk-adjusted Sharpe over equal-weighted legs?

---

## 12. Smallest Decisive Research Experiment

* **Experiment:** Compute the factor ranking across the active liquid universe over 2019–2023. Run Fama-MacBeth cross-sectional regressions against forward returns.
* **Decisive Hurdle:** Factor risk premium coefficient must remain positive and statistically significant (HAC t-statistic > 2.0) after controlling for market beta.
