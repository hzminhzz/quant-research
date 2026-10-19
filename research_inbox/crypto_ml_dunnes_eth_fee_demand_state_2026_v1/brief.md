# crypto_ml_dunnes_eth_fee_demand_state_2026_v1

**Source-only discovery — HANDOFF_VALID_UNVERIFIED if native flat validator passes; never an executable/approved strategy.**

## Source identity and evidence types
- **SOURCE_FACT:** Lucas Dünnes and Jens Felsenstein-Eckberg, *Demand-Side Fee Flows and Return Predictability on Ethereum*, written June 26, 2026, SSRN posted July 18, 2026: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7003998 .
- **SOURCE_FACT (author's method):** https://www.majorkeycapital.com/ethereum/valuation-terminal/methodology describes daily ETH-denominated fees / circulating ETH, smoothed over 30 trailing days versus 90-day trailing fee-intensity median, log deviation; demand changes after the March 13, 2024 Dencun hard fork. This webpage is author-owned, commercially promotional, not an independent replication.
- **AUTHOR_TEST_UNVERIFIED:** The authors claim 14.4% expanding-window out-of-sample R² for 45-day future ETH returns, 22.8% in-sample R² at the same horizon, and 76.4% directional accuracy on their author methodology page. These are forecasting metrics, not after-cost returns or a trained ML model beating a baseline.
- **LOCAL_INFERENCE:** Fee-demand persistence and market-state asymmetries might introduce nonlinear incremental information beyond the source's simple signal. The same economics could be wholly captured by a linear fee-deviation model.
- **PROPOSED_ADAPTATION:** Only a future, separately authorized, shallow nonlinear ETH forward-return forecast using causal lagged fee-state interactions; no synthetic cross-sectional basket, no new alpha from funding or carry.
- **UNKNOWN:** Full publisher PDF bytes, original source code/data, exact prediction/fill/timezone clocks, venue/product, ETF-like effect for other crypto assets, after-cost profitability and historical supply revisions. Do not fill these from assumptions.

## Why screen this instead of a duplicate
Main's 112 folders contain price/rank, orderflow, funding, volatility and latent-factor families, but no exact ETH protocol-fee demand hypothesis. Research refs from local and remote branches were searched for SSRN 7003998 and 'ETH fee demand' with no match. This is source-level novel within the checked refs, not a guarantee against unenumerated peer drafts. It is a **single-name ETH** hypothesis, not a relative-value basket.

## Economic contract and minimum later benchmark
Original horizon is **10–60 days**, strongest author claim at **45 days**. The exploratory horizon would be 45 calendar days with the earliest post-publication decision and next defensible ETH execution price; neither fill convention nor threshold is chosen here. Baselines must be the source fee-deviation measure, fixed fee rule, linear/Ridge fee forecast, ETH momentum and buy-and-hold, all with the exact same sample, label maturity, exposure and costs. A shallow tree only qualifies if independently generated chronological, purged OOF predictions improve cost-matched forecasting and resulting net utility. With overlapping 45-day labels and a short post-Dencun sample, low effective N is a primary falsifier, not permission to tune.

## Provenance and blockers
SSRN primary landing-page abstract accessed through indexed web result; the publisher's PDF was not obtained. Original publisher-byte SHA-256 **UNKNOWN**. File hashes below are capture-artifact hashes and are not proof of paper provenance. Chain fee/supply vintages, 30/90-day transform exactness, OOF training/embargo, score-to-position and venue transaction costs are prerequisites to any native research. Current disposition: **BLOCKED_DATA / REQUIRES_TRAINING_WORKFLOW**.

Zero training, predictions, SHAP, IC/HAC, backtests, stage runs, holdout reads and orders.
