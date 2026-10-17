# One-bar NQ 30-minute strategy tearsheet, 2013–2026

**Status:** Exploratory retrospective report. The strategy remains `NOT_APPROVED`. This report does not approve live trading.

## Data and method

The report reads the completed annual `evaluation_trades.csv` ledgers from 2013 through 2026. It uses evaluation trades only and excludes warmup and duplicated boundary trades. PnL uses one hypothetical contract at $20 per index point. The source is Dukascopy `USATECH.IDX/USD` BID-only index/CFD data. It is not a dated CME NQ contract.

The costed trial models $2.50 per fill and 0.25 adverse index points per fill. Its ledger `gross_pnl` is costed gross PnL: modeled slippage remains in fills, and commissions are excluded. Its `pnl` is net of both. The zero-cost trial provides a separate aggregate comparison. Some trades have different exit timestamps across cost variants, so the $81,458.46 aggregate difference is not pure accounting fees or row-matched attribution. Annual engine accounts reset to $1,000,000; this report separately reconstructs cumulative realized cash flows across years. The report uses installed `ml4t.backtest.analytics` and `ml4t.diagnostic.api.PortfolioAnalysis` for risk statistics. Polars aggregates Chicago session-date cash flows. UTC exit timestamps are converted to `America/Chicago`; exits at or after 17:00 map to the next session date. The report includes Monday-Friday dates from first to last mapped exit, including holidays with zero PnL, and excludes weekend dates. UTC Sunday exits that map to Monday remain included. Each daily return equals that day's PnL divided by the previous day's reconstructed continuous realized equity, starting from an assigned USD 1,000,000. The series uses zero risk-free rate and 252 periods per year. This is a weekday proxy calendar, not an exchange holiday calendar.

The plotted curves and drawdown metrics use realized trade cash flows. They do not mark open positions each day and are not native engine mark-to-market equity. The $1,000,000 base is only a scaling convention. It is not verified margin or account capital. No comparable buy-and-hold close series is included, so this report omits the benchmark.

## Costed trial metrics

| Metric | Value |
|---|---:|
| Closed evaluation trades | 5,462 |
| Zero-cost trial PnL | $247,566.38 |
| Costed gross PnL before commission (slippage remains in fills) | $193,417.92 |
| Net PnL | $166,107.92 |
| Commission drag within costed trial | $27,310.00 |
| Total difference versus zero-cost trial | $81,458.46 |
| Net PnL per trade | $30.41 |
| Trade win rate | 47.8% |
| Profit factor | 1.267 |
| Net session-weekday Sharpe (252, RF 0) | 1.279 |
| Net daily Sortino | 2.106 |
| Net realized-cashflow CAGR | 1.104% |
| Net Calmar | 0.521 |
| Maximum realized-cashflow drawdown | $-21,212.14 (-2.121%) |
| Maximum drawdown as percent of running peak | -2.121% |
| Underwater weekday sessions | 3,184; max run 1,590 sessions |
| Daily 95% VaR / CVaR | $-786.22 / $-1,249.19 |
| Best / worst net trade | $6,608.68 / $-9,116.86 |
| Long trades / PnL | 3,292 / $75,179.94 |
| Short trades / PnL | 2,170 / $90,927.98 |

## Frequency-fix metric changes

| Metric | Previous calendar-day value | Corrected weekday-session value | Change |
|---|---:|---:|---:|
| Sharpe | 1.061 | 1.279 | +0.219 |
| Sortino | 1.737 | 2.106 | +0.369 |
| Max drawdown as percent of running peak | -2.121% | -2.121% | +0.000% |
| Calmar | 0.404 | 0.521 | +0.117 |

## Annual costed evaluation PnL by entry-session year (unchanged)

| Year | Trades | Zero-cost PnL (USD) | Costed gross before commission (USD) | Costed net PnL (USD) | Net/trade (USD) |
|---:|---:|---:|---:|---:|---:|
| 2013 | 319 | 2,191.60 | -998.40 | -2,593.40 | -8.13 |
| 2014 | 393 | 1,532.00 | -2,398.00 | -4,363.00 | -11.10 |
| 2015 | 388 | 6,082.62 | 2,202.62 | 262.62 | 0.68 |
| 2016 | 369 | -1,984.70 | -5,674.70 | -7,519.70 | -20.38 |
| 2017 | 340 | 1,010.52 | -2,389.48 | -4,089.48 | -12.03 |
| 2018 | 424 | 17,534.74 | 13,314.74 | 11,194.74 | 26.40 |
| 2019 | 405 | 14,622.88 | 10,577.88 | 8,552.88 | 21.12 |
| 2020 | 437 | 15,719.22 | 11,469.22 | 9,284.22 | 21.25 |
| 2021 | 444 | 38,275.12 | 33,905.12 | 31,685.12 | 71.36 |
| 2022 | 440 | 61,419.56 | 57,214.56 | 55,014.56 | 125.03 |
| 2023 | 433 | 28,408.76 | 24,163.76 | 21,998.76 | 50.81 |
| 2024 | 416 | 23,996.98 | 19,976.98 | 17,896.98 | 43.02 |
| 2025 | 416 | 49,564.04 | 45,030.58 | 42,950.58 | 103.25 |
| 2026 | 238 | -10,806.96 | -12,976.96 | -14,166.96 | -59.53 |

2026 ends on 2026-07-14. The costed 2026 net PnL is $-14,166.96. The later period remains protected.

No Deflated Sharpe Ratio is reported. This report does not contain the complete historical strategy trial universe needed to estimate selection bias. The package trial ledger records failed and completed attempts; these annual A/B results do not by themselves define every prior choice.

## Decision and limits

The 2013–2026 historical replay is positive in aggregate after the specified modeled costs. This supports only a descriptive statement about these ledgers. It does not establish a tradable CME NQ result. In particular, 2026 is negative, the source is a BID-only proxy, source-to-contract mapping and actual costs are not verified, and minute OHLC cannot establish event ordering or atomic OCO behavior. The separate conservative ambiguity diagnostic is not a native replay and is not substituted into the totals here. No holdout remains unseen because this is retrospective reporting.

The strategy remains `NOT_APPROVED`. The next decisive question is whether a verified dated CME NQ replay with bid/ask data, native OCO execution, and certified fee and roll assumptions preserves positive net results without using protected post-2026-07-14 data.

## Artifacts

- `one_bar_nq_tearsheet_2013_2026.png`: annual and monthly panels.
- `metrics.json`: machine-readable metrics and method.
- `daily_equity.csv`: realized daily cash flows and reconstructed cash-flow curves.
- `monthly_pnl.csv`: monthly gross and net realized PnL.
