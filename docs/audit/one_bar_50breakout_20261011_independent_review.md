# One-bar 50-breakout independent verification — 2026-10-11

**Status:** COMPLETED exploratory NQ/ES proxy backtest; **NOT APPROVED** for executable CME futures performance. The prior draft review (written while the runner was still working) is superseded by this review.

## Checked actual repository state

- Repository HEAD `c095faa`, branch `main`; task files remain untracked, and unrelated dirty work was preserved.
- The `ml4t-onebar-20261011` tmux session no longer exists; no active one-bar Codex process was found.
- Report: `run_log/one_bar_50breakout_20261011/session_report.json`, marked `COMPLETED_EXPLORATORY_PROXY_WITH_EXECUTION_EXCEPTIONS`.
- Frozen rule: previous 50 completed 30m bars, long/short STOP at rolling extreme, one contract, $1,000 protective stop, exit next 30m open, maximum two filled entries per Globex day; execution underlying resolution is 1m.
- Input period: 2026-01-01–2026-07-31 inclusive; no August onward partitions selected. LSE NQ.F and ES.F remain unqualified continuous futures proxies with unknown dated-contract/roll mapping. EMD/YM not available in current LSE futures catalog.
- Native Engine proof **corrected** the prior suspected blocker: NEXT_BAR successfully fills a native stop at 101 on the next minute's high/low and a later market exit at the next 1m open. The runner recorded proof in `native_engine_gate.json`.

## Reproduced summary (USD, one contract)

| Instrument | Trades | Zero-cost total P&L | Cost-aware total P&L | Average cost-aware P&L/trade | Win rate (cost aware) | Profit factor (cost aware) | Daily-equity Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|
| NQ.F | 278 | +2,871.00 | -1,009.00 | -3.63 | 44.96% | 0.9883 | -0.0697 |
| ES.F | 273 | -8,625.00 | -16,777.50 | -61.46 | 41.03% | 0.6730 | -2.4608 |

Cost-aware assumptions: $2.50 commission per contract per fill plus one tick adverse slippage per fill. This is not a verified broker execution schedule. Initial simulated cash $1,000,000 per individual market; gross account percentages must not be confused with return on margin or a combined strategy.

**Independent arithmetic verification:** Read each saved trades.csv with Polars and sum `pnl`; all 278 NQ and 273 ES trades per trial have `status=closed`. In all four trials, summed trade P&L exactly matches `metrics.json`'s final_value minus initial_cash: NQ +2,871 / -1,009; ES -8,625 / -16,777.50. Verified NQ maximum hold 41 minutes and ES 30 minutes.

**Focused test invocation:** `uv run --no-sync python -m pytest -q tests/test_one_bar_50breakout_20261011.py`: 3 passed in 1.44 s. These tests cover the native stop/open proof, protected partition exclusion, and Globex day alignment. They are **not** full independent tests of all trading and cost invariants.

## Remaining important exceptions

- Same 1m candle crossed entry trigger and potential protective stop in 18 NQ and 5 ES cases; intraminute sequence unknown and protective stop cannot be installed until entry is observed. Results therefore are *as-modeled*, not an exact historical execution replay.
- One NQ exit occurred late (41-minute maximum hold), due to missing next-boundary source bar; the exact next-30m-open exit invariant did not hold for that trade.
- A few provider prices are off standard quarter-point tick grid. Provider futures-proxy continuous-roll mapping is unverified.
- Four-market confirmation is not possible: there is no EMD or YM dataset in the live LSE futures catalog. The comparison is retrospective January–July 2026, not independent protected final holdout.
- The report's `diagnostics[].price_performance_reason` still has stale language from its signal-only precursor, but the explicit `backtests[]` and four cost-specific ledgers are present and internally consistent. Interpret the latter as the actual executed results.

## Decision

**Exploratory NQ/ES proxy runs completed. Net edge not supported in this sample.** Do not promote strategy to approved/live. The study does not establish that the original manager's CME futures strategy fails under their historical data, execution/cost assumptions, or a broader volatility regime. For an executable confirmation, use dated CME contracts with verified roll semantics and test protective-stop/next-open edge cases. Preserve exact original strategy parameters.
