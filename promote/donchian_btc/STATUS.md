# Promotion status — Donchian BTC

- Workflow: `PROMOTED_FOR_FURTHER_RESEARCH` (archived candidate, not production).
- Research classification: `EXPLORATORY` / post-2020–2022 selection.
- Approval: `NOT_APPROVED`; live and paper deployment **not authorized** by this package.
- Exact frozen tested market: Binance BTCUSDT perpetual 1-minute aggregated to daily UTC. It is not Yahoo BTC-USD spot.
- Scored span: 2019-09-09 through 2026-10-11. Raw data at/after 2026-10-12 excluded.
- Native engine `ml4t-backtest==0.1.7`; native features `ml4t-engineer==0.1.4`.
- Native after-cost result: +208.18% compounded, Sharpe 0.68, maximum drawdown -25.07%. Engine records 1,102 closed-trade events and 2,506 fills, including rebalance trades. At 3x modeled costs, +174.66%.
- Verified claim: canonical native output hash/ledger audit passed, with zero rejected orders. Snapshots of current source code and reports preserved here.
- Unverified: signed perpetual funding, borrow/financing, liquidation, realistic leverage limits, original BTC spot strategy parity, market spread/impact, exact 252-vs-365-day annualization, and genuine unseen holdout.
- Trials: selected from seven prior 2020–2022 strategies. Complete seven-entry exploratory inventory, five extended runs, 2x/3x stresses remain outside this package. Source-author iteration count unknown.

This is a **research archive copy only**; it does not modify canonical scripts or evidence, and does not add the strategy to Shannon or a live portfolio. Future modifications require a new session and full trial accounting.
