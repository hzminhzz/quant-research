# ATS7 qualification — 2026-10-17

## Verdict and scope

ATS7's release boundary and native synthetic local execution are qualified
within the engineering scope below. ATS7 is not an approved strategy release,
completed paper observation, qualified new provider-execution campaign, or live
deployment. No external Demo or live orders were submitted or cancelled.

| Dimension | Outcome | Evidence and remaining gate |
|---|---|---|
| Engineering | QUALIFIED, scoped | Immutable release contract, durable identity, native risk, adversarial tests, independent local accounting, sandbox and supervised service drills |
| Provider capabilities | PARTIALLY_QUALIFIED | Official semantics, authenticated read-only Demo identity/product/account observations and original broker-event economic replay; fresh external execution cases remain blocked |
| Paper execution | PARTIALLY_QUALIFIED | Actual native LOCAL_PAPER lifecycle and public-feed operation pass; Provider Demo execution lacks release-specific authorization |
| Strategy-release eligibility | BLOCKED | No sufficiently qualified compatible research candidate; historical Donchian daily research is not the recreated 1-minute Demo rule |
| Operational observation | RUNNING — PAPER_RUNNING | Separate durable synthetic process started 2026-10-17 06:38:25.888122 UTC; earliest elapsed completion 2026-11-14 06:38:25.888122 UTC; all acceptance/review gates still apply |
| Live release authorization | BLOCKED | No live authorization, no qualified strategy/provider campaign/completed observation; live provider execution is explicitly unavailable in this release |

The final deployment identity and initial observation assessment are recorded
in the adjacent evidence JSON and immutable runtime receipts. RUNNING means an
operating synthetic observation process, never an elapsed four-week result.

## Frozen running observation

Release identity:
4beaef6050c75925cb0e07bf1a7e8076f28060f7eef01bd830b19828cf3bc0c0.

The separate observation-v1 instance started at
2026-10-17T06:38:25.888122+00:00. Its earliest 28-day completion is
2026-11-14T06:38:25.888122+00:00. The frozen manifest binds eleven immutable
qualification artifacts, including final regression, native accounting,
service recovery/shutdown, sandbox and generic notification evidence.

The user systemd unit is enabled, active and running with lingering enabled;
it remains supervised after this interactive session ends. The initial
read-only assessor returned PAPER_RUNNING with fresh health, zero unknown
orders and zero service failures. Subsequent initial activity and exact
artifact hashes are recorded in the adjacent evidence JSON. The main Git
commit is recorded in the post-commit run_log/ats7/deployment.json receipt,
which avoids a self-referential commit hash inside its own committed report.

The final drill instance is stopped. Earlier replay/drill time does not count
toward this separate observation. No elapsed-period or economic qualification
is inferred from an initial healthy process.

## Starting authority and preservation

The implementation branch starts from the independently verified ATS6 commit
10426fcf227869aa5bfc1e07e8fc8337166e9cf7, not a divergent primary or remote head.
All 211 original ATS6 artifact hashes matched and all 31 committed SQLite
databases passed integrity checks. ATS6 remains SYNTHETIC_SHADOW only.

Primary and connector worktrees and their unrelated dirty changes were
preserved. The connector fix is isolated at
ad982e6d644f524626ede3fe7379a8262f6b945f on
fix/ats7-bybit-order-boundary, based on
6175a948e6d253ba6f4b610b97b34d8433662e77. Nothing was pushed.

No new strategy search, parameter optimization, protected-data read, account
capital change, leverage change, evaluation purchase, live canary, or adoption
of an unrelated position was performed. No work was delegated to another agent.

## Reproducible evidence

| Proof | Original artifact |
|---|---|
| Full final regression | run_log/ats7/regressions/20261017T062913-712578ae/ |
| Final targeted ATS7 checks | run_log/ats7/attempt_007.xml |
| Connector checks | run_log/ats7/connector-final.txt |
| Native lifecycle and outside judge | run_log/ats7/acceptance/20261017T062923-ba118881/ |
| Process-death, retained exposure, resume, manual halt | run_log/ats7/service-drill-v2/ |
| Public-feed cycle with current reconciliation | run_log/ats7/service-observation-v3.json |
| Planned stop/restart latch | run_log/ats7/clean-restart-v4.json |
| Native graceful shutdown handshake | run_log/ats7/graceful-stop-v5.json |
| Preserved failed shutdown and countercheck | run_log/ats7/service-drill-v6/ and service-drill-v6-finalcheck.json |
| Preserved startup-wait harness failure | run_log/ats7/service-drill-v7/ |
| Final process-death/halt/shutdown replay | run_log/ats7/service-drill-v7-retry/ |
| Final source and artifact verification | run_log/ats7/final-source-verification.json and final-native-artifact-verification.json |
| Sandbox credential visibility | run_log/ats7/sandbox-final.json |
| Verified recipient and generic Telegram receipt | run_log/ats7/notification-recipient.json and notification-generic-delivery.json |
| Existing Alertmanager delivery path | run_log/ats7/alertmanager-generic-delivery.json |
| Private provider archive | /home/quant/.local/state/quant-research/ats3/ats7-readonly-20261017-v1 |
| Fresh private capability capture | /home/quant/.local/state/quant-research/ats3/ats7-capabilities-20261017-final |

Full regression: 489 passed, one optional real-store integration skip
(test_dual_mode_real_store requires an explicit 2025 BTC/ETH canonical build). Managed-feature
policy, managed-source lint, task-source lint and whitespace checks passed.
The final targeted ATS7 suite passed all 54 cases. All 67 Bybit tests passed.
These suite counts overlap; they are not summed as distinct test cases.
Existing dependency deprecation/mock warnings were retained.

All production/runtime and test source hashes match the final full regression
plan. The dedicated drill runner alone subsequently gained an initial-health
wait; the final actual service drill executes that change and task lint passed
after the change. The original regression source plan remains immutable.

The local lifecycle contains four actual native simulated fills and two closed
cycles. An outside-process Decimal calculation and ATS3 projection agree with
native terminal cash to the declared tolerance, with no remaining positions or
pending local orders. The terminal simulator cash is 100000.20000000001 versus
independent exact arithmetic 100000.2000. These are synthetic engineering
units, not economic performance evidence.

Both original committed opening intents were replayed into the actual ATS6
router through a separately signed SYNTHETIC_SHADOW fixture. Direction and
quantity matched. The explicit instrument/clock mapping is recorded in
shadow-comparison.json. This does not assert provider fill-price parity,
executable ATS6 reduction support, or conversion of a shadow grant to authority.

## Failure and recovery coverage

Final verification rejected the v6 drill's preliminary PASS: systemd and the
native terminal receipt showed LifecycleCountError and return code 1. Skipping
halted business callbacks had also skipped native lifecycle bookkeeping.
The repair delegates callback suppression through native dispatch, preserves
its counts and worker ownership, and adds two regression cases. The replayed
journal case failed before the repair; all 54 ATS7 tests pass afterward.
The drill now requires native return code 0 and systemd Result=success.

The first v7 runner also failed before reading its first health file, while
the service itself was healthy. A bounded startup wait repairs that harness
race. Both failed attempts and the successful final replay are retained;
neither failed attempt is counted as qualification evidence.

| Requirement | Exercised authority and result |
|---|---|
| Duplicate submission and changed payload | ATS7 durable decision journal and Bybit client-key staging reject retransmission before effects |
| Duplicate fills and event reordering | ATS3 original-event replay and ATS6 regression fixtures deduplicate exact evidence and reject conflicts |
| Lost acknowledgment, task cancellation, post-ack snapshot failure | Connector/native audit tests preserve UNKNOWN and known provider IDs |
| Partial execution, cancellation races, late fills | ATS3/ATS6 deterministic event tests and connector pending-state test pass; fresh provider execution is unqualified |
| Death before commit, after admission, after native fill | Real child-process exits and restart tests preserve committed uncertainty and native exposure |
| System process termination | Actual systemd SIGKILL drill restarts halted with retained simulated position and cash |
| Stale local journal and conflicting state | Native/release cross-reference and projection-integrity tests fail closed |
| Restart with exposure and separate resume | Actual native service drill preserves exposure; reviewed resume completes the native close |
| Exposure, order, loss, drawdown and concurrent intents | Native SafeBroker limits and frozen-risk mutation tests pass |
| Insufficient/stale account evidence | Failed/empty snapshot and no-margin cases refuse new effects |
| Changed account terms and rollback | Changed source halts; restoring original bytes still requires a separate resume |
| Authorization expiry/revocation/scope | Ed25519 scope, role, key, risk, environment, time and nonce tests fail closed |
| Stale/future/duplicate bars and wrong mapping | Native/connector/ATS7 data guards reject unsafe inputs; exact duplicate delivery cannot repeat an effect |
| Manual and automatic halt | Native and release latches survive restart; real manual halt spans two completed public bars with no new risk |
| Protective reduction | Verified native reduction cannot cross exposure; connector receives stable identity and reduceOnly; fresh external reduction remains unqualified |
| Failed notification | A transport failure creates no delivery receipt; genuine generic delivery separately verified |
| Rollback | Exact sources may be restored; stale journals and unknown exposure cannot be overwritten or cleared to resume |

No request-timeout, HTTP acknowledgment, cancellation acknowledgment, missing
order-history row, or green dashboard was treated as proof of a provider fill
or completed flatten.

## Provider qualification and limits

Authenticated read-only capture confirmed the intended Demo environment and
account fingerprint, a retained pre-existing position, and no open orders.
Private REST is api-demo.bybit.com. No Testnet/Mainnet substitution occurred.
The paired time capture had a 0.266-second round trip and a 0.050-second
server-minus-local midpoint offset, within the five-second release bound.

Observed public BTCUSDT linear-perpetual specifications included 0.001 BTC
quantity increments/minimum quantity, 0.10 USDT price ticks, 5 USDT minimum
notional, and 480-minute funding intervals. The observed maximum venue leverage
is a product capability, not an approved operating leverage or risk limit.

The independent ATS3 judge reconciled four actual trade fills, six funding
events, order records, transaction cash flows, commissions, retained position
and provider collateral valuation arithmetic. The source archive manifest hash
is 5bed3c30876416f627aa333bbb8b79d9adb4483a5fc6ec9b4fd4991cc91bb11a.
Sensitive original account records remain outside Git.

This is an economic replay result, not a new complete ATS3/ATS7 intent-to-order
qualification. The current archive alone does not reconcile every historical
intent disposition. The audit credential is execution-capable; the historical
ATS3 read-only-key exception is not silently promoted into a new least-privilege
release approval.

The correctly parameterized Demo fee-rate request returned retCode 10001.
That endpoint is not listed in the Demo supported-API table. Its current
capability remains unqualified. Actual historical execution fees were
independently reconciled rather than replaced with an assumed current rate.

Official contracts used:

- Demo identity, endpoints, API subset and seven-day retention:
  https://bybit-exchange.github.io/docs/v5/demo
- Asynchronous order acknowledgment, IOC market behavior, reduce-only,
  position index and client-order identity:
  https://bybit-exchange.github.io/docs/v5/order/create-order
- Duplicate Filled messages in a cancellation race:
  https://bybit-exchange.github.io/docs/v5/websocket/private/order
- Execution identifiers and fee observations:
  https://bybit-exchange.github.io/docs/v5/websocket/private/execution
- Delayed/incomplete historical-order visibility:
  https://bybit-exchange.github.io/docs/v5/order/order-list
- Product increments and leverage filters:
  https://bybit-exchange.github.io/docs/v5/market/instrument
- Fee-rate request parameters:
  https://bybit-exchange.github.io/docs/v5/account/fee-rate

The connector preserves uncertainty rather than claiming unlimited exactly-once
provider execution. Controlled fresh Demo partial fills, cancel/late-fill races,
reconnects with pending orders, and protective exits need explicit
release-specific Demo authorization and real observations.

## Operations, notifications, and outstanding gates

The existing Prometheus and Grafana deployment is reused. ATS7's loopback
metrics show runtime state, data age, account/reconciliation freshness,
pending/unknown orders, exposure, failures and halt status. Native metric
names are relabelled for ATS7 to avoid unintentionally activating historical
ATS3 alert expressions. The existing dashboard contains the ATS7 row.

Generic notification delivery was accepted by Telegram to the verified
established private operator chat. The existing Alertmanager's Telegram
notification count increased with no increase in failures. Bot API acceptance
does not prove that a human read the message.

Automatic approval review rejected sending project-status content without an
explicit conversation authorization for that payload and destination. The
project-status rules in ops/ats7-alerts-staged.yml remain staged. Their
activation is a concrete remaining approval gate; the generic delivery test
does not override it.

At least 28 real elapsed days, required activity/coverage, source stability,
incident review and an independent qualification decision remain necessary.
Synthetic observation cannot supply missing research eligibility, realistic
funding/cost evidence, provider execution qualification or live authorization.

See the [release boundary](../architecture/trading_system/ats7_release_boundary.md)
and [operating/incident runbook](../architecture/trading_system/ats7_runbook.md).
