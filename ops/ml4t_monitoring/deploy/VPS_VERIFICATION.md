# VPS verification record — 2026-10-15 (issue #47 canonical; #49 duplicate)

Deployment source: `ops/ml4t_monitoring/deploy/compose.yml`, using only four
isolated Docker containers named `ml4t-prometheus`, `ml4t-grafana`,
`ml4t-alertmanager`, and `ml4t-node-exporter`. Existing Docker workloads
and the unrelated process on port 9100 were left unchanged.

All monitoring interfaces listen on **localhost**:
Prometheus `127.0.0.1:19090`, Grafana `127.0.0.1:13000`,
Alertmanager `127.0.0.1:19093`, node-exporter
`127.0.0.1:19148`. Prometheus is configured to scrape
`127.0.0.1:19147` **only after** an independently approved native ML4T
paper process starts its existing read-only metrics endpoint. This deployment
does **not** start a paper strategy or risk-owner process.

Verified by live VPS HTTP and CLI evidence:

- Four monitoring containers started and running.
- Prometheus `/-/ready`: **200**; Grafana `/api/health`: **200**;
  Alertmanager `/-/ready`: **200**; node-exporter `/metrics`: **200**.
- Prometheus `/api/v1/rules` loaded **14** alert rules in two groups.
  Prometheus `promtool check rules` and `check config`: **SUCCESS**.
- Prometheus `/api/v1/targets`: `ml4t-vps-node=UP`,
  `ml4t-native=DOWN` (expected: no authorized runtime on port 19147).
- Grafana `/api/search`: imported dashboard
  `ml4t-native-safety`, title *ML4T Native Live — Safety & VPS*.
  Grafana `/api/datasources/uid/ml4t-prometheus`: Prometheus datasource
  configured at `http://127.0.0.1:19090`.
- Synthetic **information-only** alert posted to the local Alertmanager
  `/api/v2/alerts`; `ML4TReadOnlyNotificationTransportTest` appeared
  `active` on its readback API. This proves local Alertmanager *ingestion*,
  **not delivered human notification**.
- The configured receiver `unconfigured_local_only` has no delivery
  integration. **Human delivery is BLOCKED** pending approved destination
  (email/Telegram/Slack/etc.) and independently observed receipt.
- Grafana uses loopback-only access and anonymous **Viewer** role, no
  initial admin account, dashboard/datasource provisioning is read-only.
  Use a secure operator SSH tunnel rather than exposing ports publicly.
- No dedicated Bybit Demo credential environment variables were found in the
  invoking VPS session. #44 authenticated read-only preflight is BLOCKED.
  Do not substitute Mainnet keys or create an order-capable runtime.

Local management:

```bash
docker compose -f ops/ml4t_monitoring/deploy/compose.yml ps
curl -s http://127.0.0.1:19090/api/v1/targets
curl -s http://127.0.0.1:13000/api/health
# Only when deliberately removing this issue's monitoring containers:
# docker compose -f ops/ml4t_monitoring/deploy/compose.yml down
```

The deployment is bounded with a 7-day/1GB Prometheus TSDB, avoids the
occupied port 9100, and does not install or edit unrelated host services.
The canonical GitHub monitoring issue stays **OPEN** until a verified
ML4T-native scrape and human alert delivery are independently confirmed.
