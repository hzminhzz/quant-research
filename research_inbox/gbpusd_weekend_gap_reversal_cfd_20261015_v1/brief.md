# Research handoff: gbpusd_weekend_gap_reversal_cfd_20261015_v1

Candidate ID: `gbpusd_weekend_gap_reversal_cfd_20261015_v1`. Status: THESIS_READY_UNVERIFIED. No implementation, backtesting, or trading approval.

This descriptive thesis is NOT an executable ATS CandidateSpec. The original product and proposed CFD/perpetual adaptation must be independently reconciled. Missing original-source details remain blockers.

## Source 1: gbpusd-weekend-gap-reversal_20261015-1208_research-brief.md

# Research brief: GBP/USD Weekend Gap Overreaction Reversal

- Candidate ID: `gbpusd_weekend_gap_reversal_cfd_20261015_v1`
- Research timestamp: 2026-10-15 12:08 Asia/Ho_Chi_Minh
- Decision: `THESIS_READY_UNVERIFIED`; qualified as a research DESIGN, NOT as an executable or frozen strategy.
- Mission boundary: thesis research only. No market-history feature computation, backtest, optimization, repository edit, or protected-holdout access.
- Repository examined read-only: `/home/quant/dev/quant/quant-research` at HEAD `9525f35`. The checkout contains extensive unrelated untracked work; nothing was modified.
- Required documents read: `AGENTS.md`, `docs/research_operations.md`, `docs/research_sessions.md`, `docs/architecture/market_scope_policy.md`, and `config/research_contract_v1_example.yaml`.
- Methodology skill references read: `ml4t-skills` causal-identification, point-in-time, compute-features, cost-model, transaction-costs, lookahead-bias. Installed `ml4t.engineer` feature signatures were NOT inspected.

## A. Discovery and comparison

| Candidate | VERIFIED independent evidence | HYPOTHESIS and payer | Regimes and primary falsifier | Assessment |
|---|---|---|---|---|
| **GBP/USD weekend gap overreaction reversal (SELECT)** | Dao, McGroarty & Urquhart (2016) directly tested Friday-close to Monday-open FX gaps in 2002-2014 and documented subsequent week reversals. Their implemented strategy used top/bottom **5%** gap quantiles and a one-week hold. | Lower-liquidity reopening and behavioral overreaction temporarily push GBP/USD beyond information-based value; liquidity suppliers or traders fading the gap collect price reversion from urgent weekend-news order flow. A true persistent informational repricing would NOT reverse. | Likely stronger when Sunday reopening liquidity is poor but normalizes; weak or reversed when persistent fundamental news drives the gap. Falsify with nonpositive net contrarian event return, no larger reversal in extreme than ordinary gaps, or nonexecutable opening spreads. | **Selected**: primary rule available, directly published directional hypothesis, suitable quote feed present by directory. But author-era results selected among thresholds/horizons, and GBP/USD CFD after-cost edge unverified. |
| CFTC speculative GBP positioning continuation | NY Fed Klitgaard & Weir (2004) documented **contemporaneous** co-movement of speculator positioning and FX returns, while explicitly finding no following-week predictability. CFTC normally publishes Tuesday positions on Friday. | Large speculator position changes might continue to move GBP/USD after disclosure; delayed buyers pay trend followers. | Weak when positioning is stale or price already moved. Next-week no-forecast evidence directly challenges this proposal. | **Reject**: published evidence undermines the causal forecast after official publication lag. Local COT `GBP` folders exist, but this does not create a forecast. |
| BTC weekend-liquidity reversal | Kaiko found lower weekend volume/liquidity; Müller (2024) found no robust broad cryptocurrency return calendar anomaly, though low weekend activity persisted. | Thin weekend book creates temporary overreaction; new Monday liquidity pays reversal traders. | Can fail under genuine weekend news, liquidation cascades, or Monday price continuation. | **Defer/reject this hour**: weaker specific directional evidence, more perps funding/execution dependencies; repository already has extensive crypto funding and taker-flow work. |

Source-based claims and citations:

1. Dao, T.M., McGroarty, F. & Urquhart, A. (2016), *A calendar effect: weekend overreaction (and subsequent reversal) in spot FX rates*. Author postprint, sec. 3.1-3.2, 4.2: https://irep.ntu.ac.uk/id/eprint/35555/1/13113_Dao.pdf . Paper's published historical profitability is not modern validation.
2. Klitgaard, T. & Weir, L. (2004), Federal Reserve Bank of New York: https://www.newyorkfed.org/research/epr/04v10n1/0405klit/0405klit.html . Explicit finding: not useful to predict the next week's FX move.
3. CFTC official release policy: https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm . Typically Friday 3:30 pm ET, Tuesday positions, with exceptional delays.
4. Müller, L. (2024), *Revisiting seasonality in cryptocurrencies*: https://econpapers.repec.org/article/eeefinlet/v_3a64_3ay_3a2024_3ai_3ac_3as1544612324004598.htm . Calendar returns not robust; lower weekend trading robust.
5. Kaiko research as reported in Feb 2024: https://decrypt.co/219288/bitcoin-crypto-weekend-trading-liquidity-kaiko . Treat as liquidity context, NOT directional return evidence.
6. Dukascopy official historical export: https://www.dukascopy.com/api/data/get/historical-data-export . Exports can include bid and ask, but their presence in this local canonical dataset is UNVERIFIED.
7. OANDA session reference (not proof of Dukascopy conditions): https://www.oanda.com/us-en/trading/hours-of-operation/ . Sunday 17:05 New York time and opening gaps differ by broker.

## B. What the original author actually specified

VERIFIED paper rules: weekend gap `ln(Monday_Australia_open/previous_Friday_US_close)`, top or bottom 5% of a trailing 5-year sample of weekly gaps, contrarian position at Monday open, held through Friday close (one week). The paper evaluated 1-day/3-day/1-week and 5%/10%/15% variants and later chose the 5% and one-week combination based on observed past results. Original timestamps were stated approximately in GMT; those historical session conventions are NOT reliable broker-specific CFD clocks today. The original spot lending/borrowing and indicative FX cost conventions do not equal modern CFD swaps/spreads. Original USD quote direction remains GBP/USD (GBP base, USD quote).

## C. Independent proposed CFD adaptation — one frozen candidate, not an execution approval

- Instrument research proxy: canonical `forex_minute_GBPUSD`, Dukascopy-derived GBP/USD minute price store; directories visibly span 2009-2026. Source format, quote side, row coverage, timestamp semantics and missing Sunday event bars not yet qualified.
- Intended trade: GBP/USD rolling FX CFD or leveraged FX contract with contract terms to be mapped to a specific broker. An unverified Dukascopy quote proxy is NOT itself evidence of broker fills.
- Gap measurement: last valid **completed** 1-minute midpoint bar within Friday 16:45-16:59 America/New_York and earliest valid **completed** 1-minute midpoint bar within 60 minutes after the VERIFIED FX Sunday opening (normally near 17:00-17:05 America/New_York; use actual broker schedule, holidays and DST). Must have contemporaneous executable bid and ask; do not infer from mid-only OHLCV.
- Signal: `g = ln(Sunday_open_mid / Friday_close_mid)`; compute quantiles using the last 260 completed *previous* weekly gap slots, with at least 234 valid observations. Use the 10th and 90th percentiles (single preregistered adaptation, not selected after returns) to preserve a feasible independent-event count. Trade short after positive `g >= Q90`, long after negative `g <= Q10`; require correct sign, and stay flat otherwise.
- Timing: decide only after the Sunday-open 1-minute quote bar completes and all prior thresholds are known. Submit market order only for the earliest legal subsequent quote/bar event. No same-bar fill. Exit Friday via time signal at 16:45 New York, with next legal quote BEFORE session closure. If that is impossible, enforce broker close before the weekend and label the event not safely executable; never assume a Friday close fill after the market shuts.
- Sizes: 1x equity notional, one GBP/USD position, no pyramiding. Minimum broker lot, account currency conversion, spread, slippage, commission, swaps/rollover (especially midweek triple swap), and margin rules require verification.
- Source-vs-adaptation difference: 10% vs original 5% tail; causal next-minute execution vs author's Monday open; broker-timezone/DST sessions vs fixed historical GMT; earlier Friday exit; CFD financing instead of paper's interest-rate accounting. No author-performance statistics were reused as proposed results.

## D. Economic model and falsification

**Verified:** Published source documented historical weekend-gap reversals; a Dukascopy-derived GBP/USD minute dataset directory exists. **Inference:** Limited reopening liquidity plausibly amplifies weekend order-flow pressure. **Hypothesis:** The delayed executable GBP/USD gap reversal is larger than spread, market impact, commissions, slippage and swaps in a modern CFD after the first bar. **Unknown:** Whether author-era overreaction survives 2017-2024, broker execution, and close/open bid/ask bounce.

Economic payer: urgent reopening traders temporarily crossing wide spreads and other traders overreacting to weekend information. A liquidity-recovery mechanism can generate reversal; durable fundamental information can instead produce continued moves. The mechanism differs from standard unconditional mean reversion because it requires a Friday-to-Sunday **nontrading price discontinuity**, a point-in-time tail threshold, and broker-specific reopening quotes.

**H0:** Conditional on the frozen tail-gap trigger, mean net strategy return is at most zero; the additional mean reversal relative to ordinary-gap placebo weeks is nonpositive. Main tested one-strategy metric: calendar/event-block confidence interval for mean net return per qualifying week. Decision requires standalone mean >0, lower one-sided 95% block-bootstrap confidence bound >0, and credible effect exceeding estimated full round-trip friction. Do not optimize to reach this rule. Main mechanism secondary test: contrast signed post-entry moves on extreme-gap weeks versus non-extreme gap weeks, with costs and the exact clock held fixed.

**Prespecified minimum evidence:** at least 60 complete independent event-weeks across >=6 calendar years; effective weeks and year concentration must be reported. If fewer, classify `INCONCLUSIVE`, not evidence of no edge. Expected event counts from tail probabilities are design intuition, NOT inspected market outcomes. Eligible development window PROPOSED: 2017-01-01 through 2024-12-31, with warmup beginning 2012-01-01. This range is subordinate to the repository's true observed/protected partitions. If those periods are already previously observed, explicitly label retrospective and do not call them OOS. Protected allocation holdouts remain sealed.

Cost or data gates: If no true bid/ask quote history, no verified Sunday-open session or no broker rollover schedule, `BLOCKED_DATA` before a net result. If the source instrument or broker identity cannot be mapped, `BLOCKED_DATA`. Price-only directional study can still be reviewed as *nonexecutability evidence*, never as a profitable strategy. Even a strong price signal is not a net-profit claim.

## E. Adversarial review — ways this thesis fails

1. **Publication-selection bias:** The author examined 16 FX crosses, three thresholds, and multiple horizons; the selected 5% one-week result is not a pristine independently preregistered test.
2. **Time gap mismatch:** The earliest observed Dukascopy quote may not equal the paper's Bloomberg Australian-open price. A gap may shrink before executable CFD entry.
3. **Bid/ask bounce:** Friday last versus Sunday first midpoints may mechanically create spurious reversal if bid/ask sides are mixed; trade actual sides.
4. **Not a causal proof:** Large weekend gaps can represent permanent macro news, not transient liquidity pressure. Counterfactual shock attribution is unobserved.
5. **Financing:** Multi-day leveraged FX includes swaps, broker markups, and possibly Wednesday triple rollover; use actual transaction dates.
6. **Sample:** One extreme event per week at most; ~8 development years may have insufficient independent weeks after missing-data screens.
7. **Instrument mapping:** Historical spot quote data do not prove modern CFD execution, short borrow availability, min lot, or fill quality.
8. **Data structure:** Historical minute parquet schema and quote semantics are not yet independently inspected; mere directories do not prove event-level coverage.
9. **DST and holidays:** Broker reopens and closes in local time; hardcoded 22:00 GMT would drift across seasonal clocks.
10. **Prior work and protected boundaries:** Repo includes existing FTMO FX reversion and many strategy trials. Prior trial fingerprints, overlap and permissible years must be checked before any registration.

### Decision and next gate

`THESIS_READY_UNVERIFIED` **for independent implementation planning only**. Do NOT freeze a session or backtest yet. First verify exact minute schema/bid-ask sides, time gaps, price proxy identity, 260-week warmup, and broker trading/swaps. Verify ML4T native or extension bindings against the installed version. A data blocker is legitimate; no winner is presumed.

## Source 2: gbpusd-weekend-gap-reversal_20261015-1208_research-handoff.md

# Handoff to ChatGPT Web Research Lead — GBP/USD Weekend Gap Overreaction Reversal

**Candidate:** `gbpusd_weekend_gap_reversal_cfd_20261015_v1`
**Research date:** 2026-10-15 12:08 Asia/Ho_Chi_Minh
**Status:** `THESIS_READY_UNVERIFIED` for specification review only. No trial registered or run.

## Established

1. Full author postprint by Dao, McGroarty & Urquhart (2016) was inspected: https://irep.ntu.ac.uk/id/eprint/35555/1/13113_Dao.pdf . Its **original** strategy: weekend Monday-open versus preceding Friday-close FX log gap; 5% upper/lower gap tails from five years of previous gaps; fade the gap; exit Friday close. Earlier paper selection across thresholds and horizons creates a nontrivial multiple-testing caveat.
2. Current VPS repository `AGENTS.md`, `docs/research_operations.md`, `docs/research_sessions.md`, `docs/architecture/market_scope_policy.md`, `config/research_contract_v1_example.yaml` were read. Repo HEAD inspected: `9525f35` with extensive unrelated untracked work, left unchanged.
3. Canonical `forex_minute_GBPUSD` directory has year partitions 2009-2026. It was NOT established that the exact Sunday/Friday bid-and-ask quotes exist on all needed dates. The available `ml4t.engineer.compute_features` registry and execution engine signatures were NOT inspected.
4. Selection compared this source with CFTC positioning continuation and BTC weekend liquidity reversal; rejected the former because a NY Fed study explicitly found no next-week predictive power, and deferred the latter because weekday return anomaly evidence is weak.

## What must be verified independently BEFORE creating a frozen MVP

- Verify the GBP/USD instrument at the intended CFD/margin-FX broker (product type, base/quote, point value, lot increment, financing, short availability and session calendar). A Dukascopy vendor price series alone is not a broker execution contract.
- Inspect the exact minute Parquet schema. Determine if `bid` and `ask` are contemporaneously observed at the minute/event, or if the store is only mid/bid OHLCV. Qualify Friday 16:45-16:59 and first Sunday opening quotes for every eligible week, including DST and holiday changes. Do NOT reconstruct an opening quote with information from a future bar.
- Verify commission, time-varying entry/exit spreads, unfavorable slippage, swap/rollover per side and Wednesday triple swaps for the entire intended sample. If essential exact historical costs are unavailable, mark `BLOCKED_DATA` or do strictly labeled signal-only nonexecutability work, NOT net PnL.
- Verify protected/observed boundaries and prior FX reversion trials. Development dates 2017-2024 are provisional and NOT represented as unseen OOS.
- Inspect actual installed `ml4t.engineer.compute_features`, catalog parameters, native event/calendar capabilities and `ml4t.backtest` execution semantics. Bind verified primitives or a separately approved tested extension, not an ad hoc hand-rolled backtest. Need explicitly prove rolling lookback, week isolation, time alignment, next-event fill and swap cash accounting.
- Before any Phase 4 backtest, preregister the ResearchPhase 3 signal/economic event study or justify a native-only exception under `docs/research_operations.md`. Independent auditor must verify its decision and timing before Phase 4.

## Implement the smallest native ML4T contract after blockers pass

- Exact **single** candidate is in accompanying YAML. Determine Friday reference midpoint and first completed Sunday-opening midpoint from true bid/ask events; signal `g=ln(Sunday_mid/Friday_mid)`; compare with Q10/Q90 of the preceding 260 calendar-week slots with >=234 valid prior gaps. Trade opposite gap only when tail and sign agree; no tuning. Rule is a clearly labeled CFD adaptation using 10%/90% tails; it is NOT the author's 5% strategy.
- Only signal after the Sunday reopening minute is complete. Earliest possible fill is the *next* legal quote/bar after decision. Exit before Friday weekly close. Trade one GBP/USD position, target 1x reference equity gross notional, mark USD cash and actual broker side costs.
- Design only one decisive development diagnostic and, if permitted by its preregistered gate, one native event-driven MVP. Require >=60 separate qualifying weeks across >=6 years; return `INCONCLUSIVE` if sample/uncertainty insufficient and `BLOCKED_DATA` when execution costs/source identity unavailable.
- Report the event-week mean net return, one-sided 95% dependence-aware lower confidence bound, full spread/commission/slippage/swap drag, event count by calendar year, and non-extreme gap placebo. Accept for deeper validation only if standalone after-cost economic evidence and mechanism check pass. No holdout opening.

## Trade-material questions that remain OPEN

1. Which named broker and actual product class is the ultimate GBP/USD execution target?
2. Is the canonical data source bid-only, midpoint, bid/ask OHLC, or full quotes, and what does its timestamp mean?
3. What is the broker's precise weekly opening and closing clock, including 2009-2026 holiday/DST exceptions?
4. At what exact instant after reopening is the first price both known and actionable? Does spread remain so wide that no subsequent edge survives?
5. Does an available bid/ask bar produce valid executable entry/exit prices, or is tick data required?
6. Does a 10% each-tail adaptation have enough independent weeks without opening protected dates? Does the protected boundary force a shorter study?
7. Are actual long/short rollover rates, broker markups, triple swaps, commissions and contract rounding available at historical dates?
8. Can native ML4T compute or verified approved extensions represent weekly gap events and 260-week trailing quantiles exactly?
9. Can native event-driven execution account for midweek swaps, no same-bar order fills, and guaranteed Friday flattening?
10. Is Friday early exit to avoid closing spreads economically faithful enough, or does the signal vanish before that exit? Do not choose a different exit after viewing returns.
11. Do existing FX-reversion research results already include the intended sample or analogous FX weekend-gap hypothesis? If yes, label as retrospective or duplicate.
12. What is the economic account convention (GBP units, USD equity and notional), minimum lot, leverage, and contract multiplier at the named broker?

**STOP here.** This handoff does not approve a frozen session, implementation, PnL calculation, optimization, final-test access, or deployment. The separate hourly automation remains active and is not changed by this report.