# Research inbox admission copy

Candidate: `fomc_overnight_uncertainty_premium_us500_cfd_20261015_v1`.
Original source identifier: `fomc_overnight_uncertainty_premium_us500_cfd_20261015_v1`.
Status: `THESIS_READY_UNVERIFIED`; `not_execution_approved: true`; `not_a_frozen_session: true`.
Selection family: `fomc_overnight_uncertainty_premium_us500_cfd_20261015_v1` (assigned as the single-candidate family because the source did not specify a family ID).
This remains a descriptive research design. It is not an executable CandidateSpec, backtest result, or execution approval.


# Hourly economic thesis discovery — 2026-10-15

**Candidate:** `fomc_overnight_uncertainty_premium_us500_cfd_20261015_v1`
**Decision:** `THESIS_READY_UNVERIFIED` — one research-design candidate, no executed trial.
**Authority:** VPS `/home/quant/dev/quant/quant-research`, not public GitHub where they differ. This report is not a registered, frozen or approved research session.

## A. Research brief

### Evidence and three-candidate comparison

| Candidate | Evidence about underlying market mechanism | Source / execution feasibility | Cost and leakage risk | Decision |
|---|---|---|---|---|
| **FOMC overnight equity risk premium, US500 CFD** | **VERIFIED:** Lucca & Moench (2015) document a historical *24-hour* pre-FOMC equity return. **Adverse VERIFIED:** Kurov, Wolfe & Gilbert (2021) find the broad effect weakened/disappeared after 2015. **VERIFIED:** Knox & Vissing-Jorgensen (2025) identify a post-2011 **overnight component** through 2023 that reverses later. **HYPOTHESIS:** a fixed CFD exposure isolates after-cost risk compensation. | Canonical Dukascopy `index_minute_ES` bid-only 1m price history is documented in the VPS. Scheduled Fed calendar is public. Ask/spread, cash swap, detailed clock and PIT calendar evidence are **UNKNOWN**. | Overnight funding, broker break, FOMC surprise, selection from published results; correlated to general equity beta. | **SELECT for independent source qualification and one MVP design**, not to claim tradeable alpha. |
| **London 4pm WMR FX benchmark order pressure** | **VERIFIED:** FCA studied benchmark order flow, higher quote spreads/price impact and changing market liquidity. **HYPOTHESIS:** a directional pre-/post-fix trading rule could monetize temporary demand. | Local `run_log/structural_alpha_mission_report_20261011.md` explicitly lists missing event-aligned broker quotes and fixing-window costs. Direction is not specified by clock alone. | High event impact and adverse selection; buyer/seller imbalance not inferable from ordinary OHLCV. | **DEFER / BLOCKED_DATA**. |
| **Funding-extreme contra-crowding, BTC/ETH perps** | **VERIFIED:** Binance's funding transfers between longs and shorts can reflect position pressure; reversal conditional on extremes is only a hypothesis. | Local `docs/audit/funding_extreme_reversal_mvp_20261011_v1.md` already tested its own fixed reversal rule and **REJECTED it** on a historical development period. Historical funding publication latency and true spread costs remain uncertain. | Previous observed failed trial and funding/fee timing; renaming it would be an invalid fresh discovery. | **REJECT as a new hourly candidate**; do not recycle failed rule. |

Source links: [Lucca and Moench, Journal of Finance](https://doi.org/10.1111/jofi.12196); [full New York Fed manuscript](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr512.pdf); [Kurov, Wolfe and Gilbert](https://doi.org/10.1016/j.frl.2020.101781); [Knox and Vissing-Jorgensen, Annual Review of Financial Economics](https://doi.org/10.1146/annurev-financial-090524-120826); [Fed official meeting calendars](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm); [Dukascopy Europe CFD trading hours](https://www.dukascopy.com/europe/english/cfd/range-of-markets/); [FCA WMR paper](https://www.fca.org.uk/publications/occasional-papers/occasional-paper-no-46-fixing-fix-assessing-effectiveness-4pm-fix); [Binance futures fees and funding](https://www.binance.bh/en-AE/support/faq/detail/98488a516eb84e3eb34605683dffd554).

### Economic explanation and falsification

- **Observed behavior (VERIFIED):** There was a large pre-announcement US equity return premium in the older literature, a later documented decline of the aggregate effect, and evidence for a narrower overnight component after 2011. These studies use securities or indices, not executable Dukascopy CFD fills. The more recent study's approximately 20 basis-point overnight figure is **historical research evidence**, not forecast performance, modeled costs or an executable CFD result.
- **Counterparty mechanism (INFERENCE):** Risk-averse investors and hedgers may pay an opportunity cost to avoid carrying equity risk immediately before an uncertain policy announcement. They are the potential economic counterparties. Neither trade-level seller identity nor risk-transfer causality is verified. Systematic risk transfer is a candidate explanation, not a fact.
- **Persistence (HYPOTHESIS):** Public meeting dates do not remove underlying macro uncertainty. The edge could survive competition only if exposure is genuinely undesirable for constrained players and compensation exceeds broker costs. It can be destroyed by reduced uncertainty, anticipation by participants, expensive overnight funding, widened spreads, loss of short-term return asymmetry, and the fact that the relevant daylight component may have been larger.
- **Different from standard strategies:** One ex-ante scheduled macro event triggers a long; no price momentum, volatility indicator, ORB, stop-loss, mean reversion or fitted classifier drives trading.
- **Falsification:** After exact source and cost qualification, the average *paired after-cost* candidate-minus-ordinary-overnight return is nonpositive, or the candidate's own mean after-cost return is nonpositive. Also question the event-risk mechanism if the matched ordinary overnights earn the same return, or source timing explains nearly all apparent edge.

### Source and execution distinction

The authoritative VPS repo was read: `AGENTS.md`, `docs/research_operations.md`, `docs/research_sessions.md`, `docs/architecture/market_scope_policy.md`, `config/research_contract_v1_example.yaml`, `run_log/validation_status.json`, catalog and prior-source audit files, a funding strategy trial report, a Gold/FX trend trial report, and the structural-alpha mission report. The checkout has unrelated dirty/staged/untracked work. **None was changed.**

**VERIFIED repository data identity:** The canonical `index_minute_ES` store is Dukascopy `usa500idxusd` bid-only one-minute historical CFD quotes, USD, and **not** dated CME futures contracts. The catalog records acceptance for its general source, not a pass for the specific FOMC trading clock. Its exact statement-day 16:06 and 09:36 event bars have **not** been audited. Dukascopy Europe lists `USA500.IDX/USD` and a summer/winter daily maintenance break; the intended legal broker entity, historically applicable timetable, spread, financing, lot and multiplier have **not** been qualified.

**Prior selection bias:** 2017–2023 overlap published academic studies. Some 2013–2024 US500 market history has been used in existing repository research. This MVP is retrospective exploratory, not a fresh independent holdout. Historical FOMC calendar pages do not alone prove as-of-publication dates or later corrections. The protected allocation holdout in 2025–2026 must remain untouched.

### Rule contract (candidate and baseline)

**Author's original:** Lucca and Moench study approximately 14:00 ET on the day before a scheduled FOMC decision to approximately 14:00 ET on statement day. Historical statements were published near 14:15 ET in their older sample. **Our proposed CFD overnight clock is an independent adaptation**, not a replication of their full 24-hour rule. Knox and Vissing-Jorgensen motivate the overnight component but do not validate this exact CFD clock.

**Adapted product:** Historical Dukascopy US500 bid-price proxy (`index_minute_ES`, source `usa500idxusd`) representing the broker's `USA500.IDX/USD` CFD, with broker mapping still to be verified. Quote/settlement assumed USD, exact contract specifics and costs unknown. **No exchange-traded volume or futures roll is used.**

**Eligibility:** Consider only preannounced scheduled FOMC policy-statement days D from the official calendar, with a reconstructable as-of publication timestamp. The preceding calendar date D−1 and D must both be complete US cash-equity sessions with no early close or cash-market holiday. A scheduled statement must occur after the planned exit. Exclude emergency or unscheduled events. Qualify historical CFD trading hours separately from the cash calendar.

**Entry:** On D−1 at **16:05 America/New_York**, after all observations needed for the decision exist, send one long market order. Fill no earlier than the **16:06** next valid one-minute bar open/quote. Entry is **ask + adverse buy slippage**, never bid or same-bar close. **Exit:** On D at **09:35 ET**, send a market liquidation order; fill no earlier than **09:36** at **bid − adverse sell slippage**. Do not hold through the policy statement. No stop, profit target, dynamic filter or re-entry. One long position max, 10% marked equity notional, no gross leverage over 1.0. Hold through maintenance break if contract rules permit; charge full overnight swap and gap exposure.

**Control:** For each D, select **D−7 calendar days** as a hypothetical corresponding statement date and trade that preceding overnight with exactly the same local times, side, notional fraction, costs and eligibility gate. It must not itself be a scheduled FOMC night. Never replace a bad control with a better-performing night. The same pre-entry data qualification must apply to candidate and control. The comparison is candidate net return per notional less control net return per notional, averaged over paired events. Flat cash is a secondary baseline.

**Price-data clock:** Source timestamps are 1m bar **starts** in UTC. The bar beginning 16:04 becomes available at 16:05; the entry fill cannot use the uncompleted 16:05 bar. The event signal itself uses the as-of calendar and requires no market-return indicator or lookback. All local clocks must be converted using `America/New_York` with historical DST, with independent full-US-equity and CFD broker session calendars.

**Feature contract:** Two calendar-only eligibility predicates are necessary: `scheduled_fomc_overnight_eligibility` and `matched_control_overnight_eligibility`. Their complete boolean formulas, field lists, grouping, warmup, availability and adversarial test cases are in the YAML. Both are `EXTENSION_REQUIRED` pending native installed ML4T API inspection. **No native calendar feature or execution semantics have been verified.** Do not hand-roll a feature engine: use the event scheduler or an audited minimal approved calendar extension, and native ML4T execution for the eventual one trial.

### Single decisive MVP and stopping rules

**Proposed development**: 2017-01-01 through 2024-12-31 inclusive; UTC exclusive end 2025-01-01. This is eligible only if the local research lead verifies existing protected boundaries. No future or protected 2025–2026 data inspection. The calendar requires advance-publication dates before each decision. The event count has **not** been checked against actual prices. Use a provisional coverage gate of **at least 50 valid paired events across at least 6 distinct calendar years** before evaluating economic significance. These minimums are feasibility and descriptive precision floors, not statistical power guarantees.

**Primary evaluation:** Mean paired net excess over a same-weekday ordinary overnight, in fraction/basis points of position notional. Give an event-level 95% HAC interval with serial-dependence diagnostics; review year concentration descriptively, not as an extra optimization filter. Supporting metrics: candidate absolute net mean, return distributions, event count, by-year contribution, peak-to-trough account-equity drawdown, fill timing, entry-to-exit adverse gap, actual costs (spread/fee/slippage/overnight finance) and cash/equity reconciliation.

**One experiment only:** No parameter search, regime filter, secondary time window or more instruments. Freeze rules only AFTER critical unknowns are resolved and BEFORE any outcome is read. All later changes motivated by results are new trials and must be counted.

**Outcome policy:**

- `BLOCKED_DATA`: historical as-of schedule, entry/exit bar and product mapping, effective-dated ask/spread, slippage/fee/swap, or legitimate broker tradability cannot be verified. Do not run an apparently cost-aware trial with fabricated charges.
- `INCONCLUSIVE`: adequate data but fewer than 50 independent pairs/six years, source failure after position entry, a confidence interval including zero, or return concentrated in too few independent subperiods.
- `REJECT`: valid candidate has nonpositive mean after-cost return or nonpositive paired after-cost mean. Stop without modifying parameters.
- `VALIDATE_MVP_CANDIDATE`, not approved trading: if mean candidate return and paired mean both positive, paired lower 95% HAC confidence bound positive, and eligibility plus cost/parity checks pass. Acknowledge that publication overlap prevents independent prospective confirmation.

**Adversarial review:** Literature conflicts on whether the broad premium persists; the 2025 overnight study is not a true held-out result for the 2017–2024 window. Ordinary equity overnight drift can fully explain returns. Long CFD entry requires an ask that bid-only datasets lack. Overnight financing may dominate a sparse event strategy. The 16:15 ET maintenance break and 09:30 cash reopen can cause gaps/slippage; planned exits may not fill. An FOMC revision or emergency announcement must never be counted as known before publication. CFD leverage/account rules and protected holdout must be independently audited. Positive returns, even if found, likely retain conventional US equity beta and do not yet prove diversification versus the incumbent portfolio.

## C. Research handoff — addressed to the ChatGPT Web research lead

**One selected new thesis:** Calendar-triggered US500 CFD long over the night before a scheduled FOMC statement, 16:06 ET to 09:36 ET. Compare exactly one prior-week same-weekday matched control overnight, with equal 10% equity notional, real price-side/swap/commission/slippage costs. No ML or technical indicators. Reject against either absolute after-cost mean or paired after-cost excess. The YAML contains the deterministic proposed contract; it is **not registered or frozen**.

**Verified:** Primary and adverse papers; official Fed schedule site; Dukascopy's quoted instrument/hours; VPS canonical `index_minute_ES` maps to `usa500idxusd` bid-only 1m, not CME ES. Existing repo studies and holdout boundaries were inspected. No code, data transformation, trial or backtest was executed.

**Independent verification before any native ML4T work:**

1. Recover exact historical *as-of* scheduled FOMC statement dates and release-time schedules; distinguish rescheduled, cancelled and emergency events.
2. Inspect effective-dated Dukascopy US500 CFD contract identity, broker legal entity, contract multiplier, lot/tick, long financing swap calendar, historical spreads and bid/ask order execution. Determine if the canonical historical source is an adequate actual-contract price proxy.
3. Verify full event-and-control 1m coverage at 16:06/09:36 ET and each intervening broker break, DST change, cash holiday and early close. Do this as a **metadata/source qualification only**, without computing historical returns or opening protected data.
4. Inspect the installed ML4T version and event-scheduler capabilities. Implement calendar eligibility as audited scheduler metadata or approved extension only if unsupported natively. Use `ml4t.engineer.compute_features` for any features that turn out natively expressible. Run future simulations only through native `ml4t.backtest.Engine` with event-driven NEXT_BAR executable fills and matched financing/cash ledgers. Do not write a custom simulator.
5. Confirm 2017–2024 is permissible retrospective development; no 2025–2026 protected allocation access. Review any prior FOMC-specific trials not identified in the repository search; the existing work might require this to be classified as an already-observed variant.
6. Only after qualification, register ONE source-qualified trial through existing ResearchContract/RunPermit and MVP workflow. Do not treat a file integrity PASS as economic evidence. Independently audit event dates, clock, trades, costs, ledger and metric. Never deploy or place orders.

**Trade-material questions:** Which legal broker and historical instrument contract is used? Is the canonical bid OHLC equivalent to the execution product and does it exist at both clock times? What contemporaneous ask/spread and adverse slippage applied? What financing rollover and triple-swap was charged? Was the meeting date announced or moved after entry? Is each scheduled announcement strictly after the exit? Which historical cash-market early closures and CFD maintenance breaks apply? Are the event bars labeled by start or end? How is an unfillable exit handled and accounted for? Can a matched D−7 control be qualified without cherry-picking? Does the 2017–2024 period conflict with frozen study boundaries? Does native ML4T provide suitable calendar scheduling, NEXT_BAR fill semantics and cash-cost accounting? Is 50-pair/six-year coverage actually feasible? Do observed historical event profits merely reflect ordinary equity overnight beta? How correlated would the final independently valid strategy be with the current index-heavy strategies? Every unresolved item needs an evidence-backed answer before executable research acceptance.

**Final status:** `THESIS_READY_UNVERIFIED`, with source-and-cost blockers. STOP this hourly iteration after deliverables. The recurring hourly research automation must remain enabled for the next distinct thesis.

## Migration notes and source material retained

These source-local references named files absent from this checkout. Their exact reference records are retained below as unconfirmed provenance; they are not represented as validated sources.

```yaml
- id: local_repo_source_manifest
  category: inspected_authoritative_vps_repository
  relevance: Maps source symbol usa500idxusd to index_minute_ES, bid-only one-minute
    snapshots.
  local_path: docs/audit/mechanicalpremia_dukascopy_2013_2024_source_manifest_v1.json
- id: local_repo_data_eligibility
  category: inspected_authoritative_vps_repository
  relevance: Has per-day acceptance files but bid/ask, trading hours and costs remain
    unverified.
  local_path: docs/audit/mechanicalpremia-us500-us100-2013-2026-v1-data-eligibility.json
```

The exact source candidate YAML and brief are also present at `docs/research_inputs/fomc_overnight_uncertainty_premium_us500_cfd_20261015_v1/` (byte-identical to this raw source before handoff normalization). The supplemental `fed_original_calendar_2017_2024.yaml` is preserved below because inbox admission permits exactly two files. Its per-event dates, publication times, source URLs, and cancellation exclusion remain source-only material, not independently verified by this migration.

```yaml
# Pre-announced FOMC schedule reconstruction for SOURCE QUALIFICATION ONLY.
# Source: Federal Reserve original tentative-meeting press releases dated BEFORE
# all scheduled 2017-2024 meetings. All dates are STATEMENT dates, not meeting starts.
# The original release timestamps are provided as local Eastern times with UTC offsets.
# Release timestamp has no post-result use. Subsequent deviations need independent
# event-by-event as-of confirmation before any price-return trial.
# The cancelled 2020-03-18 meeting must NEVER create an entry after Mar 15 cancellation.
metadata:
  status: source_calendar_reconstruction_not_frozen_strategy
  time_zone: America/New_York
  holdout_cutoff_exclusive_utc: "2025-01-01T00:00:00Z"
  statement_release_convention: "2pm Eastern second day (subject to per-event audit)"
  source_calendar: "XNYS (separate from Dukascopy trading hours)"
years:
  2017:
    published_at: "2016-06-28T14:00:00-04:00"
    url: https://www.federalreserve.gov/newsevents/pressreleases/monetary20160628a.htm
    statement_dates: [2017-02-01, 2017-03-15, 2017-05-03, 2017-06-14, 2017-07-26, 2017-09-20, 2017-11-01, 2017-12-13]
  2018:
    published_at: "2017-05-11T14:00:00-04:00"
    url: https://www.federalreserve.gov/newsevents/pressreleases/monetary20170511b.htm
    statement_dates: [2018-01-31, 2018-03-21, 2018-05-02, 2018-06-13, 2018-08-01, 2018-09-26, 2018-11-08, 2018-12-19]
  2019:
    published_at: "2018-05-25T12:00:00-04:00"
    url: https://www.federalreserve.gov/newsevents/pressreleases/monetary20180525a.htm
    statement_dates: [2019-01-30, 2019-03-20, 2019-05-01, 2019-06-19, 2019-07-31, 2019-09-18, 2019-10-30, 2019-12-11]
  2020:
    published_at: "2019-05-17T10:00:00-04:00"
    url: https://www.federalreserve.gov/newsevents/pressreleases/monetary20190517a.htm
    statement_dates: [2020-01-29, 2020-03-18, 2020-04-29, 2020-06-10, 2020-07-29, 2020-09-16, 2020-11-05, 2020-12-16]
    cancelled_statement_dates:
      - date: 2020-03-18
        cancelled_asof: "2020-03-15T00:00:00-04:00"
        note: "March 17-18 regular meeting cancelled following March 15 unscheduled actions; Fed historical 2020 archive. Date is conservative midnight timestamp for exclusion ONLY, not exact news time."
        url: https://www.federalreserve.gov/monetarypolicy/fomchistorical2020.htm
  2021:
    published_at: "2020-07-02T10:00:00-04:00"
    url: https://www.federalreserve.gov/newsevents/pressreleases/monetary20200702a.htm
    statement_dates: [2021-01-27, 2021-03-17, 2021-04-28, 2021-06-16, 2021-07-28, 2021-09-22, 2021-11-03, 2021-12-15]
  2022:
    published_at: "2021-06-04T11:00:00-04:00"
    url: https://www.federalreserve.gov/newsevents/pressreleases/monetary20210604a.htm
    statement_dates: [2022-01-26, 2022-03-16, 2022-05-04, 2022-06-15, 2022-07-27, 2022-09-21, 2022-11-02, 2022-12-14]
  2023:
    published_at: "2022-06-24T14:00:00-04:00"
    url: https://www.federalreserve.gov/newsevents/pressreleases/monetary20220624a.htm
    statement_dates: [2023-02-01, 2023-03-22, 2023-05-03, 2023-06-14, 2023-07-26, 2023-09-20, 2023-11-01, 2023-12-13]
  2024:
    published_at: "2023-06-23T11:30:00-04:00"
    url: https://www.federalreserve.gov/newsevents/pressreleases/monetary20230623a.htm
    statement_dates: [2024-01-31, 2024-03-20, 2024-05-01, 2024-06-12, 2024-07-31, 2024-09-18, 2024-11-07, 2024-12-18]
```
