# ADR 0002 — Engineer-first feature boundary with approved extensions

**Status:** Accepted and implemented for the M2 feature slice.
**Date:** 2026-10-12.

## Context

Agent instructions already mandate ML4T but strategy scripts still calculate
ADX/VWAP/rolling indicators in different ways. This introduces lookahead,
calculation drift, source-semantic errors and misleading claims of using the
native library. The installed Engineer registry contains native ADX and
other features, but no named cash-open anchored VWAP. The installed
Engineer version and online docs may differ.

## Decision

Introduce one typed **FeatureGateway** for new/migrated strategy inputs.
Resolve native features via the *installed* `ml4t-engineer` catalog and
`compute_features` with verified input/parameter/time semantics.
Allow reusable **approved extensions** for unsupported exact semantics,
with explicit ID/version, an independent numerical oracle, warmup, group and
availability tests. Strategy state belongs to `ml4t-backtest.Strategy`,
not the indicator catalog.

Require a FeatureProof and an explicit provenance manifest before managed
backtesting. Enforce this in several small layers: Pydantic for declarations,
Ruff for restricted imports, a scoped AST policy for forbidden indicator
paths, tests for numerical/temporal behavior, and a runtime permit.
Do not assume adding metadata to the registry automatically registers a
callable in the installed Engineer API.

## Alternatives rejected

- **Prompt/AGENTS.md only:** Already demonstrably insufficient.
- **Ban all Polars/custom features:** Would prohibit session calendars,
  anchored VWAP, source preparation and independent test oracles.
- **Rewrite Engineer or monkey-patch all strategies:** Hard to maintain,
  version-fragile, hides API drift and confuses ownership.
- **Full-repo AST enforcement immediately:** Unrelated historical code would
  fail before safe parity migration; start with the managed namespace.

## Consequences

- Every feature exposes source fields, units, lookback, availability,
  group/session reset, code identity and numerical evidence.
- A native name with different default inputs is **not** an exact match.
- Extensions are shared, reviewed and versioned, not pasted into strategies.
- Changes to feature semantics create new recorded trials and, when
  required, a new frozen session.
- Cannot claim mathematical correctness from Ruff/Pydantic alone;
  the runtime proof and independent tests remain mandatory.
- The first vertical slice is ADX(14) native plus an approved
  cash-open VWAP extension on qualified source data.

Related: [architecture](../architecture/agent_research_system.md),
[contracts](../architecture/research_contracts.md),
[rollout](../plans/agent_research_system_rollout.md).
