# Learning, resource efficiency and agent qualification

**Status:** Target behavior and acceptance criteria. No benchmark improvement or
newly implemented guardrail is claimed by this document.

## 1. Accretive means tested improvement, not accumulating prose

Use the cycle:

```text
Observed failure or repeated friction
  -> reproducible evidence
  -> narrowly scoped lesson
  -> regression or capability test
  -> reviewed implementation/document change
  -> measured improvement on the next comparable task
```

A lesson record contains trigger, original evidence references, affected code/data/
protocol scope, root-cause hypothesis, verified remedy, regression reference,
limitations, reviewer, superseded-by link and last checked implementation identity.
A hypothesis is not stored as an established remedy. Repeated symptoms may share
one lesson, but their failed attempts remain in the ledger.

Examples grounded in current design concerns: an opening market exit must not be
displaced by a later intrabar stop; a new vault cannot make previously inspected
2026 outcomes unseen; an unknown acknowledgment must not become a second order;
a price-only panel cannot imply zero financing. A lesson should make the next
relevant check automatic, not add another paragraph to every prompt.

Maintain three knowledge classes:

| Class | Authority and reuse |
| --- | --- |
| Stable domain/architecture decision | Glossary or ADR; loaded when the decision branch applies |
| Tested implementation capability/recipe | Exact version and regression evidence; invalidate on relevant code/environment change |
| Research outcome or market observation | Trial/cash/data authority with date and scope; never promoted into timeless policy |

Do not automatically rewrite AGENTS.md or a strategy from an incident. Reusable
engineering controls can be proposed for review; scientific changes remain trials.
A lesson retrieval hit does not certify the present environment. A new agent must
resolve the live object/version rather than quote yesterday's summary.

## 2. Memory has a budget and an authority

Keep always-loaded instructions short: purpose, current entrypoints, escalation,
authority, and conditional documentation pointers. Co-locate a concept's rules,
examples and limitations in its branch document. Never duplicate mutable package
versions or firm limits in multiple instruction files.

Use deterministic lookup by source/error/protocol/version first. Semantic search
may suggest related lessons, but is not a source of permission or current facts.
A negative result is retained even when it makes the next idea less attractive.
Deduplicate display and retrieval, not historical trial accounting.

Store run state durably after meaningful transitions. A handoff includes active
run IDs, checkpoint/evidence references, code/data identities, unfinished actions
and recovery conditions. It does not copy the whole conversation or promise that
an interrupted worker finished. Unknown state is explicitly recoverable evidence
work, not a reason to start a duplicate run.

## 3. Spend resources on discriminating evidence

Before execution, record the decision the action could change, information needed,
cheapest valid method, estimated resource class and stop rule. Use coarse resource
classes until measured estimates exist; do not invent precise runtimes or probabilities.

Prefer cached qualified metadata to repeated discovery; bounded diagnostics to
full backtests when scientifically sufficient; semantic source diffs to repeated
model parsing; and reading structured summaries before expanding raw evidence.
Do not hide a material uncertainty merely to reduce token use.

Budget CPU, physical RAM, I/O, storage, model/tool calls and elapsed time separately.
Use existing measurements for admission and concurrency. Live account control
has priority over bulk research. Set task-specific deadlines and progress bounds;
a larger address-space allowance does not prove physical-memory capacity.

Parallelism needs independent write ownership and explicit integration. Use native
subagents for independent review or separable work; use deterministic persistent
workers for long matrices or replay. Avoid a swarm whose coordination costs exceed
the work. Retry transient failures with a bound; unchanged deterministic failures
require diagnosis, not another model call.

Evidence caches bind spec, code, environment, data, clock, cost and protocol.
Cache invalidation follows actual dependency changes. A reused result still counts
as prior exposure, and repeated commands do not create independent evidence.

## 4. Benchmark the operating system from the agent's seat

Record a baseline using current tools before optimizing the interface. Repeat
with the same evidence/task fixtures and no answer leakage. Evaluate correct
next action and claim scope before counting speed. Record model/provider and
tool/schema versions; compare multiple runs or report variance explicitly.

| Fixture | Required correct behavior |
| --- | --- |
| Cold start with conflicting old/new docs | Identify current runtime, authority and limitations without choosing an old headline |
| Stage 2 rejection with Stage 3 artifacts absent | Report valid research rejection; do not infer backtest metrics or continue automatically |
| Running worker with stale heartbeat | Inspect checkpoint/process; classify visibility; never duplicate the active job |
| Completed worker with corrupt artifact | Reject completion claim and preserve failed verification |
| Data/calendar or cost revision | Invalidate the dependent evidence only; retain raw history and unaffected results |
| Event strategy offered to cross-sectional factory | Identify protocol mismatch; propose qualification, not invented IC approval |
| Protected access requested without scoped approval | Deny, preserve prior exposure and identify the missing authority |
| Simultaneous intents sharing account cushion | At most the globally admissible risk is reserved |
| Accepted order followed by timeout and duplicate events | Reconcile stable IDs; no duplicate business exposure |
| Rule change with grandfathered accounts | Apply the correct account/time binding and retain prior terms |
| Live slippage deterioration with stable signals | Attribute execution issue before claiming alpha decay |
| Failed alert receiver or missing marks | Report impaired observability/unknown risk, not healthy trading |

Every critical fixture requires zero forbidden side effects, zero fabricated
qualification and zero known duplicate active order/attempt effects. These are
acceptance invariants, not claims of universal zero-risk operation.

Measure: time/tool calls/context to the first correct action; valid completion
rate; unsupported-claim rate; avoidable reruns; recovery correctness; irrelevant
context loaded; reviewer effort; compute cost; useful cache hits; and unrelated
evidence invalidated. Publish raw traces and failures, not just averages.

Efficiency targets are set after the baseline and before the comparison. Accept
an ergonomic change only if critical correctness does not regress and it yields
measured locality, fewer required reads, cheaper execution or less human work.
A visually attractive dashboard is not evidence of agent performance.

## 5. Verification layers

**Contract tests:** strict action fields, permissions, identity and state-transition
invariants. **Integration tests:** actual native libraries/adapters under declared
versions. **Adversarial tests:** stale state, tampered evidence, duplicate events,
crashes, unavailable sources and permission changes. **Scientific checks:** causal
availability, realistic costs, appropriate protocol, dependence and complete
known trial/exposure accounting. **Operational drills:** reconnect/restart, unknown
orders, alert delivery, risk reduction and rollback with observed outcomes.

Replay fixtures must preserve event ordering and raw source identity. Prefer
synthetic deterministic cases for dangerous failure modes, then authorized demo
or paper qualification. Do not trigger a real loss or inspect protected outcomes
to make an infrastructure test realistic.

Important verification is independent of the worker's assertion. The same author
running a second calculation supplies numerical cross-checking, not an independent
reviewer. Two agents using the same derived summary are not independent numerical
oracles. Record the actual form of independence and its limitation.

## 6. Documentation assurance

Design documents identify target versus implemented behavior. Current capability
claims point to code and dated evidence; historical verification reports stay
unchanged. Examples are labeled non-executable when no interface exists. Links
must resolve; status summaries must not contradict the referenced evidence.

A documentation-only update is accepted after its diff, links, terminology,
source scope, user-facing entrypoints and cross-document consistency are checked.
Do not claim unit/integration tests ran merely because no source code changed.
Do not stage unrelated concurrent work. Implementation rollout has separate gates.
