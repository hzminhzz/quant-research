# Agent operating architecture: decision, evidence, action

**Status:** Target design for the end-to-end system, 2026-10-15. Documentation
changes are not implementation, holdout permission, deployment approval or a
claim that the proposed tools exist. [Observed state](current_state_20261015.md)
separates inspected behavior from targets.

## The first minute

The system exists to make **correct, evidence-backed trading and research
decisions at low total cost**, not to maximize backtests, agents or activity.

An agent starts with one scoped **Casefile**. It answers:

1. What decision are we making, and what would change it?
2. What is known, from which authority, at which version and time?
3. What changed or became unreliable since the last verified observation?
4. What is running, and who owns each mutable resource?
5. What is the smallest useful action permitted now?
6. What evidence and stop condition will finish that action?

The Casefile is a regenerable view, not a new source of truth. Today, research
Casefiles cover part of this contract. Cross-system Casefiles and action tools
below are **planned**, not commands to invoke now.

```text
Intent + constraints
        |
        v
Casefile: question -> evidence -> uncertainty -> permitted action
        |                                      |
        |                               bounded execution
        |                                      |
        +<-- independent verification <-- immutable result
        |
        +--> scoped decision --> approved release --> observed execution
        |
        +--> reproducible lesson --> regression/capability improvement
```

## Read only the branch required by the task

| Task | Read | Stop reading when |
| --- | --- | --- |
| Operate current research | [Dual-mode operations](../dual_mode_20261015/operations.md), then the candidate and latest evidence | Exact supported entrypoint, data scope and next action are known |
| Design a module or decide ownership | [System design](design.md) | Its authority, caller contract and verification seam are explicit |
| Add agent tools, status or recovery | [Agent interface contracts](agent_contracts.md) | Preconditions, effects, failure semantics and completion are testable |
| Connect audit, portfolio, rules or routing | [Operating loops](operating_loops.md) | Inputs, deterministic behavior and escalation are explicit |
| Retain a lesson or measure ergonomics | [Learning and verification](learning_and_verification.md) | A reusable regression or measured decision improvement is specified |
| Select implementation work | [Dependency-aware rollout](../../plans/agent_trading_system_rollout.md) | One ready slice and its acceptance tests are identified |
| Resolve current versus historical claims | [Dated inspection](current_state_20261015.md), then actual code/artifacts | Each claim has scope, identity and freshness |

The [decision record](../../adr/0005-decision-centered-trading-system.md) explains
why this is a thin operating interface over existing modules, not a new agent
platform. Canonical vocabulary remains in [CONTEXT.md](../../../CONTEXT.md).

## Five rules that connect the whole system

**One authority per fact.** Research owns thesis and trial history. Native engines
and reconciled venue events own fills. The runtime owns reservations. A scoped
approval authority owns permissions. Dashboards own none of these facts.

**One interface, different scientific protocols.** Cross-sectional prediction,
single-instrument events, and path-dependent strategies need different evidence.
Reuse data, identity, causal checks and native execution; select the appropriate
protocol rather than forcing every strategy through IC or neutrality gates.

**Agents choose work; deterministic code controls risk.** Research/audit agents
cannot mint approvals, rewrite live limits or submit an arbitrary order. Approved
runtime policies can act without waiting for a chat session.

**Every action closes an evidence loop.** An attempt has a budget, owner, expected
artifacts, verification and terminal outcome. A process exit or worker's message
is not acceptance. Negative valid research is completion.

**Learning improves the next decision.** Incidents become scoped, tested lessons.
Research failures remain in trial accounting. New summaries never turn exposed
history into holdout or unsupported code into a capability.

## Current entrypoints versus target interface

Current new-mode research uses `scripts/quant.py` and `src.workbench.Workbench`.
Their exact installed schema and help are authoritative; legacy v1 tools serve
historical work. Existing `quant.py run` can progress to protected access when
its internal gates pass. It is not a development-only convenience command.
Check the authorization and data scope before invoking it.

The proposed Casefile/action interface is specified in
[agent_contracts.md](agent_contracts.md). It must first be implemented and tested
before it appears in an executable runbook. Build it incrementally over existing
owners. Do not introduce a second simulator, universal mutable registry,
mandatory graph database or always-running LLM supervisor.
