# USDJPY Tokyo Gotobi 2020–August 2026, USD 10,000

**Session:** `usdjpy_gotobi_2020_2026_usd10000_v1`  
**Status:** EXPLORATORY / NOT_APPROVED  
**Trading:** None; native event-driven backtest only  
**Holdout:** September 1–October 9, 2026 (not opened)

## Execution and provenance

- Repo `/home/quant/dev/quant/quant-research`, branch `main`, baseline HEAD `c095faa`.
- The prior fixed Tokyo Fix hypotheses were retained without entry-time, exit-time, or threshold optimization.
- Input provider: `ml4t-data` LSE USDJPY 1-minute OHLCV, immutable subset of Tokyo fixing windows.
- Source dataset `data/processed/gotobi_2020_2026_usd10k_v1/USDJPY_tokyo_windows_1m.parquet`, SHA256 `c740244cfdd42c53f12f623f9923ab5b7f46f51e95fafc793841fdd723fb5867`.
- 2,185 original partition files scanned; 240,845 1-minute rows retained across 1,595 strictly complete Tokyo session windows (151 minute bars, 08:00–10:30 JST).
- 1,626 expected Tokyo `XTKS` business sessions; 29 incomplete sessions and 2 absent sessions excluded. Of 506 calendar Gotobi candidates, 492 have complete windows; 14 are missing.
- `XTKS` is a Tokyo exchange-calendar **proxy**, not a separately certified historical Tokyo bank calendar for all years. Tokyo banks close weekends, national holidays, and Dec 31–Jan 3: https://www.boj.or.jp/en/about/outline/holi.htm. Additional historic bank-specific closures would require a calendar revision and new trial.
- Data does not contain executable bid/ask quotes. 1-pip round-trip all-in cost remains an illustrative constant, not a valid historical broker spread.
- All historical results, including 2026, are retrospective; this is not an unseen out-of-sample validation.

## Frozen execution rules and USD accounting

H1 long: submit following 08:29 JST minute close, buy at 08:30 next-minute open, exit 09:54 next-minute open. H2 short: if the known 08:00–09:55 upward extension exceeds 1.5 times the standard deviation of the **preceding 20** complete session extensions, submit after 09:55 minute closes, short at 09:56 next-minute open, cover 10:30 next-minute open.

- Native `ml4t.backtest.Engine`; `NEXT_BAR`, `OPEN`, no hand-rolled backtesting loop.
- Starting economic balance: USD 10,000; fixed order size: 10,000 USD base units, no compounding. No stop-loss or volume-based position scaling was added.
- Native Engine ledger uses JPY as accounting currency and a 50% margin setting to accommodate historical quote-price variation. This is **not** an actual broker-margin representation.
- USD-realized proceeds calculated per filled trade as `JPY PnL / exit USDJPY`. USD account beginning and ending values are derived from these actual Engine fills and start at exactly USD 10,000.
- Static full round-trip slippage: JPY 0.005 per USD at entry and exit (1.0 pip total); commission 0.
- Daily Sharpe uses USD closed-trade-equity returns across Tokyo business days, including flat sessions. Reported drawdown is **closed-trade-only**, not full intratrade mark-to-market drawdown.

## Verified results after illustrative costs

| Outcome | H1 pre-fix long | H2 gated post-fix short |
| --- | ---: | ---: |
| Trades | 492 | 45 |
| Native order fills | 984 | 90 |
| Average gross pips | +2.5544 | +0.4600 |
| Average net pips | +1.5544 | -0.5400 |
| USD starting balance | 10,000.00 | 10,000.00 |
| Net realized PnL USD | +573.71 | -21.61 |
| Ending USD balance | 10,573.71 | 9,978.39 |
| Cumulative return | +5.737% | -0.216% |
| Net win rate | 53.25% | 46.67% |
| Daily-equity Sharpe (closed-trade method) | 0.715 | -0.120 |
| Max closed-trade drawdown | -$241.72 | -$48.58 |

### By calendar year — H1 costed

| Year | Trades | USD net realized PnL | Mean net pips |
| --- | ---: | ---: | ---: |
| 2020 | 67 | +120.84 | +1.90 |
| 2021 | 74 | +114.08 | +1.69 |
| 2022 | 77 | +107.78 | +2.16 |
| 2023 | 77 | +143.66 | +2.54 |
| 2024 | 75 | +50.20 | +1.25 |
| 2025 | 73 | -28.10 | -0.62 |
| 2026 Jan–Aug | 49 | +65.25 | +2.08 |

H2 triggers per year: 2020=5, 2021=10, 2022=8, 2023=12, 2024=4, 2025=0, 2026 Jan–Aug=6. H2 net 2023 USD +42.63, but cumulative H2 is negative.

## Factor/statistical decision

- H1 Gotobi gross mean +2.5544 pips (HAC 95% confidence interval [0.7582, 4.3506]).
- Matched-time ordinary-business-day mean +0.9026 pips; Gotobi minus ordinary mean +1.6518 pips, HAC 95% confidence interval [-0.5835, 3.8871] (**includes zero**).
- H1 gross-minus-1pip mean +1.5544 pips, with derived HAC interval [-0.2418, 3.3506] (**includes zero**).
- H1 mean net remains positive at hypothetical 0.8, 1.0 and 1.4 pip round trips, but cost realism unverified.
- H2 45 gated events gross mean +0.460 pips, HAC interval [-3.8576, 4.7776]; after 1 pip cost mean is negative (-0.540).
- H2's 5-quantile extension-reversal profile used `ml4t.diagnostic.quantile_profile`; this does not substitute for statistically significant trading profitability.
- **Do not claim a statistically verified Gotobi-specific edge or broker-ready strategy.**

## Reproducibility and independent checks

- `config/research_sessions/usdjpy_gotobi_2020_2026_usd10000_v1.yaml` frozen via research-session CLI.
- Data gate, H1/H2 event diagnostics, H1/H2 Engine simulations and independent fill audit: all six ledger trials recorded as `completed`. Completed means executed, **not approved**.
- `run_log/usdjpy_gotobi_2020_2026_usd10000_v1/T3_H1_engine_costed/native_fills_reconciled_trades.parquet` and analogous H2 parquet contain the executed fill-based per-trade economic ledger.
- Independent oracle: `T5_native_fill_oracle/result.json`, both legs pass exact source price, 1-pip slippage, native JPY PnL, and translated USD PnL reconciliation.
- `uv run python -m pytest -q tests/test_research_session_cli.py`: 12 tests passed; 6 third-party warnings.
- The current session is research-only. No live trading, commit, or push.

## Outstanding gates

1. Validate historical bank-specific Tokyo holiday calendar rather than using only XTKS proxy, especially observed rule changes and rolled days.
2. Calibrate broker historical spreads at 08:30, 09:54, 09:56 and 10:30 JST. Historical OHLC cannot provide executable bid/ask costs.
3. Measure intratrade drawdown and price stops using the original risk thesis as a **separate preregistered** test, not silently imposed on fixed windows.
4. H1 premium over ordinary days is not significant and 2025 has negative after-cost expectancy.
5. Do not open September–October 2026 holdout until an independent final spec and actual costs have been frozen.

**Disposition:** Implementation verified; economic hypothesis not yet statistically or execution-wise validated. **NOT_APPROVED**.
