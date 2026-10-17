# Agent-operated trading system: dependency-aware rollout

**Status:** Documentation/design plan, 2026-10-15. No implementation tickets,
commits, deployments, account changes or protected-data reads are authorized by
this file. This plan extends the current research runtime; it does not restart
M1-M8 or mark earlier work unimplemented.

Entry: [Operating architecture](../architecture/trading_system/README.md).
Current evidence: [Dated inspection](../architecture/trading_system/current_state_20261015.md).
Architecture decision: [ADR 0005](../adr/0005-decision-centered-trading-system.md).

## Objective and done condition

A cold-start agent can identify the correct decision, authoritative evidence,
current permissions, live jobs, uncertainty and next bounded action without
reconstructing the repository. Approved actions survive ordinary failure without
duplicate effects. Research and operational evidence connect through stable
identity. Learning creates verified reuse rather than instruction sprawl.

End-to-end completion requires one real, explicitly approved deployment path
whose research, portfolio, rules, intent, route, fills, account marks, audit and
human decisions reconcile. Until then, report each qualified slice separately.
No profitable strategy or live approval is promised by completion of engineering.

## Work units and dependencies

These `ATS-*` IDs are local plan identifiers, not GitHub issue numbers, research
phases, factory stages or existing commands.

```text
ATS-0 authority/capability baseline
   -> ATS-1 read-only Casefile -> ATS-2 bounded action/recovery/approval
                             -> ATS-3 event evidence and operational audit
ATS-0 -> ATS-4 scientific protocol and portfolio evidence
ATS-1 -> ATS-5 rulebook capture and pure rule replay
ATS-2 + ATS-3 + ATS-4 + ATS-5 -> ATS-6 shadow account router
ATS-6 + provider qualification + explicit authorization -> ATS-7 paper/live gate
ATS-1 -> ATS-8 lesson/regression and operating benchmark (continues across slices)
```

Independent audit and portfolio work may proceed in parallel with separate write
ownership. Current research need not stop while the new read-only views are built.
Do not stall a supported cross-sectional study to finish every new protocol.
Do not release any dependent order path before its prerequisites pass.

### ATS-0 — Bind present reality

**Status:** Proposed implementation prerequisite; this documentation supplies an
initial inspected snapshot, not an automated capability service.

Owner: research lead with bounded read-only verifier. Reinspect checkout/main/
worktrees, active workers, native versions, provider capabilities and current
instructions. Preserve concurrent materialization work. Build an explicit map of
current versus historical commands, status owners and verified test scopes.

Acceptance: a reviewer can locate every current claim's source and tested identity;
no stale README headline overrides newer code/evidence; protected data and secrets
are not read. Record which advertised tools actually work. Read-only inspection
must not trigger import-time orders, data downloads or model fitting.

### ATS-1 — One decision-oriented read interface

Deepen the existing Casefile projection; do not replace the trial ledger or vault.
Implement the target `inspect_case` and `read_evidence` grammar as thin adapters.
Include status dimensions, actual source cursors, freshness, invalidations, jobs,
permissions and a bounded next-action frontier. Add a legacy/new-mode mapping
without rewriting their records.

Acceptance: pass cold-start, rejected/unrun-stage, stale-source, fake-worker-done,
missing-artifact and conflicting-document fixtures. Rebuild projections entirely
from authorities. Deleting a display cache loses no history. Every omitted list
has counts/cursor; critical unknowns remain visible. Measure current and new
first-correct-action effort before claiming improved ergonomics.

### ATS-2 — Bounded action and recovery contract

Implement prepare/start/observe/verify over existing execution tools. Separate
side-effect-free preparation from admission. Bind versions, budgets, write scopes,
worker ownership, fencing, checkpoints, outputs and independent verification.
Preserve each failed attempt. Add scoped external authorization for protected
history and future deployment actions; cooperative stage receipts alone do not
supply it. Do not require manual approvals for routine steps inside an approved
bounded research program.

Acceptance: concurrent requests do not duplicate an admitted job; stale revision
and revoked authority are denied; unknown visibility is not restarted blindly;
crash-point recovery matches a clean run and rejects source/code drift; budget
exhaustion preserves evidence. A consumed protected claim stays consumed.

Authorization tests must deny self-issued/forged approvals, untrusted issuers,
altered scope, another window/spec/selection decision, expired or revoked grants,
and replay after consumption. Passing stage receipts alone must never authorize
a protected read. Prove the positive path with a trusted issuer whose authority
the research worker cannot create or modify; state the actual trust boundary.
Use synthetic protected fixtures, not real protected outcomes.

Fencing tests must reclaim a lease, advance its token, then deliver a late write
and completion message from the old worker. Neither may become authoritative;
only the new owner can publish accepted output. Preserve rejected late evidence
and attribution without overwriting the accepted result.

### ATS-3 — Evidence bridge and first operational audit

Normalize existing strategy intents, routes/skips, orders, fills, account marks,
fees/carry and cash events with stable source/environment/strategy identity.
Keep raw events and a deterministic reconciled view. Expose this read-only to the
audit evaluator. Complete native metrics and human notification delivery only
against an explicitly selected, authorized runtime; do not start a strategy just
to turn a Prometheus target green.

Acceptance: native output and an authorized demo/paper or archived broker sample
reconcile under documented account/lot attribution; gaps, duplicates, partials
and restarts remain visible. Audit distinguishes strategy, routing, execution
and accounting effects. Missing baseline evidence yields insufficient reference,
not fabricated decay. A real notification receipt is observed. Audit credentials
cannot call order endpoints. Pure research progress is not gated on credentials.

### ATS-4 — Scientific protocol seam and portfolio evidence

**Implementation/native-parity acceptance (2026-10-17): PASS in the isolated
governed-core integration.** The existing cross-sectional route is preserved;
the frozen M8 N8 event protocol replays natively and reconciles independently.
Daily fixed-budget sleeve/cash comparisons retain known trial history and
explicit incomplete-selection and cost status. **Overall scientific
qualification remains `PARTIALLY_QUALIFIED`**, not profitable, broker-executable,
new OOS, intraday-barrier qualified, or trade-authorized. See
[the original audit](../audit/ats4_qualification_20261016.md) and
[the integration release record](../audit/ats4_release_20261017.md).
Governed-core acceptance is not a claim that the divergent GitHub `main`
implementation has been reconciled or deployed.

First type the current cross-sectional protocol and qualify one selected event or
path-dependent protocol only when a real strategy requires it. Reuse existing
features, vault, native engine and accounting checks. Add a sleeve evidence
contract and simple risk-budget/co-loss comparisons; keep gross/net costs and
capital/risk units explicit. Intraday account-limit work requires qualified marks.

Acceptance: cross-sectional behavior remains unchanged; an event strategy is not
forced through IC, beta neutrality or short-stop gates. Historical runner parity
must cover exact rules, clocks, orders and cash before retirement. Missing marks
block barrier claims while allowing appropriately limited daily analysis. Paired
joint resampling preserves dependence. Frozen simple baseline, candidate count,
cost stress and observed-history disclosure accompany each comparison.

### ATS-5 — Rulebook and program lifecycle

Capture and review only selected programs' authoritative rules. Implement pure
account-rule transitions shared by replay and live assessment. Separate published
source, effective time, account-specific applicability and release approval.
Version fees, resets, drawdown definitions, payout states and restrictions.

Acceptance: golden event fixtures cover DST reset, floating equity, trailing/static
floors, intra-period breach then recovery, phase changes, withdrawal/payout effects,
fees, incomplete cohorts and grandfathered terms. Unknown rules block only the
affected program. Cash ROI excludes counterfactual firm-absorbed losses. Semantic
diffs rerun affected simulations only. No account purchase or live rule activation.

### ATS-6 — Shadow router with transaction and failure proof

Consume approved-for-shadow intents and account snapshots. Apply eligibility,
atomic account/global risk reservation, a frozen account-ranking policy, stable
IDs, outbox and reconciliation. Single-account multi-leg intents stay together;
cross-venue composite strategies require a separately qualified protocol.
Shadow mode has no order-capable credentials and never calls mutating endpoints.

Acceptance: two individually feasible intents cannot overspend shared cushion;
restart cannot free unconfirmed exposure; duplicate event delivery and lost
acknowledgment cannot create a second routed trade. Partial fills transfer reserved
risk correctly. Rule/approval changes between prepare and dispatch are handled.
Every skipped trade has a reason; compare router versus simple admissible baselines
on identical event paths and risk/fee budgets. Tests do not presume an optimizer
or more occupied accounts is better.

### ATS-7 — Provider-qualified paper and explicitly approved live release

Bind an exact strategy, portfolio/risk policy, rulebook, account/environment,
provider version, evidence and approval in a release manifest. Qualify venue
behavior independently of native research. Test recovery, stop behavior, manual
control and notification under demo/paper first. Freeze the minimum observation
and coverage gates before collecting that evidence; use applicable repository
policy rather than inventing a shorter gate after seeing results.

Acceptance: observed signals/fills/account state reconcile; reconnect, unknown
orders, halt, risk reduction and rollback drills pass; credentials and account
binding are unambiguous; capital and loss budget are explicitly approved. A tiny
live canary is conditional on that approval, not automatic. Increase capital or
buy replacement evaluations only within an existing authorized envelope or with
new approval. Keep current live positions owned during rollback.

### ATS-8 — Continuous learning and operating benchmark

Begin after ATS-1 and apply to each slice. Turn actual recurring errors into scoped
lessons and reproducible tests. Maintain version-aware retrieval and dependency
invalidation. Benchmark the fixtures in
[learning and verification](../architecture/trading_system/learning_and_verification.md).

Acceptance: all critical safety/scientific invariants pass; raw benchmark traces
and negative runs are retained; efficiency changes improve measured effort or
resource use without reducing claim correctness. No automatic global instruction
rewrite, hidden trial deletion or reward for reporting success. Retire obsolete
advice through explicit supersession, not erasure of its historical evidence.

## Execution and integration contract

Inspect repo/GitHub state and AGENTS before a work unit. Use the healthy advertised
executor, existing session and task-owned files. The research lead determines
architecture and acceptance; bounded subagents may inspect, implement and verify.
Use persistent execution for long deterministic checks. Recompute the ready
frontier after a unit finishes instead of requiring manual issue-by-issue prompts.

Each slice publishes exact changed files, code/lock identity, tests executed,
artifact references, independent verification, capability scope and next action.
No commit/push without authorization; no issue closure based only on worker prose.
A docs-only phase is verified as docs-only, not reported as runtime qualification.

## Migration and rollback

Add read interfaces first, shadow new policies second, and switch one consumer
only after behavior/evidence parity. Existing vaults, frozen sessions, trial
history, provider journals and historical verification reports remain intact.
Rollback changes the adapter/release pointer, never deletes fills, account state,
consumed holdout records or failed attempts. A known-good code rollback does not
make an old approval valid for changed account terms.

Do not create a new repository, database cluster, event bus or services platform
unless a measured requirement cannot be satisfied within these seams. Repository
ownership and the minimal storage policy are in the
[system design](../architecture/trading_system/design.md).
