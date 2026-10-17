# Statistical review before new outcomes

Scope: Program 1. These recommendations use the mission and prior report only.
The reviewer did not read price data or the September 2026 holdout.
This document gives recommendations. The frozen main specification must state
which rules it adopts before the executor reads new outcomes.

Skills read in full:

- `.agents/skills/ml4t-causal-identification/SKILL.md`: derive admissible controls.
- `.agents/skills/ml4t-evaluate-factor/SKILL.md`: separate signal and execution evidence.
- `.agents/skills/ml4t-backtest-overfitting/SKILL.md`: freeze selection and count tests.
- `.agents/skills/ml4t-lookahead-bias/SKILL.md`: exclude future gate information.
- `.agents/skills/ml4t-point-in-time/SKILL.md`: preserve availability boundaries.

## Estimands and inference

Use one row per complete Tokyo business date per outcome window. Sort dates.
Use signed open-to-open pips: long `(exit_open-entry_open)/0.01`; short uses
the opposite sign. The sign is fixed by the economic hypothesis. No rule may
change direction after inspection.

For a group mean, fit an intercept-only `statsmodels` OLS model. Use HAC
covariance with Bartlett weights, `maxlags=5`, finite-sample correction, and
`use_t=True`. Report the actual n and residual degrees of freedom. The lag is
five observed events for a subset mean. It is five consecutive business-day
rows for a regression over the full business-day cohort. State this difference.
Use lags 1 and 10 as fixed robustness checks. Do not select the smallest p-value.
Use two-sided tests and 95 percent confidence intervals.

For Gotobi increment, fit `signed_window_pips ~ gotobi + C(weekday) + C(year)`
on Gotobi and ordinary business dates. The Gotobi coefficient is the adjusted
association of interest. Report the unadjusted difference as a separate result.
Calendar controls reduce measured calendar confounding. They do not establish
observed importer flows or a causal effect. No adjustment uses same-day return,
fix extension, volume, or realized volatility. Such variables can be mediators
or post-treatment variables.

For gated B3, fit a treatment coefficient only on dates eligible under the
identical preceding-20-session extension gate. Compare gated Gotobi against
gated ordinary days. The gate must use 08:00 and 09:55 opens and only preceding
complete sessions for its sample standard deviation. A comparison against all
ordinary days mixes calendar and gate effects. Record B3 as conditional and
potentially mediator-selected; do not infer a total calendar effect from it.

## Settlement regression

Use seven mutually exclusive settlement categories: ordinary reference, nominal
5, 10, 15, 20, 25, and 30. For a rolled event, retain its nominal settlement
day category and add `rolled`. Add weekday and year fixed effects, `month_end`,
and `quarter_end`. Quarter end is a subset of month end; check design rank.
Friday is already a weekday dummy. Do not add a duplicate Friday column.
If multiple nominal events map to a business date, preserve a list in the
registry. Mark the event ambiguous and exclude it from nominal-category
coefficient estimation; retain it once in aggregate Gotobi estimation.

Check design rank, residual degrees of freedom, and category overlap before
fitting. Report excluded rows. Do not remove covariates based on p-values.
If a declared contrast is unidentified, report inconclusive. A category requires
at least 30 complete events and representation in at least four calendar years
for a directional interpretation. Smaller samples remain descriptive.

## Multiple testing

Freeze a complete list of inferential test IDs before execution. Use one global
Holm family for all A-D window, horizon, calendar and placebo coefficient tests.
Global correction allows selection across hypotheses without hiding the number
of opportunities. Use `statsmodels.stats.multitest.multipletests(method='holm')`.
Treat failed, underpowered, or unidentified declared tests as p=1 in the family;
retain their disposition in the ledger. Costs 0.8, 1.0 and 1.4 are deterministic
translations, not three independent tests. They still constitute recorded cost
scenarios. Yearly estimates are descriptive robustness evidence, not additional
claims. If formal yearly tests are reported, add them to the frozen family.

Minute event curves use 95 percent pointwise HAC bands. Label them pointwise.
They are descriptive and cannot establish a significant onset minute. Define
pressure onset as the earliest of the seven fixed intervals with positive mean
and positive adjusted Gotobi coefficient, with its Holm-adjusted p below 0.05.
Require the sign to remain positive under both alternative fixed HAC lags.
Report an interval, not a discovered exact minute. If none passes, onset is
unresolved. No minimum p-value minute search is permitted.

The 11:55 placebo must use the same group contrast and duration where available.
The executor must name actual matched windows before reading outcomes.
A useful fixed pre-placebo 11:30-11:54 window
can be compared with 09:30-09:54. A post-placebo 11:56-12:00 window has only
four minutes and cannot serve as a duration-matched 14-74-minute reversal test.
Record unavailable placebo horizons as unavailable; do not extend the session
or shorten the main hypothesis silently. Use nominal 2/7/12/17/22/27 as a fixed
negative-control calendar, with the same rollback algorithm. Dates overlapping
actual Gotobi are excluded from negative controls and counted.

## Candidate screen

These are recommended minimum research criteria. They confer no trading approval.

- At least 100 strategy events and 200 eligible control events.
- At least five represented years with at least 15 strategy events each.
- Positive adjusted Gotobi increment, Holm-adjusted p below 0.05, and positive
  lower 95 percent HAC confidence bound for that increment.
- Positive mean after 1.0 pip cost and positive lower 95 percent HAC bound for
  that mean. Positive point mean under 1.4 pip stress.
- Positive base-cost point mean in at least five of seven available years.
  Pooled 2024-2025 base-cost point mean must be nonnegative.
- Leave-one-year-out adjusted increment and base-cost mean must remain positive
  for every omitted year. No formal claim of significance is made from these
  leave-one-year-out estimates.
- No comparable negative-control calendar effect or placebo effect that makes
  the settlement interpretation ambiguous. A nonsignificant placebo alone is
  not evidence that the main effect differs from placebo; compare effect sizes
  and uncertainty directly.
- Candidate entry and exit times are fixed listed mission windows. At most one
  pre-fix accumulation candidate and one post-fix reversal candidate. If multiple
  windows pass, use the earliest preregistered entry or earliest preregistered
  exit, not the largest mean. An unresolved placebo or confounding concern can
  leave zero candidates.

Zero candidates is a complete result. Do not run native strategy simulations
for failed candidates to search for a different accounting outcome. The entire
2020-August 2026 sample remains EXPLORATORY. Unknown prior trial count prevents
reproducible DSR or PBO assertions. A global Holm correction addresses only this
declared program; it does not erase earlier selection or make historical data
unseen. Keep September 2026 onward unread.

## Verification requirements

Verify distinct business dates and nonduplicated event categories. Independently
recompute one signed markout for each fixed window from source opens. Check HAC
configuration and degrees of freedom. Check regression rank and control timing.
Check that every Holm p-value uses the complete declared family. Verify that
subsetting never reads holdout rows. Check the gate against a hand-inspected
past-only sequence without interpreting future price outcomes.
