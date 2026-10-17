# Donchian BTC — independent trend-following research candidate

**Workflow:** PROMOTED_FOR_FURTHER_RESEARCH. **Research:** EXPLORATORY. **Live approval:** NOT_APPROVED.

This package freezes an independent BTC Donchian strategy for additional research. It is **not part of Shannon-20** and is not a component of any merged broker-account portfolio. The source variant targeted Yahoo `BTC-USD`; the tested research market is **Binance BTCUSDT perpetual**, with shorting and funding mechanics that differ from spot BTC.

## Frozen tested rule

Nine close-based Donchian direction channels with windows 10, 15, 20, 30, 45, 65, 95, 140 and 200. Each channel holds a +1 or -1 direction after a breakout of prior CLOSE extremes, and carries the previous direction otherwise. Their average is scaled using native ML4T 60-bar daily return standard deviation to target 25% annual volatility with a 2× leverage cap. The original implementation uses a 252 annualization convention even though BTC is available every day. The native ML4T strategy rebalances exposures on completed daily UTC bars using `ExecutionMode.NEXT_BAR`; margin is modeled at 50% initial. Broker funding/borrow/liquidation and exact instrument parity have not been certified.

Canonical input: `/home/quant/dev/quant/ml4t-data/.data/store/crypto_futures_minute_BTCUSDT_PERP`, daily UTC aggregation; scored 2019-09-09 through 2026-10-11; source-data cutoff before 2026-10-12 00:00 UTC. Exploratory direct costs 5 bps commission + 2 bps slippage per side, with higher-cost sensitivity. Synthetic initial account equity is 100,000.

## Archived native result, not confirmation

+208.18% compounded native account return, Sharpe 0.68 and maximum drawdown -25.07%. The native engine reports 1,102 closed-trade events and 2,506 fills; frequent resizing means those are **not 1,102 independent trading signals**. At 3× modeled commission and slippage (21 bps total per side), the native return is +174.66%. This cannot establish a tradable perpetual edge without funding and complete financing accounting. The 2020–2022 development history selected these candidates, and 2023–2026 has already been reviewed; neither is an untouched new holdout.

## Package and exact reproducibility boundaries

- `strategy.yaml`: frozen rule, exposure sizing, market identity and blockers.
- `STATUS.md` and `research_next.md`: scientific status and next test program.
- `src/`, `tests/`: byte-identical snapshots from the root checkout, retaining original import paths. They require the root repository and its installed ML4T dependencies.
- `reports/native_summary.json`, `reports/cost_stress.json`: frozen native artifacts; full fill/equity/price/signal ledgers remain in `run_log/independent_five_full_history_20261014/`.
- `provenance/data_manifest.json`, `provenance/manifest.json`: source and content hash identities.
- `scripts/verify_package.py`: read-only verification; no backtest or live orders.

From repository root run `uv run python promote/donchian_btc/scripts/verify_package.py`. Regression check: `uv run python -m pytest -q -o addopts='' tests/test_independent_seven_native_features.py`. To rerun the **registered full five-case exploratory trial**, use `uv run python -m scripts.run_independent_five_full_history_20261014` only after deciding to regenerate canonical artifacts.

**Scientific boundary:** packaging is preservation only, not a fresh performance test or production authorization. Keep trial history intact. Register any future rule or venue changes as new research sessions, and explicitly record failing trials.
