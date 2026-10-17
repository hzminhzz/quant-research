# Execution method and skill evidence

All results are EXPLORATORY. The September 2026 holdout remains unread.
The mechanism is temporary USD demand before the 09:55 Tokyo fix. The falsifier
is an absent adjusted Gotobi premium, uncertain net mean, unstable signs,
placebo ambiguity, or incomplete data coverage. The instrument is USDJPY LSE
minute OHLC. The retail broker, executable spread, margin and contract remain
unspecified. The baseline is the same-window ordinary Tokyo bank date.
The next question requires complete historical coverage and executable costs.

The executor read the following complete local skills before quantitative code.
Each path starts at `.agents/skills/` and ends in `/SKILL.md`.

| Skill directory | Reason | Required invariant | Verification |
| --- | --- | --- | --- |
| ml4t-polars-patterns | Snapshot and event transforms | Vectorized sorted grouped transforms; no Python price UDF | Source uses lazy Polars and grouped expressions |
| ml4t-compute-features | Past-only extension gate | Exclude current event from rolling sample | Gate oracle checks preceding20 values |
| ml4t-evaluate-factor | Single-instrument event effects | Appropriate inference; no forced cross-sectional IC | statsmodels event OLS with HAC |
| ml4t-causal-identification | Calendar controls and refutation | No post-treatment controls; distinguish association from cause | Frozen weekday/year controls and matched placebos |
| ml4t-calendar-ops | Holiday rollback and session dates | Instrument calendar; UTC/JST conversion | Independent official holiday calendar audit |
| ml4t-validate-data | OHLC and gaps | Valid finite prices, exact minutes, distinct dates | Snapshot checks and complete541-minute cohort |
| ml4t-point-in-time | Development boundaries | No future holdout or gate values | Partition selector and source manifests |
| ml4t-backtest-overfitting | Many fixed windows | Freeze variants and correct full family | CLI freeze before outcomes;126-test global Holm |
| ml4t-run-backtest | Conditional native execution | Engine required for qualifying candidates | Zero qualified; no simulation performed |
| ml4t-cost-model | Execution costs | Explicit per-leg costs and accounting | Hypothetical0.8/1.0/1.4pip event scenarios; no executable-spread claim |
| ml4t-transaction-costs | Economic screen | Gross effect must cover documented friction | Net means and translated HAC intervals |
| ml4t-lookahead-bias | Dependency of compute-features/point-in-time/causal/overfitting | Past-only thresholds | Shifted rollingSD and untouched holdout |
| ml4t-fetch-data | Dependency of validate-data | Canonical schema and bounded input identities | Annual source snapshots and SHA256 manifests |

The executor imported installed `compute_features`, `labeling`, `analyze_signal`,
`Evaluator`, `Engine`, and `Strategy`. The API identity artifact records actual
signatures and package versions. Calendar event estimation has no matching
feature-catalog or cross-sectional-IC contract. Fixed open-to-open event markouts
use the Polars skill. statsmodels estimates calendar associations. Native
`TradeAnalyzer` and `max_drawdown` calculate event win rate, profit factor and
additive endpoint markout drawdown. These quantities are not simulated fills,
account returns, or mark-to-market drawdown. No custom backtest loop exists.

The original B3 gate uses preceding20 complete08:00-10:30 sessions. A separate
frozen sensitivity uses preceding20 full03:00-12:00 sessions. Both compare
identically gated ordinary dates. Calendar categories retain their nominal
settlement date. Collisions remain one day for A/B and are excluded only from C.
The prior study added month-end to Gotobi. This program keeps month-end separate.
The prior492-trade cohort must not be imposed on this306-event complete cohort.

Three of303 Mondays pass the full541-minute rule. The full cohort has999 of1627
bank dates. Coverage is61.4percent. A weekly FX closure can explain some gaps;
that is an inference. No inferred or forward-filled prices support execution.
The frozen candidate screen rejects full-cohort coverage below80percent.
The estimates apply to complete dates only. No all-bankday causal claim follows.

The first preparation attempt failed on automatic CSV date inference for
semicolon-separated nominal-date collisions. It failed before market-data reads.
The executor preserved `prepare_failed_csv.log`. Explicit string schema overrides
fixed the fault. The successful preparation created immutable annual snapshots.
No outcomes were summarized before YAML initialization and the CLI PASS check.
The immutable declaration freezes126 tests. Cost scenarios are deterministic
translations and remain recorded separately. Pointwise minute bands are descriptive.
No exact onset minute was optimized.
For subset means, HAC lag5 means five observed subset events. For full-cohort
regressions, lag5 means five observed complete bank-date rows. Gaps do not become
synthetic rows. The estimator uses Bartlett weights, finite-sample correction
and Student t intervals. Fixed lag1/lag10 checks report signs without selection.

A skill recommends preregistration in Git. The mission prohibits a commit without
explicit authorization. The executor used the create-once research-session CLI
freeze, source hashes and timestamps. This override does not create unseen data.
Unknown prior trial count prevents reproducible DSR/PBO claims.

The tmux socket was inaccessible in this managed environment. Ordinary tool
sessions ran each job with durable task-owned logs. No duplicate job was started.
No older study, unrelated dirty file, live trade, commit or push was changed.
