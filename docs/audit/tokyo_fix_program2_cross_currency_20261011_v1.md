# Tokyo Fix / Gotobi — Program 2: Cross-Currency Settlement Flow

**Session:** `tokyo_fix_program2_cross_currency_20261011_v1`  
**Scope:** 2020-01-01 through 2026-08-31 JST  
**Date:** 2026-10-11  
**Decision:** **EXPLORATORY / NOT_APPROVED — NO QUALIFYING CROSS-CURRENCY STRATEGY**  
**Account for a qualifying native backtest:** USD 10,000 initial, gross exposure capped at USD 10,000. None met the preregistered gate, so no new native trade simulator was run.

## Executive conclusion

The event study identified one previously suggested association: a positive, statistically detectable calendar-controlled USDJPY movement from 07:00 to 08:30 JST on Gotobi days. The 16-test flow-family Holm-adjusted p-value was 0.0162. That observation does not identify exporter/importer demand, does not establish a broader USD factor, and is not a new out-of-sample discovery: Program 1 already inspected the historical sample.

Across **640 explicitly tracked cross-pair lead/lag predictive tests, none survived the Holm correction**. Simple USD-factor confirmation did not improve after-cost performance against the unfiltered Gotobi-short benchmark. A USD-neutral EURUSD/USDJPY hedge was not profitable at the illustrative per-leg costs. The independent JPY flow component remained **PARTIAL_UNIDENTIFIED** because the available JPY crosses came from a different historical vendor and quote basis.

No cross-pair strategy qualified for native `ml4t.backtest.Engine` execution. This is a valid negative strategy-selection result, not an incomplete or zero-return backtest.

## 1. Data, provenance and timestamp gates

- Canonical source: `/home/quant/dev/quant/ml4t-data/.data/store/forex_minute_<SYMBOL>`, Parquet one-minute research prices.
- LSE source with timezone-aware UTC one-minute bars: USDJPY, EURUSD, GBPUSD, AUDUSD.
- EURJPY and GBPJPY: legacy Dukascopy BID candles, timezone-naive source timestamps requiring interpretation; used only for a triangular quote consistency audit, **excluded from flow identification and trading signals**.
- USDCHF local store is not a verified comparable 1-minute LSE input; AUDJPY is not available in the audited archive.
- The original BOJ-bank-day calendar and the Gotobi preceding-bank-day rollover hypothesis were inherited from Program 1, not relabeled after results.
- The 03:00–13:00 JST event snapshots have bounded timestamp partitions; no raw JST date in September–October 2026 was accessed.
- **42 bounded annual snapshots** from the six audited pairs, including **28 comparable annual LSE snapshots**, are saved with file SHA256, source paths, timestamp endpoints and provider identity in `run_log/tokyo_fix_program2_cross_currency_20261011_v1/source_manifest.json`.
- The data gate records null/duplicate timestamps, OHLC geometry, five-minute unchanged-close staleness, calendar-day completeness, weekly closure and per-year observations. No observation is forward-filled into a trading fill.
- Direct legacy EURJPY versus LSE EURUSD*USDJPY: median log cross-rate deviation 0.134 basis points, absolute p95 2.55 basis points and 2.10% exceeding 5 basis points. This measures asynchronous/cross-vendor source differences; **it is not predictive triangular arbitrage**.

Artifacts: `T1_quality/result.json`, `T3_decomposition/result.json`, `triangle_identity.parquet`, `provenance_audit.json`, annual source manifest and synchronized Parquets.

## 2. Experiment A — Fixing-flow decomposition

The equal-weight USD factor uses the negative of the *previously closed* 5/15/30/60-minute log returns of EURUSD, GBPUSD and AUDUSD. This is a USD movement proxy, **not** an independent measure of institutional settlement orders. The denominator factor weights are fixed rather than fit to future USDJPY outcomes.

FX triangles satisfy `EURJPY ≈ EURUSD × USDJPY`; constructing a synthetic cross from the other two does not add an independent signal. Direct EURJPY cannot presently identify a clean JPY factor because of incompatible source provenance. Accordingly, broad USD-vs-JPY attribution is **partially unidentified**.

All 16 price flow contrasts were tested using weekday/year controls, HAC uncertainty, and a predeclared Holm correction:

| Window (JST) | USDJPY Gotobi mean | Ordinary mean | Controlled Gotobi increment | Holm-adjusted p |
| --- | ---: | ---: | ---: | ---: |
| 07:00–08:30 | +1.257 log bps | -0.248 log bps | **+2.110 log bps** | **0.0162** |
| 08:30–09:54 | +1.762 log bps | +0.821 log bps | +0.489 log bps | 1.000 |
| 09:56–10:10 (long-return convention) | -1.212 log bps | -0.358 log bps | -0.983 log bps | 0.1242 |
| 09:56–10:30 (long-return convention) | -1.482 log bps | -0.524 log bps | -1.153 log bps | 0.4372 |

**Units:** log basis points of price return (10000 × log price ratio). These are *not* FX pips and cannot be compared numerically with the Program 1 pip values without the contemporaneous FX level.

**Decision:** A distinct settlement USD-demand mechanism is **unverified**. The 07:00–08:30 USDJPY association remains a historical research lead.

The saved `intraday_profiles.png` plots four pairs with 09:55 reference and explicitly changing minute-level cohort sizes. It is descriptive, not a portfolio return.

## 3. Experiment B — Cross-pair predictive information

Declared lookbacks and prediction horizons: 5, 15, 30, 60 minutes. Anchors, instrument families and Gotobi/ordinary cohorts were frozen in `config/research_sessions/tokyo_fix_program2_cross_currency_20261011_v1.yaml`.

Signals use **the last completed minute strictly before the decision**, with the entry price in a later minute. Dense null-minute grids and completeness masks prevent shifting across unavailable observations. Fit/scale cutoffs are based on development observations, not future data.

- **640 predictive trial IDs** were recorded, including insufficient groups with their status.
- **0 / 640** tests passed the declared Holm multiplicity correction.
- The library-backed `ml4t.diagnostic.Evaluator` used chronological 2024, 2025 and 2026 stress folds when each fold had enough observations; 20 trials lack sufficient 2026 stress samples, now explicitly accounted for.
- The 2020–2023 period is development, 2024–2025 is retrospective walk-forward validation and Jan–Aug 2026 is an already inspected stress interval. None is a genuinely unseen final holdout.
- Placebo-window, yearly-effect and quote-alignment claims require their stored diagnostics and should not be treated as proof of causality merely from raw cross-pair correlations.
- The historical complete trial count outside this session is not known. The 640-trial Holm correction cannot retroactively correct undisclosed earlier experimentation.

**Decision:** No verified incremental predictive cross-pair feature. Do not use the triangular identity as a signal.

## 4. Experiment C — Economic candidates and costs

The preregistered strategies were screened from contemporaneous observed one-minute markouts. These are **not actual execution fills**, and their USD outcomes are conditional-markout calculations used only as qualification gates.

| Candidate | Selected events | Average net USD per selected event | Verdict |
| --- | ---: | ---: | --- |
| C1. USD-factor-confirmed 09:56–10:10 Gotobi short | 213 | **+$0.952** | **FAILED**: confirmation policy has no positive incremental return; predictor fails multiplicity screen; negative 2026 |
| C2. $5k USDJPY + $5k EURUSD directional hedge, USD-neutral exposure | 213 | **-$0.037** | **FAILED**: no after-cost benefit, no independent predictive power, negative 2026 |
| C3. Cross-rate basket | — | Not evaluated | **INELIGIBLE_SOURCE**: historical independent JPY-cross source not comparable |

C1 has a retrospective mean estimate CI of [+0.168,+1.735] USD per selected event, but the causal question is *whether the confirmation rule improves the unconditional policy*. The policy's estimated incremental mean is **-$0.152 USD/event**, HAC interval [-$0.634,+$0.330]. The filter does not demonstrate incremental usefulness. C1 2026 mean: **-$0.492** per selected event (19 events).

C2 mean net estimate: **-$0.037 USD/event**, CI [-$0.389,+$0.314]. The EUR hedge was explicitly constrained to USD 5,000 notional per leg, with total gross USD notional USD 10,000 and currency exposure equations independently unit-tested. Leg count doubles transaction frictions; costs remain hypothetical.

Cost screens include 1×/2×/3× illustrative per-leg round-trip costs. The historical prices lack actual executable bid/ask/commission and latency verification. No broker-specific capacity or fill-realism claim is possible.

Benchmark: The unchanged native Program 1 replay, already independently audited, used USD 10,000 initial and USD 10,000 fixed notional:
- 08:30–09:54 Gotobi long: 458 trades, +$456.94 after assumed costs.
- 09:56–10:10 Gotobi short: 458 trades, +$217.14 after assumed costs.
- 09:56–10:10 ordinary short: 1,143 trades, -$450.95 after assumed costs.
These are earlier historical benchmarks on their own completeness cohort; they are **not new Program 2 trades or exact paired execution comparisons**.

## 5. Independent verification and unresolved gates

- Frozen session and initial input check: PASS, with reference identities documented.
- Independent data/feature oracle: **PASS**, independently checked 122,826 feature prices and 31,772 target prices.
- Source fingerprint audit: 51 identities checked; original/dirty unrelated work preserved; holdout remains SEALED.
- Walk-forward folds: all saved fold counts match the sample-size gating; 20 thin 2026 subsets were not silently declared three-fold passes.
- Focused test suite: **23 passed**, six third-party deprecation warnings.
- The full 291-item repository suite was attempted but did not obtain a clean end-to-end pass due to existing unrelated notebook/Marimo execution issues; do not describe it as passing. Failure logs retained.
- Two early execution attempts (nested CSV serialization and nondeterministic sorted-history differences) were retained. Subsequent execution produced all required diagnostics. Do not overwrite the frozen originals.
- **Seven declared program trial artifacts**: quality, flow, decomposition, lead-lag, candidate screen, no-native disposition and independent verification. Ledger records to be checked before final acceptance.
- No live orders, commit, push, changes to previous frozen Program 1 artifacts or exposure of the protected September–October 2026 holdout.

## Research decisions

1. **USD-specific demand?** Unknown. A USDJPY 07:00–08:30 Gotobi drift exists in the selected sample; cross-currency movements alone do not establish importer demand.
2. **JPY-specific flow?** Partial/unknown. No verified consistent-vendor independent JPY-cross data.
3. **Lead-lag?** No effect qualified among the 640 declared tests after Holm.
4. **Tradable relative-value residual?** Not established. Mechanical triangular residuals are not signals.
5. **Hedged advantage?** No. The checked EUR hedge did not beat a simple single-pair candidate after costs.
6. **Final strategy?** **NONE**. New native ML4T candidate trades **0 by design**: no candidate passed frozen qualification criteria.
7. **Next decisive input:** Obtain timestamp-verified, consistently sourced EURJPY/GBPJPY quote bars and/or historical executable broker bid/ask. Preregister future prospective data validation; do not reopen the Sep–Oct 2026 holdout for further optimization.

## Artifact index

- Session specification: `config/research_sessions/tokyo_fix_program2_cross_currency_20261011_v1.yaml`
- Source materializer: `scripts/materialize_tokyo_fix_program2_cross_currency_20261011_v1.py`
- Research implementation: `scripts/run_tokyo_fix_program2_cross_currency_20261011_v1.py`
- Independent verifier: `scripts/verify_tokyo_fix_program2_cross_currency_20261011_v1.py`
- Root artifacts: `run_log/tokyo_fix_program2_cross_currency_20261011_v1/`
- Profile chart: `run_log/tokyo_fix_program2_cross_currency_20261011_v1/intraday_profiles.png`
- Source manifest: `run_log/tokyo_fix_program2_cross_currency_20261011_v1/source_manifest.json`
- Lead/lag details: `run_log/tokyo_fix_program2_cross_currency_20261011_v1/T4_leadlag/result.json`
- Candidate screens: `run_log/tokyo_fix_program2_cross_currency_20261011_v1/T5_candidates/result.json`
- Verified oracle: `run_log/tokyo_fix_program2_cross_currency_20261011_v1/T7_verification/result.json`
- Frozen trial records: `run_log/research_sessions/tokyo_fix_program2_cross_currency_20261011_v1/`
