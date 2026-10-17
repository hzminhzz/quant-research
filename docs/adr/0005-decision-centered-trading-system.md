# ADR 0005: Decision-centered operating interface over domain authorities

**Status:** Selected target design for the requested documentation revision,
2026-10-15. Implementation is subject to the linked rollout gates. This is not
capital, protected-data or deployment approval.

## Context

The system has native research components, frozen records, a new factory and
Workbench, provider adapters and partial operational monitoring. Its current
interfaces still require an agent to reconstruct state, evidence scope and safe
next actions across files and tools. Earlier architecture headlines can disagree
with newer code. A compact PASS can hide unrun work or absent authorization.

The user requested an end-to-end system that is intuitive for agents, economical
to operate, and improves from previous work. Creating another backtest engine or
one conversational agent per subsystem would duplicate authority and increase
coordination rather than improve decisions.

## Alternatives considered

1. **Independent research/portfolio/rules/audit agents with their own state.**
   Simple to start, but duplicates truth, status and recovery. Cross-account risk
   and evidence consistency remain caller obligations. Rejected as the backbone.
2. **One universal workflow engine, registry and mandatory validation pipeline.**
   Centralizes orchestration but conflates scientific protocols and ownership;
   creates a large migration and another mutable authority. Rejected.
3. **One small operating interface over deep domain modules and existing evidence
   owners.** A derived Casefile resolves the next decision; typed bounded actions
   delegate to current implementations; deterministic runtime owns risk. Selected.

## Decision

Use the scoped decision as the unit of work. Casefiles are rebuildable projections
that bind evidence, versions, uncertainty, permissions, running work and the next
feasible action. Retain one authority per fact, not one database for every fact.
Preserve v1 and new-mode historical meaning; unify their views without rewriting
old records or manufacturing global trial completeness.

Introduce a small action grammar for inspection, preparation, execution,
observation and verification. Enforce preconditions, side effects, ownership,
budgets and revocable permission outside the model. Identity hashes, stage receipts
and cooperative single-use claims establish integrity properties, not independent
authorization. Protected evaluation and live release retain separate authority.

Make scientific protocol an explicit seam. Shared data/feature/native-execution
components support different event, cross-sectional and path-dependent evidence
requirements. Do not force event strategies through neutral cross-sectional gates
or weaken a frozen gate retrospectively. Unsupported semantics need qualification.

Keep the live path deterministic. A single transactional owner reserves account
and shared risk, dispatches stable order identities, and reconciles uncertain
outcomes. Provider adapters remain in `trading-connector`; the router is a consumer.
Audits are read-only; approved safety controls can act without an LLM. Dashboards,
including any visualization-only terminal, remain derived consumers.

Treat learning as evidence -> scoped lesson -> regression -> measured reuse.
Do not accumulate global prompt instructions or hide negative results. Dependency
changes invalidate affected current claims, not immutable historical artifacts.

## Consequences

The first implementation is read-only orientation and evidence, followed by bounded
recovery, operational audit and scientific/portfolio seams. This earns usefulness
before a new router or larger firm universe. Use existing Python and analytical
storage; introduce transactional storage only where atomic risk/outbox state
requires it. No mandatory service fleet, graph database or agent framework.

A smaller interface transfers complexity into modules that must actually own it.
Therefore acceptance includes adversarial concurrency, permission, recovery,
accounting and cold-start tests, not just a short CLI or attractive dashboard.
The current factory's cross-sectional gates and cooperative protected-read flow
remain observed implementation facts until changed and qualified.

## Links

- [Operating entrypoint](../architecture/trading_system/README.md)
- [System design](../architecture/trading_system/design.md)
- [Agent contracts](../architecture/trading_system/agent_contracts.md)
- [Rollout and acceptance](../plans/agent_trading_system_rollout.md)
- [Dated evidence](../architecture/trading_system/current_state_20261015.md)

ADR 0001's one-authority principle and ADR 0004's shared runtime/causal-check
approach are retained. This ADR extends their operating scope; it does not undo
frozen contracts, historical exposure, native execution or existing approvals.
