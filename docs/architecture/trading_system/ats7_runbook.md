# ATS7 operating runbook

## Current permitted scope

The authorized operating process is synthetic LOCAL_PAPER with actual public
Bybit completed one-minute bars and native ML4T simulated execution. It has no
private account credentials. It cannot submit Demo or live orders. It is not an
economically eligible strategy or a realistic cost/funding backtest.

The release manifest and observation-policy files are immutable. A change to
strategy code, parameters, risk, connector, native dependencies, feed, account
terms, or operating source requires a new release identity and qualification.
Do not rewrite the old observation start or shorten the 28-day period.

The final deployment/evidence report under docs/audit records exact source,
commit, manifest, service, and evidence identities. Historical raw provider
archives remain in the private ATS3 state directory, outside Git.

## Runtime locations

- Worktree: /home/quant/.devspace/worktrees/quant-research-96f2e9fc
- Connector: /home/quant/.devspace/worktrees/trading-connector-d0370150
- Python: /home/quant/.devspace/worktrees/quant-research-25440f7a/.venv/bin/python
- Final local state: /home/quant/.local/state/quant-research/ats7-local/observation-v1
- Unit: ats7-local-paper@observation-v1.service
- Metrics: http://127.0.0.1:19149/metrics
- Existing Prometheus: http://127.0.0.1:19090
- Existing Grafana: http://127.0.0.1:13000/d/ml4t-native-safety
- Existing Alertmanager: http://127.0.0.1:19093

All endpoints are VPS loopback addresses. Reuse the existing access mechanism;
do not expose them publicly to view the dashboard.

## Read status

```bash
cd /home/quant/.devspace/worktrees/quant-research-96f2e9fc
export PYTHONPATH=.:/home/quant/.devspace/worktrees/trading-connector-d0370150
ATS7_PY=/home/quant/.devspace/worktrees/quant-research-25440f7a/.venv/bin/python
ATS7_RUN=/home/quant/.local/state/quant-research/ats7-local/observation-v1
systemctl --user status ats7-local-paper@observation-v1.service
"$ATS7_PY" -m scripts.ats7_paper status --run-root "$ATS7_RUN"
"$ATS7_PY" -m scripts.ats7_observation --run-root "$ATS7_RUN"
```

Status must have fresh completed bars, fresh account and reconciliation
timestamps, clean native reconciliation, zero unknown/pending orders, no
persistence errors, and the expected manifest identity. PAPER_RUNNING is an
operating state, not completed observation or trading approval.

The read-only observation assessor verifies the release sources and journal
chain, binds the start time to the first service-start event, counts actual
bars/cycles, and compares elapsed wall time with the frozen minimum. It never
issues authorization. At 28 days it requests operator review rather than
automatically approving a strategy.

Prometheus retains seven days in the existing deployment. The full observation
authority is the durable native/release journals and immutable observation
policy/start, not the dashboard retention window.

## Halt and stop

To prevent new synthetic risk while keeping the feed and metrics alive:

```bash
"$ATS7_PY" -m scripts.ats7_paper halt --run-root "$ATS7_RUN" --reason "operator incident review"
```

A control receipt is written beside the health file. Confirm the halt metric
and receipt. Do not infer a completed close from a halt or cancel request.

To stop the process:

```bash
systemctl --user stop ats7-local-paper@observation-v1.service
```

The unit's synchronous stop handshake waits for stopped.json with a zero
native return code. Confirm both that receipt and systemd Result=success;
a drill's preliminary PASS or stale health file is insufficient.
The state and both journals remain. Existing exposure is never erased by
stopping, expiry, restart, or rollback. User-service lingering and enablement
keep the selected service supervised after interactive sessions close.

## Resume

After checking the exact release, current sources, native position/cash,
pending and unknown decisions, reconciliation, and the incident evidence:

```bash
systemctl --user start ats7-local-paper@observation-v1.service
"$ATS7_PY" -m scripts.ats7_paper resume --run-root "$ATS7_RUN" --reason "operator review completed; evidence reference ..."
```

A restart with existing service history remains halted pending this separate
review. Unknown decisions cannot be cleared by resume. An external environment
would also need a fresh independent signed authorization for resume, but this
local service never constructs an external broker.

## Incident procedures

| Observation | Required response |
|---|---|
| Unknown order or interrupted DISPATCHING | Keep halt; preserve original intent, native journal, provider execution/order/account evidence; never retry blindly |
| Feed gap, future/stale bar, wrong instrument | Halt; compare original completed-bar time, receipt time and source mapping; do not substitute a timeframe |
| Account stale, failed snapshot, reconciliation conflict | Keep halt; preserve current exposure; verify the actual account owner and original records |
| Daily-loss, drawdown or exposure breach | Keep native and release latches; do not raise limits to make the run pass |
| Cancel acknowledgment or missing historical order | Treat obligation as unresolved until actual executions, open orders and positions agree |
| Source, terms, dependency or parameter drift | Stop new risk; restore exact bound bytes for rollback or qualify a new release |
| Unexpected process termination | Inspect systemd/journal; restart must remain halted and retain positions/cash |
| Notification failure | Preserve failure receipt/counters and stop claiming operational qualification; repair the authorized route before relying on it |
| Expiry | Block new exposure; keep obligations and only permit independently authorized risk-reducing recovery where applicable |

Neither a kill switch nor a reduce-only request guarantees an exit price,
liquidity, or a completed flatten during a provider outage.

## Rollback and evidence preservation

Halt and stop before copying a consistent forensic snapshot. Keep manifest,
native-risk.json, native journal and head, release.sqlite, observation files,
control receipts, original feed records, and current code/dependency hashes.
Restore exact qualified code without restoring an older trading journal over
newer effects. The release/native cross-reference check rejects a stale release
database beside newer native decisions. Never delete unknown records or adopt
pre-existing Demo exposure to obtain a clean startup.

Re-run the outside judge against immutable acceptance evidence; it does not
import a broker or submit orders. Re-priced fill evidence must fail against the
native cash authority.

## Reproduce engineering acceptance

```bash
"$ATS7_PY" -m scripts.ats7_acceptance
XDG_RUNTIME_DIR=/run/user/1001 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1001/bus \
  "$ATS7_PY" -m scripts.ats7_regression --detach
```

The regression runner preserves the required user-scope environment for ATS2
tests, uses the isolated connector, and writes its command/source plan before
execution. Inspect original JUnit/log/results, not only a launcher exit code.

The service drill is allowed only on a dedicated drill-* instance. It kills
that synthetic process, verifies restart with retained exposure and halt,
issues a separate local resume, observes the native close, then proves manual
halt across two completed public bars, and checks native and systemd terminal
success. It waits for the first health snapshot during startup. It never
touches the final observation instance or any provider account.

## Monitoring activation boundary

The existing dashboard includes ATS7 panels and Prometheus scrapes the new
loopback endpoint. ATS7 metric names are separated from historical ATS3 alert
expressions. Generic notification delivery has been verified through the
existing Telegram bot/chat and the existing Alertmanager receiver.

Project-status alert rules are reviewed in ops/ats7-alerts-staged.yml but are
not loaded. Automatic approval review rejected sending project status without
an explicit conversation authorization for that payload/destination. Activation
therefore requires approval to send the listed ATS7 service/halt/reconciliation,
feed/persistence, and observation-review statuses to the established operator
chat. No provider balance, credential, or detailed position payload is needed.

## External Demo and live gates

No new Demo order can be submitted under this observation service. A subsequent
Demo qualification needs exact account/strategy/risk/action/expiry authorization,
independent qualification evidence, separately owned trust provisioning, and
controlled actual execution/reconciliation tests. Historical ATS3 permission or
an ATS6 synthetic grant is not a substitute.

Live remains blocked by absent eligible strategy, absent completed qualified
paper observation, absent provider execution qualification, absent independent
live authorization, and the current runtime's unqualified live-provider gate.
This mission authorizes no live canary.
