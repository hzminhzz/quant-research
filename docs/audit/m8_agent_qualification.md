# M8-C agent qualification

This report has two records. The first records the initial state before issue
#25 recovery work. The final re-qualification below supersedes its recovery
status. It does not change the strategy or broker decision.

**Observed:** 2026-10-13. The fixed case labels and expected outcomes are in
[`agent_corpus.json`](../../run_log/m8/agent_corpus.json).

## Results

The local corpus contains four passing positive cases, nine passing adversarial
cases, and one blocked positive case. The blocked case is a negative result for
the PDF-derived strategy. The original PDF is unavailable, so no such result
can be produced. The corpus makes no general reliability-rate claim.

The positive cases verify that the current resolver selects canonical accepted
CFD sources, native ADX dispatch reaches Engineer, approved prior-high/low
features pass an independent oracle, synthetic native fills pass the
independent audit, and a visible running job can be inspected without a second
attempt. The adversarial cases reject a futures source substituted for a CFD,
unqualified data, future-dependent features, unsupported Donchian/native VWAP
claims, a future decision time, unsafe bracket execution, and an unsupported
worker success assertion. A stale readiness audit also fails closed.

The M8-specific recovery test records both outcomes:

1. An active attempt missing from tmux returns `LEASE_UNCERTAIN` while the
   lease is active.
2. After expiry, the ledger appends `ABORTED` for the old attempt and requires
   a new attempt ID.

The CLI `resume` command is read-only. It inspects an existing attempt. The
managed production path does not connect `RunPermit`, attempt claim, native
execution, and restart. Therefore, this test proves safe blocking and
duplicate prevention. It does not prove an interrupted process can continue
with the same attempt ID. The existing `ml4t-m8-qualification` tmux session was
observed at task start and was not changed.

## Executed checks

- `uv run python -m pytest -q tests/test_agent_efficiency.py tests/test_attempts.py tests/test_casefile.py tests/test_casefile_cli.py` — 25 passed.
- `uv run python -m pytest -q tests/test_m8_agent_qualification.py` — 1 passed.
- `uv run python -m pytest -q tests/test_m8_feature_capability.py` — 3 passed.
- `uv run python -m pytest -q tests/test_catalog.py -m 'not data'` — 3 passed.
- `uv run python -m pytest -q tests/test_catalog.py -m data` — 8 passed.

The checks use deterministic synthetic fixtures and the local current catalog.
They do not kill a real worker or start a tmux job. They do not access a
protected holdout or place orders.

## Decision

M8-C is incomplete. The actual interrupted-run replay criterion needs a
managed runner and an explicit replay policy. Until this exists, the current
behavior remains fail-closed and no same-attempt recovery claim is valid.
Issue [#25](https://github.com/hzminhzz/quant-research/issues/25) tracks this
work. The prior M7 tests remain unchanged.

## Cash-session managed execution and recovery evidence

The separate frozen session `m8_n8_dukascopy_us_cash_30m_v7` passed actual `RunPermit` and feature-proof preflight, then completed one bounded native pilot through `scripts/run_m8_cash_session.py` in `ml4t-m8-cash-pilot`. The attempt and report are linked in the M8 result record. A fresh native run was compared with the completed artifact. The verifier checked exact attempt and permit identity, all three cost scenarios, readable Parquet schemas, audit statuses and row counts, and exact fills/equity equality.

New negative fixtures reject hash-consistent fake Parquet bytes, wrong attempt ID, mismatched permit, missing/duplicate scenarios, altered fills with recomputed hashes, missing audit, missing native replay, partial artifacts, and disappeared tmux workers while the lease is active. Existing fixtures also reject bad audit status, truncated Parquet, and stale source identity. Terminal `ABORTED` attempts remain terminal; retry uses a new attempt ID.

The real pilot process ended after successful completion. No real process was killed or interrupted. Same-attempt continuation after an active worker disappears remains unsupported; the ledger returns `LEASE_UNCERTAIN` until expiry, then marks the old attempt `ABORTED` and allocates a new ID. This is a deliberate fail-closed limitation, not interrupted-run replay. M8-C remains incomplete and issue #25 stays open.

The native research process passed. The strategy outcome was falsified and the broker remains unqualified. This provides one concrete positive managed-path artifact and adversarial checks, not a general agent reliability rate or M8 qualification.

## Final control-plane recovery qualification

**Observed:** 2026-10-13. The fixed corpus in
[`agent_corpus.json`](../../run_log/m8/agent_corpus.json) now includes a real
managed worker interruption test and stable reason codes. Durable worker,
ledger, checkpoint, and result evidence is in
[`recovery_qualification.json`](../../run_log/m8/recovery_qualification.json)
and its artifact directory.

The managed protocol uses an exclusive OS lock. The worker holds the lock for
its process lifetime. The runner checks this lock before it treats a visible
tmux session as active. Missing or released locks do not prove a completed
run. An absent worker under its lease returns `LEASE_UNCERTAIN`.

Recovery uses a successor attempt. After lease expiry, the runner requires
known tmux state, a released worker lock, a checkpoint that matches the attempt
and permit fingerprints, and unchanged partial artifacts. It appends
`ABORTED` to the parent attempt. It then creates a new attempt ID and links it
to the parent. The successor reruns from the beginning. Parent artifacts stay
available. The system does not claim same-attempt continuation.

The controlled test checked the lock while the worker ran. It killed only the
PID recorded by its unique test-owned tmux session. It checked that the lock
was released after process death. The successor verified the parent
checkpoint and partial file. Exactly one successor completed. The test used
synthetic files. It did not execute a strategy or access market data, a
protected holdout, a broker, or an order path.

The fixed artifact tests reject a wrong attempt or permit, self-hashed fake
Parquet, truncated or incomplete Parquet, rehashed altered fills, missing
audits, tampered checkpoints, and duplicate worker claims. An independent
native replay remains required before a strategy artifact can be reused. The
corpus contains deterministic cases. It does not estimate general agent error
rates.

**Control-plane decision:** The M8-C recovery gate passes for explicit
successor-attempt replay. Same-attempt recovery remains unsupported. The
PDF-derived rule remains untested because its source document is unavailable.
Strategy approval remains `NOT_APPROVED`. This result does not qualify broker
execution or authorize live orders.
