# FOMC overnight US500 CFD — source qualification and terminal MVP intake

**Candidate:** `fomc_overnight_uncertainty_premium_us500_cfd_20261015_v1`
**Status:** `BLOCKED_DATA` (ResearchPhases 1–2 intake; **not an economic REJECT**)
**Evaluated at:** 2026-10-15, using the VPS canonical source and original Fed calendars.
**Protected holdout:** 2025-01-01 onward — **not read or scored**.
**Execution:** **No Phase 3 performance evaluation, no SessionSpecV1 freeze, no native backtest, no model, no orders.**

## 1. Method and exact scope

- Faithfully preserved the user-supplied [thesis YAML](../research_inputs/fomc_overnight_uncertainty_premium_us500_cfd_20261015_v1/thesis_candidate.yaml) and [research handoff](../research_inputs/fomc_overnight_uncertainty_premium_us500_cfd_20261015_v1/research_brief_and_handoff.md). The thesis is a **Dukascopy US500 CFD overnight adaptation** of published S&P 500 pre-FOMC studies, **not** a replication of the original paper's 24-hour trade and **not CME ES**.
- Used [original Fed advance schedule announcements](../research_inputs/fomc_overnight_uncertainty_premium_us500_cfd_20261015_v1/fed_original_calendar_2017_2024.yaml) rather than treating current archive pages as dates demonstrably known in advance. Excluded the cancelled scheduled 2020-03-18 meeting. This reconstruction is **not** a complete effective-dated audit of every later rescheduling or policy statement release clock.
- Applied `exchange_calendars` XNYS **full** sessions (no cash-market holidays/early closes), but did not substitute that exchange calendar for historical Dukascopy CFD broker hours.
- Matched exactly one control at **D minus seven calendar days**, with the original candidate/control full-session and no-FOMC eligibility gate. No price-based control replacement.
- Verified UTC bar-start semantics, `America/New_York` historical DST conversion, 16:04 available entry reference/16:05 decision/16:06 next-open price **timestamp**, and 09:34 exit reference/09:35 decision/09:36 next-open price timestamp. A present BID bar is **not** evidence of an executable buy at the ASK.
- Read only timestamp, symbol and OHLC validity information in 2017–2024 daily `index_minute_ES` Parquet partitions. No performance metrics, signal forward returns, realized price changes or broker fills were computed.
- Data source: `/home/quant/dev/quant/ml4t-data/.data/store/index_minute_ES`. Catalog mapping: Dukascopy `usa500idxusd`, historical bid-only 1-minute CFD price proxy, USD quoted. The canonical catalog accepts price observations; it does **not** qualify actual contract fills or funding.

## 2. Observations (VERIFIED local source audit)

| Gate | Direct evidence | Result |
| --- | --- | --- |
| Original scheduled 2017–2024 statement dates | 8 original tentative meetings per year, 64 total; 2020-03-18 cancelled | **63 possible candidate events** |
| As-of original schedule publication | All eight original annual schedules published before intended entry | **Pass for original schedule dates**, revisions still unverified |
| Calendar full sessions + frozen control | XNYS regular sessions and matched D−7 control | **63 initially calendar-eligible** |
| Exact 16:04/16:06 + 09:34/09:36 bar timestamps on both legs | Four planned quote-time points, four preceding completed-bar points per pair | **53 source-complete pairs** |
| Years with complete pairs | 2018, 2019, 2020, 2021, 2022, 2023, 2024 | **7 calendar years** |
| Missing candidate/control 16:06 entry time | All eight 2017 statements plus 2018-01-31 and 2018-03-21 | **10 ineligible pairs; do not shift/reconstruct entries** |
| Frozen minimum feasibility floor | >=50 paired source-complete events in >=6 years | **53/7 passes preliminary endpoint coverage floor** |
| Native ML4T versions (installed checkout) | `ml4t-engineer 0.1.4`, `ml4t-backtest 0.1.7`, `ml4t-diagnostic 0.1.6.post2` | Available; **no event/backtest executed** |
| Registered native Engineer calendar feature | `feature_catalog.search("calendar")` returned [] | Requires approved deterministic calendar/event-scheduler extension, **not a price indicator** |

**Historical source-hour change, corroborating missing entries:** `2017-01-31` contained 841 quote-minute rows with latest observed minute **16:00 ET**. `2018-03-20` ended at **15:59 ET**. From sampled `2018-06-12`, `2020-06-09`, and `2024-03-19`, the source instead reaches **19:59 ET** that day. This **explains missing planned 16:06 source bars** for early years, but the mechanism (historical broker hour changes versus provider capture differences) is **not established**.

**Limits of quote coverage:** The source script establishes *exact endpoints*, not executable quotes, complete historical broker-session continuity, exact rollover gap behavior or realistic fill latency. Source availability is a **necessary but insufficient** condition for the proposed strategy.

The immutable **current** source audit and each per-event timestamp/eligibility decision are preserved in:

`docs/audit/fomc_overnight_uncertainty_premium_us500_cfd_20261015_v1_source_preflight_v2.json`

The original `..._source_preflight.json` attempt is retained unchanged as provenance. The v2 revision corrects one descriptive count-key label from "sixteen" to **eight** endpoint timestamps per matched pair and explicitly includes historical dividend adjustments as a blocker. Counts and qualification verdict are unchanged. Reproduce in an empty/new output path with `python scripts/fomc_overnight_preflight_20261015.py --output <new_path>`. Do not overwrite either result.

## 3. Unresolved blockers (no substitution permitted)

1. **Long entry side:** The canonical `index_minute_ES` OHLC is **bid-only**. No historical ASK quote or source-validated event-time spread at 16:06 is in this store. The correct buy model (bid + contemporaneous spread + adverse slippage) cannot be applied honestly.
2. **Funding and swap:** No verified effective-dated Dukascopy USA500 long CFD funding/rollover schedule, historical weekend/holiday multiples, account tier/activity status, or per-event financing amounts. Dukascopy's published policy shows rollover adjustments depend on account/trading activity. A generic fixed cost is not authorized by the supplied YAML.
3. **Dividend cash flows:** Dukascopy's index CFD dividend policy may pay/charge cash adjustments to positions held through ex-dividend. Historical rates and applicable settlement details are missing; the correct overnight marked-cash ledger cannot assume they are zero.
4. **Market orders and size:** Missing contract-version and legal broker entity for the historical symbol, lot/multiplier/tick and event-time market-order slippage evidence. A bid-only OHLC timestamp is not an actual long BUY fill. Published Dukascopy Europe product terms alone do not certify which historical account or instrument was traded.
5. **Historical session and release clocks:** Current broker trading hours do not prove that every 2017–2024 position could legally be held across the relevant broker maintenance/rollover. Individual statement times and schedule changes require as-of historical confirmation. Missing exit quotes after entry must preserve exposure and report an invalid/inconclusive execution, never silently drop losses.

Official broker source references:

- Dukascopy Europe USA500 CFD listing and current hours: https://www.dukascopy.com/europe/english/cfd/range-of-markets/
- Account-dependent overnight CFD policy: https://www.dukascopy.com/europe/english/cfd/cfd-overnight-policy/
- CFD dividend adjustments: https://www.dukascopy.com/europe/english/cfd/cfd-dividend-adjustment/
- Broker fee schedule: https://www.dukascopy.com/europe/english/about/fee-schedule/
- Fed historical scheduled meetings and exceptions: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm

**Do not** confuse an accepted historical source with a qualified contract and execution venue. **Do not** infer an observable after-cost alpha, IC, p-value, profit factor, signal effect or trade count from these metadata checks.

## 4. Decision, protocol and next permitted step

**Research intake verdict: `BLOCKED_DATA`.** The 53 source-complete pairs establish that the original event-window coverage requirement is feasible *in timestamps only*. They cannot establish that the matched after-cost FOMC excess is positive. Because both the user's research YAML and the repository market policy require real instrument-specific spreads and funding, it would be invalid to freeze the one economic trial and run a fabricated-cost backtest.

The required **Phase 3 signal-evaluation decision is not PASSED, FAILED, or performed**. This is an upstream Phase 2 source/cost block, prior to any preregistered performance screening. Do not retroactively call this a registered/frozen session or claim a negative strategy result.

**Unblock only after** an attributable historical Dukascopy USA500 **bid/ask** and **swap/financing + cash adjustment** record for 2018–2024 is available, and verify legal contract, historical hours, event as-of release clock and slippage/commission. Then audit admissible 53 (or fewer) events, make a frozen session with exactly the YAML's one trial, run a separate predeclared Phase 3 event study and native `ml4t.backtest.Engine` simulation with independent execution and cash-equity reconciliation. No performance tuning; no 2025+ holdout; no real-money execution.

## 5. Execution evidence and skills

- Read current VPS `AGENTS.md`, research operations/sessions, market policy, catalog forensics, source manifest, and existing status.
- Consulted ML4T `validate-data`, `point-in-time`, `calendar-ops`, `feature-validation`, `case-study-development`, `cost-model`, `run-backtest`, `purging-embargo`, `horizon-design` for their applicable source, clock, causality, execution and cost invariants.
- Script: `scripts/fomc_overnight_preflight_20261015.py` — source-only, no market return calculations.
- Tests: `tests/test_fomc_overnight_preflight_20261015.py` — clock, original publication, cancelled event, out-of-sample boundary, matched calendar and archived audit invariants.
- Source and numerical/return methods have **not** been approved by the frozen engine contract; this is deliberately a metadata intake, not a backtest.
