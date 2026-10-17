# Research inbox admission copy

Candidate: `audusd_policy_carry_cfd_v1`.
Original source identifier: `AUDUSD_POLICY_CARRY_CFD_V1`.
Status: `THESIS_READY_UNVERIFIED`; `not_execution_approved: true`; `not_a_frozen_session: true`.
Selection family: `audusd_policy_carry_cfd_v1` (assigned as the single-candidate family because the source did not specify a family ID).
This remains a descriptive research design. It is not an executable CandidateSpec, backtest result, or execution approval.


# Hourly economic thesis research — 2026-10-15T02:04:19Z

**Selected:** `AUDUSD_POLICY_CARRY_CFD_V1`
**Status:** `THESIS_READY_UNVERIFIED` — design ready for independent qualification, **not** data-qualified, execution-approved, repository-frozen, or profitable.
**Work performed:** Source and VPS-document inspection only. No feature computations, market-history queries, optimization, registered trial, backtest, holdout access, repository write, or orders.

## A. Research brief

### Sources and evidentiary status

**VERIFIED — Independent literature.** Lustig, Roussanov and Verdelhan (2011), *Common Risk Factors in Currency Markets*, identify a common global-risk exposure of higher-interest-rate currency portfolios. Their design concerns diversified currency portfolios and FX forwards. It does **not** prove positive expected return from a single AUDUSD margin-FX/CFD instrument or from central-bank policy rates as the sole predictor. Source: https://www.nber.org/papers/w14082 ; published article DOI: https://doi.org/10.1093/rfs/hhr068.

**VERIFIED — Independent risk evidence.** Brunnermeier, Nagel and Pedersen (2009), *Carry Trades and Currency Crashes*, associate currency-carry positions with negative skew and crash-prone funding-liquidity deleveraging. This supplies both a possible economic payer and a refutation regime. Source: https://www.nber.org/books-and-chapters/nber-macroeconomics-annual-2008-volume-23/carry-trades-and-currency-crashes.

**VERIFIED — Authoritative input sources exist.** The RBA provides its target-rate decision history at https://www.rba.gov.au/statistics/cash-rate/. The Federal Reserve provides policy target-rate history at https://www.federalreserve.gov/monetarypolicy/openmarket.htm. Individual announcements and effective dates must still be reconstructed as point-in-time events.

**VERIFIED — Broker costs can invalidate the proxy.** Dukascopy's official rollover guide states that held forex exposures receive swap adjustments based on overnight market rates and broker costs. Applied swaps need not equal publicly displayed swaps. Source: https://www.dukascopy.com/wiki/en/forex-cfds/account-management/rollovers/. No historical applied swap series was verified in this research iteration.

**VERIFIED — VPS context.** In `/home/quant/dev/quant/quant-research`, read `AGENTS.md`, `docs/research_operations.md`, `docs/research_sessions.md`, `docs/architecture/market_scope_policy.md`, `config/research_contract_v1_example.yaml`, `run_log/validation_status.json`, `data/processed/_manifest.json`, `docs/audit/gold_fx_trend_diversification_intake_20261015.md`, and `docs/audit/tokyo_fix_program2_cross_currency_20261011_v1.md`. The existing Gold/FX intake documents Dukascopy AUDUSD one-minute quote-price history through 2024 and explicitly notes that this is **not** verified executable bid/ask or swap data. Existing Gold/FX trend research is different from rate carry; existing Tokyo-fix evidence is not reused as an unseen test. The checkout contains substantial legitimate dirty/untracked work; it was not changed.

**INFERENCE.** An investor holding the higher-yielding currency may be paid for exposing capital to abrupt funding and currency-crash risk. In a broker margin-FX product, the financing credit can differ materially from interbank rate spreads and can be negative on both directions after markup.

**HYPOTHESIS.** The last publicly known RBA cash-rate target minus the Fed upper target bound can select the net-positive AUDUSD exposure after **actual broker costs**. This has not been tested and may be false.

**UNKNOWN.** Actual broker applied swaps, exact CFD-versus-margin-FX contract mapping, historical executable spread, publication-time data joins, qualifying coverage, leverage/margin terms, native ML4T rollover support and number of independent exposure episodes.

### Three candidate mechanisms

| Candidate | Economic payer / persistence | Key regime and falsifier | Data/cost fit | Decision |
|---|---|---|---|---|
| **1. AUDUSD policy-rate carry** | Funding-currency borrowers and hedgers pay investors to bear currency/funding risk; global risk-bearing constraints may persist. | Supports orderly funding markets; crashes or broker swap markup can destroy the premium. Reject on nonpositive actual-cost mean; positive result may remain inconclusive if only one policy cycle. | AUDUSD quote prices documented; official rates accessible; *historical broker swaps unavailable in inspected context*. Very low turnover but costly financing. | **SELECT, execution blocked pending cost/source qualification.** |
| **2. S&P 500 turn-of-month return premium** | Speculative story: payroll, pension, or month-end flows might create predictable equity demand. | Original historical research observed the pattern but did **not** find higher month-end mutual-fund inflows or volume sufficient to explain it. If contemporary after-cost CFD return is nonpositive or flow explanation absent, mechanism fails. | Simple calendar and US500 historical quotes, but overlaps known equity beta and the previous index calendar discoveries. | **REJECT as a fresh economic thesis:** causal payer not established; weak incremental diversification. |
| **3. Multi-asset time-series momentum** | Hedgers can pay speculators who absorb price risk while macro information diffuses. | Whipsaw and reversals can break trend premia; persistent profits must survive real roll/swap costs. | Existing VPS contains related Gold/FX trend and index momentum research; proposed new variant would repeat the mechanism and observed samples. | **REJECT as redundant for this hour.** |

**Source for candidate 2:** McConnell and Xu (2008), *Equity Returns at the Turn of the Month*, https://rpc.cfainstitute.org/research/financial-analysts-journal/2008/equity-returns-at-the-turn-of-the-month. The original study itself describes the flow mechanism as unexplained; do not convert the calendar regularity into a claimed cashflow causal explanation.

**Source for candidate 3:** Moskowitz, Ooi and Pedersen (2012), *Time Series Momentum*, https://doi.org/10.1016/j.jfineco.2011.11.003. Previous strategy research in the VPS is an additional reason not to reselect this return driver.

### Candidate-by-candidate mechanism tests

**1. AUDUSD policy carry — selected.** **Behavior:** interest-differential-aligned positions can earn a premium. **Actors:** hedgers, global investors, funding-currency borrowers, and liquidity-constrained risk absorbers. **Persistence:** risk premia can persist because the exposure loses during adverse funding conditions, even in competitive markets. **Effective payer:** investors transferring global currency crash risk, less broker financing markup. **Supports/destroys:** calm funding regimes versus sudden risk-off deleveraging, policy convergence, or punitive swaps. **Difference:** macro policy-risk premium rather than a price breakout, trend rule, overnight equity calendar event, or Tokyo settlement flow. **Falsifier:** verified net after-cost monthly expectancy nonpositive, or no reliable signed broker carry despite the policy differential. The causal-transfer claim is **HYPOTHESIS**, not a single-pair result from the cited academic studies.

**2. S&P 500 turn-of-month — rejected.** **Behavior:** historical excess equity index return around month boundaries. **Actors:** often proposed as payroll, institutional allocation or portfolio rebalancing orders, but actor identification is **UNKNOWN**. **Persistence:** recurring institutional calendar flows are a plausible **INFERENCE**, not a verified cause. **Effective payer:** unidentified liquidity-demand participants; this is precisely why mechanism credibility is weak. **Supports/destroys:** stronger predictable flow concentrations might support it; weak flows, competition, and higher CFD friction may destroy it. **Difference:** scheduled calendar equity exposure, not a breakout, but it overlaps the previously selected S&P 500 calendar-return family. **Falsifier:** no contemporary after-cost excess return in matched dates or no evidence of the claimed incremental flow; importantly, McConnell and Xu (2008) already disputed simple fund-flow/volume explanations.

**3. Diversified time-series momentum — rejected as redundant.** **Behavior:** returns may persist over intermediate horizons and reverse later. **Actors:** end-investor hedgers, speculators and investors reacting gradually to macro news. **Persistence:** hedgers may transfer trend-following risk to speculators (a proposed mechanism supported by published evidence). **Effective payer:** risk-averse hedgers when trend-followers supply directional risk capital. **Supports/destroys:** sustained repricing can support the signal; fast reversals and range-bound markets can destroy it. **Difference:** this is **not different enough** from the repo's already-studied momentum/trend family, even though it differs from the selected macro carry mechanism. **Falsifier:** no standalone after-cost conditional return in authorized development windows or failure to differentiate existing trend sleeves. Existing trials must be reviewed, not overwritten or repackaged as a new unseen study.

### Why candidate 1 was selected

Relative to the previous S&P 500 European-opening and FOMC overnight theses, the selected proposal changes **both asset class and economic driver**: it tests the transfer of a macro currency risk premium through an OTC broker's financing schedule. The sign of a published interest-rate differential is a simple, falsifiable signal. It needs no indicator optimization, genuine exchange volume, order book, or ML model. Existing AUDUSD quote data make a source audit plausible.

This preference is **conditional**, not a claim of immediate backtest readiness. A single AUDUSD pair is a materially weaker extrapolation than the diversified forward portfolios studied in the literature. Historical broker swap availability is the highest-value go/no-go question; do not spend resources running quote-only price PnL while this is unresolved.

### Frozen proposed trade design — adaptation, not an author's original rule

- **Original academic object:** long high-interest and short low-interest currency portfolios built from forward/interest-rate information. No source paper is being represented as specifying the following retail AUDUSD trading rule.
- **Research instrument:** Dukascopy `AUD/USD` historical minute-quote proxy, canonical key candidate `forex_minute_AUDUSD`; exact executable broker OTC margin-FX or CFD contract, minimum lot, settlement and venue must be verified. Base AUD; quote and book USD.
- **Clock:** `America/New_York` with DST. Observe 1-minute UTC **bar-start** timestamps after verifying adapter conventions. On the **first eligible New York FX trading day of each month**, decide at **10:00 ET** using only RBA/Fed policy levels publicly available by **16:00 ET of the previous completed FX trading day**. The previous-day cutoff deliberately excludes same-day news and provider latency ambiguity.
- **Indicator:** `spread_pp = RBA_cash_rate_target_pct_asof - Fed_funds_target_upper_pct_asof`, in percentage points. No smoothing and no price lookback. Warm up with the last valid public policy decision from both banks. `spread_pp>0`: long AUDUSD; `spread_pp<0`: short AUDUSD; `spread_pp=0`: flat. The upper Fed bound is a deliberately simple **proxy**, not a deposit rate.
- **Orders:** Market only, earliest 10:01 ET next 1m bar open, never use the decision bar as a fill. Hold **10,000 AUD** signed units until the next monthly target-direction change; skip re-trading unchanged positions. One position maximum. USD 100,000 initial research book; no intentional leverage. Flatten at the development-period terminal eligible fill for accounting. No stops, targets, technical conditions, or optimization.
- **Missing data:** A required missing broker price, bid/ask, macro release or rollover accounting entry yields `BLOCKED_DATA`; do not fabricate prices, fills or swap credits. At the monthly event, tolerate at most 30 minutes to obtain an actual eligible future minute. Weekend/holiday settlements must follow actual broker value dates.
- **Costs:** Pay actual ask when buying and sell at actual bid. Include commission, adverse market-order slippage, exact long/short daily swaps, holiday and triple-day value dates, funding/margin and conversion where applicable. Never charge rollover twice if a broker represents the adjustment in rollover prices.
- **Research data:** proposed retrospective development window **2015-01-01 through 2024-12-31**. This period overlaps already-observed other-strategy research; it is **not** a fresh untouched holdout. No data at or after the protected boundary may be accessed to improve the design.

### Native ML4T handoff

The required signal is almost entirely event-driven macro state. Do **not** manufacture RSI, ROC, ATR or technical filters merely to increase native feature count.

| Contract | Formula / inputs | Causality / tests | Native classification |
|---|---|---|---|
| `rba_cash_rate_pct_asof` | Last RBA rate target whose public release *and effective time* satisfy previous-session cutoff. Inputs: target rate, announcement/effective timestamp. | Backward-asof, previous-FX-day 16:00 cutoff; append-future-release invariance; official announcement spot-check. | `EXTENSION_REQUIRED` |
| `fed_upper_target_pct_asof` | Last Fed target range **upper** bound satisfying same rule. | Release/effective-time tests; no full-sample backfill; check percent-unit convention. | `EXTENSION_REQUIRED` |
| `aud_minus_us_policy_spread_pp` | `rba_cash_rate_pct_asof - fed_upper_target_pct_asof`. | Numerical cases 4.25−5.50=−1.25 and 5.00−3.50=+1.50; equality→flat. | `EXTENSION_REQUIRED` |
| `ny_monthly_eligible_event` | Calendar predicate on first broker-tradable NY FX day, 10:00 ET. | NY DST tests, no weekend fills, next-minute fill only. | `NATIVE_UNVERIFIED` |
| `historical_actual_rollover_cashflow` | Broker signed daily long/short swap in USD or pip-equivalent, counted once at actual settlement. Non-predictive accounting input. | Broker statement parity; triple-day, holiday and value-date audit. | `DATA_UNAVAILABLE` |

Preferred native research stack: inspect installed `ml4t.engineer.compute_features` and `ml4t.backtest.Engine` before implementation. Use the approved repository feature gateway, a minimal point-in-time macro join extension, native Strategy/Engine execution, native broker accounting if supported, and an approved narrowly scoped financing adapter only when native capability is genuinely missing. **No native feature signature or rollover integration was verified in this iteration.** The official ML4T reference skills read were `point-in-time`, `compute-features`, `lookahead-bias`, `run-backtest`, `transaction-costs` and `cost-model`. Their examples are methodology, not proof of installed API compatibility.

### Smallest decisive MVP

**Trial budget:** one preregistered AUDUSD sign-of-policy-differential rule with no threshold, lookback, symbol, or parameter sweep. Cash is the primary baseline. Always-long AUDUSD at the same 10,000 AUD units and actual long swaps is a prespecified context comparator.

**Primary metric:** mean monthly USD after-cost strategy PnL, expressed relative to fixed USD 100,000 starting equity, in excess of cash. Use a prespecified six-month moving-block bootstrap for a 95% confidence interval. Monthly observations are **not** independent trades; report signed exposure episodes separately. Risk metrics include daily-equity Sharpe if defined, max drawdown, worst month, crash losses, swap/transaction drag, count of long/short months, and 1x/2x execution-friction sensitivity. Do not annualize by trade count.

**Minimum coverage:** at least 96 complete monthly observations over at least eight years, with 12 or more months in each direction. Four or more independent signed exposure episodes spanning both directions are necessary to treat positive evidence as potentially qualifying; if only one long and one short policy regime exist, a positive sample mean remains **INCONCLUSIVE** regardless of naive significance. No regime statistics were computed in this iteration.

**Economic falsifier:** A qualified mean monthly net return ≤0 after exact broker execution and swap costs yields **REJECT**; there is no economic justification for tuning. Positive net mean with a 95% lower confidence bound ≤0, or inadequate independent episodes, yields **INCONCLUSIVE**. Only positive after-cost mean with a positive lower confidence bound, adequate episodes, valid cashflow reconciliation and positive mean under 2x non-financing execution costs warrants **VALIDATE**, not trade approval.

**Blockers:** If exact broker identity, true historical swap credits/debits, price quote semantics, required monthly fills or point-in-time policy announcements cannot be qualified, return `BLOCKED_DATA` without executing a backtest. If the installed native engine cannot reconcile overnight financing, return `BLOCKED_CAPABILITY` unless an approved native-compatible adapter is verified. A negative or incomplete data audit is a valid research result.

### Adversarial review

1. **Is it merely a story?** No: global risk and currency crashes have independent literature. However, the transfer from forward baskets to *one CFD pair* is a new, weak hypothesis. Keep that limitation explicit.
2. **Is the input the thing that pays?** No: a policy target spread is not the contract's realizable forward discount or broker swap. Actual broker financing may charge both long and short positions. This is the central failure test.
3. **Can historical releases leak?** Yes: effective dates and revised data are not necessarily first-public timestamps. Build a release-asof archive. The previous-session cutoff is deliberately conservative.
4. **Can same-bar fills leak?** Yes: enforce decision at 10:00 and earliest eligible fill at 10:01 NY local, with actual UTC offset on each day.
5. **Is this the source paper's trading rule?** No. Authors examined diversified forwards. Single-pair, central-bank targets, and broker rollover accounting are explicit adaptations.
6. **Can broker economics dominate?** Yes. Historical swaps, commissions, bid/ask, market-order slippage, margin interest and triple/holiday rollovers are required. A quote-only PnL run would be invalid.
7. **Is the sample large enough?** Ten calendar years can contain very few independent rate-sign episodes. Standard monthly sample counts inflate effective evidence. Positive claims need independent episodes and a block-based uncertainty method.
8. **Could the edge be a known factor?** Yes: AUD is sensitive to global growth/commodity risk, USD monetary cycles, and existing FX trend exposures. Measure standalone validity first and portfolio correlation only after an economically valid result.
9. **Would negative results be informative?** Yes: a qualified cost-dominated failure establishes that this simple retail transfer is not economically viable under the chosen broker contract. Stop instead of optimizing.

## C. Research handoff — addressed to ChatGPT Web research lead

**Lead:** The selected candidate is `AUDUSD_POLICY_CARRY_CFD_V1`. It is a new macro currency risk-premium mechanism, not another index opening event or Gold/FX 60-session price-trend variant. The supporting literature is about diversified forward carry and crash risk. The exact proposed monthly AUDUSD CFD/margin-FX adaptation is untested. The machine-readable proposal is the companion `thesis_candidate.yaml`. It is **not** a frozen research session or an execution permit.

**First action:** Independently confirm whether historical **applied** Dukascopy AUDUSD long/short swaps and full contract terms can be obtained for 2015–2024, including rollover value dates. If these cannot be reconstructed, report `BLOCKED_DATA` and stop. Do not substitute policy-rate carry or today's posted swap rate as historical financing. Then verify broker product identity, exact quote side, monthly fill coverage, central-bank release and effective timestamps, and installed native ML4T and financing capabilities. Only if all gates pass should a separate executor register one bounded native MVP trial with the repository's immutable permit/attempt workflow. Preserve the dirty working tree and all holdout restrictions.

**Questions that can materially change trades or inference:**

1. Is the target tradable product a Dukascopy margin-spot FX position, a specific CFD, or another broker's AUDUSD contract? What are its lot, margin, shorting, commission, financing and settlement terms?
2. Is historical applied daily swap information available separately for each side and all holding dates? Are swaps recorded as price reopen adjustments, cash transfers, or both?
3. Do the canonical AUDUSD minute candles cover the desired 10:01 ET executions and broker rollover windows with verified UTC bar-start timestamps, actual bid and ask, and DST rules?
4. Which official Federal Reserve target value represents the USD financing proxy: upper bound as proposed, midpoint, effective overnight rate, or actual tradable OIS? A change must be registered as a **new** economic trial, not quietly fixed after returns.
5. Do RBA/Fed historical records include **first public announcement times** and **effective times**, or only subsequently maintained rate tables? Can conservative availability be independently proven?
6. What broker holiday calendar, daily rollover cutoff, Wednesday/triple-day and holiday value-date schedule applies historically?
7. Can installed native ML4T model sustained positions and actual signed financing with verifiable fills/cash/equity reconciliation, or is a sanctioned financing adapter needed?
8. How many distinct long/short policy-spread **episodes**, not merely months, fall within the authorized 2015–2024 development window? If fewer than four, can the question only be answered as REJECT or INCONCLUSIVE rather than VALIDATE?
9. Does the research's AUDUSD macro risk simply duplicate the already-observed Gold/FX trend sleeve or another existing strategy driver? Do not test allocator holdouts to answer.
10. Can any existing research evidence change the declared trial count or contaminate the proposed retrospective period? Record all known prior comparisons and never relabel old data as unseen.

**Stopping point:** Thesis discovery completed. No code, data transforms, backtests, deployments, or repository modifications were performed. The recurring hourly automation must stay enabled for subsequent distinct thesis investigations.

## Migration notes and source material retained

The source used `AUDUSD_POLICY_CARRY_CFD_V1`; the stable inbox identifier is normalized to `audusd_policy_carry_cfd_v1`. No rule or result was changed by this identifier normalization.

The original `mode`, `execution_approval`, and repository authority/iteration metadata are retained below; the required non-approval flags are explicit in the thesis YAML.

Source-only top-level metadata not represented by the handoff root schema is retained verbatim here:

```yaml
research_iteration_utc: '2026-10-15T02:04:19Z'
mode: MVP_RESEARCH_DESIGN_ONLY
execution_approval: false
repository_authority:
  repository: https://github.com/hzminhzz/quant-research
  examined_vps_path: /home/quant/dev/quant/quant-research
  branch_at_inspection: local-first-main-sync-20261014
  documents_read:
  - AGENTS.md
  - docs/research_operations.md
  - docs/research_sessions.md
  - docs/architecture/market_scope_policy.md
  - config/research_contract_v1_example.yaml
  - run_log/validation_status.json
  - docs/audit/gold_fx_trend_diversification_intake_20261015.md
  - docs/audit/tokyo_fix_program2_cross_currency_20261011_v1.md
  - data/processed/_manifest.json
  inspected_git_worktree: dirty_and_untracked_preserved
  files_modified_in_repository: []
```
