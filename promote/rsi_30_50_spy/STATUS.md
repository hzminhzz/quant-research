# Promotion status — RSI 30/50 SPY variant

- Workflow: `PROMOTED_FOR_FURTHER_RESEARCH` (archived candidate, not production).
- Research classification: `EXPLORATORY` / selected using historical positive 2020–2022 Sharpe.
- Approval: `NOT_APPROVED`; live and paper deployment **not authorized** by this package.
- Exact frozen test data: Dukascopy-derived ES CFD/index proxy, **not** dividend-adjusted SPY ETF.
- Scored span: 2011-09-19 through 2026-10-09. Raw data at/after 2026-10-12 excluded.
- Native engine: `ml4t-backtest==0.1.7`; native features: `ml4t-engineer==0.1.4`.
- Native after-cost result: +101.55% compounded, Sharpe 0.78, maximum drawdown -10.48%, 101 closed trades. At 3x modeled costs, +72.92%.
- Verified claim: original five-run artifact hash/ledger integrity audit passed. Candidate source code snapshots, report and manifest are preserved.
- Unverified: exact SPY ETF parity, dividends, vendor session/calendar rules, broker fees/spread/financing, outside-holdout significance, the uploaded variant's omitted rising-average filter.
- Trials: selected from seven prior strategies based on observed 2020–2022 Sharpe. All seven trials, five full-history runs, and 2x/3x cost results remain in canonical `run_log/` folders. Source-author prior search history unknown.

This is a **copy into a research archive**, not a move of canonical files. Preserve failed attempts and other independent strategies. A new frozen research session is required for substantive changes.
