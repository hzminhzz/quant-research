# Agent entrypoint

[`AGENTS.md`](AGENTS.md) is canonical research and execution policy. Read it,
[`docs/research_operations.md`](docs/research_operations.md), and
[`docs/architecture/market_scope_policy.md`](docs/architecture/market_scope_policy.md)
before research changes. Frozen sessions and legacy evidence keep their original
identities. No research completion grants broker or live-order authority.

Local checks (use the project's installed environment):

```bash
uv run python -m pytest
uv run marimo check notebooks/quantified_strategies_engulfing.py
git diff --check
```

In this isolated rebuild worktree, use the original installed interpreter with
`PYTHONPATH` set to this worktree, as documented in
[`docs/architecture/rebuild_20261015/verification.md`](docs/architecture/rebuild_20261015/verification.md).
