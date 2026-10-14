# Milkman six index-CFD adaptations — native Engine MVP audit

Date: **2026-10-14**. Mode: MVP Research. Status: **EXPLORATORY / NOT_APPROVED**.
This report supersedes incomplete preliminary execution attempts for this program.
No futures, stock or option replication is claimed, and nothing is approved for trading.

## Executive outcome

**All six native ML4T Engine executions completed and independent broker ledgers reconciled.**
Four strategies generated trades; two did not generate an eligible trade in the
frozen execution window. Neither positive proxy run clears an economic/robustness
qualification. No portfolio addition is authorized.

| Candidate | CFD proxy | Development period | Closed trades | Net equity return | Native daily marked-equity Sharpe | Research disposition |
| --- | --- | --- | ---: | ---: | ---: | --- |
| Morning Dip Limit | NQ | 2022 Q1 | 183 | -1.1388% | -6.403 | Negative CFD MVP |
| Legend's Buy Day | ES | 2022 Q1 | 8 | +0.1989% | +2.185 | Positive, unqualified: too few trades |
| Legend's EMA | NQ | 2022 Q1 | 0 | 0.0000% | undefined | Inconclusive: zero qualifying signals |
| Bilbo Box v2 | NQ | 2022 Q1 | 0 | 0.0000% | undefined | Inconclusive: zero qualifying signals |
| Swing Golden Gate | ES | 2020-2022 | 5 | +0.7101% | +0.708 | Positive, unqualified: only 5 trades |
| Daily Bilbo Boxes | ES | 2020-2022 | 20 | -1.9866% | -0.691 | Negative CFD MVP |

Sharpe is from daily marked equity using `ml4t.backtest.analytics.sharpe_ratio`
with 252-day annualization. **Do not use `result.metrics['sharpe']` on intraday
feeds** for portfolio comparison. It is a bar-level statistic. Zero-trade
Sharpe is undefined economically. Max drawdown and win rates on these tiny
samples do not establish stability.

## Frozen inputs and live repository context

- Program: `config/milkman_native_mvp_20261014.yaml` (frozen before trials).
- Source / feature mapping: `config/milkman_source_to_cfd_features_20261014.yaml`.
- Repository at audit: branch `local-first-main-sync-20261014`,
  HEAD `144132cd3986929aa5f1367d004be1c8bfd01d59`.
- Dependencies: `ml4t-engineer==0.1.4`, `ml4t-backtest==0.1.7`,
  `ml4t-data==0.1.0b14`. Native `Engine(DataFeed(...), Strategy(), BacktestConfig(...)).run()`.
- Data: canonical `/home/quant/dev/quant/ml4t-data/.data/store/index_minute_NQ`
  and `index_minute_ES`. Source is Dukascopy price CFD aliases, **not**
  dated CME NQ/ES futures; broker tick/quote volume is not exchange volume.
  No canonical store was modified.
- Capital: $100,000, single-strategy notional size 10% of equity.
  Native fractional share accounting is a normalized CFD price exposure proxy;
  futures contract multipliers and actual broker margin were not modeled.
- Baseline friction: **2 bps commission + 2 bps slippage per side**.
  These are declared exploratory placeholders, not measured CFD bid/ask
  spreads, financing, borrow, funding or impact. Net figures are not
  certified broker-executable PnL.
- No data on or after **2025-01-01 UTC** were loaded for this program.
  The separate 2025-2026 portfolio allocation evaluation remains LOCKED.
- No parameter optimization, automated strategy selection or promotion.

## Engine behavior versus author rules

1. **Morning Dip Limit:** Native LIMIT buy order can rest for nine minutes.
   The price/exit checks use completed 1-minute CFD bars and NEXT_BAR market
   exits, rather than one-second NQ futures price-through-limit and
   tick-level adverse-first exit priority. It is an execution adaptation.
   Trading costs consume much of the high-turnover model.
2. **Legend's Buy Day:** Setup counts three lower completed overnight-session
   closes. The CFD feed closes around 16:15 ET rather than the source's
   16:59 ET futures print. Engine BUY and SELL occur at the next available
   raw CFD minute bar's open. Eight positions have native fills and closed PnL;
   low sample power prevents a qualification.
3. **Legend's EMA:** Replaces the source's future-contaminated whole-sample
   trend-day 80th percentile with the **previous 252 completed sessions**.
   Direction is read after the 09:30 opening minute; entry is the next
   tradable minute. This fixes same-open lookahead at the cost of fidelity.
   Zero trades in 2022 Q1; this is NOT a proof of no historical edge.
4. **Bilbo Box v2:** Native EMA, ATR and sample STDEV feed a tested local
   Phase Oscillator extension. The first close-confirmed hourly breakout
   drives a CFD underlying position. Options strikes, expiry, NBBO,
   fills and premium PnL are out of scope (BLOCKED_DATA).
   Zero qualifying entries in the frozen 2022 Q1 price-proxy sample.
5. **Swing Golden Gate:** Monthly ATR rails and the EMA gate are computed
   causally from completed data. The downside-break short uses a native
   resting STOP order. Exit conditions rely on daily OHLC, which cannot
   establish all intraday stop/target priorities. The final trial uses
   native MOC for scheduled end-of-month exit and finishes with five
   closed trades and no open positions.
6. **Daily Bilbo Boxes:** The current CFD variant uses a
   close-confirmed box-break observation and NEXT_BAR market entry.
   This is **not** the author's working buy STOP at box high. Its daily
   EMA50 trail observes completed bars and exits next-bar.
   It is a weak adapted hypothesis and its negative result is not
   source strategy invalidation.

Neither Bilbo candidate is an economically independent signal family
until correlation and drawdown-overlap studies prove otherwise.

## Independent verification evidence

Canonical machine-readable audit:
`docs/audit/milkman_native_engine_20261014_verification.json`.
It checks timestamp uniqueness and protected-cutoff boundaries, validates
fill timestamps against price windows, reconciles each Engine final equity
against the sum of native trade-ledger PnL (within $0.02), and recomputes
daily marked-equity Sharpe/Sortino through native ML4T analytics.

- Native attempts, immutable input price/signal Parquet hashes, report.json,
  `fills.csv`, `trades.csv`, `equity.csv`,
  `rejected_orders.csv`: under `run_log/milkman_native_cfd_mvp_20261014_retry2/`.
- **Swing final corrected month-end MOC attempt**:
  `run_log/milkman_native_cfd_mvp_20261014_retry3/swing_golden_gate/`.
- **Historic failed/superseded attempts preserved:** the original
  `run_log/milkman_native_cfd_mvp_20261014/` contained a
  missing `asset` signal-column failure; `retry1` included warmup-only
  timestamps on the execution feed and a Swing position open at the
  final boundary. `retry2` fixes the execution-clock union;
  `retry3` fixes the Swing month-end liquidation.
- First broker audit found that engine intraday-bar Sharpe was not a valid
  daily portfolio Sharpe; the present report uses native daily metrics.
- **Integration tests:** 12 passed, including next-bar execution, native
  STOP/MOC, parity/warmup, previous-session threshold, PIT gate and future
  perturbation. `ruff check` passed for task-owned new code.
- Original source futures/options parity, certified broker costs, contract
  identity, tick-order priority and exact calendar/holiday fills remain
  unverified. The resulting positive PnL cannot be promoted.

## Final decisions

- `morning_dip_limit` — **REJECT this bounded CFD MVP**. The negative
  test is not a source-futures result.
- `daily_bilbo_boxes` — **REJECT this close-confirmed index-CFD adaptation**.
  The author's stock/stop-entry strategy has not been disproved.
- `legends_buy_day` — **INCONCLUSIVE for portfolio use** despite positive
  development equity. Larger pre-2025 source-qualified samples and verified
  financing/execution assumptions are needed.
- `swing_golden_gate` — **INCONCLUSIVE for portfolio use** despite positive
  development equity. Five closed trades across three years is inadequate.
- `legends_ema` and `bilbo_box_v2` — **INCONCLUSIVE_NO_TRADES**, not
  failed strategies. Larger causally registered samples would be new counted
  trials, not an authorized optimization.

**Portfolio contribution stage not executed:** no candidate qualified a
daily marked-equity ledger with sufficient signal coverage and cost
verification to justify changing the existing allocation research.
Existing portfolio strategies were not modified.

All artifacts are deliberately uncommitted on a shared dirty checkout.
No concurrent artifacts were reset/cleaned, no Git branches pushed, no
statuses promoted, and no trading system deployed.
