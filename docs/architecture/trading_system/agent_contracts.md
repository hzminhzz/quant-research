# Agent interface and action contracts

**Status:** Proposed interfaces, not implemented CLI commands or importable APIs.
Use current `scripts/quant.py`/Workbench only within their inspected capabilities.
The operating interface is a thin adapter over existing owners.

## 1. Six operations, one grammar

| Proposed operation | Purpose | Side effects |
| --- | --- | --- |
| `inspect_case` | Read scoped state, changes, uncertainty and ready actions | Read only; derived cache optional |
| `read_evidence` | Expand one referenced claim to bounded source evidence | Read only, with scope/holdout controls |
| `prepare_action` | Resolve dependencies, permissions, cost class and outputs | Read only; no worker, data purchase or broker request |
| `start_action` | Validate a prepared contract again and start authorized work once | Declared writes only |
| `observe_run` | Read progress, checkpoint, ownership and terminal artifact status | Read only |
| `verify_result` | Run declared independent checks and record an attestation | Task-owned verification evidence only |

An approval is supplied by its authorized principal, not minted by these agent
operations. Implementation may map these operations to CLI subcommands and typed
Python functions. Keep a common result schema; do not build six services.

Every result includes `schema_version`, scoped object identity, state revision,
observation time, freshness, provenance references, side-effect summary, terminal
or running status, reason codes, truncation/pagination and next-action references.
Errors carry the violated contract, expected/observed values, affected scope,
retry class and safe remedy. Redact secrets and private account identifiers.

## 2. The Casefile is the agent's working view

Separate **observed facts**, **inferences**, **hypotheses** and **unknowns**.
Each fact points to an authority and observation. Include:

- Decision question, requested scope, falsifier/acceptance, budget and stop rule.
- Code/branch/dirty identity, data/spec/protocol versions and current source cursors.
- Independent status dimensions: source quality, scientific evidence, execution
  qualification, job state, approval and live state. Show unexecuted stages.
- Material changes, invalidated claims and conflicts since the prior cursor.
- Active jobs and reservations, owners, last progress and reconciliation state.
- The feasible action frontier: dependency-ready actions, blocked alternatives,
  missing evidence, side effects and human decisions that genuinely remain.
- Known assumptions, prior data exposure, uncertainty and scope limitations.

**Progressive disclosure:** first show one recommended action and at most two
useful alternatives, then links to deeper evidence. Target about 1,200 tokens for
a normal first view; this is an ergonomic benchmark, not permission to omit risk.
Always surface critical blocks, stale/unreachable authorities and incomplete
reconciliation even when the response budget is exceeded. Show total counts,
priority order and a continuation cursor for omitted detail.

A fresh rendered page does not make its source fresh. Store `source_observed_at`
and `view_rendered_at` separately. A multi-source view includes individual
watermarks and consistency status; do not invent a global atomic snapshot.
Before a mutation, the owning domain rechecks current preconditions atomically.

## 3. An action is a bounded contract

Illustrative shape only; identifiers below are placeholders, not existing runs:

```yaml
schema_version: target-action-v0
kind: verify_artifact
subject: example-research-attempt
expected_revision: example-state-revision
objective: Reconcile native fills to cash and equity.
inputs:
  - authority_ref: example-native-run
    digest: example-sha256
scope:
  read: [example-development-artifacts]
  write: [example-task-owned-verification-directory]
  network: none
  broker_effects: none
  protected_data: forbidden
budget:
  wall_time_seconds: 120
  cpu_threads: 1
  max_memory_bytes: 1073741824
expected_outputs: [reconciliation.json, verification.json]
completion: All declared accounting invariants checked with stated tolerances.
stop_on: [identity_change, missing_native_events, budget_exhaustion]
authorization_ref: example-existing-research-authorization
idempotency_key: example-verify-native-run-v1
```

Budgets are per-action examples, not universal research thresholds. Real contracts
also bind implementation/dependency identity, data boundaries, market/account
scope where applicable, deadline, owner, checkpoint format, verification plan
and retry policy. Unknown capabilities fail during preparation, before expensive
execution. Validate supported operation kinds and fields, not arbitrary shell
strings generated from source prose.

`prepare_action` must not scan protected outcomes, send orders or start a worker.
Its output is a proposed diff in state, resource estimate/class and reasoned
preconditions. `start_action` rejects stale revisions, altered artifacts,
revoked/expired permissions or missing required evidence. For long approved
research programs, execute the dependency frontier autonomously within the frozen
scope instead of requesting approval after every mechanical step.

## 4. Run state, concurrency and recovery

```text
PREPARED -> CLAIMED -> RUNNING -> OUTPUT_READY -> VERIFIED -> DECISION_RECORDED
                    |              |
                    +-> FAILED     +-> VERIFICATION_FAILED
                    +-> BUDGET_EXHAUSTED
                    +-> VISIBILITY_UNKNOWN
```

This is a target lifecycle, not a replacement for existing historical status
strings. Preserve their original semantics and map them explicitly. Economic
falsification is a valid terminal result; engineering failure is not evidence
against a thesis. `OUTPUT_READY` never means accepted.

A lease binds run, worker and writable scope. Enforce a monotonic fencing token at
the writer so an expired worker cannot continue publishing accepted output. A
process heartbeat proves liveness, not progress; use counters, checkpoint cursor,
last durable output and expected progress intervals. When visibility is unknown,
inspect the existing process and checkpoint rather than launching a duplicate.

Recovery first verifies source/config/code identities, committed artifacts,
checkpoint format, process ownership and side effects. Resume only when the
specific task has a tested recovery contract. Otherwise preserve the failed
attempt and create a linked new attempt under the authorized retry policy.
An expired lease alone never authorizes reclaiming a potentially live order.

Hash-keyed reuse must distinguish complete output, partial output and reviewed
output. Crash tests cover before/after artifact commit, manifest publication,
ledger append and verification. Compare resumed versus clean execution, not
merely file existence. No retry restores a consumed holdout read.

## 5. Safety and idempotency

Permission tiers are explicit: metadata read; scoped evidence read; development
compute; task-owned document/code write; external data acquisition; protected
history; deployment/control changes; approved runtime order flow. Account
purchase and cash transfer are distinct high-impact permissions.

Research and nightly audit credentials cannot reach order-writing functions.
Untrusted source pages are evidence, never instructions. Restrict network domains,
filesystem mounts and credential access outside the model. A source page cannot
expand an allowlist or request a credential.

For live routing, use a transactional outbox and stable intent/client-order IDs.
Promise idempotent business effects where the provider permits them, **not
universal exactly-once network delivery**. A timeout after submission means
`ACK_UNKNOWN`, not rejection. Retain risk reservation and reconcile using stable
IDs, fills and positions before retrying. If provider semantics cannot resolve
uncertainty, block new exposure and escalate; never submit a replacement on a
second account merely because the first acknowledgment was lost.

Approval expiry blocks new exposure but does not erase positions. Keep explicitly
approved protective/risk-reducing actions available under their own policy.
Cancellation requests and liquidation requests remain pending until reconciled.

## 6. Completion and independent verification

A verification record binds subject artifact, source identities, verifier code,
method, assertions, tolerances, results, scope, limitations and observation time.
Separate three forms of evidence: checksum/integrity; behavioral/numerical checks;
independent scientific interpretation. None is a substitute for the others.

A second agent repeating the first report is not numerical independence. Recompute
important invariants from lower-level artifacts or a different trusted method.
For high-impact acceptance, keep verifier credentials and publication authority
separate from the executor. Cooperative local checks are labeled as such.

A final action result contains outcome, changed paths/state, artifact references,
verification, deviations, remaining uncertainty and the next allowed action.
Partial results remain visible. A failed notification, unreachable broker or
unrun stage cannot become green through summary wording.
