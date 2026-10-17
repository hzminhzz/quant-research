# ATS-6 transactional shadow router

## Scope and entry points

ATS-6 is a deterministic, single-host shadow admission and execution-evidence ledger.
It accepts explicitly authorized synthetic strategy intents, evaluates ATS-5 account
rules, reserves account and shared risk, and publishes only to a local durable shadow
sink. `src/shadow_router.py` has no broker transport, URL, exchange callback, or
credential argument. `scripts/ats6_shadow_worker.py` runs the fixed admission and
publication path in a network-isolated, credential-free Linux namespace.

The qualification and exact evidence identities are recorded in
[`../../audit/ats6_qualification_20261017.md`](../../audit/ats6_qualification_20261017.md).
The prerequisite merge is recorded in
[`../../audit/ats6_base_20261017.md`](../../audit/ats6_base_20261017.md).
Qualification applies to controlled synthetic shadow events and the tested Linux
filesystem/runtime. It does not establish real-account authority, broker finality,
market profitability, a distributed database, or ATS-7 deployment permission.

The public Python API is `ShadowRouter.create`, `claim`, `update_account`,
`update_portfolio`, `update_policy`, `update_authority`, `prepare`, `admit`,
`publish`, `confirm_publication`, `observe`, `snapshot`, `recover`, and
`audit_events`. Inputs are typed in `src/shadow_contracts.py`. The acceptance runner
is an executable usage example; it deliberately generates fixtures and synthetic
issuer keys outside the restricted worker.

## Ownership and trust

| Fact | Authoritative owner |
| --- | --- |
| Strategy/sleeve identity | ATS-4 `SleeveIdentity`, carried in the portfolio snapshot and intent |
| Account terms and loss-floor interpretation | Existing ATS-5 account-rule evaluator and append-only source history |
| Synthetic action permission | ATS-2 Ed25519 signed grant, checked against a public trust policy |
| Account/shared reservations, routes, stable IDs, local outbox | The one ATS-6 SQLite risk-domain transaction |
| Fill/cancel/reconciliation facts | Explicit synthetic source observations retained in the command journal |
| Audit normalization | ATS-3 `AuditEvent` bridge, always `environment="shadow"` |
| Independent acceptance numbers | Separate original-command oracle process; it imports no router or ATS calculator |

A caller-provided account snapshot, risk estimate, source reference, or
`coverage_complete` statement is an input assertion, not an independently authenticated
venue fact. The trusted synthetic supervisor supplies these assertions and a monotonic
UTC replay clock. The worker cannot mint grants. The ATS-5 `eligible_for_shadow`
flag is only an eligibility condition; it is never a substitute for the separate grant.
The only accepted authority domain is `SYNTHETIC_ONLY`, with the exclusive
`shadow_route` operation and `shadow_only` effect. Trading and protected-data
permissions remain denied. Existing ATS-2 native and synthetic-fixture grant paths
retain their original defaults.

## One transaction and one bounded risk domain

The store contains a projection document and an append-only hash-chained journal.
The projection includes accounts, portfolio, public authority, risk policy, owner
fence, intent decisions, reservations, execution facts, outbox, and local sink.
`BEGIN IMMEDIATE` serializes every write. Within its lock, admission:

1. Reads the committed projection and verifies its content hash and runtime identity.
2. Checks the current owner epoch, monotonic writer clock, exact source bindings,
   intent identity, signed scope, grant expiry, revocation, and replay protection.
3. Computes existing pending, recognized, disputed, and pre-existing obligations.
4. Applies shared/family constraints and every account's ATS-5, mark, margin,
   lifecycle, currency, instrument, and source-freshness checks.
5. Ranks only eligible accounts, then creates one indivisible route, its risk
   commitment, deterministic client IDs, and pending outbox entry.
6. Appends the original command, result, and new state hash, updates the projection,
   and commits all changes together.

Two processes can prepare against the same source versions. Preparation does not
reserve capacity. The second writer sees the first writer's committed obligations
inside its own transaction, so both cannot consume the same remaining cushion.
A single-account multi-leg intent is assessed as a whole; opposing legs receive no
netting credit. Cross-venue composite intents are rejected with
`CROSS_VENUE_ATOMICITY_UNQUALIFIED`.

### SQLite/runtime choice

The installed runtime is Python 3.13.5 with SQLite 3.45.3. ATS-6 uses
`journal_mode=DELETE` and `synchronous=EXTRA`, and refuses a different journal mode.
SQLite documents a WAL-reset corruption race affecting multiple concurrent WAL
connections in this version range. Rollback journaling avoids that WAL code path
without upgrading the locked runtime. See the official
[WAL-reset issue](https://sqlite.org/wal.html#wal_reset_bug) and
[transaction semantics](https://sqlite.org/lang_transaction.html).

The qualification includes real process termination immediately before/after
commit and local publication. It does not simulate power loss, disk/controller
failure, NFS semantics, arbitrary database-owner tampering, or multiple hosts.
A 20-second SQLite busy timeout raises an explicit operational error if a writer
cannot acquire the lock; it does not release risk or create a second store.
The application must keep one database per declared risk domain. Copying a writable
store and accepting routes independently in both copies is outside this protocol.

## Risk arithmetic

Money risk and margin use integer quanta in one declared currency. The fixture uses
100 quanta per currency unit. Decimal lot sizes are used for quantity/audit
conversion; binary floating point does not decide admission. For each leg:

```
unit_risk = ceil(stress_units_per_lot * account_stress_multiplier_bps / 10000)
            + account_cost_units_per_lot
pending_lots = 0 after complete terminal reconciliation,
               otherwise max(requested_lots - observed_opening_lots, 0)
recognized_lots = max(observed_opening_lots - reconciled_closing_lots, 0)
commitment = (pending_lots + recognized_lots) * unit_risk
```

Disputed opening-fill bounds and immutable opening obligations are added separately.
All legs sum into account and shared commitments. Same-family commitments also sum
across accounts: diversification credit is zero. Margin uses the analogous
pending-plus-recognized lot count. The account cap is the smaller of its explicit
risk limit and ATS-5's current minimum loss-floor headroom, rounded down to integer
quanta. A rule that breaches on touching the exact floor retains one additional
quantum when necessary.

A fill moves pending risk into recognized risk in the same transaction. It does not
free cushion. A closing fill retains recognized risk until source reconciliation.
New stress/cost information can ratchet existing route commitments upward, never
downward. Existing opening obligations cannot be removed by a snapshot replacement.
Their automatic liquidation/release is outside this implementation.

Uncertain marks, missing margin, incomplete terms, stale sources, and active-account
risk breaches block new admissions. An exposed account with stale source evidence
cannot lend apparently unused shared cushion to another account. Account or global
limit reductions retain commitments even when remaining capacity becomes negative.
Unexpected source overfills are retained using Python integer arithmetic rather
than discarded because they exceed the admission range.

## Frozen account ranking

Eligibility is computed first. The `cushion` policy sorts feasible accounts by:

1. Ascending applicable lifecycle priority.
2. Descending remaining account capacity after admission divided by incremental
   stressed risk, using exact rational arithmetic.
3. Ascending projected same-family commitment divided by account capacity.
4. Account ID as a deterministic tie-breaker.

Only active accounts are eligible. `first_fit` chooses the first feasible account ID;
`least_used` chooses the feasible account with the least committed risk, then ID.
The policy is immutable for a risk-domain store. The frozen comparison creates a
separate store for each policy and applies identical potential intents, source
snapshots, constraints, timing, and cost assumptions. It is a synthetic engineering
comparison, with no allocation tuning against market outcomes.

## Identity, authorization, and dispatch

The prepared action binds the complete intent, ATS-4 portfolio identity, every
current account snapshot hash, policy hash, public-authority hash, and runtime
fingerprint. The signed scope binds that action and its source/spec/config identities.
Transient free capacity is intentionally excluded from the signature: it is checked
under the transaction lock. Each stored decision remains tied to its original inputs.

An existing intent ID with the same intent returns its existing route/skip decision.
A changed intent under that ID is denied. An uncertain route never selects a second
account. A grant is consumed once by a committed decision. Client order IDs derive
from domain, intent, account, and leg; the outbox message ID hashes its entire payload.

Before a new local publication, ATS-6 rechecks the selected account source, public
authority/revocations, policy and portfolio bindings, eligibility, all active-source
constraints, and freshness. Changed preconditions mark the outbox `BLOCKED` and retain
the entire commitment. The operator must reconcile that obligation; changing a rule
or allowing a grant to expire does not erase it.

`publish` inserts one idempotent message into the local sink in a transaction and
sets `PUBLISHED_UNCONFIRMED`. `confirm_publication` records delivery acknowledgment
from that sink. Neither operation calls a broker. A crash after publication but before
confirmation yields one sink message and a retryable outbox record. Re-publication
returns the existing result without producing a second message.

## Execution states and release rules

| Evidence/state | Pending commitment | Recognized commitment | Next admissible action |
| --- | --- | --- | --- |
| Admitted / shadow-dispatched / no ACK | Retained | Unchanged | Retry only the same stable route/publication |
| ACK | Retained | Unchanged | Observe subsequent execution facts |
| Partial opening fill | Reduced by filled lots | Increased by the same risk | Continue observing the same account |
| Cancel/reject observation | Retained | Retained | Require complete source reconciliation |
| Closing fill observation | Unchanged | Retained | Require complete source reconciliation |
| Complete terminal reconciliation | Unfilled pending released | Open positions retained; covered closes applied | Re-evaluate any new, separately authorized intent |
| Incomplete/stale reconciliation | Retained | Retained | Resolve missing/conflicting source evidence |
| Conflicting/late terminal-breaking fill | Conservatively restored/augmented | Observed fills retained | Integrity halt blocks new admissions |

Older opening fills remain economically relevant and are incorporated by stable
execution ID. Duplicate observations and duplicate executions do not double-count.
Control observations must not rewind a newer source state. A reconciliation must
include the exact known execution set, complete coverage, a non-stale source sequence
and time, sensible completed/rejected quantities, and no unresolved conflicts before
it may release commitment. Known execution payloads and source history are immutable.

If a source later contradicts its own complete cancellation certificate, the router
records the late fill, restores possible residual pending risk, and halts admission.
This may expose a negative cushion after another intent was legitimately admitted.
That test proves visibility and containment of contradictory inputs; it does not
prove that a synthetic completeness flag makes external finality infallible.

The ATS-3 bridge preserves separate admission, publication, acknowledgment, fill,
availability, and observation clocks. Fills are explicitly hypothetical. It does not
invent absent marks, financing, or closing-order/ACK evidence, so ATS-3 can honestly
return `INSUFFICIENT_EVIDENCE`.

## Restart and recovery procedure

1. Stop admission from the previous owner; keep the same store and original runtime.
2. Construct `ShadowRouter(path)` and call `recover()` before accepting more work.
   Replay checks journal order, chain hashes, command results, every projected state
   hash, current runtime, and the final projection. No replay step publishes or
   releases a reservation.
3. If only the derived projection is damaged, use `recover(repair_projection=True)`
   under its SQLite writer lock. A corrupt journal is refused; do not delete records,
   recompute convenient hashes, or recreate the store to make a check pass.
4. Claim a new owner with the exact current epoch. All late operations from the old
   epoch are denied. Epoch changes do not release risk.
5. Inspect `usage`, negative remaining capacity, integrity halts, and unresolved
   outbox IDs. Retry only the original stable messages and obtain explicit source
   reconciliation for uncertain executions.
6. Refresh source evidence and obtain new action authorization where needed.
   A blocked old route remains an obligation until reconciled.

The fingerprint covers the router, contracts, ATS-5 evaluator, ATS-4 portfolio
module, ATS-2 authorization module, ATS-3 audit module, SQLite, Pydantic, and
Cryptography versions. Code drift refuses mutation and recovery. Upgrade/migration
of a nonempty risk domain requires a separate qualified protocol; this work unit
provides no permissive migration switch.

## Evidence and reproducibility

Run `python -m scripts.ats6_acceptance --detach` using the qualified interpreter.
Each run creates a unique directory with a frozen plan, original SQLite journals,
process exits, immutable committed backups, full projection, router replay result,
independent-process result, independent numerical trace, frozen expectations, policy
comparison, final acceptance matrix, and SHA-256 artifact manifest. Failed runs stay
alongside successful runs. The outside judge can be rerun directly against a
`committed.sqlite` backup using a fresh `--output` filename.

The outside judge derives positions, reserved/recognized/unknown risk, candidate
feasibility, and account choice from original commands. Its independent rule
arithmetic is deliberately restricted to the flat synthetic static-floor fixtures;
it does not claim to replace ATS-5's full rule engine. ATS-5's own broader regressions
are run separately. A forged projected fill with a recomputed projection hash is a
negative-control test for the oracle.

Bulk evidence remains outside source commits. The committed qualification report
and hash inventory identify the exact source, dependencies, commands, raw failures,
and successful artifacts. All results remain bounded by the declared synthetic
inputs, source trust, integer stress model, and single-host failure model.
