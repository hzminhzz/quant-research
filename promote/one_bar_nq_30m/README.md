# One-bar NQ 30-minute research package

> **PROMOTED FOR FURTHER RESEARCH — B0 RETAINED.** The original fixed 50-point-stop B0 is the user-selected promoted version. The separate fixed-percentage and B2 ATR/MNQ stop alternatives were tested but not selected to replace B0. This promotion does not certify live CME execution. See `AGENTS.md` and `promote/INDEX.md`.

This package records an exploratory one-bar breakout candidate. It is not approval to trade. The underlying prices are Dukascopy USATECH.IDX/USD BID data. They are a CFD/index proxy, not verified CME E-mini Nasdaq-100 futures data. The one-contract, USD 20 per point mapping is illustrative.

## Frozen rule description

Use the high and low of the prior 50 complete 30-minute bars. Submit one buy stop at the high and one sell stop at the low. Cancel the other entry after the first fill. Use one illustrative contract in either direction. Set a nominal USD 1,000 protective stop. Exit at the opening print of the immediately following 30-minute bar. Allow at most two entries per Chicago session day. Use extended hours. Add no filters.

## Native feature implementation

The annual feed builder computes its 50-bar upper and lower breakout levels with ML4T Engineer's registered `donchian_channels` feature through `compute_features`.

- Method: `ml4t-compute-features` (`.agents/skills/ml4t-compute-features/SKILL.md`) selected the registry feature API; `ml4t-lookahead-bias` (`.agents/skills/ml4t-lookahead-bias/SKILL.md`) requires causal availability; `ml4t-run-backtest` (`.agents/skills/ml4t-run-backtest/SKILL.md`) preserves the event-driven strategy and fills.
- Discovery found `donchian_channels`; `period=50` has lookback 49. No feature selection was run because this is a frozen, single-feature rule.
- Verification: `tests/test_one_bar_practical_yearly_20261012.py::test_ml4t_donchian_levels_match_the_50_bar_breakout_window` checks warmup and rolling-window boundaries. Discovery is metadata, not profitability or strategy approval.

## Evidence status

An earlier retrospective proxy run reported positive costs-adjusted historical values. The remediation audit found delayed exits, unresolved OCO behavior, and intraminute ambiguities. A later annual native-engine replay completed, but its source remains a BID-only CFD proxy and its OHLC event-order limits remain. Do not treat the earlier result as corrected performance or as evidence of CME execution edge.

The practical native-engine yearly run is marked `completed` in its canonical ledger at this packaging snapshot. This package includes completed per-year outputs for 2013–2026, where both zero-cost and full-tick trials have completed summaries and ledgers. The 2026 costed annual result is negative (238 trades, -$14,166.96). Annual outputs still retain modeled OHLC ambiguities, and the native broker does not provide atomic OCO. This result does not resolve those execution limits or approve the strategy. Consult `STATUS.md` and the copied trial ledger for exact results.

## Contents and reproduction

- `src/` and `tests/` are snapshots of the task-owned root scripts and tests. They retain their original workspace paths and dependencies.
- `backtests/` contains copied completed run artifacts. Superseded duplicate-logic directories and transient logs are omitted. Their source run paths are recorded in `provenance/manifest.json`.
- `data/data_manifest.json` identifies the canonical external source. The raw multi-million-row Parquet store is not duplicated.
- Run `python promote/one_bar_nq_30m/scripts/verify_package.py` from the repository root to validate required files, YAML, and SHA256 values.
- After the yearly job has completed, run `python promote/one_bar_nq_30m/scripts/refresh_completed_runs.py` from the repository root to copy only years with completed summaries and both completed trial artifacts. This script does not write to source runs.
- To reproduce source backtests, use the copied runner with the source workspace and its original dependencies, then compare outputs with the frozen specs and manifests. The external raw dataset must be present at its canonical path and pass the frozen hashes. A package copy alone does not contain that dataset.

## Research limitations

The native broker cannot enforce atomic OCO. Minute OHLC cannot establish the order of events inside a minute. Stop gaps can exceed the nominal USD 1,000 risk. The input is BID-only and does not provide verified ASK quotes. The cost assumptions are illustrative. The historical trial set is retrospective and incomplete for multiple-testing correction. No protected data after 2026-07-14 was used by the historical strategy run.

See `audits/` for the review reports. The original run folders and source files remain in place.
# Retrospective tearsheet

The annual practical replay summary is available in [`reports/one_bar_nq_tearsheet_2013_2026.md`](reports/one_bar_nq_tearsheet_2013_2026.md), with the PNG, machine-readable metrics, daily realized cash-flow series, and monthly PnL in the same directory. Regenerate it with:

```bash
python promote/one_bar_nq_30m/scripts/generate_tearsheet.py
```

The report uses completed evaluation-trade ledgers only. It does not rerun the backtest. It is a retrospective report of a BID-only Dukascopy index/CFD proxy, not verified CME NQ performance. It does not change the `NOT_APPROVED` status. Its cumulative realized cash-flow series does not mark open positions and does not represent native mark-to-market equity.

## 2026 regime attribution

See [the historical 2026 regime report](reports/regime_2026/README.md) and its [machine-readable metrics](reports/regime_2026/metrics.json). This is an accounting and conditional-attribution review. It does not change the fixed strategy or its `NOT_APPROVED` status.

## Separate Hyperliquid shadow runner

Run `uv run python scripts/run_one_bar_shadow_xyz100.py` for a virtual shadow session on Hyperliquid `XYZ100`. It does not place exchange orders: `SignedEquitySafeBroker` uses a `NullBroker` adapter and writes owner-only audit and risk state under `~/.local/state/xyz100_shadow/`. Older run records remain under `run_log/paper_trading/xyz100_shadow/`.

Shadow equity uses signed position quantities for drawdown checks. This avoids treating short-sale proceeds and the short liability as two positive account assets in the installed ML4T virtual portfolio.

The runner retries CCXT network, request-timeout, and exchange-unavailable errors indefinitely, with exponential backoff capped at 30 seconds. Separately, LiveEngine halts the runner after 180 seconds without a market event; this silence stop does not limit retry attempts. After an exit, the runner suppresses another entry for the remainder of that 30-minute bar so repeated evolving-bar updates cannot replay an entry.

This is not an NQ backtest replay or a broker paper account. It uses Hyperliquid live bars and virtual trigger-price fills, with no verified exchange execution costs. SafeBroker's quote-based staleness and price-deviation checks are disabled because evolving bars do not provide quote snapshots; LiveEngine rejects stale events and halts after 180 seconds without an event, while SafeBroker retains configured size and loss limits. It does not change this candidate's `NOT_APPROVED` status.
