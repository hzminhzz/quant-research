# Thesis-driven research sessions

Use this guide before starting crypto or index research, changing a strategy,
or reviewing historical results. A session organizes a falsifiable thesis and
its evidence; it does not confer permission to trade. All new sessions are
`EXPLORATORY`, including sessions that satisfy their research criteria.

At the start of each working session, read the thesis specification and the
latest session report before choosing the next trial. For an existing session,
use its frozen specification and regenerate the report from recorded evidence;
for a new session, read the proposed thesis and explicitly note that no report
exists yet. Identify the current falsifier, unresolved evidence, and next
planned trial rather than restarting selection from remembered results.

## Writing standard: ASD-STE100

Use ASD-STE100 as the writing standard for agent replies, research reports,
documentation, comments, and handoffs. Apply it to new or revised prose.
Use the following rules:

- Write short, complete sentences. Use one topic per sentence.
- Use active voice. State who does the action.
- Give direct instructions. Put one action in each instruction step.
- Use the same term for the same concept. Define technical terms on first use.
- Use simple words. Remove idioms, metaphors, and unnecessary words.
- State conditions before instructions. Keep each condition explicit.
- Separate observations, assumptions, conclusions, and unresolved questions.
- Preserve exact code, commands, paths, API names, symbols, units, and error text.
  Do not change a technical identifier to simplify its wording.

Check clarity and technical accuracy before you deliver written output.
Claim formal ASD-STE100 compliance only after you check the applicable rules
and approved vocabulary. Otherwise, describe the output as ASD-STE100-style
writing. These rules do not require a rewrite of unchanged historical artifacts.

## 1. Specify the thesis before running trials

Write a session specification that answers these questions:

- **Economic hypothesis:** What return or risk effect is expected, over which
  horizon, and relative to which simple baseline?
- **Mechanism:** Who pays for the effect, why should it persist, and under what
  market conditions should it disappear? An indicator pattern alone is not an
  economic explanation.
- **Falsifier:** Which observable result would reject the thesis? Define the
  metrics, minimum evidence, acceptance criteria, and stopping rule before
  inspecting trial results.
- **Tradable instruments:** Identify the venue or broker, exact symbol or
  contract, instrument type, quote and settlement currencies, contract
  multiplier, tick/lot constraints, trading calendar, and shorting constraints.
  BTC spot and a BTC perpetual are different instruments. An index value or
  `NAS100` vendor alias is not an executable futures, ETF, or CFD contract;
  specify the actual product and the mapping from research prices to fills.
- **Trial plan:** Declare the baseline, candidate features, parameters,
  universes, labels, execution rules, and selection criteria. Record subsequent
  changes as additional trials rather than silently changing the plan.

Choose labels and diagnostics to test that thesis. Fixed-horizon returns,
path-dependent barriers, event outcomes, or direct strategy returns may each
be appropriate. Triple-barrier labeling is an option, not a universal mandate.
Cross-sectional rank IC and quantile diagnostics apply to comparable asset
panels; single-instrument time-series or event strategies need diagnostics
matched to their forecast and decision horizon.

## 2. Fix data, evaluation, and costs

Record data sources, versions, availability timestamps, bar open/close
semantics, time zones, session calendars, gaps, and instrument history.
Features and universe membership must be available at the decision time;
fills must occur at an actually tradable time after the required information
is known. Use point-in-time joins and training-only preprocessing. Address
revisions, delistings, listing dates, and survivor-only datasets explicitly.

Use chronological development and walk-forward evaluation. Purge overlapping
label or holding intervals and apply an embargo appropriate to the information
horizon where needed. Random splits or combinatorial diagnostics do not replace
chronological out-of-sample evaluation. Keep a final test period separate and
freeze the data boundary, specification, model, parameters, costs, metrics, and
decision rule before opening it.

Never tune, select, or repeatedly test against that frozen final period.
Report its result even when adverse or inconclusive. A change motivated by
final-test results is a new exploratory trial, requiring genuinely untouched
future data for a new final test; renaming the session does not make an observed
period unseen.

Use costs for the exact instrument and market:

- **Crypto spot:** Venue/tier maker or taker fees, spread, slippage and market
  impact, plus borrow availability and charges when shorting.
- **Crypto perpetuals or dated futures:** Those execution costs plus signed
  funding at actual funding timestamps, margin/liquidation constraints,
  settlement and expiry, and rolls where applicable.
- **Index futures:** Per-contract exchange, clearing and broker fees, tick
  value, spread, slippage, contract expiry, roll execution and basis. Separate
  continuous-series adjustments from tradable contract PnL.
- **Index ETFs or CFDs:** Product-specific commissions, spread and slippage,
  borrow or overnight financing, distributions, and broker trading conditions
  as applicable.

Document the cost source, effective date, units, charging frequency, and stress
assumptions. Generic 2 bps commission plus 1 bps slippage is an exploratory
placeholder only, not evidence of executable economics. Generic IC, DSR, PBO,
or profitability thresholds cannot approve deployment. Report net performance
against the baseline, uncertainty, stability, capacity, and multiple-testing
limitations; derive research criteria from the thesis and market.

## 3. Track every trial and its evidence

Count every evaluated variant, including manual notebook experiments, changes
to features, parameters, universes, labels, costs, and execution rules. Record
planned trials before execution and retain completed, failed, abandoned, and
inconclusive attempts in the research accounting. Preserve failed-run artifacts
and failure reasons; a missing result is not evidence that no trial occurred.
Disclose unregistered or missing attempts instead of claiming a complete ledger.
The CLI below accepts terminal records for `completed` and `failed`; retain
other dispositions in the session evidence without inventing extra CLI statuses.

Retain the specification, config/data/source fingerprints, trial identity,
timestamps, metrics, artifacts, and deviations needed to reproduce each result.
Use the full known trial count for selection-bias analysis, including DSR and
Sharpe haircuts when appropriate, and state when missing history makes an
adjustment unreproducible. A hash identifies recorded evidence; it does not
validate the data, statistical method, completeness, or trading readiness.

### Schema and example declarations

The v1 schema in `src/research_session.py` requires `session_id`, `thesis`,
`mechanism`, `falsifier`, `market`, `instruments`, `data`, `evaluation`,
`baseline`, `costs`, and `trials`. Optional `config` and `evidence` link existing
files. Quote YAML timestamps to keep values JSON-compatible. Declare trial
kinds as `preregistered`, `diagnostic`, or `historical_review`; only historical
review declarations include an `artifact` path.

Use [`crypto_example.yaml`](../config/research_sessions/crypto_example.yaml) or
[`indices_example.yaml`](../config/research_sessions/indices_example.yaml) as a
declaration example. Their `UNMAPPED_*` symbols, missing identity fields, missing
data files, illustrative future dates, and zero cost placeholders are deliberate.
They demonstrate initialization followed by a blocked audit, not executable
strategy claims. The legacy-review trial links an existing `NOT_APPROVED` ORB
decision; it supplies neither crypto evidence nor new index-strategy validation.

For real research, fill exact product identity and point-in-time data, replace
dates and costs, and specify the evaluation/selection rules before `init`.
Crypto perpetuals require a venue. They require funding data unless
`costs.funding_included` is explicitly `false`. Indices require identity,
session, and a valid IANA timezone. These mechanical checks do not verify that
a supplied mapping or fee estimate is economically correct. Price Parquet
inputs require `timestamp`, `open`, `high`, `low`, and `close`; funding requires
`timestamp` and `funding_rate`. Timestamps must be timezone-aware, sorted and
unique, with valid finite numeric values. The audit is bounded to 100 MB and
1,000,000 rows per file, so prepare justified bounded inputs rather than
treating an oversized audit failure as a strategy result.

### Concrete CLI workflow

Run from the repository root. `--root .` means the project/workspace root,
not a separate log directory. All specification, data, config, evidence, and
artifact paths are relative to that root and must stay inside it without
symlinks or parent traversal. Session records live under
`run_log/research_sessions/<session_id>/`.

Run the following commands individually. The unfilled examples intentionally
produce `BLOCKED` from `check` and a recorded `failed` diagnostic from
`diagnose`, both with exit code 2; `init` and `report` succeed. `report` emits
JSON to stdout and does not save a separate report file.

```bash
uv run python scripts/research_session.py init --spec config/research_sessions/crypto_example.yaml --root .
uv run python scripts/research_session.py check --session crypto-example --root .
uv run python scripts/research_session.py diagnose --session crypto-example --trial development-summary --root .
uv run python scripts/research_session.py report --session crypto-example --root .

uv run python scripts/research_session.py init --spec config/research_sessions/indices_example.yaml --root .
uv run python scripts/research_session.py check --session indices-example --root .
uv run python scripts/research_session.py diagnose --session indices-example --trial development-summary --root .
uv run python scripts/research_session.py report --session indices-example --root .
```

`init` freezes the specification and observed config/data/source/evidence
identities as an `EXPLORATORY` session with `approval_status: NOT_APPROVED`.
`check` audits identities and declared data requirements; it does not run a
strategy or prove point-in-time correctness. `diagnose` is the built-in
descriptive experiment: it summarizes gaps, price returns and funding observations
within `[development_start, development_end)`, bounded to 100,000 rows per
dataset. It creates and hashes its diagnostic artifact and terminal trial
record automatically, including audit-blocked failures. It fits no model,
runs no backtest, and does not score the holdout. Do not call `record` again
for that diagnostic trial.

To link the existing historical decision after reviewing it, use an example's
declared `legacy-review` trial:

```bash
uv run python scripts/research_session.py record --session indices-example --trial legacy-review --status completed --artifact run_log/validation_status.json --root .
uv run python scripts/research_session.py report --session indices-example --root .
```

`completed` means the review was recorded, not that the strategy passed.
Execute models and backtests separately through existing scripts or Marimo
notebooks. For example, only if a separately executed `thesis-baseline` trial
actually failed and produced `run_log/crypto_baseline/failure.json`, record it
with:

```bash
uv run python scripts/research_session.py record --session crypto-example --trial thesis-baseline --status failed --artifact run_log/crypto_baseline/failure.json --root .
uv run python scripts/research_session.py report --session crypto-example --root .
```

For a completed external trial, use `--status completed` and its actual result
artifact instead. `record` hashes an existing artifact but does not verify its
generation. `report` includes pending and failed trials and current identity
checks; neither a successful check nor any report approves deployment.

Frozen sessions and terminal records are create-once. After filling an example
that was already initialized, assign a new `session_id` and initialize a new
session before executing its trials. Adding previously missing data or editing
the original YAML cannot repair a frozen declaration; never overwrite or
reclassify the old evidence.

## 4. Keep historical review separate

Historical review audits already-observed results and reconstructs provenance.
Preregistered trials timestamp the hypothesis, specification, and selection
rules before their outcomes are observed. Retrospectively importing artifacts
does not preregister them or restore an unseen test period. Label the evidence
as historical review, disclose what was already known, and distinguish any new
prospective trials in the session report.

Preserve existing notebooks, whitepapers, dashboards, tables, and run logs as
historical artifacts. Write corrected research into separate versioned
artifacts rather than overwriting old evidence. Existing Marimo conventions
and reusable pipeline patterns remain in force.

The legacy ORB strategy remains `NOT_APPROVED`, as recorded in
[`run_log/validation_status.json`](../run_log/validation_status.json) and
[`validation-remediation-status.md`](audit/validation-remediation-status.md).
Its incomplete trial ledger and unreproducible DSR are not repaired by starting
a new session. New `EXPLORATORY` sessions cannot replace that decision or turn
historical claims into live-readiness evidence.

## Completion criteria

A research session report is complete when it states the thesis and falsifier,
exact instruments, data and evaluation boundaries, cost assumptions, every
known trial and missing record, hashed evidence, deviations, and the frozen
final-test outcome or why that test was not performed. State whether the
thesis was rejected, supported within the observed scope, or remains
inconclusive. Keep research completion separate from deployment approval.

At the end of each working session, record the next decisive question: which
uncertainty matters most, what observation would resolve it, and which declared
trial or required input will supply that observation? Include that question
and any blocker in the handoff alongside the latest report so the next session
continues the thesis rather than opening an untracked search.
