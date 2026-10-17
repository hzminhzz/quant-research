# B0 daily marked equity prerequisite

## Scope

This work prepares one input for a separate `EXPLORATORY` allocation study. It does not train an allocator. It does not qualify paper or live trading.

The preserved strategy is B0 from `promote/one_bar_nq_30m/strategy.yaml`: one illustrative contract, a fixed 50-point stop, a 50-completed-bar breakout, the Chicago 17:00 session anchor, and the frozen full-tick costs of $2.50 commission and 0.25 index points adverse slippage per fill. The data is a Dukascopy BID CFD proxy. It is not dated CME NQ data. The $20 per point contract mapping is illustrative.

The development window ends on 2024-12-31. The adapter filters later rows before it reads their outcome or price fields. It does not score 2025 or 2026 results.

## Evidence

**VERIFIED — native equity is marked.** The installed `ml4t-backtest` source records equity as broker cash plus marked position value in `ml4t/backtest/engine.py::_record_portfolio_state`. The configured mark defaults to `PRICE`. The installed `DataFeed` defaults its price column to `close`. The B0 run supplies minute OHLC prices. Therefore, the native equity snapshots use the current feed close to mark open positions.

**VERIFIED — independent accounting reconciliation.** The adapter uses signed native fills, actual fill prices, fill commissions, and the canonical source close at each native daily snapshot timestamp. It computes cash plus signed position market value. It does not charge the saved slippage column twice because the fill prices already include the modeled slippage. All 3,347 observed daily marks from 2013-01-01 through 2024-12-30 match the native daily equity snapshots. The maximum absolute difference is approximately $0.0000000042. No snapshot lacks an exact source mark. No day exceeds one contract.

**VERIFIED — realized and open components are distinct.** The output reports cumulative closed-trade net PnL separately from the residual open-position mark contribution. The identity is checked against native equity. A flat position has a zero open contribution within floating-point tolerance.

**VERIFIED — missing observations remain missing.** The CSV has one calendar row per date from 2013-01-01 through 2024-12-31. It labels 3,347 rows `OBSERVED_SOURCE_MARK` and 1,036 rows `NO_SOURCE_OBSERVATION`. Missing rows have null mark and NAV fields. The adapter does not forward-fill a price or PnL.

**VERIFIED — source identity.** The practical run manifest hash is `84da309947b84149a4aa44f0ef7d552173937df216c5eff361d17cde0567136f`. Its frozen source manifest hash matches `run_log/one_bar_dukascopy_2013_2026_20261011/source_manifest.json` at `fd810bef0a390a77972d22d1cb0100e6d17f46dec437bed5abf865f39e579e75`. The adapter reads source partitions for 2013–2024 only.

**INFERENCE — allocation input use.** The daily NAV can support development-only allocation diagnostics if the study joins on observed dates and retains the proxy identity. It does not establish CME NQ performance or production account equity.

**VERIFIED — internal year-boundary positions are flat.** The native fill ledgers imply zero contracts at both the last available December daily snapshot and first January daily snapshot for both adjacent workers at all 11 internal boundaries from 2013/14 through 2023/24. Exact timestamps and native equity values are in `run_log/allocation_prerequisites_20261014/b0/b0_year_boundary_audit.json`. This verifies the sampled boundary positions. It does not test the excluded 2024/25 boundary.

**BLOCKED — continuous reference NAV.** Flat boundary snapshots do not establish one path through the years. For every adjacent worker pair, the native fill sequences in the common daily-snapshot overlap differ. The native equity offset also changes within every overlap, so there is no constant cash/equity translation that reconciles the two paths. The pairwise fill counts range from 14 vs 28 (2017/18) to 33 vs 48 (2021/22). The equity-offset spans range from -$8,036.94 to -$7,862.66 (2016/17) and from +$56,410.92 to +$57,015.00 (2022/23), among other changing offsets. See the boundary JSON for all 11 windows, fill counts, exact timestamps, and offsets. Therefore no continuous NAV is produced. Re-basing or compounding annual returns would assume away the worker path differences and would not be a reconciliation of the frozen native fills.

The boundary comparison reads only worker snapshots and fills dated on or before 2024-12-31. The 2024/25 boundary is explicitly excluded; no 2025 data is read. A continuous path would require a single native worker/replay ledger with carry-forward cash and position state across years, preserving the frozen strategy, fills, and costs. The current annual workers do not supply that evidence.

## Accounting method

For each snapshot timestamp, the adapter applies all fills at or before that timestamp:

```text
cash = initial cash - signed fill notional - commissions
position value = signed open quantity * exact source close * $20 per point
equity = cash + position value
```

Actual fill prices include the frozen run's adverse slippage. The adapter therefore subtracts commissions once and does not subtract slippage again. It uses the B0 native trade ledger for realized net PnL and uses the difference between ledger equity and realized PnL for open mark contribution.

The annual-reset output is `run_log/allocation_prerequisites_20261014/b0/b0_daily_mtm_nav_2013_2024.csv`. The row-level reconciliation is `run_log/allocation_prerequisites_20261014/b0/b0_daily_mtm_reconciliation.json`. The boundary audit is `run_log/allocation_prerequisites_20261014/b0/b0_year_boundary_audit.json`. No continuous-NAV output exists because the continuity gate is blocked.

## ML4T procedures and checks

| Procedure | Local source | Invariant checked |
| --- | --- | --- |
| `ml4t-run-backtest` | `/home/quant/.cache/ml4t-skills-f0ea019/backtest/run-backtest/SKILL.md` | Use native engine semantics and future fills; this task audits the existing engine output and does not run a new simulation. |
| `ml4t-cost-model` | `/home/quant/.cache/ml4t-skills-f0ea019/backtest/cost-model/SKILL.md` | Deduct commission once and do not duplicate slippage embedded in fill prices. |
| `ml4t-calendar-ops` | `/home/quant/.cache/ml4t-skills-f0ea019/data/calendar-ops/SKILL.md` | Preserve timezone-aware UTC marks; retain the existing Chicago session rules and annual boundaries. |
| `ml4t-risk-metrics` | `/home/quant/.cache/ml4t-skills-f0ea019/portfolio/risk-metrics/SKILL.md` | Do not compute or report performance metrics in this accounting prerequisite. |

The installed library is the source of truth for equity snapshots. The fill ledger and source closes independently verify those snapshots. This adapter does not implement a backtest loop or calculate risk metrics.

## Reproduction

Run these commands from the repository root:

```bash
.venv/bin/python scripts/allocation_b0_mtm_20261014.py
.venv/bin/python -m pytest -c /dev/null -q tests/test_allocation_b0_mtm_20261014.py
```

The focused tests pass: `5 passed`. The script exits successfully after writing both the annual-reset MTM reconciliation and the boundary audit. A successful audit command does not mean the continuous-NAV gate passed; its explicit status is `VERIFIED_FLAT_BUT_CONTINUITY_BLOCKED`.

The explicit `-c /dev/null` bypasses the current shared `pyproject.toml` merge conflict for the focused test command. It does not edit that file. The normal pytest invocation cannot parse the conflicted file. The repository-wide `git diff --check` currently fails on leftover conflict markers in the shared `uv.lock`; the B0 files are outside that conflict. Do not resolve shared conflicts as part of this task.

## Limits and next question

The source has no ASK prices, and it is not a dated NQ futures contract. The yearly workers do not form a continuous multi-year account. The allocation study must decide whether annual-reset daily returns are acceptable for its development comparison or whether it needs a continuous native B0 replay from the original run source. Do not use this artifact to approve a strategy.
