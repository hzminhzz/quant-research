# M8 N8 cash-session result

## Frozen run

Session `m8_n8_dukascopy_us_cash_30m_v7` froze before outcome generation. The run used `ml4t-backtest==0.1.7`, the existing 57,504-row Dukascopy `usatechidxusd` 30-minute Parquet file, and its unchanged SHA-256 `36e6a5dd5e16feb21ba5828ed306dc32c703d74143692dce1019322a52d159c8`. The frozen spec SHA-256 is `8dd1d431176e4e04a47142609fad02b71e993fe5cbeccc6978ceb57faae98f55`; the frozen envelope SHA-256 is `b3e756e944b5bd232775017c6c05d64dd598d8f95cba8d60ed6f55a5d72a71dd`.

Attempt `e908ef2f-0d1d-44f4-a484-0203b616cbb4` ran in `ml4t-m8-cash-pilot` from the exact prepared command. The permit was `fbd75de44f522ddb069b3b3a649d52ae763f63c7a85402b71e2b5689af589e3d`. The feature proof hash was `e76b0622b9af37182fb0d603e088a768a9e565ff5d17cd8df86e2b56aeabb215`. 2025+ was not loaded or scored. The result classification is exploratory, broker execution remains unqualified, live order authority is false, and approval remains `NOT_APPROVED`.

The scheduled XNAS calendar selected 805 signals. Each of the three native scenarios has 805 round trips and 1,610 fills. The frozen cost assumptions are 3/6/9 bps adverse price impact and 0.6/1.2/1.8 bps commission per fill. Price impact changes execution prices; native gross PnL is before commission, and net PnL includes both cost components. All values below are normalized to one research unit at $1 per index point, not a verified broker multiplier.

| Cost | Win rate | Gross PnL | Net PnL | Native net expectancy | Daily Sharpe (252) | Calmar (252) | Max drawdown |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1x | 39.63% | -$4,689.90 | -$6,082.95 | -0.000520 | -2.57 | -0.206 | -6.05% |
| 2x | 24.97% | -$11,655.14 | -$14,441.24 | -0.001196 | -5.36 | -0.214 | -14.40% |
| 3x | 15.16% | -$18,620.38 | -$22,799.52 | -0.001752 | -6.93 | -0.222 | -22.75% |

The native strategy is falsified under the preregistered rule: gross PnL and 1x net expectancy are negative. Yearly 1x net PnL was negative in each development year: 2020 -$1,187.69; 2021 -$796.24; 2022 -$532.52; 2023 -$1,463.34; 2024 -$2,103.15. Daily equity risk metrics use `PortfolioAnalysis` with its 252-period convention over 1,258 scheduled CFD trading dates; it is not a claim of exactly 252 sessions per year.

## Independent verification

A fresh native execution was replayed against the completed artifact. `_restore_completed_artifact` accepted only after exact attempt, permit, session, trial, frozen identity, and scenario checks passed; all six Parquet files were readable, schemas and audit row counts matched, audit status was `PASS`, and replayed fills and equity exactly equaled stored tables. The report, manifest, and table hashes are in `run_log/m8/n8/cash_session/results/e908ef2f-0d1d-44f4-a484-0203b616cbb4/`.

The result remains influenced by the earlier 24-hour attempt, which found 26 missing scheduled fill bars and motivated the XNAS-only design. The cash-session study is therefore post-hoc with respect to data availability. These retrospective results are not untouched OOS evidence, profit robustness, or broker-execution evidence. The source PDF binary was waived by the research lead; the 12-page extracted source text and existing source manifest are preserved. The PDF binary hash is not established here.

## Process history and limitations

The immutable 24-hour attempt `70841083-b113-4319-8981-dfaef88c13ab` remains failed. Cash v1 and v6 blocked before a native attempt. Cash v2-v5 are retained as technical failures: command target, calendar bound, drawdown oracle, and audit-status serialization, respectively. None is treated as a separate parameter selection. Cash v7 is the single completed preregistered primary trial. No failed historical session or attempt was reopened.

The normalized $1/point unit and cost estimates do not establish broker lot size, financing, live execution, or market impact. No additional parameter search or holdout analysis is justified by this negative result.
