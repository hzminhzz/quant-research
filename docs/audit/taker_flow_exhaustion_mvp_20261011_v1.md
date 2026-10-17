# Aggressive taker-flow exhaustion — fixed one-rule MVP

**Study:** 2026-10-11. **Classification:** EXPLORATORY. **Approval:** NOT_APPROVED. **Conclusion:** REJECT. The one fixed contrarian signal loses money both before and after costs during Jan–Jul 2026.

## Hypothesis and fixed trial

Extreme directional taker-flow demand can temporarily overshoot price, causing a reversal after market makers replenish liquidity. For BTCUSDT and ETHUSDT Binance USDT perpetuals, compute signed hourly quote-volume taker imbalance `(2*taker_buy_quote_volume - quote_volume)/quote_volume`. Require absolute imbalance at least the **95th percentile of the previous 720 valid completed hours**, hourly close-to-open return aligned with the imbalance, and quote volume at least its **previous 24-hour average**. Fade positive imbalance with a short and negative imbalance with a long.

Both signals and prior thresholds are from COMPLETE hourly source candles. Source timestamps are **bar starts**. On signal bar t, submit only during the callback for bar t+1h, execute through `ml4t.backtest` NEXT_BAR OPEN at t+2h, and close at t+6h (four-hour actual hold). Initial simulated cash $500, target 0.4× equity per instrument, maximum two positions and ≤1× marked gross equity. Do not overlap scheduled BTC/ETH 00:00, 08:00 or 16:00 UTC funding settlements. After backtesting, audit every fill against actual source funding timestamps; all held intervals were free of settlements, so the zero funding cash flow is valid **only for this restricted strategy**.

**Development:** 2026-01-01T00:00Z inclusive to 2026-08-01T00:00Z exclusive; warmup starts November 1, 2025. This period is known historical development, not independent OOS. **The 2026-08 onward protected TSMOM holdout was not read.** No ML, no parameter optimization, no secondary trading rule. Prior TSMOM taker-flow studies exist and prevent a claim of novel prospectively independent feature discovery.

## Result (one fixed rule)

| Measure | Result |
| --- | ---: |
| Available completed hourly development bars | 5,088 each asset |
| Extreme-flow signals before time/funding filter | 206 |
| Signals excluded due to scheduled funding overlap | 93 |
| Remaining admissible candidate signals | 113 |
| Positions actually opened and closed | 105 |
| All-market fills | 210 |
| Winners | 41 / 105 (39.0%) |
| Simulated initial cash | $500 |
| Gross portfolio return | **-7.57%** |
| Net portfolio return | **-12.12%** |
| Net final equity | **$439.39** |
| Daily-equity annualized net Sharpe | **-3.20** |
| Maximum net drawdown | **-12.62%** |
| Combined closed-trade net PnL | -$60.61 |
| Total trade commissions | $17.90 |
| Estimated slippage cost | $5.97 |
| Maximum observed positions | 2 |
| Peak marked gross exposure | 0.846× equity |
| Rejected orders | 0 |
| Cash / no-trade baseline | 0.00% |

**Standalone results** (each starts at $500; returns are not additive): BTC 56 trades, 23 winners, net return **-4.59%**, Sharpe -2.56, DD -4.90%; ETH 49 trades, 18 winners, net return **-7.87%**, Sharpe -2.75, DD -8.76%. Gross and net runs use the same signal ledger; different equity paths alter later percentage-based sizing.

**Decision:** Both price-only gross and execution-cost net results are negative. The net 12.62% drawdown violates the target 10% prop challenge maximum. The initial hypothesis is unsupported by this development trial. Do not tune percentile, filter or holding period on this data and call it validated.

## Data evidence and independent verification

Source inputs (unchanged): 
- BTC hourly `data/processed/crypto_tsmom_flow_inputs_20261008/btcusdt_1h.parquet`, SHA-256 `67528cbf7f936e41f34f08fa033b05cfb2800a9f21ee39e6048051dd577db8b7`.
- ETH hourly `data/processed/crypto_tsmom_flow_inputs_20261008/ethusdt_1h.parquet`, SHA-256 `f0c4959e7ed53afeb12cfe93e3776aa3047cb39be2759187d6cd3df866dacab1`.
- BTC funding `data/processed/crypto_tsmom_flow_inputs_20261008_v4/btcusdt_funding.parquet`, SHA-256 `750fd743783bc0285cde779d9c1573e12bf31b3c2f5a53b97e782ebcb8585a1a`.
- ETH funding `data/processed/crypto_tsmom_flow_inputs_20261008_v4/ethusdt_funding.parquet`, SHA-256 `ee1864a96892c708b4ed6cb784b13373b22015335d77412fab48fce226231c23`.

Original price inputs have 48,912 hourly bars each through July 31, 2026. Both 2026 development windows contain 5,088 consecutive hours, and funding files have 636 event observations per instrument over the window. Price OHLC, quote volume, taker buy quote, 60-minute completeness, duplicate timestamps and 8h funding schedule were validated in the runner. Prior 720-hour quantile and prior 24-hour volume thresholds shift one full hour to exclude the signal bar. A separate VPS read verified all 4 input SHA-256 hashes, all 113 candidate signals use bar-start t+2h entry and t+6h exit with no scheduled or recorded funding crossing, all 105 trades matched signal direction and four-hour duration (the runner fails on mismatch), 210 fills, zero order rejections, and gross exposure below 1× equity.

All net-performance metrics come from installed `ml4t.backtest` using continuous **daily** portfolio equity `EquityCurve`, not annualizing trade return by trade frequency. Execution costs are **4.5 bps taker commission + 1.5 bps percentage slippage per fill**, 12 bps per complete two-fill trade, applied by the engine. Source lacks historical bid/ask quotes and impact calibration; 1.5 bps is a research estimate, not fill evidence. Minimum quantity, tick-size and prop CFD execution differences also remain unmodeled. The script refuses to overwrite completed trial output.

## Reproduce and audit

- Frozen specification: `config/research_sessions/taker_flow_exhaustion_mvp_20261011_v1.yaml`.
- Versioned engine runner: `scripts/run_taker_flow_exhaustion_mvp_20261011_v1.py`.
- Regression checks: `tests/test_taker_flow_exhaustion_mvp_20261011_v1.py`.
- Outcome: `run_log/taker_flow_exhaustion_mvp_20261011_v1/trial_result.json`, `signal_ledger.parquet`, `transaction_ledger.csv`, `rejected_orders.csv`.
- Frozen research session: `run_log/research_sessions/taker_flow_exhaustion_mvp_20261011_v1/frozen_spec.json` and its trial ledger.
- Run on a clean artifact directory: `.venv/bin/python scripts/run_taker_flow_exhaustion_mvp_20261011_v1.py`. The existing outcome is immutable; a new evaluation must use a new trial identity and never overwrite this run.
- Three extra execution checks and four unit tests passed. No live trading, holdout read, or unrelated file modification occurred.

**Methodology:** ML4T strategy-workflow, point-in-time, Polars patterns, compute-features, evaluate-factor, run-backtest, cost-model. One fixed model-free structural mechanism with cost-aware execution and explicit rejection, not a performance optimization search.

**Next decision:** Do not promote this rule or optimize it in the same period. A different mechanism (for example, conditional trend continuation following aggressive flow rather than reversal) requires a separately registered exploratory study, not a re-interpretation of this failure.
