# Statistical review of executed evidence

Disposition: The no-candidate conclusion follows the frozen program gates.
The reported claims about the main adjusted estimates are correct. Report
limited sample coverage and the difference between gross means and calendar
premiums explicitly. This review did not read any holdout prices.

Reviewed evidence:

- `execution_v1/results.json`, SHA256
  `956326b80e33197f7013067b9b6814072e3cb84bf7d6234de3dc1ca07819a6db`.
- `execution_v1/event_panel.parquet`, SHA256
  `95786d341e4b653b5d3657aeb88ff0d58755c634476a03463f7e697b339c0325`.
- The persisted study code and `execution_v1/trial_ledger.json`.

The additional skill `.agents/skills/ml4t-polars-patterns/SKILL.md` was read
before the panel count audit. The audit used Polars group and filter operations.
It introduced no features, new hypotheses, or new strategy outcome tests.

## Sample accounting

The event panel has 999 rows and 999 unique dates. Its actual minimum date is
2020-01-10. Its actual maximum date is 2026-04-24. The source selection boundary
is August 31, but the analyzed complete-session cohort does not extend to August.
Do not describe complete-window estimates as covering all months through August.

There are 306 Gotobi dates and 693 ordinary dates. These categories form an
exact partition. There are 54 month-end dates: 30 overlap Gotobi and 24 overlap
ordinary dates. There are 108 rolled Gotobi dates. These are overlapping group
summaries, not additional independent observations. Calendar regression excludes
one nominal collision, which reduces its subgroup counts by one where relevant.

Weekday counts are Monday 3, Tuesday 241, Wednesday 244, Thursday 258, Friday 253.
The study therefore has weak support for Monday effects. It cannot establish an
all-bank-day unconditional effect. The reported preparation coverage is 999 of
1,627 expected dates. Structural FX-opening gaps and provider gaps may affect
both group composition and return patterns. The frozen missingness gate rejects
strategy selection.

Strict B3 has 24 Gotobi and 60 ordinary gated observations. Original B3 has 21
Gotobi and 50 ordinary gated observations. Both outcome cohorts require full
03:00-12:00 completeness. The original gate scale uses narrow complete-session
history, but its analyzed outcome count is not the prior narrow-study count.
Both B3 versions fail the minimum candidate sample criteria.

## Main claims verified

No fixed pre-fix interval establishes pressure onset under the frozen corrected
increment rule. No Gotobi increment passes the global 126-test Holm family.
The smallest Holm p-value among increment tests is approximately 0.310.

The 08:30-09:54 Gotobi long gross mean is 2.2059 pips. Its base-cost mean is
1.2059 pips with 95 percent HAC interval [-0.8893, 3.3010]. Its weekday/year
adjusted Gotobi increment is -0.5650 pips with interval [-3.5181, 2.3881].
Its Holm p-value is 1.0. This is not evidence for a Gotobi-specific premium.

The 09:56-10:10 Gotobi short gross mean is 2.0363 pips. Its base-cost mean is
1.0363 pips with interval [-0.0414, 2.1140]. Its adjusted increment is 1.9766
pips with interval [0.5508, 3.4024]. The unadjusted-for-multiplicity regression
p-value is 0.00663, but the global Holm p-value is 0.78288. Report the positive
exploratory point estimate and failed corrected evidence threshold together.

Ordinary post-fix short base-cost means are -0.8974, -0.8505, and -0.0812 pips
for 10:10, 10:30, and 11:00 exits. Gotobi means are positive at all three exits,
but all base-cost confidence intervals include zero. The gated Gotobi short
means are negative at all three horizons for both gate definitions.

The gross 09:56-10:10 Gotobi short mean itself passes Holm with p=0.02961.
The matching long-sign A test reports the opposite sign for the identical
outcome and also passes. This does not contradict the failed increment test.
Use the statement "no Gotobi-specific premium passes Holm". Do not use the
broader statement "no significant effect exists" or "all Holm tests fail".

Both calendar regression designs have full rank: 20 columns and rank 20.
All 20 declared calendar coefficients have Holm p=1.0. Quarter-end has 17
observations and is correctly marked INCONCLUSIVE in both models. Nominal-day
coefficient differences remain exploratory point estimates, not established
settlement-day rankings.

The matched pre-placebo increment difference is -0.9267 pips with interval
[-2.9852, 1.1318]. The matched short post-placebo difference is 0.7393 pips
with interval [-0.2633, 1.7419]. Both have Holm p=1.0. Settlement specificity
remains unresolved. Negative-calendar adjusted contrasts also include zero.

## Metrics and ledger labels

The event summaries provide gross and deterministic 0.8/1.0/1.4 pip cost
translations, win rate, profit factor, and additive endpoint-markout drawdown.
They use the imported ML4T analytical implementations. They do not represent
executed orders, capital-equity backtests, or intratrade marked-to-market risk.
The stored `metrics_source` and drawdown field labels make this distinction.
Retain it in the audit report. A small event drawdown cannot establish actual
margin, stop-loss risk, or broker execution.

The inferential ledger has the complete 126-test family. It contains two
inconclusive quarter-end tests, three cost scenarios, a no-qualified-native-run
record, and an unavailable longer post-placebo record. Thus it has 131 records.
No qualifying candidate exists. Skipping native Engine strategy simulations is
consistent with the mission rule that only qualifying candidates receive them.

Holdout remains untested. Unknown older trial history still prevents a
reproducible DSR or PBO claim. Global Holm here corrects this program's declared
family only. Research completion does not change EXPLORATORY / NOT_APPROVED.
