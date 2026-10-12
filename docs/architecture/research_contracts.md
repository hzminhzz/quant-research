# Research control-plane contracts

**Status:** M1/M2 schema, gateway, and read-only commands implemented. M3-A
scoped static policy implemented; remaining M3-M7 work remains design. Read the
[system architecture](agent_research_system.md) first.
**Compatibility target:** Existing immutable research-session **v1**,
`ml4t-engineer==0.1.4`, `ml4t-backtest==0.1.7`,
`pydantic==2.13.5`, `ruff==0.16.8` observed 2026-10-12.
Pin exact versions for trial execution only after proving a lockfile
with the same environment. The website API for 0.1.6 is not proof
that methods exist in 0.1.4.

## 1. Small interface hierarchy

Use **one read-only capability layer**, **one typed plan**, **one
run permit**, and **append-only evidence**. Favor simple files over
a service bus. Each contract has one owner; other modules use it
through an adapter, not by copying its content.

| Contract | Owned by | Required consumer | Identity |
| --- | --- | --- | --- |
| `SessionSpecV1` | Existing `src/research_session.py` | Session freeze/report | Existing frozen SHA |
| `CapabilitySnapshot` | Inspectors for catalog + installed packages | Planner | Environment/catalog identities |
| `ResearchContractV1` | Pydantic model of frozen `config` file | Runner | Canonical JSON SHA |
| `DataView` | Source resolver/market clock | Feature gateway | Data and coverage SHA |
| `FeatureSet` | Engineer-first gateway | Diagnostics and signals | Semantic feature SHA |
| `FeatureProof` | Independent numerical/timing tests | Gate | Input/output/proof refs |
| `ExecutionPlan` | Experiment planner | Native engine adapter | Engine/cost/fill SHA |
| `RunPermit` | Fail-closed preflight gate | Managed runner | Bound run intent |
| `AttemptRecord` | Durable worker lifecycle | Verifier/Casefile | Unique attempt ID |
| `VerificationReport` | Independent auditor | Decision renderer | Checks + source artifacts |
| `Casefile` | Derived index/view | Agent/human | Regenerable, non-authoritative |

**Do not** replace `src/research_session.py` to implement these.
Its schema v1 currently validates only its declared root keys.
Store the proposed `ResearchContractV1` in a standalone YAML file
and reference it via the existing session spec's optional
`config: ...` field **before freezing**. Subsequent changes to
source, feature, strategy, costs, or evaluation windows require a
new versioned session. Later schema changes need explicit migration.

### Implemented Pydantic policy

- `extra="forbid"`, strict discriminated unions for provider kinds,
  bounded parameter types, explicit units and timestamps.
- Canonical names as enums or constrained strings where stable.
- Reject unknown top-level fields instead of ignoring them.
- Validate syntactic structure with Pydantic. Validate **semantic
  support** by inspecting the installed registry and source catalog.
- Never use Pydantic validation alone as evidence that
  `compute_features()` executed or that a market-clock rule is valid.
- `ResearchContractV1` is strict, rejects unknown fields, and hashes its
  canonical JSON form. The existing session v1 schema is unchanged.
- The checked example is
  [`research_contract_v1_example.yaml`](../../config/research_contract_v1_example.yaml).
  It is a contract example, not a frozen session declaration.
- The gateway currently supports native `adx(period=14)` and `typprice`,
  plus approved `cash_open_vwap` and `prior_n_high_low` extensions.
  Other registry entries remain discoverable but are not executable through
  this managed gateway.

## 2. `CapabilitySnapshot`: first cheap question

Proposed fields:

```yaml
schema_version: 1
snapshot_at: "<UTC timestamp>"
repository:
  head: "<git SHA>"
  dirty_diff_sha256: "<hash or null>"
  untracked_task_file_hashes: {}
environment:
  python: "<version>"
  lock_sha256: "<hash>"
  engineer_version: "0.1.4"
  backtest_version: "0.1.7"
  ruff_version: "0.16.8"
  supported_api_signatures: {}
features:
  registry_count: 120
  registry_fingerprint: "<hash of sorted metadata>"
  native_feature_ids: []  # resolved by installed library
data_catalog:
  catalog_identity: "<from ml4t-data>"
  readiness_identity: "<from ml4t-data>"
  source_choices: []
runtime:
  active_job_refs: []
  available_executor: "<verified provider>"
```

The values shown are **examples**, not live output. Never store a
bare symbolic provider name as a capability without probing it.
Capabilities are observed facts with timestamps and provenance,
not a promise that the agent can execute anything.

Supported `ml4t-engineer` 0.1.4 public surface observed locally:
`compute_features(data, features, group_col=None, timestamp_col=None,
assume_sorted=False)`, `feature_catalog.list()`,
`feature_catalog.search()`, `feature_catalog.describe()`.
The registry accepts feature **metadata**, but custom function
dispatch is **unverified**. A feature metadata entry is not an
approved executable feature. `scripts/research.py discover` shows the live
function signature and version. The M2 gateway uses a fixed allowlist for
verified input semantics; discovery does not expand that allowlist.

## 3. `ResearchContractV1` attached before session freeze

The runnable example is an **illustrative gateway contract**, not valid
`SessionSpecV1` root YAML. Its exact accepted structure is in the linked YAML
file. Key source and feature fields are shown below:

```yaml
schema_version: 1
session_id: "vwap-pullback-dukascopy-proxy-example"
dataset:
  requested_product: "Dukascopy USATECH.IDX/USD CFD price proxy"
  source_vendor: "Dukascopy"
  source_symbol: "USATECH.IDX/USD"
  catalog_dataset_key: null
  external_exception_id: "dukascopy-usatech-proxy-example-v1"
  authority: "staged_noncanonical"
  product_class: "cfd"
  role: "price_proxy"
  volume_semantics: "broker_tick_or_quote_proxy"
  timeframe: "1m"
  timestamp_convention: "bar_open"
  timezone: "America/Chicago"
  group_columns: [symbol]
feature_set:
  - id: "adx_14"
    provider: {kind: "engineer.native", name: "adx", params: {period: 14}}
    inputs: {high: high, low: low, close: close}
  - id: "cash_vwap"
    provider:
      kind: "extension.approved"
      extension_id: "cash_open_vwap"
      version: "1.0.0"
      session_open: "08:30"
      timezone: "America/Chicago"
    inputs: {high: high, low: low, close: close, volume: volume}
strategy:
  rule_id: "vwap_pullback_adx_v1"
  engine: "ml4t.backtest"
evaluation:
  development: ["2026-01-01", "2026-07-01"]
  retrospective_validation: ["2026-07-01", "2026-09-01"]
  holdout_start: "2026-11-01"
```

The example is intentionally **not automatically qualified**:
a staged Dukascopy rebuild is not canonical by default; a
`catalog_dataset_key: null` requires a reviewed exception record.
Likewise the `15:14` exit changes the original `15:55` thesis
and requires a separate session. The contract rejects a false CME volume
claim, a Dukascopy-to-LSE source mismatch, and unsupported native inputs.
The M1 doctor reports source and time blockers for existing frozen sessions.

### `DataView` invariants

- One exact source selection and product mapping. No alias-based
  fallbacks across CFD, continuous future, index and dated future.
- Source timestamp means `BAR_OPEN`, `BAR_END` or `EVENT_TIME`;
  availability is an explicit UTC instant, not the timestamp by
  assumption.
- Data window has requested range, observed range, excluded
  intervals, accepted session calendar, warmup and gap policy.
- Volume semantics are typed. A cash-index `volume` column does
  not satisfy a requirement for genuine CME executed contracts.
- Instrument precision, tick, multiplier, trading hours and fees
  have distinct `verified`, `assumed`, `unknown` fields.
- A gap may invalidate a session without making the whole source
  invalid. Coverage criteria are declared before scoring.
- Source identity, catalog snapshot, code transform and result
  Parquet identities are all recorded.

### `FeatureRequest` invariants

- `engineer.native` requires an installed registry match, valid
  parameter names, supported input/output shape and a real call
  through the gateway.
- `extension.approved` requires ID, version, owning module,
  numerical oracle, causality tests and explicit approval.
- `execution.state` belongs to an engine strategy, not the
  Engineer feature catalog; reject it in `FeatureSet`.
- Multi-asset features require explicit partition keys. Stateful
  session features require explicit reset calendars.
- Lookback semantics distinguish inclusive current completed
  bar from previous completed bars. No generic `shift(1)`
  rule should accidentally shift a legitimate bar-close
  feature twice or permit a future bar.
- The output has `source_timestamp`, `available_at`,
  exact name/type/units, warmup validity and transformation
  provenance. Null/NaN rules are explicit.

The installed Engineer `maximum`/`minimum` metadata and runtime use `close`.
The gateway rejects them for prior highs/lows. The approved
`prior_n_high_low` extension uses only the previous N completed bars, groups
by the declared instrument keys, and requires a full warmup window.

## 4. `FeatureProof`: a hash is not an indicator test

A gateway result includes canonical contract, input, feature-set, output, and
extension-code hashes; installed provider versions; resolved feature
semantics; and runtime checks for schema, rows, availability, and hashes.
Numerical and DST/session proofs come from the independent tests. A gateway
hash alone does not verify numerical semantics.

```yaml
proof_version: 1
feature_set_sha256: "<sha>"
resolved_provider_versions: {}
checks:
  registry_resolution: PASS
  exact_input_output_semantics: PASS
  independent_numeric_oracle: PASS
  session_and_group_boundaries: PASS
  warmup_and_null_contract: PASS
  causal_timestamp_alignment: PASS
  deterministic_replay: PASS
trace:
  requested_feature_ids: ["adx_14", "session_vwap_1"]
  resolved_call_graph: []
  output_columns: []
  reference_artifacts: []
decision: FEATURE_VERIFIED
```

**Independent** means reference computation has different
failure modes from the gateway. Comparing the same function
to its own output is not parity. For native Engineer features,
the test verifies the gateway actually invoked Engineer with
the expected spec. For a new extension, tests include synthetic
session resets, weekend/DST, zero volume, missing minute,
last-bar changes and bar-close availability.

## 5. `ExecutionPlan` and the managed run permit

Native ML4T strategy/engine owns market and stop orders,
position state, fills, margin and cash ledger. An adapter may
repair a documented missing feature; it must be versioned,
tested and identified. Custom execution loops are not a
substitute for the engine.

```yaml
execution_plan_version: 1
requested_symbol: "DUK_USATECH"
actual_product: "Dukascopy CFD price proxy"
execution_backend: "ml4t.backtest"
backend_version: "0.1.7"
decision_time: "bar_completion"
earliest_fill: "next_executable_bar_open"
long_only: true
position_sizing: {units: 1, unit_type: "hypothetical_nq_equivalent"}
target: {lookback: 5, source: "completed_highs", updated_after_entry: false}
stop: {lookback: 20, source: "completed_lows", updated_after_entry: false}
hard_flat: "15:14 America/Chicago"
costs:
  commission_per_side_usd: 2.50
  slippage_market_stop_points: 0.25
  slippage_passive_limit_points: 0
  cost_source: "illustrative"
guarantees:
  OCO_live_atomic: false
  CME_contract_resolved: false
  passive_queue_fills_verified: false
```

Before a run, the **RunPermit** must bind and check:

1. Frozen `SessionSpecV1` and linked research contract hashes.
2. Catalog-exact Data View, instrument and source role.
3. FeatureProof and signal availability at decision time.
4. Engine version, executable time, costs, exit, and stress plan.
5. Preregistered trial ID and permissible data window.
6. Existing attempts and active job leases; no duplicate work.
7. Compute budget and allowed effects; no protected-window use.
8. Expected artifact names and independent verification recipe.

A permit is **valid only for its exact identities**. Drift
invalidates it. Changing a code file after the permit cannot
reuse the permit to score a new implementation. A cached
computation may satisfy unchanged inputs, but the trial and
holdout exposure must still be recorded.

For sensitive final tests, the runner should obtain **read-only
scoped data access** only after authorized unseal. If OS-level
data permissions are not available, the gate is advisory against
arbitrary Python and must be reported as such. Never advertise
physical holdout enforcement when the process can open raw files.

## 6. Attempts, gates, and evidence records

Use normalized terminology:

- `trial_id`: declared question. All observed variants count.
- `attempt_id`: unique execution, including failed/aborted trials.
- `run_id`: content-addressed execution intent (may be shared
  by repeated attempts with identical immutable inputs).
- `gate_report`: mechanically checked evidence about one
  boundary, not a trading conclusion.
- `decision`: interpretation within scope and uncertainty.
- `approval`: a separately authorized production state.

A proposed `AttemptRecord` is append-only:

```yaml
schema_version: 1
trial_id: "B2_base"
attempt_id: "<uuid>"
run_id: "<hash of executable intent>"
status: "RUNNING" # PLANNED|RUNNING|COMPLETED|FAILED|BLOCKED|ABORTED
lease: {owner: "<executor>", tmux: "ml4t-vwap-B2", expires_at: "<timestamp>"}
fingerprints: {git_head: "<sha>", dirty_patch: "<sha>", config: "<sha>",
               data: "<sha>", code: "<sha>", env: "<sha>"}
commands: ["<full sanitized command>"]
artifacts_expected: []
artifacts_observed: []
failure: null
timestamps: {started_at: "<timestamp>", finished_at: null}
```

Existing v1 `record_trial` accepts only terminal
`completed` and `failed`. Proposed lifecycle records must
**not** be passed as undocumented v1 statuses. Keep attempt
facts in separate append-only files until migration.

`GateReport` states a scoped result:
`PASS | BLOCKED | FAILED | INCONCLUSIVE`, with
`reason_code`, `checks`, `evidence_refs`, `inputs`,
`limitations`, `next_safe_action`, and
`observed_at`. `RUNNING` is attempt state, not a
research pass. Every result retains scope:
development, retrospective/previously observed, or
protected prospective holdout.

### Suggested stable failure codes

| Code | Meaning | Suggested first action |
| --- | --- | --- |
| `SOURCE_IDENTITY_CONFLICT` | Requested product disagrees with catalog or file | Resolve exact product and explicit proxy consent |
| `DATA_SESSION_MISMATCH` | Requested executable time missing in feed | Fix source or register changed execution variant |
| `DATA_UNQUALIFIED` | Source authority, gaps, or volume not fit for requested claim | Qualify source; downgrade claim explicitly |
| `FEATURE_UNRESOLVED` | No exact installed native feature or approved extension | Show registry candidates; propose extension |
| `FEATURE_SEMANTICS_MISMATCH` | Feature named similarly but math/input differs | Provide independent parity fixture |
| `FEATURE_CAUSALITY_FAIL` | Feature not available at decision time | Correct alignment and add regression |
| `ENGINE_EXECUTION_INVALID` | OCO/limit/fill/ledger invariants broken | Isolate minimal native engine reproduction |
| `TRIAL_UNDECLARED` | Evaluated parameter/variant absent from ledger | New registered trial; never erase observed one |
| `HOLDOUT_EXPOSED` | Proposed pristine period already viewed | Record exposure; find future genuinely unseen data |
| `ACTIVE_RUN_EXISTS` | Reuse or inspect running worker rather than duplicate | Inspect lease, tmux and logs |
| `IDENTITY_DRIFT` | Code/data/library differs from frozen intent | Stop; create versioned run/contract |
| `BUDGET_EXCEEDED` | Requested compute/side effects exceed permit | Narrow test or request authorization |

Each blocked response must include `expected`, `observed`,
`where_found`, and **one safe next command** when possible.
Avoid vague "data quality failed" errors.

## 7. Compliance boundary and proof of enforcement

Use layers of increasing cost:

- **Pydantic**: schema, type/units and discriminated provider specs.
- **Installed registry resolver**: feature existence and exact
  semantics, checked before `compute_features`.
- **Ruff**: standard lint and banned direct API imports in the
  *managed strategy feature namespace*, not blanket bans.
- **Small AST policy**: restricted call sites, unsupported
  indicator shadow functions, and allowed extension imports.
  AST checks **cannot prove numeric equivalence** or stop all
  dynamically generated Python.
- **pytest**: negative fixtures (direct ADX implementation,
  unregistered VWAP, missing availability timestamp,
  wrong source alias, invalid stop fill) must fail the gate;
  positive fixtures must pass.
- **Managed runner**: refuses a validated result without
  matching typed contract, feature proof, run permit, audit,
  and source coverage proof.
- **CI/branch protection**: required checks for code changes,
  separate from authenticated external-data audits.

M3-A applies only to Python files under
`src/managed_strategies/**/*.py`. Run the AST check with
`python scripts/check_managed_features.py` and the restricted Ruff check with
`ruff check --config scripts/ruff-managed.toml src/managed_strategies`.
The AST command emits sorted JSON with the checked scope, file count, and
stable reason codes: `CUSTOM_INDICATOR_IMPLEMENTATION`,
`FORBIDDEN_INDICATOR_IMPORT`, `ENGINEER_BYPASS`,
`LEGACY_INDICATOR_IMPORT`, and `UNSUPPORTED_NATIVE_VWAP`. The Ruff policy
uses `TID251` only for the same explicit directory. The feature gateway and
independent oracle tests remain outside the managed-strategy scope. Existing
legacy modules are not linted. This static check catches direct and common
aliased source patterns; it cannot prove indicator mathematics or prevent
arbitrary dynamic Python execution.

Do not declare compliance merely because lint exits with 0.
Do not scan every legacy research script on day one: existing
`src/features.py` and `src/pipeline.py` knowingly contain
alternative implementations. Classify them as **LEGACY_UNMANAGED**;
prohibit *new* managed runs from importing them, and migrate
them with parity tests. Their historical results stay available
but are not upgraded by the new rules.

**GitHub reality:** the observed `.github/workflows/ci.yml`
was untracked at inspection. CI policy must be tracked and
required on the actual default branch before claiming enforcement.
A local `git diff --check` is not a substitute for protected-branch CI.

## 8. Reproducible execution and safe recovery

Use existing `src/research_session.py` frozen/record semantics
and `run_log/` artifact directories. Prefer atomic
create-once writes and immutable observed artifacts.
Each long worker has one identifiable tmux session, a
command, exact checkout, env, log file, heartbeat and
expected outputs. Resume must inspect existing sessions,
exit code, logs, trial ledger and hashes before creating
another attempt.

Avoid automatic `git reset --hard`, `git clean -fd`,
blind stash, or writing unowned files. Do not run a final
holdout merely to confirm a broken development result.
If a worker reports success but proof is absent, status
is `OUTPUT_PRESENT` at most, not `AUDITED`.

## 9. Acceptance-test inventory

The initial vertical slice must produce these tests:

1. **Native lookup:** Engineer's installed ADX(14) called
   through gateway with expected params and columns.
2. **Name trap:** `maximum` on default close cannot be
   substituted for prior-5-high without verified mapping.
3. **Extension:** cash-open VWAP resets at session open,
   refuses absent/zero/unqualified volume when required.
4. **Time:** completed-bar, next-open execution and DST
   preserve the decision/fill inequality.
5. **Source:** selecting Dukascopy never silently yields
   LSE `NQ.F`; staged rebuild requires explicit exception.
6. **Coverage:** no 15:55 fill on a 15:14 source,
   no synthetic gap-filling to satisfy a session.
7. **Lint mutation:** introduce an unauthorized strategy
   indicator and confirm the **real CI check** fails.
8. **Execution:** legal sell-limit, stop-first dual-hit,
   native sibling cancellation, net ledger reconciliation.
9. **Holdout:** previously observed period cannot be
   called pristine; code drift voids permit.
10. **Recovery:** interrupted worker is found, not
    duplicated; failed attempt remains in ledger.
11. **Authority:** v1 frozen hash and legacy trial files
    remain byte-identical after gateway integration.
12. **Provenance:** a cached feature result is reused
    without hiding a new evaluated statistical trial.

Pass/fail thresholds are specified per work item in the
[rollout plan](../plans/agent_research_system_rollout.md).
All data-free contract tests must run in fresh CI. Large
VPS market-data tests require a separate, explicitly
scoped runner and recorded input fingerprints.
