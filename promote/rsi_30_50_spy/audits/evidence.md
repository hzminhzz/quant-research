# Evidence and limits: RSI 30/50

User selected this candidate for research promotion on 2026-10-14, after screening seven variants on 2020-2022 Sharpe and later reviewing full history. This selection is exploratory, not a prospective final test.

Canonical evidence: run_log/independent_five_full_history_20261014/rsi-30-50/. It contains native ML4T prices and signals Parquet, fills, trades, equity and rejected-order ledgers. The package includes the native summary and hashes but does not duplicate large datasets or ledgers. The original five-case audit PASS is at run_log/independent_five_full_history_20261014/audit.json.

The core engine outputs are internally reconciled, but original SPY ETF rules and market data have not been reproduced. Data uses Dukascopy ES index/CFD proxy, with missing dividends, financing, true spread and broker mapping. Native backtest costs are research assumptions. The two higher-cost trials were made after baseline results had been inspected.

Copied code and test files are snapshots, not standalone executable modules. They retain their original root repository import paths. The package verifier checks copied bytes and source hashes, not the economic claims.
