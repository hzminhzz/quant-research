# One-bar execution remediation audit

Status: stop-gap handling `VERIFIED`; full rule replay `BLOCKED`; strategy approval `NOT_APPROVED`.

The frozen account remains $1,000,000 initial cash, with short selling and leverage enabled, $25,000 initial margin, and $20,000 maintenance margin per contract. The unchanged stress case is 0.25 adverse index points and $2.50 commission per fill. The instrument remains one indicative contract at $20 per point.

## Work completed

The bounded scenarios used `ml4t.backtest 0.1.7 Engine`. No code in site-packages changed. The installed `StopFillMode.STOP_PRICE` implementation checks the source bar's `open`. It fills at that open when the open crosses a stop. It fills at the trigger when the bar crosses the stop after the open. Synthetic Engine tests verify both long and short entry gaps and protective-stop gaps. They verify that a $1,000 trigger is not a guaranteed maximum loss.

The previous gap diagnostic used `reference_price` as if it were the bar open. The saved fill ledger contains the actual `price_source=open`, but the diagnostic compared reference prices to stop prices. The corrected audit joins each saved stop fill to the source OHLC row at its timestamp. It checks the trigger/open rule and recorded side-adverse slippage.

| Check on saved full-tick ledger | Result |
|---|---:|
| Stop fills joined to source OHLC | 5,581 |
| Missing source rows | 0 |
| Fill-price mismatches after recorded slippage | 0 |
| Actual stop gaps | 286 |
| Actual entry gaps | 282 |
| Actual protective-stop gaps | 4 |
| Gross minus net minus commission | $0.00 |
| Fill versus trade slippage-cost difference | $0.00 |
| Trade ledger versus final equity difference | less than $0.000001 |

The 3,335 entry gap count and its $409,132.58 “price advantage” are not supported by source opens. The 105 stop-gap count and $19,993.80 amount are also not supported by source opens. Do not use these earlier diagnostics.

## Source-minute execution and 30-minute decisions

`prepare_execution_feed` retains every valid source-minute row. It creates a signal event only after 50 complete 30-minute bars are available. For a completed bar `b`, the level is the rolling maximum/minimum of bars `b-49` through `b`, inclusive. Its availability timestamp is `bar_start + 30 minutes`, the close boundary of `b`. A backward as-of join attaches that event to the first source minute at or after the boundary. A minute stamped at the boundary is the opening execution event for the next bar, so it can use the released level. A missing boundary print does not remove the event; the next observed source minute receives the latest released level.

The old exact-bin join exposed a level from bars `b-1` through `b-50` on source minutes inside `b`. That level was not the level intended for orders submitted after `b` closed. The corrected join has no same-bar lookahead and does not use completeness of the current bar to choose whether to execute at its open. A 14-test focused suite verifies release at the 50th completed bar close, retention of the next incomplete bar's opening print and level, invariance to future-bar mutations, session-gap carry, and distinct UTC boundaries across the repeated Chicago DST hour. The machine-readable timing proof is in `run_log/one_bar_execution_remediation_20261012/timing_audit.json`.

The saved historical output had 216 delayed scheduled exits. The source audit classifies them as follows:

- 191 scheduled boundary opens exist in source data. The previous inner join removed those execution minutes because their 30-minute bins were incomplete.
- 25 scheduled boundary opens do not exist in source data. Those exits remain unresolved until a real later print. The audit does not fabricate an opening event.

The source timestamps are shifted before any decision-bin filter. UTC boundary logic passed the repeated Chicago DST hour test.

## OCO and intrabar limits

The native synthetic OCO fixture triggers buy and sell stops within one minute. Both orders fill at the same timestamp. `Broker.submit_order` has no OCO group parameter. The installed native API cannot pass the atomic OCO invariant. Do not treat the one-minute candle as an ordered event, and do not select the favorable side after observing its result.

The prior saved run contains one same-minute opposing stop-order event and 44 entry/protective-stop same-minute ambiguities. Minute OHLC cannot establish their order. These events remain unresolved. A stop trigger at $1,000 risk does not cap loss if the market gaps.

The source store contains BID OHLCV only. The local canonical store has no verified index ASK or index tick/quote dataset. `index_minute_NAS100` is also OHLCV. The source is a Dukascopy USATECH.IDX/USD BID CFD proxy, not CME NQ futures. No ASK was synthesized.

## Trial and execution status

R1 verified native stop-gap fills. R2's source-minute timing was corrected and verified with focused synthetic Polars tests. R3, the full-history zero-cost and 0.25-point/$2.50-cost replay, is blocked. An exact replay would require atomic OCO handling that the installed Broker does not provide. A replay that admits the observed double fill would create false exposure. No post-hoc PnL adjustment was used. This timing fix does not establish a corrected historical performance result.

The prior ledger reconciles to $166,521.58 net and $1,166,521.58 final equity, with $26,860 of commission and reconciled fill slippage. These are historical output values only. They are not corrected performance results because the previous feed delayed 191 exits and contains OCO/intrabar ambiguities. The mission's corrected full-history outcome remains unavailable.

No data after 2026-07-14 was used. The complete test and run evidence is in `run_log/one_bar_execution_remediation_20261012/`. The updated focused suite passed 14 tests. The prior native fixture suite passed 6 tests.
