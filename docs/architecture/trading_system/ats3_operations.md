# ATS-3 operational audit — observed engineering scope

Status: **PARTIAL ENGINEERING EVIDENCE**, not ATS-3 qualification or broker/provider qualification.

## Read-only entry point

`/home/quant/dev/quant/quant-research/.venv/bin/python -m src.research_control.ats3_native <existing-native-output-directory>`

The adapter reads existing `fills.parquet`, `funding.parquet`, and
`equity.parquet` without modifying them. The paths and SHA-256 digests
are included in the returned evidence. Stable event identities bind the
immutable fills hash, native order ID and source row ordinal; no source
event IDs are fabricated. Naive native fill clocks are interpreted as UTC
in accordance with the currently documented native export behavior.

The independent cash computation applies signed fill notionals,
observed per-fill commissions, and signed native financing cashflows.
Only a **flat** ending portfolio can compare cash directly against
native ending equity without further marks. A non-flat ending account
requires authoritative synchronized marks and remains insufficient.
Unobserved commission or financing is unknown, not zero.

Native order inference from a fill does **not** establish an outbound
route, transport acknowledgment or broker acceptance. Missing ack is
deliberately reported. Historical simulated fills do not establish
live execution quality, slippage versus a causal reference or account
cash withdrawals. The attribution between strategy, routing,
execution and accounting requires a bound, frozen research baseline and
a sufficiently complete archived broker event journal; otherwise
`INSUFFICIENT_EVIDENCE` is mandatory.

## Reproduction sample

Selected existing read-only native sample:

`/home/quant/.devspace/worktrees/quant-research-25440f7a/run_log/dual_mode_runtime_smoke/20261016T075418661458`

The sample has 4 fills, 42 funding observations, 168 equity marks.
Independent ending cash is approximately 98482.66511989635 versus native
98482.66511989634, absolute difference about 1.46e-11. This is an
**independent native accounting cross-check** only, not a completed
real-world operational audit.

Run regression: `python -m pytest -q -o addopts= tests/test_ats3_audit.py tests/test_ats3_native.py`.

## Known ATS-3 gaps

- No selected and bound archived broker fills + native baseline pair has been reconciled.
- No authenticated read-only source has been proven to include intent,
  routes, skips, rejects, orders, acknowledgments, corrections, account
  marks and transfers for the same execution history.
- Native records lack transport acknowledgments; inferred order identity
  cannot substitute for the actual routing journal.
- No end-to-end independently observed notification delivery receipt was
  established in this work unit.
- Operational health metrics are not qualified for a selected production
  process. No new process or orders were launched to satisfy a dashboard.
- No protected market history or credentials are used by this audit.

Future verification must keep the research, provider and live-operational
qualifications separate. Do not upgrade this report to `QUALIFIED`
because native arithmetic passes.
