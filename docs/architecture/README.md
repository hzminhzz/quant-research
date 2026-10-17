# Architecture entrypoint

**Start here for orientation, not for an implied approval.** The current new-mode
research route is the shared Workbench/factory. The end-to-end operating layer is
a target design over existing authorities. Inspect code and dated evidence before
claiming that a target capability is implemented.

## Choose the question

| Question | Authority or guide |
| --- | --- |
| How should the whole trading system operate for an agent? | [Decision-centered operating architecture](trading_system/README.md) |
| What owns each fact and interface? | [Target system design](trading_system/design.md) and [domain glossary](../../CONTEXT.md) |
| How do current supported research runs work? | [Dual-mode operations](dual_mode_20261015/operations.md), actual `scripts/quant.py` and `src.workbench.Workbench` |
| What has actually been qualified? | [Initial verification](dual_mode_20261015/verification.md), [later Phase 2 evidence](dual_mode_20261015/phase2_cutover_verification.md), exact tested identities |
| Which old strategies have moved? | [Migration map](dual_mode_20261015/migration.md) and [archive inventory](dual_mode_20261015/archive_inventory.md) |
| Which new implementation unit is ready? | [End-to-end rollout](../plans/agent_trading_system_rollout.md) |
| How are agent actions, state and recovery specified? | [Target action contracts](trading_system/agent_contracts.md) |
| How do historical v1 sessions work? | [Research sessions](../research_sessions.md), [v1 contracts](research_contracts.md) and [v1 Casefile](agent_casefile_ux.md) |
| Why choose this structure? | [ADR 0005](../adr/0005-decision-centered-trading-system.md) and existing ADRs |

## Current versus historical interfaces

New supported research uses `scripts/quant.py` and `src.workbench.Workbench`.
Read current help/schema, applicable AGENTS and the exact candidate first. The
factory is presently qualified for the scopes in its evidence reports, not every
legacy event/CFD/stop-entry strategy. `quant.py run` may progress to protected
access after its internal gates; verify scope and authorization before running.

The older `scripts/research.py` and `scripts/research_session.py` support
historical v1 evidence and compatibility. A `resume` inspection is not proof that
an interrupted job can resume safely. Historical milestone documents below keep
their original design/status snapshots; they are not the current feature backlog.

Before acting, identify the exact checkout and dirty state, source/spec/clock,
active worker, current evidence, permission and smallest useful next step.
Keep native ML4T execution, complete known trial/exposure accounting and independent
checks. Research completion does not grant broker or deployment authority.

## Historical design references

[Agent research design](agent_research_system.md),
[original rollout](../plans/agent_research_system_rollout.md), and
[rebuild checkpoint](rebuild_20261015.md) explain earlier decisions. Their dated
implementation statements can be superseded by newer code and verification.
Preserve frozen artifacts rather than rewriting them to match today's narrative.
