# ATS-6 qualification — 2026-10-17

## Decision and scope

**Engineering acceptance: QUALIFIED_SYNTHETIC_SHADOW.** The final acceptance run
passed all **30 gates**, including actual concurrent processes, four process-death
boundaries, independent economic reconciliation, isolated shadow execution, and
the frozen three-policy comparison. Manual verification checked all **31 committed
SQLite backups** and all **211 listed artifact hashes** with no mismatch.

**Final regression gate: PASS — 435 passed, one optional fixture skipped, zero
failures.** Managed feature policy, managed Ruff, task-owned Ruff, and whitespace
checks also passed. The sole warning is the existing websockets deprecation.

This is qualification of a single-host synthetic shadow ledger under the declared
source and filesystem assumptions. It grants no paper/live deployment, broker
credential activation, real-account authority, account purchase, or protected
research read. No such action was performed. Work was implemented and verified
directly by the supervising assistant, with no delegated coding or verification
agents.

The design and restart procedure are in
[ATS-6 operations](../architecture/trading_system/ats6_shadow_router.md).
The source/hash inventory is in [ats6_evidence_20261017.json](ats6_evidence_20261017.json).
The local delivery commit and exact file census are recorded after commit in
[run_log/ats6/delivery.json](../../run_log/ats6/delivery.json).

## Exact integration and implementation identity

| Item | Identity |
| --- | --- |
| Branch | `feat/ats6-shadow-router` |
| Worktree | `/home/quant/.devspace/worktrees/quant-research-25440f7a-39b7dab4-d00c5a58` |
| Governed-core starting integration | `769ef9807b9823bfe3127cacbd4db05568fd4ddc` |
| Latest qualified ATS-3 incorporated | `b8a9746566c55ba69a5c52b74f78ebe1dddae4d1` |
| Coherent prerequisite merge commit | `a7827ee09125df0f6a6d0d8d64ec16ac307e9b8e` |
| Qualified ATS-6 runtime fingerprint | `b9ac357a1a00a8ac3ebcc68e61332822a75ef17f790c73dcfb79bc58343eed73` |
| Dependency lock SHA-256 | `a7e8a326248584d57cbaa4249c127f1bd99202f25803f9f075f99fbcefbc5628` |
| Final acceptance run | `run_log/ats6/acceptance/20261017T041533-9b9f0ee7` |
| Final regression run | `run_log/ats6/regressions/20261017T042204-50962e5b` |
| Acceptance artifact-manifest SHA-256 | `0ddb698187eb65e64a5b4b5c6be115e07d08648cb492ec613d956807cc53cbc6` |

The prerequisite merge incorporated the five later ATS-3 commits without conflicts,
retained ATS-4/5, and passed **123 compatibility tests, zero skips**. The original
dirty checkout, predecessor worktrees, concurrent ATS-8 work, and historical
evidence were preserved. No remote branch was written. The full inspection and
baseline command are in [ats6_base_20261017.md](ats6_base_20261017.md).

The pinned interpreter is
`/home/quant/.devspace/worktrees/quant-research-25440f7a/.venv/bin/python`.
Versions: Python 3.13.5; SQLite 3.45.3; ml4t-backtest 0.1.7; ml4t-live 0.1.2;
ml4t-engineer 0.1.4; ml4t-diagnostic 0.1.6.post2; Pydantic 2.13.5;
Cryptography 50.0.1; pytest 9.1.1; Ruff 0.16.8. No package was upgraded.
The ATS-3 connector import uses the existing source
`/home/quant/dev/trading-connector` at
`6175a948e6d253ba6f4b610b97b34d8433662e77`; it was not modified.

The runtime fingerprint binds both new core modules and the existing ATS-2
authorization, ATS-3 audit, ATS-4 portfolio, and ATS-5 rule modules, plus SQLite,
Pydantic, and Cryptography. The evidence inventory additionally hashes the
acceptance/fixture/oracle/worker/comparison/regression code, tests, and lock files.
The containing commit identifies the documentation without a circular self-hash.

## Implementation decisions and why the boundary is sufficient

One SQLite transaction owns the account and shared reservation, admitted/skipped
decision, stable route/client identities, grant consumption, outbox, and local sink.
`BEGIN IMMEDIATE` serializes source updates, admission, publication, and execution
observations. Feasibility is recalculated after acquiring that lock; prepared actions
do not reserve capacity. Different processes therefore cannot spend the same cushion.

The store uses rollback journaling (`DELETE`) and `synchronous=EXTRA`.
SQLite's official [WAL documentation](https://sqlite.org/wal.html#wal_reset_bug)
identifies a concurrent WAL-reset corruption issue affecting the installed 3.45.3
version range. Choosing rollback mode avoids that code path without silently
upgrading the runtime. See also the official
[transaction documentation](https://sqlite.org/lang_transaction.html).
All committed qualification backups reported journal mode `delete` and
`PRAGMA integrity_check = ok`.

Risk uses exact integer currency quanta; fixture quantity uses 0.01-unit lots.
Every leg contributes its stressed loss plus declared cost allowance, with no
opposing-leg or cross-account diversification credit. Pending, recognized,
disputed, and immutable opening obligations consume account/shared/family capacity.
ATS-5 owns the account loss-floor semantics, including exact breach-on-touch
boundaries. Source updates can increase existing stress commitments; they cannot
erase accepted fills or reduce existing quoted stress.

ATS-2 owns signed permission; its extension adds only an explicit
`shadow_route`/`shadow_only` path in the `SYNTHETIC_ONLY` trust domain.
ATS-5 synthetic eligibility does not grant authorization. The prepared action binds
the intent, source/account/rule snapshot hashes, ATS-4 portfolio identity, public
authority, policy, and runtime. Dispatch checks current versions, grants, rules,
marks, margin, coverage, and active obligations again inside its transaction.

The shadow worker receives a fixed request, public grant, and one writable state
directory. Its source/interpreter mounts are read-only; home and issuer key are
not mounted; environment inheritance is cleared; its network namespace is distinct.
It exposes no general callback, broker adapter, or order endpoint. The native
SQLite/zlib libraries are pinned into that namespace so the signed runtime identity
does not change through a dynamic-loader fallback.

## Acceptance matrix: transactional, lifecycle, and failure requirements

Every row below is an observed PASS in the final run. Each scenario directory
contains `committed.sqlite`, original command evidence, `projection.json`,
`router_recovery.json`, a separate-process `independent.json`, subprocess exits,
and frozen `expectations.json`. Process-death cases also retain
`crash_evidence.json` and the pre-retry recovery state.

| Requirement / failure scenario | Status | Direct evidence |
| --- | --- | --- |
| Two separately feasible 700-unit intents cannot share 1,000 units of cushion. | PASS | [simultaneous_shared_cushion/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/simultaneous_shared_cushion/independent.json) |
| Two concurrent 500-unit reservations fit across accounts and reserve exactly 1,000 shared units. | PASS | [simultaneous_multiple_accounts/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/simultaneous_multiple_accounts/independent.json) |
| Clean routing establishes the economic reference and a single local sink message. | PASS | [clean_control/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/clean_control/independent.json) |
| Actual child process exits before admission commit; no partial reservation survives. | PASS | [admit_before_commit/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/admit_before_commit/independent.json) |
| Actual child process exits after admission commit; retry preserves one decision. | PASS | [admit_after_commit/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/admit_after_commit/independent.json) |
| Actual child process exits before local publication commit; recovery retries the original message. | PASS | [publish_before_commit/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/publish_before_commit/independent.json) |
| Actual child process exits after publication; retry does not create another message or route. | PASS | [publish_after_commit/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/publish_after_commit/independent.json) |
| Partial fills transfer commitment; cancellation and closing fills release only after reconciliation. | PASS | [partial_cancel_late_close/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/partial_cancel_late_close/independent.json) |
| Unknown acknowledgment retains risk through restart; duplicate intent/ACK cannot reroute. | PASS | [lost_ack_restart_duplicates/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/lost_ack_restart_duplicates/independent.json) |
| Delayed control evidence cannot clear newer uncertainty; late fills and their original clocks remain visible. | PASS | [stale_control_and_audit_clocks/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/stale_control_and_audit_clocks/independent.json) |
| Rejection alone releases nothing; complete rejected-state reconciliation releases the pending obligation. | PASS | [rejection_reconciliation/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/rejection_reconciliation/independent.json) |
| Expired source/mark evidence blocks admission before ranking. | PASS | [mark_source/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/mark_source/independent.json) |
| Incomplete account-rule observation coverage blocks admission. | PASS | [coverage_source/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/coverage_source/independent.json) |
| Missing margin information blocks admission. | PASS | [margin_source/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/margin_source/independent.json) |
| Revoked authority between admission and publication blocks dispatch while retaining risk. | PASS | [revoke_change/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/revoke_change/independent.json) |
| An appended rule amendment invalidates publication without rewriting the old rule. | PASS | [rule_change/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/rule_change/independent.json) |
| Reduced shared limit exposes a deficit and blocks new publication without erasing commitments. | PASS | [global_limit_change/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/global_limit_change/independent.json) |
| Reduced account limit blocks publication and retains the account's existing obligation. | PASS | [account_limit_change/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/account_limit_change/independent.json) |
| A changed account snapshot invalidates a prepared/signed action before admission. | PASS | [prepared_account_change/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/prepared_account_change/independent.json) |
| Reclaimed ownership advances the epoch; late old-owner writes are rejected. | PASS | [superseded_owner/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/superseded_owner/independent.json) |
| An intent is never split to make it fit; unqualified cross-venue composites are refused. | PASS | [indivisible_multileg/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/indivisible_multileg/independent.json) |
| Out-of-order opening fills remain economic facts; duplicate executions do not double-count. | PASS | [reordered_duplicate_events/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/reordered_duplicate_events/independent.json) |
| Conflicting execution payloads retain the first fact plus a conservative disputed bound and halt admission. | PASS | [conflicting_events/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/conflicting_events/independent.json) |
| Pre-existing unresolved exposure survives restart and cannot be erased by a new snapshot. | PASS | [preexisting_unknown_restart/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/preexisting_unknown_restart/independent.json) |
| Missing execution coverage cannot release pending risk. | PASS | [incomplete_reconciliation/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/incomplete_reconciliation/independent.json) |
| A terminal-breaking late fill is recognized, residual risk restored, and further admission halted. | PASS | [late_after_certified_terminal/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/late_after_certified_terminal/independent.json) |
| A damaged derived projection is detected and rebuilt from the immutable command journal. | PASS | [projection_rebuild/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/projection_rebuild/independent.json) |
| The fixed worker runs with no broker imports, inherited credential sentinel, host private canary, or reachable host network. | PASS | [credential_free_namespace/independent.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/credential_free_namespace/independent.json) |
| Interrupted and clean runs have identical committed economic totals. | PASS | [run_log/ats6/acceptance/20261017T041533-9b9f0ee7/acceptance.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/acceptance.json) and the five clean/crash independent reports above |
| Frozen ranking is compared with two feasible simple baselines on the same original event stream. | PASS | [run_log/ats6/acceptance/20261017T041533-9b9f0ee7/policy_comparison.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/policy_comparison.json) |

## Additional integration and delivery requirements

| Requirement | Status | Direct evidence |
| --- | --- | --- |
| Latest ATS-3 reconciled into ATS-4/5 governed core before implementation | PASS | [Prerequisite record](ats6_base_20261017.md); [run_log/ats6/baseline/compatibility_with_connector.xml](../../run_log/ats6/baseline/compatibility_with_connector.xml) |
| Existing ATS-2 authorization and ATS-3/4/5 owners reused | PASS | [src/research_control/action_authorization.py](../../src/research_control/action_authorization.py); [src/shadow_contracts.py](../../src/shadow_contracts.py); final regression receipt below |
| Account eligibility precedes ranking; all skipped candidates retain reasons | PASS | [policy_comparison/cushion/projection.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/policy_comparison/cushion/projection.json); [policy_comparison/cushion/source_observations.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/policy_comparison/cushion/source_observations.json) |
| Bad signature, wrong effect, trading flag, public-only terms, and expired sources fail closed | PASS | [tests/test_ats6_shadow_router.py](../../tests/test_ats6_shadow_router.py); ATS-2 authorization tests in [run_log/ats6/regressions/20261017T042204-50962e5b/pytest.log](../../run_log/ats6/regressions/20261017T042204-50962e5b/pytest.log) |
| Strict ATS-5 floor-touch boundary and stale exposed-account sharing are guarded | PASS | [tests/test_ats6_independent.py](../../tests/test_ats6_independent.py); [run_log/ats6/regressions/20261017T042204-50962e5b/pytest.log](../../run_log/ats6/regressions/20261017T042204-50962e5b/pytest.log) |
| Account/portfolio/rule/grant/policy/source versions are bound and rechecked | PASS | source-change scenario reports above; `test_dispatch_rechecks_sources_and_authority_and_keeps_risk` in [run_log/ats6/regressions/20261017T042204-50962e5b/pytest.log](../../run_log/ats6/regressions/20261017T042204-50962e5b/pytest.log) |
| Independent oracle is sensitive to a forged fill even with a recomputed projection hash | PASS | `test_outside_judge_rejects_changed_fills_even_with_valid_projection_hash` in [run_log/ats6/regressions/20261017T042204-50962e5b/pytest.log](../../run_log/ats6/regressions/20261017T042204-50962e5b/pytest.log) |
| Original event clocks and availability are retained in ATS-3 | PASS | [stale_control_and_audit_clocks/ats3_events.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/stale_control_and_audit_clocks/ats3_events.json); [run_log/ats6/review_regression_green.xml](../../run_log/ats6/review_regression_green.xml) |
| All relevant ATS-2/3/4/5, all dual-mode, and selected legacy/M8 regressions | PASS; one optional fixture skipped | [run_log/ats6/regressions/20261017T042204-50962e5b/pytest.xml](../../run_log/ats6/regressions/20261017T042204-50962e5b/pytest.xml) and [run_log/ats6/regressions/20261017T042204-50962e5b/result.json](../../run_log/ats6/regressions/20261017T042204-50962e5b/result.json) |
| Managed feature AST policy, managed Ruff, task-owned Ruff, diff whitespace | PASS | [run_log/ats6/regressions/20261017T042204-50962e5b/result.json](../../run_log/ats6/regressions/20261017T042204-50962e5b/result.json) and corresponding individual logs |
| All listed acceptance artifacts and committed database structures inspected | PASS | [Evidence inventory](ats6_evidence_20261017.json); [run_log/ats6/acceptance/20261017T041533-9b9f0ee7/artifact_hashes.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/artifact_hashes.json) |
| Failed attempts/raw traces retained | PASS | Failure history below and [hash inventory](ats6_evidence_20261017.json) |
| Exact commands, source identities, assumptions, and recovery documented | PASS | This report; [operations](../architecture/trading_system/ats6_shadow_router.md); [run_log/ats6/regressions/20261017T042204-50962e5b/plan.json](../../run_log/ats6/regressions/20261017T042204-50962e5b/plan.json) |
| Only task-owned source/docs delivered in the local commit; no push | PASS at delivery | [run_log/ats6/delivery.json](../../run_log/ats6/delivery.json) |

The delivery receipt records the exact containing commit and verifies its file
census after commit. The broad regression scope ran 436 collected tests; the sole
skip is the declared, absent 2025 BTC/ETH canonical smoke fixture. It was not
substituted with another source or a protected market window.

| Final regression group | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: |
| ATS-2 | 28 | 0 | 0 |
| ATS-3 | 40 | 0 | 0 |
| ATS-4 | 75 | 0 | 0 |
| ATS-5 | 18 | 0 | 0 |
| ATS-6 | 34 | 0 | 0 |
| Dual-mode runtime | 52 | 0 | 1 |
| M8 | 47 | 0 | 0 |
| Other selected legacy/governance | 141 | 0 | 0 |
| **Total** | **435** | **0** | **1** |

## Independently reconciled economic examples

All numbers below are integer risk quanta, not realized money profit.

| Scenario | Final reserved | Final recognized | Remaining shared capacity | Interpretation |
| --- | ---: | ---: | ---: | --- |
| Two simultaneous 700-unit intents, shared cap 1,000 | 700 | 0 | 300 | Exactly one admitted |
| Two simultaneous 500-unit intents across accounts | 1,000 | 0 | 0 | Both fit; no overspend |
| Clean and all four controlled crash paths | 600 | 0 | 400 | One route and one local sink message; no execution ACK invented |
| Partial fill, cancel, late fill, then reconciled close | 0 | 300 | 900 | Risk reductions occur only at complete reconciliations |
| Missing execution in a cancel certificate | 400 | 200 | 400 | Full 600-unit commitment retained |
| Stale ACK after newer unknown state, then a late fill | 400 | 200 | 400 | Uncertainty stays visible; late execution is retained |
| Conflicting payload for an existing execution ID | 700 | 200 | 1,100 | 400 pending plus 300 disputed; first 200 recognized is immutable |
| Pre-existing unresolved exposure | 700 | 0 | 300 | Restart does not reset the budget |
| Global limit reduced from 1,000 to 300 | 600 | 0 | -300 | Existing obligation retained; publication blocked |
| Late opening fill contradicts a complete terminal certificate | 1,100 | 300 | -400 | Exogenous contradiction recognized and admission halted |

For the partial-fill path, a 1,000-unit reservation becomes 600 pending plus 400
recognized, then 400 pending plus 600 recognized. Reconciled cancellation releases
the remaining 400 pending. A subsequent closing fill initially leaves 600 recognized;
only a complete position reconciliation reduces it to 300. The independent event
trace exposes every intermediate total, not merely the final state.

There is no over-admission in the tested valid-source cases. The two negative
capacity examples deliberately lower a limit or contradict earlier authoritative
input. The router makes those deficits visible and prevents additional admission.
They are not evidence that a synthetic completeness flag can guarantee external
venue finality. All risk arithmetic is conditional on the declared conservative
stress and source-completeness model.

The independent oracle imports no router, ATS-2 validator, ATS-3 bridge, ATS-4
calculator, ATS-5 evaluator, or fixture module. It reconstructs decisions, positions,
risk, grant signatures, source versions, event clocks, and ownership from original
journal commands, then compares the persisted projection. Its independent rule
arithmetic supports the flat synthetic static-floor source fixtures used here;
broader ATS-5 semantics are covered by inherited ATS-5 tests, not claimed as a
second independently qualified general rule engine.

## Frozen allocation-policy comparison

The comparison used 20 predeclared potential events containing nine intents,
identical timing and constraints, account caps of 700/1,000, shared cap 1,400, and
synthetic cost allowances of 0/5 units per lot on accounts A/B. No policy was tuned
after observing its results. An event attached to an originally skipped intent
does not become a fabricated fill.

| Measure | Cushion ranking | First feasible account | Least-used feasible account |
| --- | ---: | ---: | ---: |
| Accepted / skipped intents | 5 / 4 | 5 / 4 | 5 / 4 |
| Peak reserved + recognized | 1,345 | 1,345 | 1,345 |
| Peak shared utilization | 96.0714% | 96.0714% | 96.0714% |
| Account A peak commitment / utilization | 600 / 85.7143% | 400 / 57.1429% | 400 / 57.1429% |
| Account B peak commitment / utilization | 945 / 94.5% | 945 / 94.5% | 945 / 94.5% |
| Peak pending execution uncertainty | 1,345 | 1,345 | 1,345 |
| Final pending / recognized commitment | 840 / 500 | 825 / 520 | 825 / 520 |
| Conditional modeled cost | 10 | 20 | 20 |
| Peak same-family stress: trend | 945 | 925 | 925 |
| Peak same-family stress: reversion | 400 | 420 | 420 |
| Shared-limit breaches | 0 | 0 | 0 |
| Realized profit / incremental return effect | Not established | Not established | Not established |

All three policies skipped `t4`, `t6`, `t7`, and `t9`, with the aggregate
reason `NO_FEASIBLE_ACCOUNT`. The stored candidate explanations show shared-limit
blocking on all four. Account-limit blocking appears on three of those intents for
cushion ranking and all four for the two baselines (counted once per skipped intent
if any candidate has that reason). Reasons can overlap; these counts are not
additional skipped trades.

Cushion ranking has lower conditional cost on this fixture, but the accepted count
and peak shared commitment are identical. It also holds more peak stress in the
trend family. These are arithmetic consequences of the declared account costs and
allocation sequence; they are not evidence of better expected returns. Same-family
simultaneous stress is a conservative co-loss scenario, without empirical
correlation, probability, or intraday-barrier claims. Daily/real incremental portfolio
returns remain unsupported by the synthetic sources.

Sources: [run_log/ats6/acceptance/20261017T041533-9b9f0ee7/policy_comparison.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/policy_comparison.json);
[run_log/ats6/acceptance/20261017T041533-9b9f0ee7/policy_comparison/frozen_stream.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/policy_comparison/frozen_stream.json);
the three policy `independent.json`, `projection.json`, and
`source_observations.json` files under that directory.

## Regressions, retained failures, and repairs

| Attempt | Observed result and action | Evidence |
| --- | --- | --- |
| Initial prerequisite baseline | One collection error: existing connector source absent from PYTHONPATH. Added the actual existing connector source; no upgrade. | [run_log/ats6/baseline/compatibility.xml](../../run_log/ats6/baseline/compatibility.xml) |
| Corrected prerequisite baseline | 123 passed, zero skips. | [run_log/ats6/baseline/compatibility_with_connector.xml](../../run_log/ats6/baseline/compatibility_with_connector.xml) |
| ATS-6 attempt 001 | One early failure exposed strict JSON-list/tuple parsing in public trust-policy restoration. Corrected parsing through the strict JSON API. | [run_log/ats6/attempt_001.xml](../../run_log/ats6/attempt_001.xml) |
| ATS-6 attempts 002 / 003 | 29 passed; then 39 passed including ATS-2 authorization. These preceded the final rollback-journal and review refinements. | [run_log/ats6/attempt_002.xml](../../run_log/ats6/attempt_002.xml); [run_log/ats6/attempt_003.xml](../../run_log/ats6/attempt_003.xml) |
| Independent boundary/oracle checks | Four passed, including valid-hash forged-fill rejection, exact floor touch, and stale exposed-account sharing. | [run_log/ats6/independent_001.xml](../../run_log/ats6/independent_001.xml) |
| First complete acceptance | PARTIALLY_QUALIFIED. Post-publication retry assertion expected an admitted state instead of the existing published state. Isolated worker correctly rejected dynamic-loader SQLite drift. Dependent clean/crash comparison was unavailable. | [run_log/ats6/acceptance/20261017T040126-67f02efb/acceptance.json](../../run_log/ats6/acceptance/20261017T040126-67f02efb/acceptance.json) and per-case failure/process JSON |
| Corrected acceptance | 29/29 PASS after the harness assertion and exact SQLite/zlib namespace mounts were repaired. | [run_log/ats6/acceptance/20261017T040339-bf6b535b/acceptance.json](../../run_log/ats6/acceptance/20261017T040339-bf6b535b/acceptance.json) |
| Broad regression before final review refinements | 434 passed, one absent optional real-store fixture skipped. Tool response timed out, but the test process completed and wrote JUnit. | [run_log/ats6/regressions/final_001.xml](../../run_log/ats6/regressions/final_001.xml) |
| Final-review negative controls | Two failures reproduced admission-time reuse in order/ACK audit events and an older ACK clearing newer uncertainty. Fixed original clocks and stale-control rejection. | [run_log/ats6/review_regression_red.xml](../../run_log/ats6/review_regression_red.xml) |
| Final-review repairs | Both negative controls passed; raw failures retained. | [run_log/ats6/review_regression_green.xml](../../run_log/ats6/review_regression_green.xml) |
| Final core acceptance | 30/30 PASS; 31 independent committed-database reconciliations. | [run_log/ats6/acceptance/20261017T041533-9b9f0ee7/acceptance.json](../../run_log/ats6/acceptance/20261017T041533-9b9f0ee7/acceptance.json) |
| First durable full regression runner | 428 passed, seven failed, one skipped. Runner omitted the existing DBus user-session setting required for ATS-2 cgroup visibility, and Ruff's executable directory. Restored only those explicit prerequisites. | [run_log/ats6/regressions/20261017T041519-c0c830bc/pytest.xml](../../run_log/ats6/regressions/20261017T041519-c0c830bc/pytest.xml); [run_log/ats6/regressions/20261017T041519-c0c830bc/pytest.log](../../run_log/ats6/regressions/20261017T041519-c0c830bc/pytest.log) |
| Final corrected full regression runner | 435 passed, one optional fixture skipped, one existing warning; all five runner gates PASS. Runtime 269.93 seconds. | [run_log/ats6/regressions/20261017T042204-50962e5b/pytest.xml](../../run_log/ats6/regressions/20261017T042204-50962e5b/pytest.xml); [run_log/ats6/regressions/20261017T042204-50962e5b/result.json](../../run_log/ats6/regressions/20261017T042204-50962e5b/result.json) |

The isolated ATS-6 worker remains environment-cleared and network-isolated. The
regression runner's explicit DBus session settings are used only to exercise the
existing ATS-2 systemd/cgroup contract. No cgroup enforcement was weakened or mocked.

The repository-wide `ruff check` returned **625 diagnostics**, all in tracked files
unchanged from the prerequisite merge, including legacy code, notebooks, and
historical fixture scripts. None were in task-owned ATS-6 files. That wider lint
result is **FAIL, pre-existing and outside this work unit**, not a clean-repository
claim. Raw diagnostics: [run_log/ats6/regressions/repository_ruff.json](../../run_log/ats6/regressions/repository_ruff.json).
The required managed-policy and task-scoped lint results are recorded separately.

## Reproduction commands

Run from the isolated worktree. These commands create new unique artifact directories;
they do not overwrite earlier evidence.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 POLARS_MAX_THREADS=2 /home/quant/.devspace/worktrees/quant-research-25440f7a/.venv/bin/python -m scripts.ats6_acceptance --detach

/home/quant/.devspace/worktrees/quant-research-25440f7a/.venv/bin/python -m scripts.ats6_regression --detach

/home/quant/.devspace/worktrees/quant-research-25440f7a/.venv/bin/python scripts/ats6_outside_judge.py run_log/ats6/acceptance/20261017T041533-9b9f0ee7/partial_cancel_late_close/committed.sqlite --output run_log/ats6/independent_recheck_new.json
```

The full regression runner expands and records the exact test filenames, commands,
source hashes, and environment allowlist in [run_log/ats6/regressions/20261017T042204-50962e5b/plan.json](../../run_log/ats6/regressions/20261017T042204-50962e5b/plan.json). It includes all
`tests/test_ats*.py`, all `tests/test_dual_mode_*.py`, all M8 tests, and the relevant
native execution, permit, attempt, research-control, managed-feature, archive-safety,
market-time/scope, and point-in-time alignment regressions. Separate logs retain
pytest, managed Ruff, managed AST policy, task Ruff, and whitespace checks.

Acceptance crash hooks use actual child `os._exit(91)` and `os._exit(92)` at fixed
before/after-commit points. Concurrent processes synchronize on a barrier and share
one database. The independent judge runs as a distinct interpreter process against
an SQLite backup of committed state. Manual verification reads backups with
`mode=ro`, checks SQLite integrity and journal counts, compares independent totals,
and recalculates every entry in `artifact_hashes.json`.

## Boundaries and unproven extensions

| Claim beyond the accepted work unit | Status | Reason |
| --- | --- | --- |
| Real-account authorization or live/paper deployment | BLOCKED / not authorized | Only synthetic shadow permission is implemented; ATS-7 requires a separate qualified provider and explicit approval |
| Broker completeness, actual ACK/fill finality, liquidation, or real order recovery | BLOCKED / unqualified | No provider mutation or real broker execution path was introduced |
| Empirical co-loss probability, incremental portfolio return, alpha, or realized profit | BLOCKED / insufficient source | The comparison uses declared synthetic potential events and stress/cost assumptions |
| Real intraday account-barrier survival | BLOCKED / insufficient source | No qualified real mark/financing path was added; ATS-4's existing scientific limitations persist |
| Optional real 2025 BTC/ETH smoke in this checkout | BLOCKED / fixture absent | The declared canonical fixture is absent; no protected source was substituted |
| Multiple hosts, writable store forks, NFS, power loss, or malicious filesystem owner | BLOCKED / outside qualification | Tested boundary is cooperative single-host SQLite transactions and controlled process death |
| Automatic migration of a nonempty store to changed code | BLOCKED / no protocol | Runtime drift fails closed; use original implementation or separately qualify migration |
| Automatic release of immutable imported opening obligations | BLOCKED / not implemented | These remain conservative commitments until a separately governed reconciliation/migration is qualified |

These extension limits do not silently become production permissions. The accepted
engineering claim is that, with the typed synthetic sources and clock authority
used here, concurrent admissions cannot over-allocate the account/shared budget,
uncertain executions remain commitments, committed decisions survive controlled
crashes, and a separate event-derived oracle reconciles the resulting positions
and risk. Historical outcomes, source versions, accepted fills, and failed
qualification attempts remain intact.
