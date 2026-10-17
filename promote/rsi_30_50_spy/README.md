# RSI(5) 30/50 — independent SPY mean-reversion research candidate

**Workflow:** PROMOTED_FOR_FURTHER_RESEARCH. **Research:** EXPLORATORY. **Live approval:** NOT_APPROVED.

This package freezes an independent RSI mean-reversion strategy for further audit. It is **not part of Shannon-20** and has not been merged into the five-strategy analytical portfolio. Its current backtest trades a **Dukascopy ES index/CFD price proxy**, not actual SPY ETF shares.

## Frozen tested rule

At a completed daily bar, enter long when native ML4T RSI(5) is below 30 and close is above native SMA(200). Exit when RSI(5) is at least 50. The native ML4T broker executes orders at the next daily bar under the source runner's `ExecutionMode.NEXT_BAR`. Binary-rule sizing targets 95% of current equity when long; initial synthetic equity is 100,000. No short positions. Feature/warmup semantics and original Yahoo SPY source-rule parity remain unqualified.

Source-data store: `/home/quant/dev/quant/ml4t-data/.data/store/index_minute_ES`, grouped by NY 17:00 session end. Native scored history 2011-09-19 through 2026-10-09. The raw input cutoff is strictly before 2026-10-12 00:00 UTC. Direct exploratory friction: 2 bps commission + 2 bps slippage **per side**. ETF dividends, actual bid/ask, CFD financing, instrument lot/tick mapping and participation impacts are not independently modeled.

## Archived native result, not confirmation

101 native closed trades; +101.55% compounded native account return, Sharpe 0.78, maximum drawdown -10.48%. Under 3× the assumed fee and slippage (12 bps combined per side), native return +72.92%. These figures are **not a fresh holdout**: the five candidates were selected on observed 2020–2022 results; 2023–2026 has since been reviewed. Full results, yearly metrics, independent ledger integrity audit and stress artifacts remain under canonical `run_log/independent_five_full_history_20261014/`; package `reports/native_summary.json` and `reports/cost_stress.json` are frozen snapshots.

## Package and exact reproducibility boundaries

- `strategy.yaml`: instrument, rules, cost, research status and blockers.
- `STATUS.md` and `research_next.md`: decision and next validation falsifiers.
- `src/`, `tests/`: **byte-identical frozen snapshots** from repository source; these scripts retain original import paths and must run from the root checkout. A snapshot alone is not a self-contained Python environment.
- `audits/evidence.md`: source and audit identities, limitations.
- `provenance/data_manifest.json`: source coverage and market clock.
- `provenance/manifest.json`: content hashes, source paths and canonical ledger pointers.
- `scripts/verify_package.py`: read-only verification of frozen package bytes and source artifacts.

From repository root run `uv run python promote/rsi_30_50_spy/scripts/verify_package.py`. The canonical test is `uv run python -m pytest -q -o addopts='' tests/test_independent_seven_native_features.py`. To regenerate the full previously specified five-run sample, use `uv run python -m scripts.run_independent_five_full_history_20261014` **only after explicitly deciding to rerun the entire registered trial**, and compare against the frozen artifacts. The package verifier does **not** repeat backtests.

**Scientific boundary:** research packaging preserves existing evidence and does not certify source parity, a genuinely untouched out-of-sample period, or live trading. Keep original runs and failed candidates unchanged. New parameter research requires a new frozen session.
