# Gemini thesis to native ML4T: autonomous MVP execution

**Purpose:** Reusable execution prompt for a Gemini-generated research thesis.
**Owner:** ChatGPT Web, acting as principal engineer and final research lead.
**Scope:** MVP Research only. This prompt does not authorize protected holdout
access, strategy promotion, production changes, or live orders.

## Copy-ready prompt

```text
# Mission: Execute Gemini Research With Native ML4T

## Input

Mode: MVP Research
Research proposal: Gemini's attached or pasted research brief and thesis YAML.
Repository: /home/quant/dev/quant/quant-research
Execution: @VPS-cloudflare / DevSpace

## Objective

Take the supplied Gemini research thesis and autonomously implement,
backtest, validate, and report the strategy using native ML4T.

Execute through a terminal MVP research decision. Do not stop after
planning, writing features, or obtaining the first backtest result.

Gemini has already performed thesis discovery and economic research.
Treat the submitted economic hypothesis and intended strategy rules as
the research input. Do not repeat the literature review or redesign
the strategy unless a material contradiction blocks valid execution.

## 1. ChatGPT Web owns the work

ChatGPT Web is the principal engineer, researcher, orchestrator, and
final verifier. Inspect, design, write, test, debug, execute, and evaluate
directly through DevSpace whenever practical.

Do not automatically delegate primary implementation to Codex.
Use Codex selectively for expensive backtests, long test suites, or
genuinely independent bounded tasks. Use tmux for persistent jobs.
Review all delegated evidence directly; workers do not approve results.

## 2. Inspect actual repository and ML4T environment

Inspect branch, HEAD, Git status, remotes, active jobs, and existing
research artifacts. Preserve unrelated staged, dirty, and concurrent work.
Never reset, clean, overwrite, or commit unrelated work.

Read AGENTS.md, nested instructions, docs/research_operations.md,
docs/research_sessions.md, applicable market policies, and matching
official ML4T skills. Inspect actual installed ml4t-engineer,
ml4t-backtest, and ml4t-data versions and APIs, plus reusable code.

Avoid new infrastructure when the repository or libraries already
provide the capability.

## 3. Implement the supplied thesis faithfully

Do not commission another thesis-discovery cycle. Keep Gemini's
mechanism, strategy rules, and default parameters where coherent.

Resolve only implementation-critical uncertainties using the actual
source, market data, and installed APIs: feature definitions, instrument
mapping, bar/session availability, timezone, causal timestamps, order
types, entry/exit semantics, sizing, trading costs, or funding.

Record corrections and explicit adaptations before observing outcomes.
Do not invent missing details, add filters, or tune thresholds to improve
historical PnL. Escalate a material economic hypothesis change.

## 4. Qualify data and freeze the smallest valid experiment

Inspect the canonical local ml4t-data catalog first. Verify instrument
and venue identity, source/version, coverage, bar timestamps, timezones,
gaps, raw field semantics, and point-in-time availability.

Do not treat CFD, futures, spot, options, and perpetuals as identical.
Do not forward-fill missing executable prices or fabricate liquidity,
funding, swaps, multipliers, fees, or fills.

Register and freeze a bounded MVP session and all planned trials BEFORE
looking at new backtest outcomes. Freeze the original thesis, precise
rules, baseline, development window, warmup, cost assumptions, primary
falsifier, minimum sample, and stopping rules. Preserve all prior
observed history as observed, not unseen.

Never access protected final/portfolio evaluation holdouts.

## 5. Engineer features using native ML4T

Use ml4t.engineer.compute_features and the verified installed feature
catalog for supported indicators. Use a documented, tested deterministic
extension only when a required calculation is not natively supported.

Do not replace supported native features with custom NumPy or Polars
calculators.

Verify numerical parity, parameter and smoothing definitions,
symbol isolation, lookback/warmup, completed-bar availability,
multi-timeframe synchronization, session/DST behavior, and lack of
future-data leakage. Write useful adversarial and regression tests.

## 6. Execute the native event-driven backtest

Implement the submitted entry, exit, risk, and position state machine
using ml4t.backtest.Engine and its native broker.

No homemade vectorized PnL simulator. Enforce causal signal/fill
ordering. Distinguish actual market/limit/stop orders from close-
confirmed exits. Account for instrument-specific commissions,
slippage, spread, funding, financing, rollover, and margin as relevant;
disclose any unavailable component and its effect on qualification.

Run the preregistered baseline, strategy, and any predetermined
replications or controls. Use bounded resources and tmux for long jobs.

Diagnose ordinary errors, fix them, and rerun. Preserve original
failed attempts and immutable successful evidence. Do not create an
unregistered parameter sweep.

## 7. Validate results and independently audit

Inspect native trades, fills, rejected orders, order timestamps,
positions, cash, costs, and marked equity. Reconcile trade PnL to
native broker equity and verify data/config/code/trial identities.

Compute daily-equity metrics with correct annualization, not
intraday-bar Sharpe. Report where supported:
trade count, wins/losses, expectancy, profit factor, net PnL,
daily Sharpe and Sortino, Calmar and max drawdown, yearly/subperiod
performance, turnover, costs, cost sensitivity, sample uncertainty,
baseline comparisons, and preregistered replication behavior.

Treat missing or undefined metrics as unknown, not zero or success.
Keep process correctness, economic evidence, and broker execution
readiness separate.

## 8. Apply the MVP research gate

Use the frozen hypothesis and falsifier, not a post-hoc success bar.

REJECT: Valid results fail the economics or technical qualification;
stop without rescuing the strategy through parameter optimization.

INCONCLUSIVE: Insufficient data, fidelity, events, costs, or statistical
evidence; identify the exact blocker.

VALIDATE: Sufficient MVP evidence justifies a separate chronological
validation program. Do not automatically access a protected holdout or
promote the strategy.

A positive historical Sharpe alone does not justify VALIDATE.

## 9. Deliverables and execution autonomy

Save task-owned artifacts: frozen session/config, qualified data
provenance, native feature and strategy code, tests, native broker
trade/fill/equity files, baseline comparisons, full trial/failure
records, independent audit, and terminal decision.

Commit and push only verified task-owned changes when authorized.
Preserve secrets and unrelated changes. No production updates or
live orders.

ChatGPT Web remains the main worker. Do not transfer task ownership
to Codex or stop after asking another agent to work.

Continue autonomously to REJECT, INCONCLUSIVE, VALIDATE, or a genuine
documented blocker. Escalate only material hypothesis changes,
destructive operations, protected holdout access, live capital risk,
missing essential credentials, or major unresolved alternatives.

Input: Use the Gemini thesis, research brief, and YAML attached to
this conversation. Begin actual implementation immediately.
```

## Workflow boundaries

This prompt specializes the [research operations guide](../research_operations.md)
for cases where Gemini has already supplied thesis research. It **does not**
override `AGENTS.md`, the installed ML4T skill rules, the repository's frozen
session and RunPermit contracts, or protected holdout controls.

Retain the existing seven ResearchPhases. A valid MVP outcome is not a
Promotion decision and does not grant live order authority.
