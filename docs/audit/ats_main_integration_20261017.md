# ATS-0–8 additive main integration — qualification delta

Date: 2026-10-17. Decision: **READY_FOR_PR (code integration only)**.
This is not a strategy promotion, legacy-engine retirement, provider qualification, account authorization, or production deployment.

## Refs and ownership

| Role | Ref |
| --- | --- |
| Remote main, checked before and after integration | `fbfc2ed2288ec12f9ed07e6de191dfb9fde36d9d` |
| Qualified ATS-7 parent (includes ATS-0–6) | `8f114c76985721cd690fcd514d190b717f94c660` |
| ATS-0–7 semantic merge onto main | `58a58f4991600d1a39bf6b667691f8e157bd1f7f` |
| ATS-8 port | Five cherry-picks from `8f114c76..9fa18cf455d790d77d4caf42768fc5cab50b4ee8`, applied through `ce0ec0fd` |
| Independent Session C audit | Original `5e2c7cfb95801d647e4f80c10100bd6667096f71`, cherry-picked as `9f754a3a` |
| ATS-8 metric integrity repair | `0a1158cdf2d7ca83cfa290f767636feccb2c95da` |
| Integration branch | `feat/ats-main-integration-core-20261017` |
| Isolated worktree | `/home/quant/.devspace/worktrees/quant-research-d134d8bd` |

The 24 Git conflicts were resolved on the isolated worktree. Conflict-sensitive files included `scripts/quant.py`, `src/engine/funnel.py`, `src/engine/backtest_runner.py`, `src/data_vault/panel_builder.py`, `src/workbench.py`, portfolio policy, the research protocol, and dual-mode tests. The integrated code retains the mainline dual-mode factory and Workbench, native ML4T execution, and additive ATS authorization, scientific protocol, audit, risk, release, and advisory-learning contracts. Both the original research CLI and its new `ingest` and `materialize-markets` commands remain available.

**Session C follow-up:** No path is deleted relative to the inspected remote main. All 29 archived historical runners/configurations are also present at their original paths, with identical SHA-256 bytes and no symlinks. The archive inventory regression validates all 38 inventory entries. Original legacy strategy execution is not replaced or declared parity-qualified. `AGENTS.md` still directs new research to `scripts/quant.py` or Workbench; preserved runners are for historical compatibility. Git's archive whitespace attribute preserves old bytes instead of rewriting evidence.

The original ATS-7 source files `src/shadow_router.py`, `src/release_runtime.py`, `src/research_control/action_authorization.py`, `src/shadow_contracts.py`, and `src/research_control/ats3_native.py` have no diff against the ATS-7 source branch. No unexplained ATS runtime deletion was observed.

## Verification on the integrated source tree

All source/test commands below ran using existing Python 3.13/ML4T packages without package upgrades. The combined source and tests were committed at `0a1158cdf2d7ca83cfa290f767636feccb2c95da`. A subsequent documentation-only commit does not change this tested source.

| Gate | Observed result |
| --- | --- |
| Full standard non-data/non-slow regression, three xdist workers | **712 passed, 0 failed, 9 warnings** |
| ATS-6 acceptance including independent outside-process economic oracle | **30/30 PASS**, `QUALIFIED_SYNTHETIC_SHADOW` |
| ATS-7 synthetic native lifecycle and outside-process Decimal audit | **PASS**; expected cash 100000.2000; native cash 100000.20000000001; no positions or pending orders |
| ATS-8 benchmark | **14/14 critical fixtures**, three samples each; stale advice rejected 6/6 |
| ATS-8 benchmark efficiency | **33 tool calls with learning versus 18 without**; no demonstrated improvement |
| ATS-8 remedy-positive fixture coverage | **0 eligible cases**; correctly reported `NOT_EXERCISED (0/0)`, not a fabricated 14/14 |
| Additional ATS-8 regression after metric repair | **11 passed** |
| Archived/original legacy SHA and path regression | **PASS** |
| Managed runtime and ATS-8 Ruff checks | **PASS** |
| Git checks | No unresolved conflicts; working tree clean after commits; `git diff --check` PASS |
| Remote main | Still `fbfc2ed2288ec12f9ed07e6de191dfb9fde36d9d` |

Test invocation:

```bash
PYTHONPATH="$PWD:/home/quant/dev/trading-connector" \
  /home/quant/.devspace/worktrees/quant-research-25440f7a/.venv/bin/python -B \
  -m pytest -q -n 3 --dist loadfile -m 'not data and not slow' \
  --tb=short --maxfail=15 \
  --junitxml=.workspace/ats_main_integration_20261017/pytest_unified_final.xml tests
```

Local evidence is retained separately from source commits to avoid adding generated databases, bulk traces, or protected data:

| Artifact | Relative path | SHA-256 |
| --- | --- | --- |
| Unified JUnit | `.workspace/ats_main_integration_20261017/pytest_unified_final.xml` | `beac047914d736619e7aaa2786ebcbb46f6c9928e6ae194997bbcf9c600db3d6` |
| ATS-6 acceptance | `.workspace/ats_main_integration_20261017/ats6_acceptance/20261017T081943-153539ae/acceptance.json` | `987e49fbc01b294ffe8ffff825b1ab6394bc50c2110cbfd1c84594b1b62572aa` |
| ATS-7 independent native lifecycle | `.workspace/ats_main_integration_20261017/ats7_acceptance/20261017T082040-7aa832b4/result.json` | `684e067e9d514695bd5d8f09ad5f238072c6bca0b5bf68942752caeb1dd39b92` |
| Corrected ATS-8 benchmark | `.workspace/ats_main_integration_20261017/ats8_benchmark_corrected/report.json` | `34db4c637e8ae114168f1bfc03cda547375f78c07480e865e0cc5655de7218aa` |

The uncorrected ATS-8 benchmark output is separately retained in `.workspace/ats_main_integration_20261017/ats8_benchmark/`, not overwritten. The corrected benchmark ran with the fixed working-tree source immediately before its `0a1158cd` commit; its embedded `head` field therefore names the preceding `9f754a3a` commit. The post-commit ATS-8 regression and final unified suite ran on `0a1158cd`.

## Safety and remaining limits

- The primary dirty checkout, concurrent B/C worktrees, raw data, frozen trials and historical records were not edited by this integration. Nothing was pushed or merged to remote main.
- No Demo/live orders, accounts, credentials, service restarts, or deployment changes were made. Read-only systemd inspection found `ats7-local-paper@observation-v1.service` **active/running**, main PID 300958, with the original 2026-10-17 06:38 UTC observation start. The 28-day observation has not elapsed and was not modified.
- The non-data/non-slow gate excludes optional source-dependent and slow-market qualification. The existing real-data smoke and full-universe capacity tests were not reproduced here. Historic source assumptions and the known exposure to 2026 data remain disclosed.
- ATS-6 is synthetic shadow only; ATS-7 is synthetic local-paper qualified, not fresh external provider-execution or live-release qualified. No production or account authority is granted.
- EOW, ORB, CFD/Dukascopy, M8, FTMO and other legacy strategy modules have **no general verified native behavior/accounting parity**. Their original CLI and frozen YAML paths must remain available until strategy-specific reconciliation.
- ATS-8 learning is optional advisory evidence only. The benchmark establishes safe rejection, but its managed efficiency worsened (18 to 33 tool calls), and it has zero remedy-positive benchmark fixtures. It must not become an authority for trading, protected history or scientific outcomes.
- Historical reports remain immutable. This report is an additive *merged-tree* qualification delta, not a rewrite of ATS-6/7 certificates or the independent Session C audit.

**Decision:** the additive integration may enter a reviewed pull request. A future change to remote main requires rechecking the base and rerunning affected acceptance. No remote push, main merge, deployment or legacy retirement is authorized by this decision.
