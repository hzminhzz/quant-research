# M8-C agent qualification

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
