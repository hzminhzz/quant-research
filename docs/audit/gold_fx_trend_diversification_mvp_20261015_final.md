# Gold/FX monthly ROC60 — native ML4T development MVP

**Status:** EXPLORATORY / NOT_APPROVED. **Decision:** REJECT THE FROZEN MVP.
Session: `gold_fx_trend_diversification_mvp_20261015`.
Frozen before trading outcomes: `config/research_sessions/gold_fx_trend_diversification_mvp_20261015.yaml`.

## Registered hypothesis and trading mechanics

The fixed hypothesis was that 60 completed-session own-price momentum,
re-evaluated once per calendar month, could create positive Gold/FX
trading returns and later diversify an NQ/ES/BTC-heavy portfolio.

- Dukascopy historical **Gold XAUUSD, EURUSD, AUDUSD** quote-based proxies.
  These are **not** named executable CFD broker contracts.
- Indicator: native `ml4t.engineer.compute_features` ROC(60), computed
  separately for each market on completed 17:00 New York session bars.
- Decision: after the first eligible completed session close of each month.
  Orders: native `ml4t.backtest.Engine` NEXT_BAR market execution.
- A single independent $100,000 book per market, target **10% gross
  equity notional**, monthly long/short sign rebalancing. No annual reset,
  optimizer, ML classifier or trial search.
- Development: January 2015 through December 2021. Earlier 2013–2014
  daily price history is warmup. 2022–2024 never enters this trial's
  signal, execution, or equity; 2025–2026 allocation holdout never accessed.
- Assumed cost: 2 bps commission and 3 bps slippage per side. The native
  broker applied these to every filled order.
- Missing: actual executable CFD bid/ask, overnight financing/swap,
  contract specifications, broker margin/currency conversions. Therefore
  results do not establish actual broker-executable PnL.

## Native Engine trial outcome

| Market | Native daily equity marks | Monthly decisions/fills | Net equity return | Native daily Sharpe | Native daily max DD | Cost charged (USD) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| XAUUSD | 1,694 | 84 / 84 | **-3.4869%** | **-0.3687** | **-5.3298%** | 242.00 |
| EURUSD | 1,813 | 84 / 84 | **+1.0849%** | **+0.1954** | **-1.3059%** | 266.88 |
| AUDUSD | 1,813 | 84 / 84 | **-4.7543%** | **-0.6790** | **-5.6205%** | 280.38 |

No rejected orders. One real inventory position remains marked-to-market
at the end of each standalone trial. Native trade-ledger `partial` rows
represent **realized partial closes**, not additional open positions.
The initial runner's `open_trades_at_boundary` field incorrectly counts
`partial` rows as open; the **independent audit corrects this to one
true open position per strategy** without changing historical artifacts.

Positive or negative period returns are calculated from complete
native marked equity including commission and slippage. Native
`ml4t.backtest.analytics.sharpe_ratio` and `max_drawdown` operate
on daily marked equity rather than intraday fills.

## Development subperiod evidence

| Market | 2015–2017 return* | Daily Sharpe | 2018–2021 return* | Daily Sharpe |
| --- | ---: | ---: | ---: | ---: |
| XAUUSD | -4.991% | -1.283 | +1.697% | +0.315 |
| EURUSD | +1.233% | +0.426 | -0.099% | -0.035 |
| AUDUSD | -2.185% | -0.684 | -2.598% | -0.669 |

*Each row is the first-to-last equity change inside the specified
subperiod, not an independently reset account. The two displayed
changes do not need to sum to the full-sample return.

Only EURUSD is positive overall, and its later subperiod is flat to
slightly negative. Gold switched from negative early to positive late;
AUDUSD was negative in both groups. Thus the preregistered condition
for at least two positive candidates fails. No cross-market selection,
portfolio allocation, cost-stress expansion or 2025–2026 evaluation
is justified.

## Independent verification

Code:
- `research_programs/gold_fx_trend_20261015.py` — exact native
  feature and strategy runner.
- `research_programs/audit_gold_fx_trend_20261015.py` — separate
  read-only verifier.
- `research_programs/test_gold_fx_trend_20261015.py` — focused
  native ROC/clock/next-open integration tests.

Artifact:
`docs/audit/gold_fx_trend_diversification_mvp_20261015_verified.json`.

Audit checks:
1. Native input/output parquet and CSV SHA256 identities.
2. The unchanged canonical daily snapshot identities in the frozen
   session; no execution bar after 2021-12-31.
3. All **252** decisions are first eligible completed session monthly.
   All ROC60 signs agree with an independent past-60-close ratio.
4. All **252 fills** occur at the NEXT observed daily open, with the
   registered broker-side 3 bps slippage. No same-close fills.
5. Fill amounts/directions and native commission match the broker,
   with zero rejected orders.
6. Each final equity equals initial cash plus total native
   trade-ledger PnL to within two US cents.
7. Three genuine open positions at terminal (one per strategy),
   separate from partial-close ledger rows.
8. Recomputed daily marked-equity Sharpe/DD agrees with trial reports.

All three native trial artifacts are registered via
`scripts/research_session.py record` as terminal `completed`.
`completed` means the research computation and link exist; it is
**not** an economic or promotion pass. The legacy record reports
`artifact_generation_verified=false`, so the fully permit-bound
managed execution gate is not claimed. In this research MVP, independent
file/clock/broker audits supply additional direct evidence but do not
upgrade that control-plane field.

Trial evidence:
`run_log/gold_fx_trend_diversification_mvp_20261015/<trial_id>/attempt01/`.
Files: `started.json`, `prices.parquet`, `signals.parquet`,
`decisions.json`, `fills.csv`, `trades.csv`, `equity.csv`,
`rejected_orders.csv`, `report.json`.

Tests: 6 focused tests passed; Ruff passed. No strategy parameter was
changed in reaction to the results; no reruns, missing failures, or
unrecorded optimizer trials.

## Terminal research decision

**REJECT** this three-market, monthly ROC60, 10%-notional CFD
adaptation. Observed edge is not broad or stable. Do not increase
leverage to inflate nominal equity return. Do not optimize
lookbacks or continue searching for a winner under this frozen
session. Do not claim that price-only proxy PnL captures forward
points, Gold financing, interest-rate carry or actual CFD swap costs.

**Portfolio contribution analysis skipped by frozen gate.** The
unchanged existing strategy equity series were not opened or modified.
No promotion status, allocator or live trading was changed.
