# ATS-4 governed-core integration and release verification — 2026-10-17

## Decision and exact scope

**ATS-4 engineering acceptance: PASS.** The isolated governed-core integration includes
the ATS-2 authority baseline, ATS-3 read-only operational-evidence implementation,
ATS-4 event scientific protocol and native portfolio-evidence bridge, and ATS-5 pure
account-rule replay. No cross-sectional behavior, frozen M8 history, protected
partitions, trading credentials, or orders were changed or consumed.

**ATS-4 scientific/market qualification: `PARTIALLY_QUALIFIED`.** The historical
M8 strategy remains economically falsified, executable broker costs remain
unverified, and fresh OOS, generic stop/target protocols, intraday account
barriers, multi-strategy native account execution, and deployment are not claimed.
A valid negative strategy is not a failed engineering release.

Other bounded work remains separate: ATS-3 overall operational audit is **NOT
QUALIFIED** without matched real broker records, account marks and notification;
ATS-5 is **engineering-fixture qualified only** with no reviewed real account;
ATS-8's advisory learning benchmark is partially qualified and had a negative
tool-call ablation, so it was not incorporated into this ATS-4 integration.
These limitations do not invalidate ATS-4's scientific-protocol implementation.

## Provenance and isolation

- Original ATS-4 worktree: `/home/quant/.devspace/worktrees/quant-research-25440f7a-13e55b9b`;
  original commit `fc71cc0fda2f3791fbb6fcb8201eeb8c12aaf988`.
- Isolated integration worktree: `/home/quant/.devspace/worktrees/quant-research-25440f7a-39b7dab4`;
  branch `feat/ats-integration-20261017`.
- Governed-core base `d9070e12e6e512650202548d691988ef721d8ff5`,
  with ATS-3 commits `dec0bbcc` and `23642cc7`.
- ATS-4 replay-preserving cherry-pick: `2918f5d5` (original `fc71cc0f`);
  ATS-5 cherry-pick: `2dffa10a` (original `d077b583`).
- Three shared ATS-4 research entrypoints (`scripts/quant.py`,
  `src/engine/funnel.py`, `src/workbench.py`) were integrated without
  overwriting ATS-2/ATS-3 or ATS-5 edits.
- Latest inspected GitHub `origin/main` includes an independent new dual-mode
  implementation (`fbfc2ed2`); `git merge-tree` found 27 conflicting paths
  against the governed-core lineage. No blind conflict preference or direct
  merge to `main` is authorized by this bounded release. Mainline reconciliation
  is a **separate unresolved integration gate**, not evidence against ATS-4.

## Durable original authority and evidence

The development source has been copied from the historical M8 worktree to the
host-persistent **read-only** file:

`/home/quant/dev/quant/research_artifacts/ats4/20261016/source/prices_30m.parquet`

Source SHA-256, identical before and after relocation:
`36e6a5dd5e16feb21ba5828ed306dc32c703d74143692dce1019322a52d159c8`.
Row count: 57,504. Its previous worktree-relative location remains recorded
unaltered in `ats4_qualification_20261016.md` for historical audit. The
`event_protocol.SOURCE` constant now names the archived source. A missing or
changed source still fails closed; no alternative input is silently substituted.
This local path needs independent provisioning on another host before a real
replay. It is not part of the Git tree.

The original untracked 2026-10-16 verification evidence (38 files, including
JUnit reports, actual native orders/fills/equity and casefile) is preserved at:

`/home/quant/dev/quant/research_artifacts/ats4/20261016/evidence/`

The post-integration 2026-10-17 evidence (25 files at initial archive,
including two JUnit reports and all public-CLI artifacts) is preserved at:

`/home/quant/dev/quant/research_artifacts/ats4/20261017_integration/evidence/`

The original and archive copies of both JUnit reports and the new event
evidence JSON were compared byte-for-byte. Release artifacts are not committed
to source control.

## Reproduction and qualification

Locked interpreter:
`/home/quant/.devspace/worktrees/quant-research-25440f7a/.venv/bin/python`.
Use explicit `/usr/bin/env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 POLARS_MAX_THREADS=2`;
the PATH-resolved `env` and `python -m pytest` have previously been shadowed
by non-executing stubs on this host. Genuine pytest was invoked with
`python -c 'import sys,pytest; sys.exit(pytest.main(sys.argv[1:]))'`
and `-o addopts= -q`.

| Verification | Result | Durable evidence |
| --- | --- | --- |
| Initial integrated ATS-3/4/5 focused smoke | 90 passed | `run_log/ats_integration_20261017/smoke.xml` |
| Real ML4T native / legacy / ATS-4 regression | 186 passed, 1 skipped | `run_log/ats_integration_20261017/full_native.xml` |
| ATS-2/3/5 cross-module authorization and safety suite | 86 passed | `run_log/ats_integration_20261017/safety_final.xml` |
| Scoped ATS-4/ATS-5 Ruff, managed-feature Ruff, AST feature policy, diff whitespace | PASS | Executed on integration worktree |
| Public CLI three-cost native M8 replay | Exit 3, `PARTIALLY_QUALIFIED`, **native parity PASS** | `run_log/ats_integration_20261017/public_cli/` |

The sole full native skip is the pre-existing BTC/ETH real-store smoke requiring
an explicit BTC/ETH canonical build. It is **not** the frozen M8 replay.
During the CI-portability improvement a deliberately fake small Parquet fixture
first failed its expected-message assertion; it was corrected to expect the
earlier strict file-size identity guard, and the final safety suite passed. Red
evidence is retained, not silently treated as a market failure. Real replay tests
are explicitly `@pytest.mark.data` and skip only when their frozen source is
not provisioned, so source-free CI does not claim native-parity coverage. A
data-free corrupt-source guard still executes everywhere.

The live public command was:

```sh
PY=/home/quant/.devspace/worktrees/quant-research-25440f7a/.venv/bin/python
/usr/bin/env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 POLARS_MAX_THREADS=2 \
  "$PY" scripts/quant.py run config/candidates/ats4_m8_n8_cash.yaml \
  --run-log run_log/ats_integration_20261017/public_cli
```

Its real attempt identifier is `20261017T015029-dbde90168e`.
The casefile reports `holdout_access=false` and no engineering exception.
Native event `parity.status=PASS`, with M8 historical economics
`FALSIFIED_NONPOSITIVE_GROSS_OR_BASE_NET_EXPECTANCY`. Broker execution costs are
`ASSUMED_NOT_QUALIFIED`. Thirty-minute native source-close marks reconcile;
intraday account barriers remain unqualified. The source checksum remains
unchanged. New event runtime digest
`c366bdbc0fc8b28266ab33fb9e0bddcc7892f4bd87c2ddd8677eed9acd420066`
is the expected result of integration changes and is identical before/after
native replay, not falsely presented as the original ATS-4 digest.

Evidence hash pins:
- Full native JUnit: `9e73e7faccb92af83111af770f5b0eb8d0065658f627cbba13f3d6fd68492159`.
- Final safety JUnit: `1c6e3050bbef5d2d5f6ce65b6217e38a00471219d92fe1d0045afb0321c0c457`.
- New CLI `event_evidence.json`: `299c8e376204265ae930bbf2982e72432180bd4144872dd3dee114dc747ae822`.

## Release boundaries

Publish the verified integration branch as a PR targeting
`feat/rebuild-20261015-governed-core` after synchronizing its verified
`d9070e12` local baseline to the remote. Gate merge on the observed GitHub CI
result and review of the exact commit SHA. After merge, ATS-4 is complete **in
the governed-core release branch**, not yet ported to the divergent `main`.
Keep ATS-8 independent and preserve ATS-3/ATS-5 qualification caveats.
No production connector, trade, account purchase, new protected-data read,
or live order was authorized or executed by ATS-4 integration.
