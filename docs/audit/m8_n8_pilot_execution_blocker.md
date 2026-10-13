# M8 N8 native pilot execution blocker

Date: 2026-10-13

## Decision

The frozen N8 pilot is terminally blocked before the native engine. The frozen
execution rule requires the complete bounded trial to fail if an eligible
signal cannot receive its actual next-bar entry and next-next-bar exit. The
pilot found such gaps. It did not remove signals, run the native engine, produce
fills or equity, or calculate candidate metrics. The holdout was not accessed,
and no live order was placed. This is not a strategy result or a failed economic
hypothesis.

## Freeze and attempt record

The first immutable contract, v1, failed preflight with `IDENTITY_DRIFT` before
any attempt or outcome. Its source was preserved. The corrected contract v2
bound the independent audit source to `run_log/m8/n8/audit_recipe.json` and
passed session validation and preflight. The frozen v2 SHA-256 is
`06d3cc71c2e2fe6311878b045fcdb57822e2e974b1aa3e1a9765fce477000dc0`.

The sole native pilot attempt is
`70841083-b113-4319-8981-dfaef88c13ab`, for trial
`N8_primary_3cost_stress`. Its managed worker reached terminal `FAILED` with
`RuntimeError: N8_RUN_BLOCKED: EXECUTION_EXCEPTION`. This terminal attempt is
preserved. Do not replay it or change its status. A future trial requires a
new, separately counted attempt and a new approved freeze after the execution
calendar/data contract is resolved.

## Independent gap evidence

The independently produced diagnostic applies the frozen signal eligibility
rule without checking future bar presence to select signals. It found 2,491
eligible signals; 26 signals lack one or both of the predeclared actual fill
bars. The trial therefore failed as a whole, as frozen. No signal was dropped
and no fill was synthesized. The diagnostic enumerates the affected timestamps
and records the data identity, permit identity, and the explicit no-holdout/no-
live/no-native-engine state.

The casefile status is `BLOCKED`, reason `ATTEMPT_REVIEW_REQUIRED`, with one
terminal failed preregistered trial. Artifact hashes:

| Artifact | SHA-256 |
| --- | --- |
| Attempt report | `7443346eb3f6060719d4eeeeca918534ff61fb5c1a9a9e8bb3d07bf025eb0f19` |
| Attempt manifest | `6907eb39f0e9da0d46ff3012374444a89ebac2b78e4bad0574dae8ed389b198f` |
| Independent execution-gap diagnostic | `f4876430598034d5e6f6d3743e38d6c09b28beae045d50ef51fa3776e8be0710` |
| Casefile | `c134bcfef5985ba50cf735e443fc3cb1ccb8637daae005f3067fd8612d6358d4` |

The current official [Dukascopy range-of-markets page](https://www.dukascopy.com/swiss/english/cfd/range-of-markets/)
was recorded as the schedule reference. It does not establish the historical
special-session hours for all affected dates. That calendar question remains
unresolved; the diagnostic does not infer an alternate schedule from the gaps.

## Scope and next gate

The source implementation and its pre-freeze tests remain as frozen. Any
calendar or bar-availability change is a new research contract: resolve and
cite historical instrument hours, state how scheduled closures differ from
missing data, update fill eligibility and independent checks, then freeze a new
trial before execution. Do not access 2025 holdout data or place live orders.

The trial remains `NOT_APPROVED` and `EXPLORATORY`. Issue #33 remains open for
native candidate evidence; this attempt does not qualify a candidate. Managed
agent qualification is evidence about control behavior only and cannot turn
this blocked pilot into a strategy result.
