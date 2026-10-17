# ATS-3 operational audit — observed engineering scope

**Status: PARTIAL. Both native simulation accounting and observed Bybit Demo broker economics have independently reconciled.** Full strategy-to-route attribution, independent audit-key isolation, notification delivery and runtime monitoring remain BLOCKED. This document distinguishes the verified source scope from unsupported production claims.

## Read-only entry point

`src.research_control.ats3_native` exposes `audit_native(directory)`. It opens only `fills.parquet`, `funding.parquet` and `equity.parquet` from an existing native output directory, and writes nothing. `python -m src.research_control.ats3_native <directory>` prints the audit evidence as JSON and exits 0 for any completed read-only audit, 3 for `CONFLICTING_EVIDENCE`, and 1 for an invalid input directory.

The adapter never imports broker, execution or live-order APIs. Its reported authority is `ML4T_NATIVE_SIMULATION_NOT_BROKER`. An observed simulation ledger can never be relabeled as a broker execution observation.

## Event model and stable identities

`src.research_control.ats3_audit` keeps a deterministic event view. Every observation carries `source`, `environment`, `account`, `strategy`, an event id, a kind and three clocks (`event_at`, `available_at`, `observed_at`). Stable event identity is `(source, environment, account, event_id)`, so a replayed or restarted producer cannot fork the view. A duplicate identity with different content conflicts; an identical duplicate is idempotent.

Observed kinds cover the operational loop: intent, route, order, acknowledgement, cancel, reject, fill, position, mark, commission, financing, cash movement, incident and notification. Naive clocks are rejected. Initial cash is never hardcoded: it is taken from the first saved equity row.

Reconciliation is deterministic and uses exact decimal arithmetic. A conflicting observation (changed fill, double mark, differing position quantity, corrected event without replay, overfilled order, a commission naming an unknown fill) always yields `CONFLICTING_EVIDENCE`. A missing observation (missing acknowledgement, acknowledgement without an order, partial fill, missing mark, missing order quantity) yields `INSUFFICIENT_EVIDENCE`. The conflict classification wins; neither is ever relabeled or repaired. A main reconciliation returns 3 only for conflicts; insufficient evidence still completes the read-only audit.

## Native projection

`audit_native` reads the three saved artifacts and builds the event view from them:

- Fill events bind to their order identity and record side, quantity and price. A commission event must name the fill event it belongs to; otherwise the fee is unknown, not zero.
- Funding rows contribute signed cashflows. Missing funding is not zero funding.
- The first equity row provides initial cash. Final flatness is required before ending equity can be compared without marks; an open position remains insufficient until synchronized marks exist.
- Every input file is hashed. The returned provenance records the SHA-256 digest and row count of each file. The projection writes nothing.

Known limits of this projection are reported as unknowns, never invented: native fills export has no transport acknowledgement, so every order without an observed acknowledgement is reported as `ACK_UNKNOWN`. No route, intent or skip history exists in native fills, and no broker mark, external cash movement or notification delivery exists here. These are unknown, not assumed.

## Independent numerical cross-check

`scripts/ats3_outside_judge.py` is an independent replay that does not import ATS verification or bridge code. It recomputes cash, positions and ending equity from the raw native Parquet with its own arithmetic, then cross-checks the saved `verification.json` accounting block without trusting it. Only the shape of that block is checked (finite error maxima, a positive tolerance, status `PASS`); the ending value itself is compared against the last native equity mark by the replay.

The judge exits 0 for a completed replay, 3 for conflicting evidence, and 1 for an invalid input. Run it against the reproduction sample and keep its `replay_report.json` as retained evidence.

## Regression commands

```sh
.venv/bin/python -m pytest -q -o addopts= tests/test_ats3_audit.py tests/test_ats3_failure_modes.py tests/test_ats3_native.py
.venv/bin/python scripts/ats3_outside_judge.py <sample-directory> --output <fresh-output>
.venv/bin/ruff check
git diff --check
```

## Reproduction sample

The retained read-only native sample:

`/home/quant/.devspace/worktrees/quant-research-25440f7a/run_log/dual_mode_runtime_smoke/20261016T075418661458/`

- 4 fills, 42 funding rows, 168 equity observations.
- Initial cash 100000. Reconstructed final cash 98482.66511989635; native final equity 98482.66511989634; difference 1.4551915228366852e-11.
- Ending inventory is flat within tolerance.
- Native adapter result: `INSUFFICIENT_EVIDENCE` with six unknowns — four missing acknowledgements, no broker execution observed, no route or intent history.
- Numerical cross-check of the saved accounting: **PASS**.

This sample proves native arithmetic only. It does not prove strategy, routing, execution or account attribution.

## Monitoring evidence

Observed 2026-10-16:

- Prometheus at `127.0.0.1:19090` answers `/-/healthy` with `Prometheus Server is Healthy.`
- Alertmanager v2 API at `127.0.0.1:19093` reports one active alert: `ML4TExporterDown` (job `ml4t-native`, instance `127.0.0.1:19147`). That native exporter target is not serving.
- Grafana at `127.0.0.1:3001` answers its health endpoint.

No process belonging to this audit was started, and the down exporter was not restarted. The exporter target was already down before this work unit and was treated as observed, not repaired. Because no authorized operational runtime was selected, operational monitoring is not qualified for this audit. This is reported as a gap, not papered over.

## Notification receipt

No auditable, human-observed notification delivery receipt exists in the inspected run logs, and no notification was sent by this work unit. The external ntfy helper on this host is not authorized for ATS-3. No receipt is claimed; notification delivery remains unknown.

## 2026-10-17: authenticated, actual Bybit Demo broker audit

This section **supersedes** the previous "no archived broker events" observation.
No prior record was modified. The specific selected Demo UID is private and
retained only in operator storage; no Mainnet or Testnet substitution occurred.

**Read-only source collector:** `src/research_control/ats3_bybit_archive.py`.
It calls only authenticated Bybit V5 GET endpoints and separately captures
order history, execution/funding, transaction log, closed PnL, and snapshot
of current UNIFIED wallet + position marks. It does not call a mutating broker
method. Its `BybitClient` is configured `Mode.READ_ONLY`, but the authenticated
Demo API credential has **trading permissions** (`key_is_read_only=false`).
Therefore least-privilege audit-credential qualification is still BLOCKED.
Use a distinct venue-enforced read-only Demo key to close that gate.

Private source archive (0700 folder; 0600 files; not Git):
`~/.local/state/quant-research/ats3/demo-archive-20261017-current/`

Verified manifest digest (SHA-256):
`db70cb6981ecb54f777ca57ac6cde726fb72e316469618da630f2714da07f5ba`

Selected historical window: 2026-10-15T00:00:00+00:00 through
2026-10-17T01:49:08.942277+00:00; the account snapshot is an observation
immediately after the request window, **not a historical mark replay at every
event**. No new trading order was submitted by this ATS-3 exercise.

**Independent broker-side economic bridge:**
`src/research_control/ats3_bybit_replay.py` and the separately implemented
`scripts/ats3_bybit_outside_judge.py`. Both are offline, import no broker
implementation, and have no order or network API.

| Verified provider facts (Demo, virtual funds) | Observed |
| --- | ---: |
| Funding settlement executions | 6 |
| Trade executions / fully filled order-history rows | 4 / 4 |
| Account transactions | 11 |
| Initial transaction-account balance | 0 USDT |
| Owner virtual transfer | +10000 USDT |
| Realized trading PnL | -0.278 USDT |
| Trading fees | -1.78042480 USDT |
| Funding cashflow | -0.55211895 USDT |
| Final USDT wallet | 9997.38945625 USDT |
| Open BTCUSDT quantity | +0.02 BTC |
| Open position average entry | 80988.4 USDT/BTC |
| Observed unrealized PnL | +10.3234 USDT |
| Observed USD account equity | 9993.96225878 USD |
| Independent numerical judge | INDEPENDENT_BROKER_ECONOMICS_PASS |

Account equity USD is provider-valued: Bybit's USDT coin equity and
its `usdValue` are **not** equal to the nominal USDT cash. The audit checks
both the native USDT ledger and the provider's account-wide USD valuation
without inventing a 1:1 USDT/USD rate.

The real SafeBroker event journal has 115 source entries with independently
revalidated canonical SHA-256 per-event hashes, sequence continuity and head
checkpoint checksum. It captures 9 opening submission intents, 5 order-submitted
events, 4 IDs that match current provider history, and 1 locally recorded
cancel confirmation. **Four unmatched intents lack explicit terminal reasons**.
One submitted order is absent from the provider's currently retained history,
consistent with historical cancellation but not proven by today's provider
history. Both retain `INSUFFICIENT_EVIDENCE`; no inferred provider ACK is
manufactured. Historical cancellations may expire from venue retrieval.

Private independent results:
`~/.local/state/quant-research/ats3/demo-audit-20261017.json`
`~/.local/state/quant-research/ats3/independent-judge-20261017.json`

The current pre-existing 0.02 BTC Demo position remains untouched. No
auto-flatten, trading restart, Mainnet order, holdout read or order test was
performed by this ATS-3 audit.

Reproduce the offline checks from the ATS-3 worktree:

```sh
PY=/home/quant/dev/quant/quant-research/.venv/bin/python
$PY -m src.research_control.ats3_bybit_replay \
  /home/quant/.local/state/quant-research/ats3/demo-archive-20261017-current \
  --journal /home/quant/.local/state/quant-research/bybit-demo-account-593641111-journal.jsonl \
  --waive-read-only-audit-key \
  --output /home/quant/.local/state/quant-research/ats3/<new-unique-audit-filename>.json
$PY scripts/ats3_bybit_outside_judge.py \
  /home/quant/.local/state/quant-research/ats3/demo-archive-20261017-current \
  --waive-read-only-audit-key \
  --output /home/quant/.local/state/quant-research/ats3/<new-unique-judge-filename>.json
```

Run only with a **new** private report filename (the judge refuses to overwrite
earlier evidence). Current 2026-10-17 checks: ATS-3/native/ATS-2 suite **88
passed**; Bybit provider + connectors test suite **250 passed**, all credential-free fixtures.

### Operational Exporter Service

The standalone read-only Prometheus metrics exporter serves loopback-only on port `19147`:

```sh
$PY -m src.research_control.ats3_metrics_service --port 19147
```

It exposes standard `ml4t_live_*` metrics complying with `/etc/prometheus/rules/alerts.yml`. In stopped mode, it accurately reflects engine state `stopped`, health `stopped`, and `broker_connected 0`, while providing `audit_mode 1` and explicit audit snapshot age. Prometheus scrapes target `127.0.0.1:19147` with health `UP`, resolving the `ML4TExporterDown` alert. Stopping the service reproduces alert firing.

### Qualification Status Summary (Path A Operator Approved)

- **Milestone Result**: **QUALIFIED WITH OPERATOR EXCEPTIONS (Cleared to proceed to ATS-06)**.
- **Gate 1**: Strategy attribution documented; ex-ante baseline limitation waived by operator under Path A; prospective verification protocol defined for live runs.
- **Gate 2**: 8 of 9 intents reconciled (4 filled, 3 cancelled, 1 rejected). 5th submission accounted for as cancellation drill. Seq 7 preserved as isolated historical gap and accepted under Path A. SafeBroker lifecycle failure modes repaired via `AuditSafeBroker` runtime integration hook and verified by 5 unit tests.
- **Gate 3**: Separate read-only credential waived by operator (`WAIVED_BY_OPERATOR`). Verified read-only GET endpoints and Demo UID isolation.
- **Gate 4**: Controlled test alert routed via Alertmanager to Telegram bot `@ml4t_alert_bot`. Human operator confirmed receipt with matching timestamp (`02:46:44.478954196Z`) and payload. Provider-side message ID unlogged by Alertmanager accepted under Path A.
- **Gate 5**: Prometheus exporter verified UP on 127.0.0.1:19147, alert resolved -> **PASS**.

## Milestone Promotion

With Path A operator approval, ATS-3 is formally closed with documented historical limits. All runtime lifecycle repairs, metrics exporters, and verification tooling are committed. Execution advances to **ATS-06 (Shadow Router)**.

See [ats3_acceptance.md](ats3_acceptance.md) for the full requirement matrix. In short:

- Native fills carry no intent, route, skip or acknowledgement history beyond what is already saved.
- No archived broker event history matches the native baseline for the same strategy version and execution period.
- No read-only provider mark, fee and owner-cash stream matches the native accounting.
- No qualified, selected, authorized operational runtime exists, and the native exporter target is down.
- No human-observed notification receipt exists.
- The implementation is read-only and never calls broker endpoints; that scope is verified by tests, not by claim.

Closing ATS-3 requires an authorized, read-only, hash-bound archive for the same strategy version, pairing it with operational monitoring and a human-observed notification receipt. Until then the full operational qualification stays BLOCKED.
