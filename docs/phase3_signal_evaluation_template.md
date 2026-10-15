# Phase 3 signal/economic evidence — report template

Copy this template to a **new** immutable report under `run_log/diagnostics/<session_id>/phase3_signal_evaluation.md`. Declare the corresponding `diagnostic` trial in the session spec **before** `init`. Link the finished report with `scripts/research_session.py record`. Do not store the result under the `run_log/research_sessions/<session_id>/` control directory. Do not overwrite an existing evaluation. Treat results found after a completed backtest as **retrospective**, not preregistered.

## Identity and frozen plan

| Field | Actual value or evidence path |
| --- | --- |
| Session ID and trial ID | `<session_id>` / `phase3-signal-screen` |
| Frozen spec SHA and criteria | `<hash plus exact falsifier or frozen config reference>` |
| Method selected *before outcomes* | `<event study / cross-sectional factor / OOS prediction / N/A native-only>` |
| Declared input identity | `<data source/product/version, feature proof, SHA>` |
| Development / validation interval | `<ISO date bounds; note protected final-test start>` |
| Instrument and settlement semantics | `<venue, product, currency, multiplier, fees/financing>` |
| Event/signal clock and availability | `<bar start/end, time zone, latest observable data>` |
| First executable observation | `<next open or eligible venue time; do not use signal close for entry>` |
| Frozen outcome horizon / label | `<hours/bars/days; label must end before protected holdout>` |
| Frozen baseline and economic null | `<unconditional/matched event or comparable simple rule>` |
| Expected direction and effect | `<what would constitute evidence for the thesis>` |
| Frozen pass/fail/stop criteria | `<numerical or qualitative limits, uncertainty policy, minimum evidence>` |
| Declared trials / variants | `<all horizons, baselines and alternatives; no hindsight selection>` |

## Diagnostic evidence (populate only when applicable)

- **Data and feature validity:** `<missingness, timestamp validity, numerical proof, point-in-time join, no cross-symbol contamination>`.
- **Signal count:** `<raw events and approximately independent events; deduplication/spacing rule>`.
- **Conditional forward outcomes:** `<signed returns / abnormal return, hit rate or other thesis-matched outcome at each *prespecified* horizon; source label clock>`.
- **Baseline difference:** `<candidate versus null, units and practical magnitude>`.
- **Uncertainty and dependence:** `<HAC/block-bootstrap/clustered interval or reason it cannot be estimated; event overlap, effective sample size>`.
- **Temporal stability:** `<per-year, predefined chronological folds/regimes; note any inconsistent sign>`.
- **Cost feasibility:** `<cost assumptions and effective date; signal magnitude versus commissions + spread + slippage + financing/funding where relevant; do not assert net PnL without execution>`.
- **Limitations:** `<data/signal proxy, capital capacity, unverified execution assumptions, selection/number of trials>`.

**Do not run generic rank IC on one instrument and label it a cross-sectional test.** For a path-dependent payoff whose entry and exit cannot be assessed by a fixed-horizon price label, identify that incompatibility *before* looking at returns; use a bounded, audited **native** event-driven experiment instead.

## Phase 3 decision (select exactly one)

| Decision | Required evidence |
| --- | --- |
| **PASS** | Meets the preregistered, signal-level criteria. Phase 4 may run, but strategy PnL remains unknown. |
| **FAIL** | Adequate predeclared evidence falsifies the economic signal. Stop ordinary Phase 4 and report MVP **REJECT**; do not retune the same trial. |
| **INCONCLUSIVE** | State what is missing, why, and whether a *predeclared* bounded native test would resolve the specific uncertainty. Otherwise stop. Do not promote to PASS. |
| **NOT_APPLICABLE** | Record the *pre-result* reason signal-level metrics would misrepresent the mechanism, plus the bounded native trial and tests that are necessary instead. No automatic pass. |

**Selected decision:** `<PASS / FAIL / INCONCLUSIVE / NOT_APPLICABLE>`

**One-paragraph justification:** `<cite actual frozen criteria and observed admissible evidence; do not cite a protected holdout>`

**Next permitted action:** `<STOP / BOUNDED_NATIVE_PHASE4 / OTHER_NEW_TRIAL_WITH_NEW_SPEC>`

**Independent reviewer / check:** `<independent numerical, temporal and evidence verification; do not infer correctness from an artifact SHA alone>`

**Retrospective flag:** `<NO — preregistered before any relevant performance was seen / YES — historical diagnostic only>`

## Recording and scope

Use the frozen trial ID. After writing the result once, register it:

```bash
uv run python scripts/research_session.py record \
  --session <session_id> --trial phase3-signal-screen \
  --status completed \
  --artifact run_log/diagnostics/<session_id>/phase3_signal_evaluation.md \
  --root .
```

Registry `completed` means the trial record was written, **not** that Phase 3 was a PASS. Record execution failures as `failed` with their own existing artifact and do not claim a decision based on missing evidence. This template adds **no** `SessionSpecV1` fields, new CLI or automatic runtime `RunPermit` check. The research lead must verify the artifact before proceeding.
