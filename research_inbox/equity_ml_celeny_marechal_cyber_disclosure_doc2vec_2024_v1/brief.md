# Celeny–Maréchal: semantic cybersecurity risk premium (source capture)

**Candidate ID:** `equity_ml_celeny_marechal_cyber_disclosure_doc2vec_2024_v1`
**Authority:** source-faithful descriptive handoff only; `HANDOFF_VALID_UNVERIFIED` if strict validator passes. No models, backtests, ATS trials or orders.

**Primary source:** Daniel Celeny and Loïc Maréchal, *Cyber risk and the cross-section of stock returns*, arXiv:2402.04775v2 (March 5, 2024); https://arxiv.org/html/2402.04775 . Author project page: https://www.loicmarechal.dev/project/internal-project10/ . Source accessed October 18, 2026.

## SOURCE_FACT — actual strategy and economic mechanism

The original study uses US-listed equities with SEC 10-K disclosures, CRSP/Compustat and 2007–2022 monthly data. An unsupervised Paragraph Vector (Doc2Vec) representation compares full 10-K paragraphs with MITRE ATT&CK descriptions. The 10-K score is the average of its top 1% highest-scoring paragraphs by maximum positive semantic similarity. The authors assign stocks to five value-weighted cyber-score quintiles using their latest filing and rebalance quarterly; the high-minus-low quintile is the original long/short return-spread test. This is a **cyber-risk-factor** strategy, not next-hour crypto return regression.

## AUTHOR_TEST_UNVERIFIED — what the source reports, not reproduced performance

The authors report 18.72% annual excess return for the high-cyber-risk quintile and 6.93% annual excess return for high-minus-low, controlling for common stock factors. Their semantic score identifies contextual risk missed by an existing keyword/dictionary comparator, especially in paragraphs outside the usual risk section. These are source-reported **risk premia**, not verified after-cost brokerage profits or independent causal estimates.

## LOCAL_INFERENCE and incremental ML rationale

The nonlinear semantic feature may capture cybersecurity exposure missed by word lists and traditional equity characteristics, adding a *measurement* benefit. Cyber risk being compensated is different from discovering market inefficiency. A trained supervised forward-return model is **not** part of the original authors' claim. There is no justification to translate this into crypto basket alpha.

## Proposed independent future checks — NOT RUN

Benchmark against the Florackis dictionary cyber score and conventional factors using the identical historical stocks, filing availability, quintile weights, quarterly refresh and borrow/transaction costs. Treat the actual SEC timestamp, MITRE and Doc2Vec training-vintage provenance, delistings, liquidity and shortability as first-class scientific preconditions. If a return-predicting ML model is later proposed, require immutable fold-local preprocessing and chronological OOF predictions with label overlap control. ATS generic cross-sectional IC/HAC does not perform NLP training or certify this factor-pricing study.

**Status:** BLOCKED_DATA / REQUIRES_TRAINING_WORKFLOW / BLOCKED_PROTOCOL for source-faithful reproduction until the source equities and type-specific scientific checks are qualified. Prop-firm stock permissions, margin/borrowing fees and execution are UNKNOWN. This work contains no funding-rate, basis or carry alpha.
