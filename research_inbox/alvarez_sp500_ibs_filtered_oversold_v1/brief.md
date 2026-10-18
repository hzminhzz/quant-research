# Internal Bar Strength for Mean Reversion

Candidate: `alvarez_sp500_ibs_filtered_oversold_v1`. Status: THESIS_CAPTURED, descriptive only.

Primary: Cesar Alvarez, 2022-02-16, https://alvarezquanttrading.com/blog/internal-bar-strength-for-mean-reversion/

SOURCE_FACT: Test S&P 500 member stocks. RSI(2) crosses below 2.5; stock closes above 200-day moving average; SPX 126-day return positive. Buy one share next open; sell next open after RSI(2) closes above 50. IBS=100*(close-low)/(high-low). Study adds low-IBS bucket filter to the same baseline, not an independent trading strategy.

SOURCE_REPORTED_TEST (not replicated): IBS <10 keeps 34% of eligible entries and increases average percentage per-trade return by 58%; IBS <25 keeps 63% with 21% improvement. Source is an all-trades study, NOT a portfolio with capital limits and transaction-cost qualification. A reader found extraneous historical-volatility ranking in an earlier text version, and Alvarez explicitly corrected it in comment dated Feb 28, 2022; no ranking applies to the all-trades study.

LOCAL_INFERENCE: A daily close near its low might indicate temporary closing-auction selling pressure conditional on an oversold RSI trigger. Counterparty and causal explanation UNKNOWN. Null: no incremental after-friction trade expectancy from IBS screening compared with same RSI2/SMA200/index-trend signals without IBS.

ADVERSE: Cutoffs selected after inspecting ten and four buckets, exposing selection bias; source author could not get IBS-only trading to work; all-trades signal-level diagnostics do not establish portfolio economics. Need point-in-time historical S&P 500 membership, full price and corporate actions, RSI smoothing/zero-range semantics, open fills and fees/spread/slippage.

ADAPTATION_PROPOSAL: None. Original common equities must not be silently mapped to an index CFD. Decision after daily close; earliest feasible next opening session. Size source one share for per-trade study; no portfolio sizing.

PRIMARY_FALSIFIER (future, NOT RUN): IBS<25 does not improve post-cost return per eligible RSI2 setup relative to the identical base selection rule after accounting for different coverage. Phase 3 event-conditioned signed-return study, not a fabricated independent stock rank IC.

Portfolio tags HYPOTHESES: equity oversold reversal, days horizon, net long stock market, likely overlaps other equity RSI mean reversion. No empirical correlation measured.
