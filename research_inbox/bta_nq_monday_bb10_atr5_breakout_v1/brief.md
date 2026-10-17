# Monday NQ lower-Bollinger ATR stop-buy — ATS research admission

**Candidate ID:** `bta_nq_monday_bb10_atr5_breakout_v1`  
**Selection family:** `bta_nq_monday_bollinger_atr_breakout`  
**Decision:** `THESIS_READY_UNVERIFIED` — descriptive research-design admission only. Not a frozen session, executable CandidateSpec, market-data qualification, native backtest, or trading approval.

## Practitioner triage (three tested strategies, no return computation)

| Source | Original product and tests | Decision |
| --- | --- | --- |
| Breakout Trading Academy, *Steal This Monday NASDAQ Strategy*, 2026-07-16 | CME NQ futures, 60-minute, author says 15 years of testing, IS/OOS confirmation, 72% proprietary audit and near-100% space robustness. | **Selected as an unverified hypothesis**, with unresolved source-clock and order semantics. |
| Kris Longmore, *Exploring mean reversion and cointegration with Zorro and R: part 1*, 2015-12-03 | AUD/NZD mean-reversion experiment with code; author admits lookahead from full-history half-life and excludes substantial rebalancing costs. | Rejected as already self-described non-implementable proof of concept. |
| Rob Carver, *Simulating my futures system*, March 2015 | Diversified systematic futures system, author reports net Sharpe 0.88 and worst drawdown 33%. | Not selected: an entire multifactor portfolio rather than one new isolated author-exact entry/exit rule. |

Sources: [BTA Monday primary](https://breakouttradingacademy.com/steal-this-monday-nasdaq-strategy-super-simple/); [Robot Wealth original](https://robotwealth.com/exploring-mean-reversion-and-cointegration-with-zorro-and-r-part-1/); [Carver original](https://qoppac.blogspot.com/2015/03/simulating-my-futures-system.html).

## ORIGINAL_AUTHOR_RULES — not a local reconstruction

**Primary dated source:** Breakout Trading Academy, *Steal This Monday NASDAQ Strategy (Super-simple)*, **July 16, 2026**. The page uses first-person narrative without an independently established personal byline in the checked text; credit the organization rather than guessing an author.

- Original **instrument**: **CME E-mini Nasdaq-100 (NQ) futures**, not ETF, cash index, MNQ or CFD.
- **Bars**: 60-minute.
- **Entry reference**: the **lower Bollinger Band**, lookback **10**, **1 standard deviation**, plus **0.8 × Average True Range(5)**.
- **Order**: **buy stop** at that combined trigger level; **only if hit on the next 60-minute bar**.
- **Day and window**: **Monday only**, entry window **midnight to 11:00 PM**, close at **11:00 PM on the same day**.
- **Source gaps**: published text does **not** identify the clock's timezone, first-bar anchor, Bollinger sample/population std definition, ATR smoothing, handling of a stop across the next-bar expiry, daily vs Globex day semantics, fixed stop-loss, contract count, margin or fee schedule. Stop buy implies long-only, but no short-side strategy is described.

**Rule fidelity: PARTIAL — fatal clock ambiguity unresolved.** Do not select a Chicago, New York, UTC, platform or other 23:00 interpretation without author platform/code confirmation. An assumed 23:00 ET exit would be a different strategy from 23:00 UTC or CT. Do not manufacture profitable same-bar OHLC fills. Do not borrow unmentioned safety stops.

## SOURCE_TEST_EVIDENCE — original published claims only

The July 16 source asserts 15 years of NQ historical testing, in-sample building followed by out-of-sample confirmation, a **72%** platform-defined backtest audit score and near-**100%** score for robustness to changes in the space component. It does not publish a verifiable date window, trade ledger, actual number of fills, net PnL, Sharpe, maximum drawdown, fees, slippage or standalone full-period vs recent-period results. The percentages are **not a trade win rate**, independently measured probability of success or verified alpha.

**The strongest adversarial evidence is the author's own negative cross-index test:** on July 16, the author explicitly says this **0.8 ATR** Monday model did not cross-validate well away from NQ. The earlier **July 8, 2026** BTA [1,800 Bollinger breakouts study](https://breakouttradingacademy.com/i-tested-1800-bollinger-bands-strategies/) reports a **different selected 1.8 ATR multiplier**, 86% robustness and recent, not long-history, cross-index performance. Its positive recent period cannot validate the July 16 0.8-ATR rule; its large scan and Monday filter demonstrate serious **multiple-selection exposure**. Do not collapse the two parameterizations into one unrecorded trial.

CME primary [NQ product reference](https://www.cmegroup.com/markets/equities/nasdaq/e-mini-nasdaq-100.html) confirms a genuine futures contract (USD 20/index point; 0.25-point minimum tick). [CME futures roll education](https://www.cmegroup.com/education/courses/introduction-to-futures/understanding-futures-expiration-contract-roll) explains why an expiry/roll policy must not be silently inferred from back-adjusted research prices. Neither proves that a particular VPS price panel is executable.

## Scientific challenge: mechanism, counterparty and null

- **HYPOTHESIS:** after overnight repricing, unusually strong Monday directional flow crossing a lower-band-plus-ATR threshold continues sufficiently to compensate a stop buyer's spread, slippage and fees.
- **INFERENCE — who pays:** subsequent liquidity-demanding buyers and short-coverers after the trigger may transfer favorable price movement to an early buyer; order-flow identity is not demonstrated by the article.
- **NULL:** conditional, causally executable **net** filled-event expectancy is no greater than an unconditional, time-matched Monday long NQ control with the same risk/notional and fee model.
- **Competing explanations:** ordinary long Nasdaq beta, Monday calendar mining, hindsight filter selection among 1,800 Bollinger variants, session-bar data vendor conventions, favorable stop-gap fills, and recent-regime concentration.
- **Failure scenarios:** long-signal post-trigger reversal, non-generalisability, futures roll artifacts, DST misalignment, high opening spreads and a source performance claim which disappears under true fill-grade data.

## LOCAL_ADAPTATION and intended causal mathematics (not source-verified)

**No product substitution:** Retain CME **NQ futures** for the initial fidelity question. A price-only NQ 1-second store mentioned by repository AGENTS.md does not grant actual exchange bid/ask, queue execution or exact fill prices. No equivalent CFD/QQQ/spot/instrument is asserted.

**Explicit candidate formula awaiting independent source parity:** for completed 1-hour bars indexed `t`, `LB10_t = mean(C[t-9:t]) - 1 × population_std(C[t-9:t])`; `TR_t = max(H_t-L_t, abs(H_t-C[t-1]), abs(L_t-C[t-1]))`; proposed `ATR5_t` is computed from historical completed `TR` values with author-specific smoothing **UNKNOWN**. Source stop threshold is `LB10_t + 0.8 × ATR5_t`, to be placed only **after** bar `t` completes and effective only in the next eligible hour. Population-vs-sample band variance, Wilder-vs-SMA ATR and 23:00 clock selection are not settled by the article. Label any chosen variant as a separately approved and versioned adaptation, not exact reproduction.

**Sizing adaptation:** possible one contract per independently qualified signal solely for normalizing research economics. Author's sizing is UNKNOWN. CME multiplier, quarter-contract dates, roll gap, ticks, holidays, breaks and margin must be verified. Never infer flat-by-23:00 means zero risk when an actual Monday 23:00 trading halt is possible under some timezone interpretation.

**Costs:** predeclare one-way execution on exchange-relevant asks/bids, aggressive buy-stop gap slip, commission, exchange, clearing and broker charges, contract multiplier, tick rounding, halt/limit conditions and missing quotes. A same-day flat strategy avoids overnight futures exposure if actually filled/exited, but futures basis (and any roll adjustments) is not a CFD swap or crypto funding feed. No cost assumption is source-verified.

## Intended diagnostic and falsifier — NOT executed

This is a **single-market, stop-fill/path-dependent event thesis**. Cross-sectional IC is **NOT_APPLICABLE**: it does not rank a stock universe. Nor is a vectorized return conditioned on an hourly bar's high crossing the stop an execution-faithful pre-backtest event study: the bar high says neither whether the order was placed first nor what the stop order actually paid.

**Pre-backtest scientific diagnostic:** reconstruct source exact clock, 60-minute bars, Bollinger and ATR, and frozen stop-order lifecycle from a small public sample or independently permitted development *metadata*. Audit whether the next-bar stop is even eligible, bar timestamps and exchange pauses, amount of missing tick/bid/ask coverage, and the number of source-permitted Monday opportunities. Perform parity/prefix-invariance, stop-before-signal rejection, expiry and DST tests. Do not calculate returns as part of this discovery.

**Smallest later native economic test (requires separate approval):** one NQ contract-month stream, the original **0.8 ATR** configuration once source ambiguity resolved, one chronological development segment with cost-qualified finer-than-hour bid/ask, one actual native stop-order lifecycle, and a matching unconditional Monday long benchmark. Cluster Mondays by calendar week, include roll and year slices; log all losing periods and actual filled/canceled counts. Do not tune the window, days, ATR period, multiplier, or band based on results. Do not access protected holdout.

**Single predeclared primary falsifier:** if enough independently qualified filled events exist, a conservative-cost **incremental mean per matched event over the baseline** whose **upper one-sided 95% confidence bound is at or below zero** falsifies the proposed economically positive incremental edge. Wide uncertainty => **INCONCLUSIVE**; missing valid clock/quotes/costs => **BLOCKED_DATA**, not a negative return finding. This test design is not a claim of profitability or a new backtest approval.

## Gate failures and next research admission step

1. **CLOCK/BAR:** identify the author's exact timezone, exchange-session meaning of Monday, valid start/end, Sunday-evening Globex mapping, US DST, 1-hour bar anchor and 23:00 exit feasibility. High-priority blocker.
2. **SOURCE MATH/ORDER:** recover BreakoutOS's original ATR smoothing, band stdev, next-bar stop expiry/rearm, exit order timing and any hidden stops. Reconcile July 8 vs July 16 as **different** parameter versions.
3. **DATA:** establish actual per-contract NQ PIT bar/tick/quote data with roll and bid/ask; price-only 1-second observations cannot demonstrate stop fills or market impact.
4. **COST/NATIVE:** qualify execution costs and current installed native ML4T order functionality through independent tests before Phase 3/4. A passing ATS two-file validator does not certify these.
5. **STATISTICS:** locate public trade count, source expenses, loss years and dated IS/OOS boundaries; document the 1,800-variant scan and any further selection history before formal trial registration.

**Verified as document facts:** primary pages and official CME product exist and explicitly make the attributed statements. **Not independently verified:** any source trade result, numeric performance, source data provenance, platform robustness score semantics, trading edge or native engine support. No historical return computation, Phase 3/4, credential, order, deployment or protected-data read was authorized or performed.

**Repository state:** Current main `041477bec24eb4936ed65214c20227b747f3b0c3` does not contain the descriptive handoff validator; the authoritative validated inbox branch `research/inbox-handoff-20261017` at `2fa13c03628b70a477a975a00e9de0970fe567a9` does. This pair is staged against that checked-out branch's actual `scripts/quant.py validate-handoff` command and is not claimable as present on remote main until merged.
