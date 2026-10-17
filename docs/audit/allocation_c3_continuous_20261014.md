# C3 continuous account prerequisite

**Status: VERIFIED for the mechanical continuous-account prerequisite.** This work supports a separate exploratory allocation study. It does not train an allocator or approve paper or live use.

## Scope and method

- The replay covers `[2013-01-01, 2025-01-01)`. Its loader enumerates 2012 warmup through 2024. It does not read 2025 or 2026 partitions.
- The replay uses C3 `SOURCE-US2`: H1 weight 23.36%, D1 weight 76.64%, nominal risk budget 1%, gross cap 1.90, 1 bp commission and 2 bp slippage per side.
- The replay uses frozen C3 features, UTC hourly aggregation, the 17:00 New York daily session, and `NEXT_BAR` execution.
- The replay uses native `ml4t.backtest.Engine` through `scripts/mechanicalpremia_us2_2013_2026_v1.py`. It does not implement a custom simulation loop.
- Method selected: `.agents/skills/ml4t-run-backtest/SKILL.md`. The applied controls are native orders, fills, positions, cash and costs, plus a fill-ledger check of ending account equity.
- Canonical stores: `/home/quant/dev/quant/ml4t-data/.data/store/index_minute_ES` and `index_minute_NQ`.
- Both promoted and root source snapshots have SHA-256 `24c0bec21e9530b523b39becbdde49cf85fd07cd796729cf3dfe6ca66d63fc33`.

## VERIFIED

- The native equity curve has 3,803,769 points, from 2013-01-01 00:00 UTC through 2024-12-31 23:59 UTC. It contains no 2025 observations.
- The native ledger contains 2,445 fills and 1,223 trades. Native positions cross 2014, 2016, 2017 and 2018 year boundaries. The C3 rules retain the US500 D1 position from 2015-03-04 through 2018-04-15, including year-end marks in 2016, 2017 and 2018.
- At the 2024 cutoff, the native trade ledger has one open long `US500_D` position. It has 9.45709053644089 units, a 5,887.449 mark, and a 2024-12-18 entry.
- The fill-ledger cash reconstruction is 91,620.191906. The open-position mark is 55,678.138222. The native engine equity at cutoff is 147,298.330128. The reconciliation difference is 0.00 price units.
- The annual equity file records the native account at each year's last available bar. It retains one starting account and carried positions. It does not link independent annual returns or sum standalone sleeve PnLs.
- The focused tests pass: `13 passed`.
- The exact artifact paths, byte sizes, and SHA-256 values are recorded in `run_log/allocation_prerequisites_20261014/c3/report.json`.

## Artifact replay guard

Before it reads any fill, trade, equity, or annual outcome columns, the audit scans only event-time columns in all four Parquet files. It requires `continuous_equity.timestamp`, `fills.timestamp`, both `trades.entry_time` and `trades.exit_time`, and `year_end_equity.as_of`. Each event must satisfy `2013-01-01 <= t < 2025-01-01`; the end is exclusive. A missing, null, non-datetime, pre-start, or future timestamp blocks full artifact reads. An open trade's recorded `exit_time` is its final mark time and must also be before the cutoff.

The validator rejects unknown fill sides and trade directions. Adversarial tests add a 2025-01-01 event to each event-time column and prove that no full Parquet read starts. Other tests reject a missing timestamp column and invalid side/direction values.

## INFERENCE

- The annual equity sequence is suitable as a continuous-account input for a separate exploratory allocation study, subject to the limitations below.
- The simulated account uses synthetic index price units. It is not verified USD CFD equity.

## BLOCKED limitations

- Overnight CFD financing is not modeled.
- The data contains BID quotes only. Observed ASK spread and broker execution parity remain unverified.
- The CFD multiplier, lot rules and point-value mapping remain unverified.
- The frozen H1 stop attaches after entry fill confirmation. The initial one-minute protection gap remains.
- The final 2024 D1 position remains marked open at the cutoff. No 2025 behavior is evaluated.

These limitations prevent a broker-PnL or deployment claim. They do not invalidate the mechanical finding that the native engine carried positions and account equity across annual boundaries.

## Reproduction and verification

Run the full native replay:

```bash
PYTHONPATH=. .venv/bin/python -m scripts.allocation_c3_continuous_20261014
```

Audit the saved native artifacts without rerunning the engine:

```bash
PYTHONPATH=. .venv/bin/python -m scripts.allocation_c3_continuous_20261014 --from-artifacts
```

Run the bounded tests:

```bash
PYTHONPATH=. .venv/bin/python -m pytest -c /dev/null -q tests/test_allocation_c3_continuous_20261014.py
```

The focused test command passed with the repository configuration. A temporary conflict-marker error appeared in the shared `pyproject.toml` during this work. I did not edit that file, and it parsed at final verification. `uv run` could not acquire its global cache lock on the read-only filesystem. The commands above use the installed repository `.venv` directly.

## Next decisive question

Can a separate exploratory allocation rule use this continuous account series while preserving the same dated information and instrument-cost limits? Any such work needs a new frozen specification and must keep the reserved 2025–2026 period unopened.
