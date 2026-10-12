# Agent entrypoint — Quant research control plane

**Read this first.** M1 read-only status and capability commands and the M2
strict feature contract/gateway are implemented. Later rollout milestones are
not implemented. Current repository state and installed APIs remain the
authority.

## The one-minute mental model

```text
Thesis -> Qualified Data -> Proven Features -> Native Execution
       -> Independent Evidence -> Scoped Research Decision
```

A **Research Capsule** is a *view* linking the existing frozen session,
canonical data catalog, feature and execution contracts, run evidence,
and next safe action. It is not a new database.

When resuming, answer **what is known, which sources are authoritative,
what is running, what is blocked, and what small action resolves it**.
Do not start a duplicate job or recreate an observed holdout.

## Which file answers which question?

| Question | Open |
| --- | --- |
| Vocabulary: what does "pass", "trial", "holdout" mean? | [Domain glossary](../../CONTEXT.md) |
| System boundaries and why they exist | [Architecture](agent_research_system.md) |
| Exact feature/data/run evidence fields | [Contracts](research_contracts.md) |
| What should a coding agent build next? | [Rollout plan](../plans/agent_research_system_rollout.md) |
| Why not a new registry or raw custom indicators? | [ADRs](../adr/0001-research-capsule-authority.md) |
| Existing working session CLI and freeze behavior | [Research sessions](../research_sessions.md) |
| Existing agent operating rules | [AGENTS.md](../../AGENTS.md) |

## Current commands that actually exist

```bash
uv run python scripts/research.py doctor
uv run python scripts/research.py doctor --session vwap_pullback_adx_nq_20261012
uv run python scripts/research.py status --session vwap_pullback_adx_nq_20261012
uv run python scripts/research.py discover --feature adx
uv run python scripts/research_session.py report --session <id> --root .
uv run python scripts/research_session.py check --session <id> --root .
```

The second command checks declared input data identities; it does
**not** prove feature math, backtest execution, or approval.
Always inspect HEAD, dirty state, applicable skill, source metadata,
active tmux jobs and artifact identities before further work.

`doctor`, `status`, and `discover` are read-only. A `status` result is a
derived view of the existing frozen v1 session. It does not scan data or
rehash artifacts; use the legacy `report` command for those checks.
`doctor --session` also checks the declared source identity and the last input
bar against the declared session exit. `discover` queries the installed
Engineer registry. No managed run or resume command exists yet.

## Nonnegotiable boundaries

- Use `src.catalog` authority and the **requested** exact product.
  Do not silently substitute a different feed.
- Use the installed Engineer registry for supported indicators.
  Verify input field, lookback and time semantics; unsupported
  features need a reviewed extension.
- Treat an index/CFD or continuous proxy as a **proxy**.
  Do not claim real contract-level futures execution.
- Use native ML4T backtest and independent fill/ledger checks.
- Keep trials and failed attempts. No holdout reset or silent
  repricing of old results.
- A successful mechanical test, profitable simulation, or
  completed record **never grants live-trading approval**.
- Preserve unrelated dirty work. No automatic reset/clean/stash.

**Current implementation authority:** `src/research_session.py`,
`src/catalog.py`, `src/research_control/`, current code, and current artifacts.
M1/M2 and the M3-B runtime feature-proof gate are additive. Existing session
v1 files and historical evidence remain unchanged.
