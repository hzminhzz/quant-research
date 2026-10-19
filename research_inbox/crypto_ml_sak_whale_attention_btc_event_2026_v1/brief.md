# BTC whale activity and lagged retail attention: source-only event research

Candidate ID: `crypto_ml_sak_whale_attention_btc_event_2026_v1`. Status: descriptive only, not executable.

**Primary source:** Ahmet Furkan Sak, *Whales And Retail Attention: Dual Channels of Bitcoin Return Dynamics*, JOEEP 11(1), 465–474, June 25 2026. https://dergipark.org.tr/en/pub/joeep/article/1837177

**SOURCE_FACT:** Author studies BTC event observations, top 100 non-custodial wallet transfers and normalized Google Trends. Study reports 2,647 daily observations (January 2018–March 2025) and event horizons 1, 7, 14, 28 days. Exact trading venue and causal signal-release time UNKNOWN.

**AUTHOR_TEST_UNVERIFIED:** The abstract attributes whale-event vs non-event return differentials of +0.79 percentage points (7d), +1.66 (14d), +2.44 (28d). Attention events are associated with +1.76 (14d), +2.36 (28d). These are statistical event comparisons, not actual cost-adjusted executable profits.

**LOCAL_INFERENCE:** Transactions and slower-growing public attention may interact to identify continuation vs reversal. Endogeneity and overlap could entirely explain event differences.

**PROPOSED_ADAPTATION:** An event-level BTC-only classifier predicting whether an observed whale event earns a positive **after-cost** forward outcome, with horizon matching source evidence. Compare against first-observable whale-only fixed threshold, Google-only rule and logistic interaction; a shallow boosted tree needs genuine incremental OOF benefits. Position/sizing/entry threshold not yet specified. Do NOT replace the BTC signal with a basket.

**UNKNOWN and stop conditions:** Top-100 wallet historical PIT membership may reflect future wallets; Google Trends restatements/release clocks unknown; original event triggers, earliest venue fill, 1/7/14/28-day return clocks and overlapping event outcomes require original-text/source-data recovery. No model trained, backtest executed, empirical IC, holdout read, ATS stage, order or execution authorized. BLOCKED_DATA, BLOCKED_PROTOCOL, REQUIRES_TRAINING_WORKFLOW. Capture file SHA-256 does not verify publisher document bytes.
