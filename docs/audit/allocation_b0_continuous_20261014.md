# B0 continuous native account prerequisite

## Result

**VERIFIED — one continuous native account path and cash-plus-mark equity.** The retained artifact comes from a single installed `ml4t.backtest.Engine` run over the B0 feed from `2013-01-01 00:00 UTC` through the final authorized source minute, `2024-12-31 23:59 UTC`. It used one initial cash balance and one native strategy instance. It did not combine or rebase annual worker outputs. The same frozen run was inadvertently launched twice because the first logging pipe started before its task-owned output directory existed. Both session summaries completed with identical reported reconciliation and boundary values; attempt 2 produced the retained files. The duplicate is recorded in `execution_attempts.json`.

The native Engine produced 3,583 daily equity observations. The existing B0 cash/MTM adapter independently applied the native fill ledger to exact source closes. No daily mark was missing. The maximum absolute difference between `cash + signed quantity × close × $20` and native Engine equity was `$0.0000000121`. Maximum absolute position was one contract. The native closed trade ledger reconciled to the Engine equity change within `$0.000000011`.

**VERIFIED — cash and positions carry across internal year boundaries.** The audit records 22 observations across 11 internal December/January boundaries. Cash and position come from the same continuous fill ledger. One boundary observation is open: at `2019-12-31 23:59 UTC`, quantity was `+1`, cash was `$837,492.52`, the source close was `8744.58`, marked position value was `$174,891.60`, and equity was `$1,012,384.12`. This position is carried by the native replay. The other 21 sampled boundary observations are flat. All boundary rows reconcile to native equity within `$0.000000011`.

At the first observed January snapshot for that boundary (`2020-01-01 23:59 UTC`), the native ledger is flat with cash/equity `$1,012,484.82`; the native sell fill at `2020-01-01 23:00 UTC` closes the contract after it remained open over the boundary. The account is flat at the final available development mark on `2024-12-31`. The replay does not read 2025 or 2026 source partitions. It does not inspect the `2024/25` boundary, force-liquidate after the data cutoff, or use a post-cutoff close-out row.

## Scope and frozen settings

The replay used the promoted B0 settings after checking them against the current strategy and backtest YAML files:

- One illustrative contract, multiplier `$20` per point and tick `0.25` points.
- A 50-completed-bar Donchian breakout on complete 30-minute bars.
- Buy-stop and sell-stop entries; cancel the opposing entry after a fill, as the current strategy implements its intended OCO behavior.
- A 50-point protective stop, maximum two entries per Chicago session date, and a market exit at the next 30-minute boundary under the original strategy code.
- An extended session anchored at `17:00 America/Chicago`.
- `$2.50` commission and `0.25` points adverse slippage on each native fill.
- Dukascopy `USATECH.IDX/USD` BID minute OHLCV. This is an index CFD proxy, not dated CME NQ data.

The replay used the single trial B cost setting. It did not fit a model or train an allocator.

## Native execution limit: exact OCO and exit timing remain blocked

The continuous account and its native ledger are verified **as modeled by the installed engine and existing B0 strategy code**. Exact intended broker behavior is not fully established:

- The installed native broker does not provide atomic OCO. The replay retained the strategy's opposing-stop cancellation behavior. The saved native diagnostics flag 22 same-minute OHLC ambiguities, including one timestamp where both opposing entry stops filled. The one-contract position invariant still held in the resulting native ledger.
- There are 36 native exits whose fill timestamps differ from the exact next 30-minute boundary. The current strategy submits its market exit at the scheduled boundary and the native engine fills on a subsequent available source event. Do not describe these as exact boundary fills.
- One-minute OHLC cannot resolve the order of all same-minute stop events. No intraminute path was inferred or substituted.

Therefore, **strict atomic-OCO and exact-next-boundary execution fidelity is BLOCKED** by the installed broker semantics and source resolution. The accounting result remains a reproducible single native path. This limitation must travel with any exploratory allocation use.

## Method and source identity

The new script imports the existing practical B0 feed feature builder and the existing `CausalOneBar`/`run_native` implementation. The native execution call is `ml4t.backtest.Engine(DataFeed(...), strategy, config).run()` from the installed package. The new script does not implement an event loop, fill model, or backtest. The already-existing B0 cash/MTM adapter is reused for the independent daily accounting reconciliation.

Source processing used one Polars lazy Parquet scan over 3,583 day partitions whose directory dates fall between `2013-01-01` and `2024-12-31`, followed by a timestamp cutoff at `2024-12-31`. The selected source contained 3,803,769 minute rows and ended at `2024-12-31 23:59 UTC`. It had 125,711 complete 30-minute bars, 2,559 incomplete bins excluded from signal bars, zero duplicate timestamps, zero null OHLC values, and zero invalid OHLC rows. The input contained no 2025/2026 partitions.

Per-partition SHA-256 values and a canonical manifest digest are in `run_log/allocation_prerequisites_20261014/b0/continuous_2013_2024/source_hashes.json`. The manifest contains 3,583 partition hashes and has SHA-256 `237bf30d7fbb4e41ee8ec889fd9633225a52b35284d559ba38f366d972fcdd27`. It also records hashes for the B0 strategy YAML, backtest YAML, practical feed builder, native B0 runner, and the new replay script as they existed at run start.

The installed library identity is recorded in `native_library_identity.json`: `ml4t-backtest==0.1.7`, `engine.py` SHA-256 `e0b90bd959bb15c2f19aaf4227646cc4b1fca45f82a3007430d8c298a406cd11`, and `datafeed.py` SHA-256 `e30b9e45d9d5875063ddd7dc3da35ff0c56e281ae12614ffa73336c485174ae8`.

## Artifacts

- Replay summary: `run_log/allocation_prerequisites_20261014/b0/continuous_2013_2024/continuous_replay_summary.json`
- Native fills, trades, daily equity and metrics: `run_log/allocation_prerequisites_20261014/b0/continuous_2013_2024/native_full_tick_cost/`
- Independent daily cash/MTM reconciliation: `run_log/allocation_prerequisites_20261014/b0/continuous_2013_2024/daily_cash_mtm_reconciliation.csv`
- Cash, quantity, mark and native equity at each annual boundary: `run_log/allocation_prerequisites_20261014/b0/continuous_2013_2024/year_boundary_cash_mtm.csv`
- Input hashes and source quality: `source_hashes.json`, `source_quality.json`, and `frozen_b0_check.json` in the same run directory
- Installed Engine and DataFeed identity: `native_library_identity.json` in the same run directory
- Run attempt and logging record: `execution_attempts.json` in the same run directory
- Preserved command output: `run_log/allocation_prerequisites_20261014/b0/continuous_2013_2024/continuous_run.log`

## Procedures and verification

| Procedure | Local skill file | Invariant checked |
| --- | --- | --- |
| `ml4t-run-backtest` | `/home/quant/.cache/ml4t-skills-f0ea019/backtest/run-backtest/SKILL.md` | Use the installed event-driven Engine, native future-event fills and native cost configuration. |
| `ml4t-cost-model` | `/home/quant/.cache/ml4t-skills-f0ea019/backtest/cost-model/SKILL.md` | Preserve the frozen commission and slippage inputs on every native fill. |
| `ml4t-polars-patterns` | `/home/quant/dev/quant/quant-research/.agents/skills/ml4t-polars-patterns/SKILL.md` | One projected lazy source scan, date and column filtering, sorted feed and streaming collection. |
| `ml4t-calendar-ops` | `/home/quant/dev/quant/quant-research/.agents/skills/ml4t-calendar-ops/SKILL.md` | Keep UTC timestamps and the Chicago 17:00 session boundary explicit. |
| `ml4t-lookahead-bias` | `/home/quant/dev/quant/quant-research/.agents/skills/ml4t-lookahead-bias/SKILL.md` | Release each completed-bar level only after the bar is complete; use no future source rows. |
| `ml4t-compute-features` | `/home/quant/dev/quant/quant-research/.agents/skills/ml4t-compute-features/SKILL.md` | Reuse `ml4t.engineer.compute_features` for the 50-bar channel feature. |
| `ml4t-build-bars` | `/home/quant/dev/quant/quant-research/.agents/skills/ml4t-build-bars/SKILL.md` | Accept a decision bar only when it contains 30 unique minute observations. The source is OHLCV, not tick data. |

Commands run from the repository root:

```bash
set -o pipefail; PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/allocation_b0_continuous_20261014.py 2>&1 | tee -a run_log/allocation_prerequisites_20261014/b0/continuous_2013_2024/continuous_run.log
mkdir -p run_log/allocation_prerequisites_20261014/b0/continuous_2013_2024 && set -o pipefail; PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/allocation_b0_continuous_20261014.py 2>&1 | tee -a run_log/allocation_prerequisites_20261014/b0/continuous_2013_2024/continuous_run.log
.venv/bin/python -m pytest -c /dev/null -q tests/test_allocation_b0_continuous_20261014.py
```

The first replay command returned exit code 1 because `tee` could not open the missing directory; the managed session itself completed and printed `status: VERIFIED`. The second command created the directory first, reran the identical trial, and returned exit code 0. Both commands and the duplicate execution are retained above and in `execution_attempts.json`. The focused B0 test suites pass: **9 passed** across the MTM and continuous replay modules. `-c /dev/null` avoids parsing the unrelated shared `pyproject.toml` conflict. Before execution, the host showed about 9.2 GB available RAM and the selected 2013–2024 partitions occupied about 83.6 MB. The usual tmux socket returned `Operation not permitted`; a task-owned tmux socket also returned `Operation not permitted`. The replay ran in monitored managed execution sessions, and attempt 2 output was preserved in the run log. No other process or tmux session was changed.

## Limits

This artifact is an `EXPLORATORY` allocation prerequisite only. It does not train or validate an allocator, authorize paper/live use, validate the CFD-to-CME mapping, or open the reserved 2025–2026 evaluation period. Daily observations exist only on source-observation dates; no missing dates are forward-filled.
