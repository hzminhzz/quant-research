# Agent entry point

Read [AGENTS.md](AGENTS.md); it is the canonical agent policy.

For new research, use the shared dual-mode runtime documented in
[operations](docs/architecture/dual_mode_20261015/operations.md).
Invoke only `scripts/quant.py` for new factory work and
`src.workbench.Workbench` for interactive development-only research. Convert
research handoffs via `scripts/quant.py ingest`; see AGENTS.md for required
explicitness. Treat `archive/legacy_v1/` as historical evidence, not entry points. Feature names do not grant or deny
execution: verify native/custom computations through the runtime causal tests.

Read [verification](docs/architecture/dual_mode_20261015/verification.md) before
claiming a capability is qualified. Preserve original dirty work, frozen legacy
records and prior holdout exposure. Never replace missing evidence with a PASS.
No research completion grants broker access, real orders or deployment authority.
