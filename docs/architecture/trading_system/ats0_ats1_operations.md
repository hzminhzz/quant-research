# ATS-0 / ATS-1 read-only operating interface

Implementation scope: `src/research_control/agent_interface.py`.
This is an additive metadata projection, not a new trial store, permission
authority, job scheduler, holdout reader, or broker adapter.

## Commands

From repository root:

```sh
.venv/bin/python -m src.research_control.agent_interface inspect_case --root . --limit 10
.venv/bin/python -m src.research_control.agent_interface inspect_case --root . --candidate CANDIDATE_ID
.venv/bin/python -m src.research_control.agent_interface read_evidence --root . --reference dual_mode/CANDIDATE/ATTEMPT/casefile.json
.venv/bin/python -m scripts.benchmark_ats_cold_start --root . --samples 5
```

All entrypoints are read only. The evidence reader accepts only registered
factory casefiles inside `run_log/dual_mode`; protected-result Casefiles
are denied. Stage statuses are projected, not certified as independent numerical
evidence. Missing or oversized artifacts block scoped claims. No automatic retry
or protected fetch is permitted. Its result does not authorize deployment,
development compute, orders, or protected-history access.

## ATS-0 authority map

| Authority | Actual location | Limitation |
| --- | --- | --- |
| Code / dirty state | Local Git worktree | Does not inspect all other worktrees atomically |
| Current factory research | `run_log/trial_ledger.jsonl`, hash chain | Research status, not broker authority |
| Factory Casefile | `run_log/dual_mode/<candidate>/<attempt>/casefile.json` | Nonprotected status fields only; bounded JSON |
| v1 research Casefile | `src/research_control/casefile.py` | Existing separate compatibility entrypoint |
| Protected boundary | `src/data_vault/vault.py` | Not entered/read by ATS |
| Jobs | tmux session names | A named session does not prove active work |
| Broker / live state | Separate connector/runtime | Uninspected; reported NOT_VERIFIED |
| Approval | External authority required | No ATS-0/1 ability to mint permission |

Legacy `scripts/research.py` and native `scripts/quant.py` retain their
existing status semantics. Do not interpret `FALSIFIED_STAGE_2` as a runtime
failure or an unexecuted Stage 3 as a passing test.

## Acceptance limitations

- Each tmux session name is visible, but process identity, heartbeat, checkpoint,
  and lease ownership are not yet reconciled. They remain unknown.
- Git working state and tmux observations are non-atomic. Source watermark and
  render time are distinct for inspected casefile metadata.
- Large factory Casefiles intentionally fail bounded expansion rather than
  opening high-volume or protected content.
- The proposed ATS-2 `prepare/start/observe/verify` control plane does not exist
  in this slice. No action generated here may be executed as authorization.
- The benchmark reports actual new-view latency and deterministic action. The
  existing multi-step baseline has no measured timing; no speedup is claimed.

For adversarial verification run `tests/test_ats_read_interface.py`, then run
the existing `tests/test_casefile.py` and `tests/test_casefile_cli.py`.
