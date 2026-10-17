# Operating loops and deterministic deployment

**Status:** Target integration contracts. Schedules below are planning defaults,
not installed jobs. Each loop terminates with evidence; a scheduler may invoke
it again. No loop silently changes the approved live strategy.

## 1. One feedback system, different clocks

```text
Research result -> portfolio evidence -> reviewed deployment release
       ^                                    |
       |                                    v
Research question <- attributed audit <- intents/routes/fills/account marks
                           ^                 ^
                           |                 |
                    regime baseline    effective rulebook
                                             ^
                                        rules watcher
```

Use event triggers for material state changes and scheduled checks for freshness.
Debounce duplicate events by identity. A deterministic scheduler invokes narrow
jobs; an LLM handles genuinely ambiguous synthesis or experiment choice, not
routine arithmetic, polling or order admission.

| Loop | Inputs and trigger | Output and stop condition | Authority |
| --- | --- | --- | --- |
| Research | Frozen question or reviewed audit question; explicit trial/compute budget | Verified reject/inconclusive/validate decision; stop on falsifier or exhausted scope | Development-only unless separately authorized |
| Portfolio | Qualified sleeve change, material dependence/cost drift or scheduled review | Frozen baseline comparison and portfolio recommendation | Analysis; no allocation change |
| Operational audit | Reconciled events after session close; immediate integrity triggers | Attributed report, gaps and scoped flags | Read-only accounts and evidence |
| Rules watcher | Scheduled official-source snapshot and dated agreement updates | Semantic diff, applicability decision, affected simulation queue | Source capture and analysis only |
| Runtime safety | Every risk-changing intent and material account/data event | Admit, reduce or block under approved policy; durable reason | Deterministic, separately authorized |

The first four are finite work units. Runtime safety continues without a chat
session. Stale or missing inputs block the affected opening-risk path, not all
unrelated research. Report dependencies explicitly to avoid a global deadlock.

## 2. Research: optimize the next experiment, not the backtest count

Retrieve current candidate, previous attempts, exposed windows, capability
snapshot and relevant lessons. Select the smallest experiment able to change the
decision. Freeze hypothesis, exact source, causal clock, baseline, costs, trial
budget, protocol and falsifier before observing outcomes.

Use development-only Workbench for exploration and the matching qualified factory
protocol for formal evaluation. Protocol selection is not selection after seeing
which gate passes. Unsupported event/stop semantics become an adapter qualification
task; they do not justify a handwritten substitute simulator.

Parallelize independent inspections and trials with separate mutable ownership.
Keep one integration owner. Let long deterministic jobs use available persistent
execution, with identity, checkpoint and resource budgets. An ordinary code/runtime
failure is diagnosed and retried within scope; a changed economic hypothesis is
registered as a new trial. Preserve negative results and consumed data exposure.

Protected evaluation needs both verified development evidence and a scoped
human authorization binding the actual window and selection decision. The current
factory's cooperative single-use claim is an integrity mechanism; the additional
authorization boundary is a planned rollout gate, not a capability already proven.

## 3. Portfolio: distinguish strategy ownership from account execution

Start with explicit strategy versions, capital/risk units, native net returns,
positions, fees/carry and coverage. Align observation clocks without silently
turning missing prices into zero PnL. Retain different market-session calendars
and the difference between a date label and an equity valuation instant.

Daily return overlays answer coarse allocation questions. Account-limit questions
need synchronized intraday mark-to-market paths, open orders, pending reservations,
costs and applicable rule clocks. A daily series or closed-trade list cannot prove
that no intraday barrier was crossed. If OHLC cannot resolve event order, use
conservative declared path scenarios or report insufficient evidence; do not
invent a precise account-survival probability.

Compare a frozen equal-risk/simple allocation baseline with a small declared set
of candidates. Evaluate incremental contribution, joint loss episodes, stressed
exposures, turnover and uncertainty. Use walk-forward estimation and dependence-
preserving joint resampling; do not independently shuffle each sleeve and destroy
its shared bad days. Normalize comparisons to the same risk/fee budget where
appropriate and show unscaled outcomes too.

Drawdown-level correlation is one diagnostic, not the sole authority. Complement
it with synchronized negative-return dependence, conditional co-loss probabilities,
tail overlap, market/strategy-family exposure and drawdown duration. Define window,
peak and inactive-period treatment. A 0.5 correlation cutoff and 3-4 strategies
per account are candidate heuristics, not universal production rules.

For independent losing-month indicators, 0.4^3 is the probability that all three
lose, not the probability that their weighted portfolio loses. Loss sizes and
weights still matter. More trades increase observations, not necessarily independent
information. Adding a sleeve must improve a predeclared portfolio objective rather
than merely fill empty trading days.

A portfolio return cache can feed many firm-rule scenarios when the native events
and sizes remain identical. Changed sizing, skipped trades, netting, fills or
account state require native replay through the execution seam. Do not rescale a
closed-trade list as though path-dependent execution were invariant.

## 4. Rules watcher and account lifecycle

Capture authoritative source pages/agreements with raw content hash, retrieval
time and source identity. Store separately: source publication time if available,
effective time, account applicability, extraction confidence and review decision.
Unknown dates remain unknown. Social posts may trigger review but do not silently
override an account agreement. Retrieved instructions cannot execute tools.

The typed rulebook needs program/environment, phases, tradable products, reset
calendar/timezone/DST, balance/equity formula, realized/unrealized inclusion,
static/trailing floor, high-water update timing, consistency conditions, minimum
activity, fees, payout eligibility and cash withdrawal effects. Include copying,
automation, hedging and account-limit permissions when relevant. Unsupported or
ambiguous terms make that program ineligible pending review.

A semantic change identifies affected accounts and future cohorts. Existing
accounts may retain prior terms. Preserve old rule versions and decisions. Do not
apply new marketing-page rules retroactively to historical tests unless the
scenario is explicitly counterfactual. Review applicability, rerun affected
simulations, then request a new release approval if operating policy changes.

Model evaluation -> funded -> payout-eligible -> payout pending/received -> breach
or expiry as explicit program-dependent transitions. Fresh-account cohorts start
with fresh state and cannot inherit profitable history. Represent incomplete
cohorts and payout delays; do not count only successful accounts. Withdrawal can
change cushion and floor behavior. Budget fees, failed attempts and waiting time.

Keep three financial quantities distinct: trading account PnL; verified owner
cashflow (received payouts minus paid fees/expenses); modeled counterfactual
personal-capital losses. "Losses the firm absorbed" are not cash receipts and
must not be added to ROI. Pending payout is not received cash. State the ROI
denominator and time horizon; show net cash, timing and uncertainty alongside it.

Start with the programs actually used. Frequency is configured by materiality
and publication cadence; a six-hour sweep is an optional policy, not a research
fact. Detect content changes cheaply before invoking model extraction or simulation.

## 5. Deterministic router: admission before account preference

The default routable unit is an indivisible **Strategy Intent**, not each order
leg. Carry identity/version, signal time and expiry, instrument/product, desired
exposure, execution policy, risk envelope and any required leg relationships.
Single-account strategies select at most one account for the whole intent. Genuine
cross-venue hedges are a separate composite protocol with explicit multi-account
risk and failure policy; they must not be split by the ordinary prop router.

Perform eligibility first: active approval, exact account/environment, applicable
terms, instrument/strategy permission, current reconciled state, margin, pending
risk, aggregate stress and data freshness. Then rank feasible accounts using a
small frozen policy. Normalize cushion by stressed incremental risk, consider
concentration and payout/lifecycle constraints, and use a deterministic tie-break.
"Healthiest" is never synonymous with highest balance. One open position may be
a preference; test it against the same risk-budget baseline before making it a rule.

The transaction owner reserves both account-level and shared portfolio risk
atomically, binds a route decision to current versions, and persists an outbox
entry before dispatch. Two individually admissible orders may not spend the same
remaining cushion. In a multi-account composite, reserve the entire approved
risk domain in one coordinator transaction or reject unsupported atomicity.

Pending/partial fills consume risk. Convert reservations to realized exposure
without a release-and-reacquire gap. On unknown acknowledgment, hold reservation
and reconcile; do not route to another account or expire the reservation by wall
clock alone. On partial multi-leg failure, use only the preapproved hedge/unwind
policy. Account netting and strategy attribution use a documented deterministic
lot-allocation rule; research sleeves are not independent broker positions.

Recheck rules, approval, account revision and freshness at dispatch. Venue events
update the journal and equity path. Runtime loss/cushion controls act immediately;
nightly audits are not the kill switch. Use reduced-risk or halted states with
explicit recovery. No risk model can guarantee zero breach under unbounded gaps.
Account replacement, evaluation purchase and increased capital require applicable
explicit approval, not a router's automatic attempt to recover lost profit.

## 6. Audit: attribute before diagnosing decay

Bind the audit to the exact deployed version and its frozen, comparable baseline.
Use the full intent stream, including skipped/rejected trades, to avoid selection
bias induced by routing. Compare the following layers:

1. Frozen strategy on the observed live market stream: signal/feed/feature parity.
2. Eligible intents versus selected routes: allocation and intentional skips.
3. Orders versus fills: latency, slippage, rejections, partial fills and netting.
4. Fills versus account marks/cash: fees, carry, cash movements and reconciliation.
5. Reconciled net behavior versus an ex-ante conditional baseline: possible decay.

These counterfactuals are diagnostic model outputs, not actual profit. Record
model assumptions and confidence. Do not call an execution-cost problem a failed
signal or a regime change a proven implementation bug.

Report rolling trade windows and fixed calendar windows with effective sample
limitations. Freeze simple causal regime definitions and historical calibration.
Use conditional predictive/resampling intervals, sample adequacy and multiple-
alert controls rather than declaring decay from one bad 30-trade window. Overlapping
30/60/90 windows are correlated checks. An unfamiliar regime can mean insufficient
reference evidence, not either success or failure.

Output one short decision report plus structured evidence. Classify integrity,
execution and statistical flags separately. Only a reviewed statistical flag
creates a bounded research question. It cannot mutate a live strategy. Safety
violations feed the deterministic risk controller independently of the agent.

## 7. Operational completion

A loop is ready only when duplicate triggers, missed schedules, restart, source
outage, expired approval, unknown acknowledgment, cost/time budget exhaustion and
notification failure have explicit tested outcomes. Reconcile before resuming.
Record schedule and input cursors so closing a laptop has no effect on correctness.
Run alerts end-to-end to an observed human receipt; local ingestion is insufficient.
