# Independent research audit — FOMC leveraged US500 Phase 4

**Verdict: REJECT under the frozen Phase 4 research gates.** This is a separate,
post-Phase-3 exploratory native backtest, not unseen validation, not executable
historical Hyperliquid PnL, and not authorization to trade capital.

## 1. What was actually tested

- **Source:** Dukascopy `index_minute_ES` bid-only 1-minute OHLC price proxy,
  100,382 actual source bars. Original predeclared FOMC/control 53 matched
  overnight pairs, 2018–2024; no synthetic source fills and no 2025+ bars.
- **Rule:** Enter long at 16:06 ET on the cash day preceding the scheduled
  FOMC statement. Exit at 09:36 ET on statement day. The strategy submits
  NEXT_BAR market orders at 16:05 and 09:35 respectively. Matched control
  is the ordinary overnight exactly seven calendar days earlier.
- **Broker:** Actual installed `ml4t-backtest.Engine` and native broker,
  hypothetical fractional synthetic index units, zero external funding.
  Price and session clocks are audited. No homemade PnL, cash or position
  simulator was used.
- **Primary frozen model:** 3.0× equity notional at each entry.
  Each side charges 2.5bps commission + 2.5bps execution slippage =
  **10bps round-trip hypothetical friction**. Native margin initial 10%,
  maintenance 5% is unqualified as a real Hyperliquid SP500 margin model.
- **Frozen sensitivity trials:** 1× and 5× at 10bps, 3× ordinary
  overnight control at 10bps, 3× FOMC at 20bps, and 3× FOMC zero-cost
  attribution. No parameter/cost selection after performance was observed.
- **Prior exposure:** Phase 3 showed gross FOMC overnight mean +17.758bps,
  matched ordinary overnight +14.451bps, and an uncertain +3.307bps
  increment (95% HAC [-20.847, +27.461], p=0.785). This Phase 4
  experiment was explicitly approved after that finding. It is not
  independent discovery or final-test evidence.

## 2. Native broker results

All results use 100,000 initial cash and 53 completed trades per trial.

| Trial | Net PnL USD | Profit factor | Win rate | Daily Sharpe | Daily DD | Intraminute DD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| FOMC 3× 10bps (primary) | +12,191.02 | 1.469 | 39.6% | 0.393 | −8.64% | **−10.32%** |
| Matched ordinary 3× 10bps | +6,287.88 | 1.172 | 50.9% | 0.204 | −18.57% | −20.33% |
| FOMC 3× 20bps | **−4,306.53** | **0.872** | 35.8% | −0.119 | −10.51% | −12.99% |
| FOMC 1× 10bps | +4,097.30 | 1.488 | 39.6% | 0.395 | −2.93% | −3.53% |
| FOMC 5× 10bps | +20,051.66 | 1.451 | 39.6% | 0.391 | −14.16% | −16.76% |
| FOMC 3× 0bps diagnostic | +31,470.16 | 2.654 | 58.5% | 0.888 | −6.95% | −8.55% |

**Daily Sharpe is the only strategy Sharpe in this report:** use the
calendar-daily equity series and ML4T Diagnostic with 365-day annualization,
including all flat days. The native Engine also prints a **1.383 Sharpe** for
the primary trial, but this is based on irregular quoted in-position minute
bars. It is **not comparable** to continuously sampled calendar-day returns,
and using it as annualized strategy Sharpe would be misleading.

**Risk:** Native engine intraminute maximum drawdown is −10.32% for
the primary 3× test and −16.76% at 5×. These larger drawdowns are more
conservative than the end-of-calendar-day values. The maximum observed
gross exposure/equity was 3.116× for primary and 5.399× at 5×,
reflecting intratrade price-driven leverage drift after entry.

**Annual primary net equity returns:**

| Year | Net equity return |
| --- | ---: |
| 2018 | −1.73% |
| 2019 | −1.37% |
| 2020 | +10.62% |
| 2021 | −7.37% |
| 2022 | +10.84% |
| 2023 | −2.73% |
| 2024 | +4.77% |

Three of seven years are positive. Full-sample primary total equity return
is +12.19%, with **1.74% CAGR** in the native daily-equity diagnostic.
Leverage increases absolute return/drawdown but does not raise daily Sharpe.

## 3. Independent verification (direct evidence)

- **Fills:** 106 native broker fills per trial (53 BUY, 53 SELL), exactly
  at the frozen 16:06/09:36 next-bar timestamps. All 53 original scheduled
  events and matched controls are accounted for; zero native rejections in
  the completed runs.
- **Native fill price:** `price_source=open`. BUY execution is actual
  source bid bar OPEN × (1+per-side-slippage), SELL is OPEN ×
  (1−per-side-slippage). Native fee per fill is
  `filled_notional × commission_rate`. Verified for **all six ledgers**.
- **Native API detail:** `Fill.reference_price` stores the candle close in
  the installed library even for native OPEN execution. It is **not**
  the actual market-fill reference. Independent validation uses the
  native `Fill.price`, `price_source`, and original bar open.
- **Trade/accounting:** Independently verified the native identity
  `trade.pnl = trade.gross_pnl − trade.fees`. Slippage is already
  reflected in entry/exit fill prices and must not be subtracted twice.
  Sum of closed trade PnL matches native final equity minus 100,000 USD,
  and `cash + net_exposure = equity` for native portfolio snapshots.
  Source and frozen data SHA identities match.
- **Primary native commission:** 8,220.39 USD. Primary slippage estimate:
  8,220.39 USD. Modeled total execution drag is roughly 16,440.77 USD
  over the actual 106 fills. Zero-cost results differ by more due to
  path-dependent sizing/compounding, not a cost arithmetic inconsistency.
- **Data integrity:** Source includes all exact decision and fill bars,
  no event overlaps or 2025+ observations. Longest actual gap in
  selected quote windows was 106 minutes. No fake minute fill was added.
  Cash and position history remain entirely in the native broker.
- **Tests:** The independently authored tests in
  `tests/test_fomc_us500_native_phase4_20261015.py` recompute native
  Profit Factor, cash/equity reconciliation, fee and slippage parity,
  matched calendar clocks, and calendar-daily Sharpe.

## 4. Technical retries and evidence conservation

The frozen market rules, event calendar, cost grid, and target exposure were
never changed. Failed **technical attempts** remain in the local
`run_log/diagnostics/fomc_us500_overnight_native_phase4_20261015_v1`
plus the published `attempt_failures` archive.

1. Native broker requires short maintenance margin no greater than initial
   margin even when only long orders are allowed. Set unused
   short-maintenance setting consistently to 5%.
2. Native `order_target_percent(0)` occasionally rounds the close quantity
   slightly beyond the existing long, which the broker rejects as
   `Position reversal not allowed in cash account`.
   Corrected to native `submit_order(asset, exact_position.quantity, SELL)`,
   eliminating floating-point over-closing; no relaxation of broker checks.
3. Corrected the independent execution-price reference check to read
   actual native fill price from the bar OPEN with slippage, rather than
   the native fill metadata's candle-close `reference_price`.
4. Five technical failure records are retained; the subsequent complete
   native six-trial run has zero rejected orders and reconciled trades.

## 5. Frozen decision and limitations

**REJECT:** primary 3× 10bps daily-equity Sharpe **0.393 below 0.50** and
20bps doubled-cost stress **negative net equity**. The 10bps primary
FOMC PF (1.469) beats the frozen 1.30 hurdle and also beats the control
PF and Sharpe. That does not waive the frozen independent Sharpe
and cost-robustness requirements.

Actual Hyperliquid S&P 500 perp economics **remain UNKNOWN**: this
proxy contains **no historical Hyperliquid index-perpetual book, funding
cash flow, realized spread, slippage, funding impact, or liquidation**,
and the product did not trade in the 2018–2024 sample. A positive native
proxy result is not a venue-qualified edge.

Trial files under `docs/audit/fomc_us500_overnight_native_phase4_20261015_v1/`
include every native trade, fill, equity, broker portfolio state, daily equity,
yearly summary, rejected-order proof, per-trial metrics, frozen spec,
failed attempt records, and the terminal decision.

**Terminal action:** Do not promote or open the protected 2025+ holdout.
No strategy parameters, events, clocks or costs are tuned to improve the result.
