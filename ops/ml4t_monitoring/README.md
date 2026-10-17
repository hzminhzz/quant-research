# ML4T native read-only observability — issue #47

**Status (2026-10-15): credential-free local monitoring artifacts are verified.
Actual Prometheus/Grafana scrape and alert delivery are BLOCKED / UNVERIFIED.**
Neither this issue nor its implementation grants Demo or Mainnet order permission.

## What exists

- `src/ml4t_native_metrics.py` reads only **installed native ML4T 0.1.2**
  `LiveEngine.runtime_status()`, `LiveEngine.operational_events`,
  `SafeBroker.persistence_status`, `SafeBroker.reconciliation_report`,
  plus the **existing** local native JSONL audit journal (read-only).
- A bounded, local Prometheus text projection with fixed state/health/event
  label vocabularies. No broker account IDs, symbols, order IDs, user-defined
  labels, journal payloads, credentials or exception text are emitted.
- A lightweight **loopback-only** `GET /metrics` endpoint. Other GET routes
  return 404; POST requests return 405. It has no order/control endpoints.
  Importing the module creates no background worker, scheduler, connection or
  trading process. The caller owns the HTTP server lifecycle.
- Grafana import JSON in `grafana/native_safety_dashboard.json`.
- Alert rules in `prometheus/alerts.yml` covering feed silence, broker
  disconnection, bounded-recovery exhaustion, reconciliation missing/mismatch,
  persistence and audit failures, unverified identity, exporter outage and
  VPS CPU/RAM/disk stress, with an operator action per rule.
- An example scrape file in `prometheus/prometheus.example.yml`.
  **This is an uninstalled template.** Alertmanager receiver and Prometheus
  datasource must be configured by an authorized operator.

**Account safety:** Do not install a second risk owner or create an order
journal. The metrics projection never touches `submit_order_async`,
`cancel_order_async`, `close_position_async`, `connect()`, or native
kill-switch controls. Native `SafeBroker` remains the risk authority.

## Integration boundary (only after separately approved paper deployment)

Attach the projection to the *existing* single-owner process; never start a
new `LiveEngine` just to collect metrics. After the account preflight and
separate paper authorization, the existing process can create the endpoint:

```python
# The following is an integration pattern, NOT a standalone trading launcher.
from threading import Thread
from src.ml4t_native_metrics import create_readonly_metrics_server

# Existing authorized engine owns the broker and risk (not created here).
metrics_server = create_readonly_metrics_server(
    engine, engine.broker, port=19147,
)
metrics_thread = Thread(target=metrics_server.serve_forever, daemon=True)
metrics_thread.start()
# On the *existing* engine's shutdown/cleanup path:
# metrics_server.shutdown()
# metrics_server.server_close()
# metrics_thread.join()
```

Exporter binds **127.0.0.1:19147**. Use host-network Prometheus or a private
network reachability method; a default isolated Docker network cannot scrape
the host loopback. Do not expose the exporter, Prometheus, Alertmanager or
Grafana openly to the internet. The dashboard must use a read-only
Prometheus datasource; metric endpoints contain operational information.

## VPS availability inspection (2026-10-15)

- No active Prometheus, Grafana or Alertmanager was detected via systemd,
  process inspection or Docker container listing. **No scrape or alert
  delivery was executed**.
- Port **9100 is already owned by `panda-node`**, not `node_exporter`;
  requesting `http://127.0.0.1:9100/metrics` returned 404.
  **Do not rebind or kill this unrelated process.**
- The host exporter example therefore reserves **127.0.0.1:19148** for a
  future independently managed `node_exporter`. Verify availability and
  permission before any deployment. Do not claim host metrics exist merely
  because the sample scrape config references them.
- No Alertmanager receiver/notification destination is configured or verified
  for this issue. Test-alert delivery is **BLOCKED**, not PASS.

After operator authorization to deploy monitoring, install or locate an
approved Grafana/Prometheus stack, configure one verified local scrape on
`127.0.0.1:19147`, configure node_exporter at a non-conflicting private
port, import the dashboard and the Prometheus rules, and test an approved
Alertmanager receiver. Independently capture:

1. Prometheus `/api/v1/targets` showing both jobs UP and timestamps.
2. `promtool check rules ...` success and a real rule evaluation.
3. Grafana datasource/dash panels matching metric samples from a running,
   authorized paper process.
4. One harmless synthetic **Alertmanager** test alert and independent receiver
   receipt with time/recipient evidence. Do **not** simulate trading actions
   to trigger an alert; never route monitoring back into order control.

Only mark the actual VPS scrape and notification criteria PASS after evidence
from those services. If any receiver/credential/service is missing, remain
BLOCKED. Do not install monitoring agents blindly on an existing production VPS.

## Metric semantics and limitations

- `ml4t_live_engine_state{state=...}` and
  `ml4t_live_engine_health{health=...}`: **fixed** one-hot enumerations.
  States include `ready`, `running`, `degraded`, `recovering`,
  and `failed`; health distinguishes `waiting_for_data`,
  `idle_market_closed`, `feed_silent`, and `broker_disconnected`.
- `ml4t_live_broker_connected` only exists when native connectivity is known;
  `broker_connection_known=0` means unknown, **not** connected.
- Last-bar **wall-clock age** is produced by native
  `runtime_status()` on scrape; never treat an old event timestamp as a
  fresh observation. Also export the configured feed-silence threshold.
- Native continuity counts and retry/exhaustion state come from the engine,
  not an independent feed tracker.
- `reconciliation_known=0` means **unknown**; do not emit
  `reconciliation_clean=1` without native evidence.
- `state_error`/`journal_error` and
  `audit_evidence_available` distinguish healthy/missing evidence.
  The audit reader uses at most 1 MiB of the **existing JSONL audit file**.
  If unavailable, incomplete or larger than that bound, it emits
  `audit_evidence_available=0` and **omits** outcome gauges. Never interpret
  omitted outcomes as zero activity or PASS.
- `audit_event_count{event=...}` counts a fixed whitelist of **native**
  audit records. `audit_paper_filled_count` recognizes a native
  `order_submitted` event whose verified provider status is `filled`.
  These are file-snapshot *gauges*, not forever-monotonic counters; do not
  use `rate()` or assume full fill histories after journal retention/rotation.
- A native risk-limit rejection can throw before `record_event()` is called.
  **The installed 0.1.2 public hooks do not expose a reliable risk-rejection
  count.** Do not invent it or equate a broker `order_rejected` with a native
  risk denial. Monitoring of such errors requires a separate upstream hook
  or a later narrowly reviewed extension, not a replacement risk engine.
- `configured_kill_switch` reports the public config flag only; it is
  not a claim to reconstruct every persisted native kill-switch state.
- `up{job="ml4t-native"}==0` alerts when exporter/process is lost.
  Monitoring does not restart the execution engine.
- Host CPU/RAM/disk panels and alert rules consume **standard** node_exporter
  metrics. No bespoke host agent or trading PnL store is included.

## Tests

```bash
cd /home/quant/dev/quant/quant-research
PYTHONPATH=/home/quant/dev/trading-connector \
  .venv/bin/python -m pytest -n 0 -q \
  tests/test_ml4t_native_metrics.py
.venv/bin/python -m ruff check \
  src/ml4t_native_metrics.py tests/test_ml4t_native_metrics.py
```

**VPS verification (2026-10-15):** Combined Bybit + recovery + monitoring
regression: **117 passed, 5 non-failing warnings**. Ruff clean, Python
compilation passed, and a Prometheus exposition parser accepted **37 metric
families / 37 samples** in an independent sample. The synthetic HTTP server
responds to GET /metrics and rejects POST. These checks are not evidence of
actual Grafana datasource import, Prometheus scrape, PromQL rule evaluation
or received alert.

Tests use fixed synthetic status transitions, a **real installed ML4T**
engine with a synthetic Bybit client, a synthetic JSONL native-audit sample,
local HTTP GET/POST, redaction, fixed labels, and dashboard/rule shape checks.
No broker mutation method is invoked. Rule YAML is structurally parsed with
PyYAML, but an actual Prometheus `promtool` evaluation is **not verified**
on this VPS (binary not found). This fact and alert delivery must remain
explicit qualification gaps.

Related: `docs/bybit_demo_preflight.md`, `docs/bybit_paper_runtime.md`,
`docs/bybit_native_recovery.md`, and spec
<https://github.com/hzminhzz/quant-research/issues/43>.
