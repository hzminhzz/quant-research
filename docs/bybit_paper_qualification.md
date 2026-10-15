# Issue #48 — Bybit Demo paper qualification contract and operator runbook

**Status: PREPARED OFFLINE / OPERATIONALLY BLOCKED.** The contract template and
credential-free rehearsal are implemented. No research-approved, Bybit-compatible
strategy or verified Demo account was selected in this issue. No paper-session
duration, account-specific risk numbers, trade counts or alert thresholds have
been approved. Nothing here authorizes an external order.

Parent: [#43](https://github.com/hzminhzz/quant-research/issues/43).
Dependency: [#45](https://github.com/hzminhzz/quant-research/issues/45).
Use installed `ml4t-live==0.1.2`, native
`LiveEngine -> SafeBroker -> BybitLiveBroker`, one execution owner per Demo
account. Do **not** add a trading engine, scheduler, risk store or watchdog.

## 1. Freeze one explicit research decision

The *only* packet is `config/paper_qualification_issue48.example.yaml`.
Copy it to protected local operator storage outside both repositories.
**Never populate credentials, account UID, account equity, broker snapshots or
private research results in a committed YAML file.**

The final packet must bind a **single** approved
`ml4t.backtest.Strategy` source/digest, its independent promotion verdict,
the venue-compatible instruments, Bybit Demo (NOT Testnet), expected
public **mainnet** bar source, bar cadence, an alias for the account
(not its UID), the exclusive account/risk owner, and a risk reviewer.

**Research candidate warning:** `promote/donchian_btc` is marked
`PROMOTED_FOR_FURTHER_RESEARCH` and `NOT_APPROVED`. The ORB registry
`run_log/validation_status.json` says `NOT_APPROVED`. Do **not** silently
select either. A candidate must complete the required research promotion and
venue/instrument parity checks and receive a traceable independent
`APPROVED_FOR_PAPER_REVIEW` decision. This is a **paper-review** research
decision, not a live authorization.

Freeze exact user-reviewed numerical values in `risk`, including quantity,
order value, position value/quantity, total exposure, maximum positions,
orders/minute, daily loss, drawdown, allowed assets, price deviation, data age,
intent deduplication, feed silence and native retry attempt/cooldown limits.
A `reviewed: true` flag without a named reviewer/traceable decision is not
independent authorization. The validator invokes
`make_native_risk(ReviewedPaperAccount)`, which reuses the native
`LiveRiskConfig` fields rather than inventing a second risk policy.

The native state file is exclusively
`<private-state-dir>/bybit-demo-account-<private-UID>.json`;
its audit journal is derived by native ML4T as
`<private-state-dir>/bybit-demo-account-<private-UID>-journal.jsonl`.
Keep the connector's separate **existing** Bybit order-intent journal.
All actual private files and directories must live outside both repositories;
directories must have mode 0700, sensitive evidence files 0600. All
strategies on the same broker account must use **the same** canonical state
directory. The native single-writer lock is **local**, not cross-VPS.

## 2. Predeclare the observation and binary gates

Before monitoring starts, record **exact future UTC start/end** in the packet,
together with explicit values for each of the following. Unapproved numerical
values remain `null` and cause `BLOCKED`; do not reuse synthetic test values.

| Gate | PASS condition | FAIL / abort |
|---|---|---|
| Account and strategy | Approved source digest, independent reviewer, correct Demo UID; one native owner | Unknown/ambiguous account or unapproved strategy |
| Reconciliation | Zero unmatched positions/orders after each connect/recovery | Any unresolved mismatch |
| Orders and fills | All paper fills attributed to provider ID, native journal and state | Any unattributed fill or unknown outcome |
| Risk | No breached hard order, exposure, loss or drawdown cap | Any native risk/kill-switch event requiring halt |
| Availability | Observed healthy fraction at least the *preapproved* threshold | Below frozen threshold or unverifiable intervals |
| Lifecycle drills | At least the *preapproved* positive counts for observed order/fill/cancel and native bounded recovery | Incomplete or non-independent evidence |
| Integrity | No unresolved journal/state errors or safety incidents | Any unresolved incident |
| Completion | Frozen window completed with independently linked evidence | Early abort, missing data or retrospective rule changes |

For unresolved material incidents, the configured hard-zero thresholds must
remain **zero**. Mandatory abort reasons are in the template; they may be
expanded but not deleted. Recovery exhaustion, broker disconnection,
reconciliation mismatch, unknown order outcomes, stale/gapped feed, journal
failure or unexpected Mainnet identity are reasons to **stop and investigate**.
Do not change limits during an observation to manufacture PASS. Reopen a new
frozen observation if material parameters change.

## 3. Read-only authenticated preflight — NO ORDERS

Create/check a private account-scoped state directory (0700). Use dedicated
**Demo** credentials and an independently observed numeric Demo UID.
The two credential scopes are distinct: this step must use a **read-only**
Demo key; a later separately authorized Demo execution session requires
an appropriate Demo-scoped execution credential.

With `BYBIT_ENVIRONMENT=demo`, `BYBIT_MODE=read_only`,
`BYBIT_DEMO_API_KEY`, `BYBIT_DEMO_API_SECRET`, and
`BYBIT_DEMO_EXPECTED_UID` set in secure operator environment storage:

```bash
cd /home/quant/dev/quant/quant-research
umask 077
export PYTHONPATH=/home/quant/dev/trading-connector
.venv/bin/python -m scripts.bybit_demo_preflight \
  --state-file "$PRIVATE_STATE_DIR/bybit-demo-account-${BYBIT_DEMO_EXPECTED_UID}.json" \
  --evidence-file "$PRIVATE_EVIDENCE_DIR/read-only-preflight.json"
```

**Critical:** use the **same** account-scoped state file that
`make_native_risk()` will use in the paper runtime. The older #44 runbook
contains a generic demonstration path; do not use a different state path to
claim clean reconciliation. A private preflight JSON must show
`status=PASS`, Demo endpoint and UID match, native paper identity,
clean reconciliation, healthy state/journal, zero unknown connector intents
and zero submitted orders. A report older than 24h is rejected for the
*operator rehearsal*. That freshness check is an operational policy for this
rehearsal, not a claim that native ML4T imposes a 24-hour limit.

No paper authorization is granted by clean read-only preflight alone.

## 4. Offline operator rehearsal — always fail closed on uncertainty

After freezing a private YAML packet (including account owner, reviewer, risk
budgets, evidence paths and objective gates), run this **read-only validator**:

```bash
cd /home/quant/dev/quant/quant-research
umask 077
PYTHONPATH=/home/quant/dev/trading-connector \
  .venv/bin/python -m src.paper_qualification \
  --packet "$PRIVATE_EVIDENCE_DIR/paper-qualification.yaml" \
  --evidence-file "$PRIVATE_EVIDENCE_DIR/packet-rehearsal.json"
```

The rehearsal reads files and checks environment variables for **presence only**;
it never opens Bybit transport, instantiates `SafeBroker`, acquires a live
writer lease, changes risk state or submits any order. It validates frozen
source digest, Demo/environment selection, reviewer declarations, all native
risk fields, venue-qualified instruments, cadence, protected state paths,
reconciliation/preflight identity, current native health report, finite
observation window and abort/pass criteria.

- `BLOCKED` (exit **2**): review `blockers`, remediate the named input/
  evidence gap, retain failed reports and do not start an order-capable runtime.
- `READY_FOR_MANUAL_REVIEW` (exit **0**): only means the locally supplied
  fields and evidence **passed the offline checks**. These artifacts can be
  synthetic or incorrectly attributed; an independent human must authenticate
  the source, identity and approved operating permit.
- Both statuses always include
  `paper_qualified=false`, `paper_order_authorized=false`,
  `live_money_authorized=false`, `submitted_orders=0`.
  This validator **cannot** set any of these to true.

The included repository template is intentionally `BLOCKED`.
A true `native_health_report` requires a separately authorized owner to
capture a private JSON object with UTC `checked_at` no older than 10 minutes,
`engine` from `LiveEngine.runtime_status()`, `persistence` from
`SafeBroker.persistence_status`, and `reconciliation` from
`SafeBroker.reconciliation_report` from the actual selected runtime. **Before the first authorized engine connection,
this post-connect evidence is legitimately unavailable**; the rehearsal is
therefore BLOCKED and must not be used as a bootstrap bypass. The human
operator reviews the contract and authorizes any Demo connection as a
*separate* action; only then capture the health snapshot and repeat the check
before running the strategy.

## 5. Operator start, inspect, stop and restart

**These are runbook instructions, not a trading launcher.** No remote Demo
orders, no Testnet substitution and no Mainnet orders are authorized by #48.
Only after issue #44 read-only qualification, safety gates #45–#46, chosen
account/strategy research promotion and a separate explicit Demo execution
permit may an operator exercise the existing runtime.

1. Before starting, inspect real VPS branch/dirty work and native version;
   check the frozen packet digest and permitted symbols. Confirm one
   canonical state directory and one local owner (no second engine or
   competing VPS). Check file modes/journal integrity.
2. Build the **same unchanged Strategy class** through
   `build_native_paper_engine(strategy, bybit_broker, feed, reviewed_account)`
   using a verified **Demo execution-mode** connector. This construction
   creates native broker objects but does not itself trade. A source approved
   for research is not automatically venue-parity-certified.
3. Operator explicitly permits Demo **connect only**.
   `await engine.connect()` must reach native `ready` with clean
   `SafeBroker` reconciliation and healthy journal/state. Save this report
   privately, without account identifiers in logs. If it fails,
   `await engine.stop()`, `engine.broker.close_persistence()`, and
   leave the session **BLOCKED**. Do not issue orders.
4. Independently inspect `engine.runtime_status()`,
   `engine.operational_events`,
   `engine.broker.persistence_status` and
   `engine.broker.reconciliation_report`. If the packet rehearsal
   subsequently passes and **separate Demo mutation authorization** exists,
   a designated operator can invoke native `await engine.run()`. The
   existing native Strategy handles all intents; do not build an alternate
   execution loop. Observe the frozen time window; never infer fills from bars.
5. **Manual stop:** request native `await engine.stop()`. On safety
   breach, use the native risk stop/kill-switch as appropriate to stop
   further opening orders; do not assume it flattens the account. Preserve
   provider positions/pending orders for operator-only read-only inspection.
   After cleanup, `engine.broker.close_persistence()` releases the native
   writer lock, and the **existing** connector journal must be closed.
   Confirm a final native `stopped`/terminal status and record cleanup result.
6. **Native bounded recovery:** `auto_recover=True`,
   `feed_silence_seconds` greater than a completed bar period, explicit
   finite attempt/cooldown. Recovery reuses native broker identity and
   reconciliation gates. If `engine_recovery_exhausted` or
   `reconciliation_blocked_startup`, leave FAILED/STOPPED, notify operator,
   capture the native event/journal and **do not** schedule an infinite restart.
7. **Restart only after documented incident resolution** and a clean
   read-only account snapshot. Never delete/reinitialize native state,
   native audit journal, connector intent journal or lock files to clear a
   mismatch. Repeat the operator validation; only a newly authorized start
   can resume trading.

No automatic flatten, direct-broker fallback or release of ML4T risk checks
is permitted as an incident response.

## 6. Qualification evidence and decision

Private output directory: freeze evidence under a protected directory
outside both repos, with append-only attempt/incident history where possible.
Required links at paper-review close:

- Frozen packet hash and independent research verdict.
- Identity-verified read-only preflight report and private risk-state path.
- Actual native runtime health/reconciliation transitions, native journal,
  connector intent records and unexpected-order/partial-fill outcomes.
- Independently retrieved provider positions/open orders/fill/cancel records
  (obtained only during separately authorized Demo operations).
- Native bounded recovery drills, operator-restart decisions and incident log.
- Actual Prometheus target-scrape evidence, Grafana screenshot or exported panel
  evidence, alert receipt confirmation (issue #47), or explicit BLOCKED entries.
- Frozen observation period coverage and the pass/fail measurements above,
  including *missing* observations, not just passing subsets.

**Decision labels**:

- `BLOCKED`: missing identity/approval/evidence, unresolved safety state,
  unobserved broker orders or unusable monitoring.
- `PAPER_QUALIFIED`: only after the full frozen observation and independent
  end-to-end account/order/recovery/alert evidence have passed, with a
  separately documented operator acceptance decision. The *packet validator
  cannot award this label*.
- `LIVE_AUTHORIZED`: completely separate later human capital-risk approval,
  never derived from `PAPER_QUALIFIED`.

The present packet is **BLOCKED**; the work product is an executable
**credential-free rehearsal and human runbook**, not paper deployment.

## 7. Verify with synthetic evidence only

```bash
cd /home/quant/dev/quant/quant-research
PYTHONPATH=/home/quant/dev/trading-connector \
  .venv/bin/python -m pytest -n 0 -q tests/test_paper_qualification.py
.venv/bin/python -m ruff check \
  src/paper_qualification.py tests/test_paper_qualification.py
```

Tests use explicit synthetic approval, risk values and account IDs in private
temporary directories only. They verify the `BLOCKED` cases for absent
credentials, unapproved research, wrong environment, stale/failed preflight,
mismatched native state path, unhealthy runtime, missing risk caps and
observation criteria. The synthetic READY case **never** confers broker
permissions. No trade/order path is imported or called from this validator.
