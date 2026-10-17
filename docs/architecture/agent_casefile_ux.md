# Agent Casefile: read-only cold-start and recovery UX

> **Scope:** Existing v1 read-only Casefile behavior. The new factory has a
> separate derived research Casefile; neither implements the complete proposed
> cross-system view. Its target contract is in
> [agent interfaces](trading_system/agent_contracts.md), with
> [implementation gates](../plans/agent_trading_system_rollout.md).
> Preserve the read-only and evidence-authority semantics below.

The authoritative data still lives in frozen `SessionSpecV1`, v1 terminal
records, and append-only attempt events. The Casefile is a rebuildable derived
view. It does not re-hash full source files, scan Parquet, run models or certify
trading readiness.

Use from the repository root:

```bash
uv run python scripts/research.py casefile --session <session_id>
uv run python scripts/research.py explain --reason-code JOB_VISIBILITY_UNKNOWN
uv run python scripts/research.py explain --gate-file run_log/<path>/gate.json
uv run python scripts/research.py resume --session <session_id> --attempt <attempt_uuid>
```

- **Casefile** includes economic hypothesis/falsifier, frozen source identity,
  evaluation windows, costs, trial and attempt records, source evidence,
  holdout exposure, job visibility, and the next safe action.
- **Explain** returns stable code, expected, observed, original evidence
  location and specific remedy. It may read a size-bounded JSON gate file only
  inside the workspace; it does not treat asserted worker success as proof.
- **Resume** is read-only and idempotent. It identifies a live named tmux job;
  it never launches a second job, kills a session, or silently records a terminal
  result. Unknown visibility, missing jobs, and uncertain leases remain
  blocked. A terminal `COMPLETED`/worker-done claim has status `REVIEW`,
  pending independent artifact verification.

The Casefile never changes `NOT_APPROVED` or `EXPLORATORY` authority.
A cached computation or append-only terminal event does not approve a
strategy or justify unsealing protected holdouts.

Tests: `tests/test_casefile.py` and `tests/test_casefile_cli.py` use
temporary frozen sessions, mock tmux visibility, fake worker-done,
frozen-record immutability and repeated cold reads. No proprietary market
data or external provider API is needed. Read-only output can be rebuilt
after deleting any derived display cache.
