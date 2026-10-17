# ATS-3 operational audit — observed engineering scope

**Status: PARTIAL. Native accounting slice only; full operational qualification is BLOCKED.** This document describes the implemented read-only audit surface, its deterministic reconciliation, its independent numerical cross-check, and the evidence gaps that remain. It does not qualify broker execution, provider operations, notification delivery, or production monitoring.

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

## Known gaps and closing requirements

See [ats3_acceptance.md](ats3_acceptance.md) for the full requirement matrix. In short:

- Native fills carry no intent, route, skip or acknowledgement history beyond what is already saved.
- No archived broker event history matches the native baseline for the same strategy version and execution period.
- No read-only provider mark, fee and owner-cash stream matches the native accounting.
- No qualified, selected, authorized operational runtime exists, and the native exporter target is down.
- No human-observed notification receipt exists.
- The implementation is read-only and never calls broker endpoints; that scope is verified by tests, not by claim.

Closing ATS-3 requires an authorized, read-only, hash-bound archive for the same strategy version, pairing it with operational monitoring and a human-observed notification receipt. Until then the full operational qualification stays BLOCKED.
