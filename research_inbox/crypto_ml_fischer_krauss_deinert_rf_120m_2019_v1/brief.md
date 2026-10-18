# Fischer–Krauss–Deinert (2019): 120-minute cryptocurrency relative-performance Random Forest

**Candidate ID:** `crypto_ml_fischer_krauss_deinert_rf_120m_2019_v1`
**Status:** Source-only descriptive ML hypothesis; not executable or model-ready.
**Original paper:** Thomas Günter Fischer, Christopher Krauss, Alexander Deinert, *Statistical Arbitrage in Cryptocurrency Markets*, Journal of Risk and Financial Management, February 12, 2019. https://www.mdpi.com/1911-8074/12/1/31
**Adverse independent practitioner account:** Jackson Thorn, *Tauro*, https://www.thornlabs.io/crypto-arbitrage (2021 project revisited in 2024; website © 2026).

## Original mechanism and identity — SOURCE_FACT

The original 2019 study uses minute-binned observations from **40 cryptocurrency coins**, not a newly selected Binance perpetual basket. It trains a Random Forest to rank the probability of **outperforming the cross-sectional median over the next 120 minutes**, with a one-minute gap between prediction and execution. A market-relative portfolio **buys the top three and shorts the bottom three** forecast coins. The design opens overlapping 120-minute portfolio cohorts every minute. Source uses lagged returns at multiple lookbacks; the 60-minute return is especially important in the authors' explanatory comparison. The study also includes a simple logistic regression trained to classify the same target.

The paper's reported test window is June–September 2018, historically selected coins. Exact venue/product membership, borrowability, consolidated-source timestamps, skipped-order rules and real margin limitations must be separately established; no modern prop-firm permission is established here.

## ML versus simple benchmark — AUTHOR_TEST_UNVERIFIED

The authors report after their assumed **15 bps one-way** transaction costs: **7.1 bps average daily portfolio return for Random Forest versus 4.9 bps for logistic regression**, and annualized Sharpe 2.5 versus 1.4. These are *author-reported* and not independently reproduced. A future third comparator should be a simple short-term-return/reversal ranking under the same cohort clock, positions and costs. The published RF-versus-LR difference could arise from nonlinear conditioning, but market regime or short-leg selection could also explain it.

## Adverse evidence and deployment limitations — INDEPENDENT SOURCE REPORTED, NOT REPLICATED

Jackson Thorn reports a 2024 retail-cost variant failed after fees: profitable longs, bleeding shorts in a bull market, and rapid execution-decay. **This is not an exact replication**: the account explicitly changes data source, feature windows, random-forest size/regularization, stop losses, cost conventions, and portfolio compounding. It also omits the logistic baseline. The practitioner highlights source-reported RF performance decaying as order delay increases, with little measurable advantage by four or five minutes. That places this research far closer to latency-sensitive intraday stat-arb than ordinary 15-minute to hourly prop trading.

## Causality and future scientific gate — PROPOSED_ADAPTATION, NOT PERFORMED

Any future model training would need historically valid universe membership, fold-local feature construction, mature 120-minute labels, chronological purged walk-forward **out-of-fold predictions**, immutable artifact hashes and calibration provenance. Future performance comparison must match account cost schedules, slippage, financing and short availability. ATS return-IC and basket testing do **not** train RF or prove this event-overlap strategy. Current discovery is **REQUIRES_TRAINING_WORKFLOW / BLOCKED_DATA / BLOCKED_PROTOCOL**.

## Audit and limitations

Source-content SHA-256 is **UNKNOWN** because an immutable fetched original artifact was not preserved by this task. Source URL/DOI and provenance are explicit; staging file SHA-256 hashes must be computed after writing. No historical model scores or market returns were computed in this task. Funding, basis and carry signals are **not** features; future short financing remains unknown.

**SOURCE_CAPTURE_ONLY:** zero model training, prediction generation, empirical tests, ATS runner interactions, protected reads and orders.
