# Script review before new outcomes

Reviewed `scripts/run_tokyo_alpha_map_program1_v1.py` after persistence.
This review read code and calendar column definitions only. It did not read
event outcome files or holdout prices. Findings were sent to the implementation
agent and the main agent before the intended freeze.

## Findings requiring action

1. Frozen negative-control prose specifies rollback. The calendar registry
   selects actual business-day dates with day of month 2/7/12/17/22/27.
   Align the declaration before freeze. Both designs are possible controls.
   They are different estimands.
2. Small calendar categories receive p=1 and an inconclusive interpretation,
   but retain `status=ESTIMATED`. The ledger maps this to completed. Set the
   inferential status to INCONCLUSIVE while retaining descriptive estimates.
3. `run()` loads the mutable YAML and only asserts that a frozen file exists.
   Load `frozen['spec']` for inference. Verify its input-spec identity and
   assert that runtime window constants equal the frozen window declaration.
   Verify the registry/calendar identity before joining event outcomes.
4. The pressure-onset list includes post-fix A windows. Separate supported
   interval diagnostics from the earliest qualifying pre-fix interval. The
   pre-fix onset interpretation uses only the first four A intervals.
5. The native stage raises if any candidate passes. If a candidate passes,
   the mission requires implementation and verification of the native stage.
   A raised exception is a blocker, not mission completion. If no candidate
   passes, this contingent branch is not required for the observed disposition.
6. Reported preparation coverage is 999 of 1,627 days. The main agent identified
   possible structural absence of Monday 03:00 JST prices before the FX open.
   If all Mondays are absent, the hardcoded C weekday dummies 1/2/3/4 plus
   intercept are collinear. Use the first observed weekday as the reference,
   as the general increment model already does. State weekday/year coverage
   and interval-eligible counts before freeze. Complete-case results cannot
   establish an effect for all Tokyo bank dates.

Follow-up code review verified corrections to findings 1 through 4 before the
intended freeze. The executor now computes rolled negative-control dates, marks
small C subsets INCONCLUSIVE, loads frozen specification after equality checks,
checks the calendar hash and runtime windows, and limits onset to four pre-fix
intervals. Confirm that the prepared registry uses the revised negative calendar.
Run the session CLI identity check immediately before analysis.

## Verified design properties

- Source partition selection parses dates before Parquet reads. It excludes
  September 2026 and later partitions. The UTC row cutoff is August 31 15:00,
  which maps to September 1 00:00 JST.
- Both extension gates sort session dates. They calculate rolling sample
  standard deviation with 20 observations and `shift(1)`. The current event
  does not enter its own scale. Original and strict cohorts are distinguished.
- Gated increment regressions use identically gated ordinary controls.
- All complete-day outcome windows use observed opens. No price forward fill
  appears in the study code.
- The inferential family has 126 planned IDs: 90 window/group/increment tests,
  12 gated tests, 20 calendar coefficients, two negative-calendar tests, and
  two matched-placebo tests. Exact ID-set equality precedes global Holm.
- The small calendar model uses weekday Friday once. It checks design rank.
  It excludes nominal collisions only from the nominal-category regression.
- Group means and regressions use statsmodels OLS HAC with the declared
  Bartlett kernel, correction, five lags, and t-based intervals.
- Fixed alternative HAC lags 1 and 10 do not replace the primary p-value.
- Calendar regressions use calendar variables and year/weekday controls.
  They do not adjust for realized return, volume, or same-day volatility.
- Curve bands are pointwise and descriptive. The script does not optimize
  entry or exit from minute-level curves.
- Candidate screening evaluates frozen windows and rejects uncertain
  increments, net means, unstable yearly signs, and unresolved specificity.
  It does not select the largest historical mean.

## Limits to retain in the report

Full-window completeness changes the cohort relative to the prior narrow study.
The original gate uses prior narrow complete sessions, but its reported outcome
sample still requires full-window completeness. The report must disclose this.

The 24-minute and four-minute matched-placebo contrasts are specificity screens.
They do not measure duration-matched placebos for every candidate horizon.
Rejecting a candidate with this conservative screen is permitted by the freeze.
Do not claim that it identifies absence of a longer-window effect.

Calendar associations do not identify dealer demand. Complete-case exclusions
may depend on provider outages. Observed source OHLC does not establish
executable spread, slippage, or broker contract terms. Program Holm correction
does not repair unknown historical trial count or create unseen historical data.
