# One-bar practical 1m recovery audit

## Result

The failed monolithic run was recovered with 28 isolated annual runs on the installed `ml4t.backtest.Engine`, `Strategy` and `DataFeed`. The source is the Dukascopy USATECH.IDX/USD BID index CFD proxy. It is not CME NQ futures. The evaluation covers 2013-01-01 through 2026-07-14. All 14 annual shards completed. The result is retrospective and exploratory.

The source manifest SHA-256 is `fd810bef0a390a77972d22d1cb0100e6d17f46dec437bed5abf865f39e579e75` (163 partitions; 74,010,288 bytes). The date-bounded raw input contains 3,883,929 one-minute rows. Partition hashes match the frozen manifest. Annual feed row coverage and the 26 paired year-boundary warm-up reconciliations passed.

The failed attempt `A` remains in the ledger. The recovery attempt is `RESHARD-ANNUAL-20261012`. The original strategy rules and frozen settings were retained. Each annual process used a $1,000,000 account and a 14-day warm-up with at least 80 complete prior 30-minute bars where source history allowed it. The first year has no earlier source history. Yearly account resets mean the summed PnL is not a continuous full-period portfolio equity curve.

## Aggregate results

| Run | Closed trades | Net PnL | Mean per trade |
|---|---:|---:|---:|
| Native zero cost | 5,462 | $247,566.38 | $45.33 |
| Native full-tick cost | 5,462 | $166,107.92 | $30.41 |

Full-tick cost uses $2.50 commission and 0.25 index points adverse slippage per fill. The $41 manager reference is descriptive only. The cost-aware mean is $30.41 per trade. Annual Sharpe and drawdown are calculated from each shard’s daily native equity; no single full-period Sharpe is reported because annual accounts reset.

## Annual full-tick result

| Year | Trades | Net PnL | Mean/trade | Daily Sharpe | Max drawdown | Ambiguity bound |
|---:|---:|---:|---:|---:|---:|---:|
| 2013 | 319 | $-2,593.40 | $-8.13 | -1.23 | -0.27% | $-2,593.40 |
| 2014 | 393 | $-4,363.00 | $-11.10 | -1.95 | -0.46% | $-4,363.00 |
| 2015 | 388 | $262.62 | $0.68 | 0.10 | -0.13% | $262.62 |
| 2016 | 369 | $-7,519.70 | $-20.38 | -1.48 | -0.96% | $-7,519.70 |
| 2017 | 340 | $-4,089.48 | $-12.03 | -2.14 | -0.50% | $-4,089.48 |
| 2018 | 424 | $11,194.74 | $26.40 | 1.73 | -0.32% | $11,194.74 |
| 2019 | 405 | $8,552.88 | $21.12 | 1.61 | -0.43% | $8,552.88 |
| 2020 | 437 | $9,284.22 | $21.25 | 0.86 | -0.77% | $8,269.22 |
| 2021 | 444 | $31,685.12 | $71.36 | 3.26 | -0.44% | $31,685.12 |
| 2022 | 440 | $55,014.56 | $125.03 | 3.78 | -0.50% | $45,879.56 |
| 2023 | 433 | $21,998.76 | $50.81 | 1.99 | -0.53% | $18,953.76 |
| 2024 | 416 | $17,896.98 | $43.02 | 1.21 | -1.25% | $8,761.98 |
| 2025 | 416 | $42,950.58 | $103.25 | 2.10 | -1.66% | $27,725.58 |
| 2026 | 238 | $-14,166.96 | $-59.53 | -1.68 | -1.66% | $-24,316.96 |

The ambiguity bound totals $118,402.92. It applies a separate conservative loss to 46 events: 45 entry/protective-stop same-minute events and one same-minute dual-entry event. Native fills remain unchanged; this bound is a diagnostic and is not a native replay.

## Checks and known limits

- Independent reconciliation passed for all 14 years. Trade PnL reconciles to each yearly summary, recorded commissions and slippage reconcile, the daily entry cap is at most two, and no evaluated trade remains open. The 26 adjacent-year warm-up comparisons match.
- Source quality checks found no duplicate timestamps, null OHLC values or invalid OHLC values in the annual feeds. The calendar audit checked all 3,883,929 raw rows and found zero differences in absolute 30-minute bin assignment from the earlier expression. The earlier `Int8` overflow changed only the session-date label, not the bars, features or trades.
- The exit audit found 98 late scheduled market exits. In 79 cases, the exact boundary minute is absent and the next observed source minute was used. In 19 cases the boundary minute exists but the preceding submission minute is absent; native `NEXT_BAR` execution fills one minute later. The maximum observed delay is 3,100 minutes. The installed engine cannot submit at the boundary open and fill on that same open. This execution deviation is material and remains unresolved.
- At the 2026-07-14 source cutoff, there are no open trades, but two unfilled entry orders remain in the strategy state. The source ends before their outcome can be observed.
- The feed is an index CFD proxy, not CME NQ. The cost assumptions are illustrative. This evidence does not approve the strategy or establish live execution quality.

## Artifacts

- Annual runner: `scripts/run_one_bar_practical_yearly_20261012.py`
- Focused tests: `tests/test_one_bar_practical_yearly_20261012.py`
- Final report: `run_log/one_bar_practical_1m_20261012/final_report.json`
- Independent audit: `run_log/one_bar_practical_1m_20261012/validation/recovery_audit.json`
- Exit timing audit: `run_log/one_bar_practical_1m_20261012/validation/exit_timing_audit.json`
- Source coverage: `run_log/one_bar_practical_1m_20261012/validation/source_coverage.json`
- Hashes: `run_log/one_bar_practical_1m_20261012/hashes.json`
