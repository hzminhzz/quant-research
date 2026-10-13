# ADR 0003 — Fail-closed run permits and separate research, holdout, live authority

**Status:** M4-A preflight contract implemented. Managed execution and attempts remain unimplemented.
**Date:** 2026-10-12.

## Context

The v1 CLI can hash a successfully produced file without proving the
implementation, order semantics, trial accounting, or data window. Agents can
run Python scripts directly, and a local CI workflow is not proof of
GitHub branch protection. Real-world examples include mismatched CFD/NQ
source aliases, missing 15:55 exit bars, invalid limit-fill slippage,
non-atomic live-order assumptions and incomplete July–September data.

## Decision

The managed runner requires a **RunPermit** binding immutable session,
data view, feature proof, strategy/execution plan, library version,
trial identity, evaluation window, compute budget and allowed effects.
Before starting, inspect running jobs and persisted evidence. Verify native
fills and a separate numerical/accounting oracle before declaring an
audited result. Failure records are append-only; valid retries create new
attempts.

Evaluation exposure is monotonic across session names. The managed runner
refuses unauthorized protected-holdout access. Production authorization is
an independent, explicit decision that cannot follow mechanically from
a research PASS, profitable backtest or completed trial.

## Alternatives rejected

- **CI alone:** A local VPS script can execute without opening a PR; CI
  cannot police raw Python running with unrestricted file access.
- **Implicitly downgrade to a nearby dataset or later time:** Hides a
  material change of economic and execution assumptions.
- **Boolean "validated strategy" status:** Conflates source, math,
  execution fidelity, inference and live readiness.
- **Assume a wrapper protects holdouts even with raw access:** False
  security. Strong isolation requires OS permissions or separate storage.

## Consequences

- Managed status must distinguish data/source, features, simulation,
  statistical inference, holdout and deployment.
- Print exact reason and one safe next action on a gate failure.
- Inspect tmux/run leases and identities before resuming or retrying.
- A cached computation saves resources but cannot erase a statistical
  trial or reset holdout exposure.
- External costs, dated futures mappings, quote data and live broker
  OCO remain BLOCKED when not independently evidenced.
- An OS-enforced holdout/access boundary requires separate design and
  authorization; until then, disclose that arbitrary Python bypasses
  the managed runner.

## M4-A implementation boundary

`src/research_control/run_permit.py` defines strict v1 `RunIntentV1`,
`RunPermitV1`, compute budget, cost and multiplier evidence, and an independent
audit recipe. `preflight_run` returns a structured `GateReport` with a stable
reason code, expected value, observed value, source location, and one safe next
action. It rechecks frozen v1 identities, the declared preregistered trial,
the development window, the exact source contract, costs, multiplier evidence,
the exit bar, and the compute budget.

The preflight calls the M3-B `verify_feature_proof` and
`require_verified_feature_proof` functions on the runtime computation and its
input data. It does not accept serialized proof JSON or a caller assertion of
verification. It issues an identity-bound research permit with
`live_order_authority: false` and only `READ_ONLY` or `EVIDENCE_APPEND` effects.
The permit is not an executor, lease, attempt record, protected-data sandbox,
or permission to place orders. The synthetic acceptance fixture uses only
locally generated bars and does not access market data or run a backtest.

Related: [architecture](../architecture/agent_research_system.md),
[contracts](../architecture/research_contracts.md),
[rollout](../plans/agent_research_system_rollout.md).
