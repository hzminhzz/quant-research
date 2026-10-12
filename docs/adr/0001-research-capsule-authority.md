# ADR 0001 — One authority per fact; Research Capsule as a derived view

**Status:** Accepted for M1/M2; later attempt and evidence layers remain open.
**Date:** 2026-10-12.

## Context

The repository already has an append-only v1 research-session registry and an
external `ml4t-data` catalog. Agents repeatedly reconstruct context from
YAML, Python scripts, run logs, memory and chat, sometimes arriving at
different data or result identities. Another mutable registry would increase
disagreement. Yet the existing registry proves identity, not generation or
research validity.

## Decision

Treat a **Research Capsule** as a typed *view over linked authorities*:
frozen thesis and trial declarations from the current session registry;
dataset authority/qualification from the producer catalog; capability
observations from the installed libraries; attempt/verification records from
append-only evidence; and conclusions derived from scoped checks.
The Casefile is a regenerable read model, never a second authoritative store.

Keep the existing v1 session CLI and its immutable files. Attach future typed
contracts via the existing frozen `config` reference. Introduce any v2
record format with explicit migration, never silent rewriting or promoting
legacy evidence.

## Alternatives rejected

- **Replace everything with a new SQL research database:** Powerful queries
  and transactional updates, but premature schema migration, more operational
  work and a second authority during transition.
- **Make agent memory or chat the central state:** Low setup cost but
  incomplete trial accounting, stale results and no reproducible identities.
- **One giant immutable YAML file:** Simple to inspect, but poor attempt
  lifecycle handling and difficult partial recovery.

## Consequences

- Add small derived indexes/CLI views only as needed.
- Record distinct identities for source, contract, code, environment,
  attempt and verified evidence. A digest is not a proof.
- Preserve unknown/failed attempts, already-observed windows, and blocked
  decisions. Historical `NOT_APPROVED` remains authoritative for its scope.
- For heavy artifacts, retain references and hashes rather than copying data.
- Migration tests must show identical v1 frozen files and trial records before
  and after the gateway is introduced.

Related: [architecture](../architecture/agent_research_system.md),
[contracts](../architecture/research_contracts.md),
[rollout](../plans/agent_research_system_rollout.md).
