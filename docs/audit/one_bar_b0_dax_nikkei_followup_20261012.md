# B0 cross-index: DAX source repair and Nikkei execution validation

Research date: 2026-10-12. Scope: approved follow-up to Phase 3/4.
Status: **DAX SOURCE REPAIR BLOCKED**; **NIKKEI EXECUTION INCONCLUSIVE**.
No changes to promoted `promote/one_bar_nq_30m/` or any canonical ML4T data store. No new strategy backtest, no live orders, no commit or push.

## Procedure and immutable baseline

Use the repository's ML4T skill guidance: `ml4t-validate-data`, `ml4t-polars-patterns`, `ml4t-calendar-ops`, `ml4t-point-in-time`, `ml4t-lookahead-bias`, `ml4t-run-backtest`, and `ml4t-cost-model`. Use lazy Polars data inspection and the already recorded native `ml4t.backtest.Engine` trade/fill ledgers. No new signal or trading simulation was invented.

The reference B0 is unchanged: 50 previous complete 30-minute-bar breakout, 50-index-point stop, exit at the next 30-minute bar open, two entries per Chicago session, long and short, no indicators, ATR, new sizing, or price-percent stop. All outcomes through July 14, 2026 were already observed and are not a new holdout.

## DAX — source forensics

Provider authority from `ml4t-data/docs/lse-index-authority-plan.md` and the reference contracts: London Strategic Edge (LSE), `DE30/EUR`, canonical `index_minute_DAX`. An archive in `.data/archive/lse-index-refresh-20261005T112409Z/index_minute_DAX` was compared against the current canonical source.

In sampled months (December 2023, January 2024, September 2024, November 2024, July 2025, November 2025, January 2026, June 2026), archive and current monthly datasets share the same timestamps and **zero price differences over the paired rows**. A rollback does not fix the defect. Historical Dukascopy rebuilding stores have no 2024 data and were explicitly retired as current authority.

The current LSE DAX source switches between the ~600–900 and ~17,000–25,000 price levels. The full original forensics found **1,000 adjacent price jumps over 25%** from 2024 through July 2026. The expected five-digit scale is supported by separate daily DAX price records, but that daily series has unresolved provenance and duplicate date records. It is not a replacement 1-minute source.

A fixed **5,000-point floor**, below the uncontaminated 2013–2023 sample minimum, was used solely for forensic quarantine; no scaling/interpolation or signal rule was changed. It removes source rows whose OHLC values are below the floor. Do not use this rule as a production strategy feature. Complete 30-minute bins must still have all 30 genuine, chronological minutes.

| Year | Raw one-minute rows | Low-scale close rows | Original fully complete 30m bins | Fully complete bins retained after quarantine | Retention |
|---|---:|---:|---:|---:|---:|
| 2024 | 129,543 | 90,655 | 4,318 | 1,291 | 29.9% |
| 2025 | 142,787 | 115,945 | 4,596 | 726 | 15.8% |
| 2026 Jan–Jul14 | 162,622 | 43,326 | 5,012 | 3,567 | 71.2% |

Filtering would remove most 2024/2025 minutes and invalidate an uninterrupted executable B0 evaluation. **Do not run a 2024–2026 full DAX backtest on the filtered fragment and declare it a verified repair.** The original native DAX 2013–2023 +112.85R, Sharpe 0.98 remains provisional and is not affected by this source gate.

A limited independent Dukascopy `DEUIDXEUR` public-minute feed pilot was prepared for 2024-09-10, 2025-07-10 and 2026-06-17, but the VPS execution tool blocked the data-fetch command. It did **not** run; no HTTP result or independent replacement bar is available. Any future pilot must use an isolated output with retrieval hashes, and only a verified source with adequate coverage can replace the broken LSE intervals.

## Nikkei — execution validation

Source: LSE `JP225/USD` 1-minute index-price proxy (not exchange tick prints, BID/ASK, or the dated OSE Nikkei futures).

The local `data/processed/JP225_USD_5m_2017_2026.parquet` provides 5-minute OHLCV but **not an independent reconstruction**: **36,447 out of 36,447 matched complete 2026 five-minute windows** have identical open, high, low and close values to 1-minute data aggregated into five-minute bars. Reaggregating does not resolve tick ordering.

The 2026 native cost-aware ML4T ledger has 251 closed evaluation trades. **91 trades (36.3%)** crossed the entry and protective stop within the same minute according to the native ambiguity audit. The nominal 50-index-point stop was a median **0.0859% of price** at the 2026 entry level. These bar extrema cannot resolve whether a stop should have fired after entry.

| Nikkei 2026 | Net synthetic R |
|---|---:|
| Native one-minute ML4T replay | +64.11 |
| Pessimistic non-native ambiguity replacement | -19.78 |

The pessimistic result replaces every ambiguous trade's observed PnL by a -1R loss plus the illustrative round-trip cost, retaining other native trades. It is **not a second Engine replay, not an actual fill sequence and not a guaranteed loss bound**: gaps can be worse. The original 2013–2023 Nikkei +78.9R and the previous Monte Carlo are exploratory only. The 2026 positive result is **not robust to unobserved within-minute ordering**.

No 2026 Nikkei instrument-specific tick/BID/ASK store was found among the canonical source store names. The local 5-minute source is derived from the same vendor minute prices. Independent tradable-venue quotes or tick updates at the original event times are required to establish 2026 execution.

## Decision and next data gate

**DAX: BLOCKED**. Obtain a reliable, independently verified 2024–2026 1-minute price feed, confirm true market scale and historical provenance against external authoritative data, and quantify missing 30-minute decision/exit windows. Preserve the original price series, introduce a versioned replacement data manifest and make an explicit data-source trial entry. Do not substitute the archived equally contaminated files.

**Nikkei: INCONCLUSIVE**. Obtain timestamped trade or BID/ASK updates from the intended execution venue covering the ambiguous entry/stop minutes; verify contract type, multiplier, tick, 50-point stop semantics, OCO and commission/spread/slippage. Rerun original B0 through native ML4T Engine only once execution ordering can be modeled independently; maintain a complete ledger of changes. Do not promote based on the 2026 +64.11R figure.

**NQ:** original promoted B0 is preserved and its package integrity is verified independently.

## Artifacts

- DAX current-vs-archive: `run_log/one_bar_b0_cross_indices_20261012/followup_dax_nikkei_20261012/dax_source_comparison.json`
- DAX quarantine/coverage: `run_log/one_bar_b0_cross_indices_20261012/followup_dax_nikkei_20261012/dax_quality_repair_gate.json`
- Nikkei 1m/5m agreement and native ambiguity: `run_log/one_bar_b0_cross_indices_20261012/followup_dax_nikkei_20261012/nikkei_execution_validation.json`
- Original native results: `run_log/one_bar_b0_cross_indices_20261012/phase34/final_research_metrics.json`
- Original independent sensitivity: `run_log/one_bar_b0_cross_indices_20261012/phase34/intraminute_ambiguity_sensitivity.json`
- New forensic scripts: `scripts/inspect_b0_cross_followup_sources_20261012.py`, `scripts/gate_b0_cross_dax_source_20261012.py`, `scripts/validate_b0_cross_nikkei_execution_20261012.py`.

No model parameters or 2013–2023 clean DAX findings were refit. The later source defect was identified by absolute price-scale discontinuity, not by optimization of backtest returns.
