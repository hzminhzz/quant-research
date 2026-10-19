# crypto_xs_tvl_price_divergence_vfund_20261019_v1 — on-chain TVL–token-price divergence

**Disposition:** HANDOFF_VALID_UNVERIFIED only if the installed native structural validator passes. This is a descriptive capture, not a test or executable approval.

**SOURCE_FACT.** In the original [VFund implementation](https://github.com/Abdirahmanjabdi/VFund/blob/main/vfund/strategy/cross_sectional.py), `TVLDivergence(lookback=60)` scores crypto protocols by `(TVL[t]/TVL[t-60]-1) - (price[t]/price[t-60]-1)`. The class ranks high scores for the long leg and low scores for the short leg within a generic cross-sectional engine. The data and study are daily. Exactly which instruments qualified, which portfolio weighting and rebalance parameters were used, and the per-asset financing are not independently verified.

**AUTHOR_REPORTED_TEST_UNVERIFIED.** The [author's case study](https://github.com/Abdirahmanjabdi/VFund/blob/main/docs/CASE_STUDY.md) reports standalone in-sample Sharpe **1.09** and out-of-sample Sharpe **0.44**, while reporting that naive TVL momentum failed. These are not local replication, economic qualification, or a claim of future profit.

**LOCAL_INFERENCE.** Lagged protocol adoption relative to token price is a different information set from price momentum. However, TVL may merely mark assets at moving token prices, comprise short-lived incentives, and be revised or available late. Today's API records are not proof of what was knowable in past decisions.

**ADAPTATION_PROPOSAL.** An hourly execution layer could use only verified historical daily TVL vintages, but this is not the author's backtested clock. Do not invent token-to-protocol mappings, rank cutoffs, costs or funding assumptions.

**Falsifier:** a correctly lagged, point-in-time, borrowable-universe, full-cost comparison fails to outperform TVL-only and price-only ranking after the same risk and capacity rules. No future test was run here.

**Constraints:** Crypto CFD/perp broker availability UNKNOWN; financing remains payable when assessed; no funding/carry/basis-based signal; financing, shorting, trailing DD and daily DD remain blockers. No training, IC, Stage 1–4, holdout, orders, or accounts were touched.