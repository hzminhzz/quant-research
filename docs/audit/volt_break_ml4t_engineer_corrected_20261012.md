# VOLT BREAK — ML4T Engineer feature correction and native backtest
**Date:** 2026-10-12

## Result and status

**Verified:** Implemented a versioned ML4T Engineer indicator pipeline and
completed native ML4T backtests on local LSE NQ.F data from late 2025.

**Not verified:** An exact creator-code reproduction, actual dated CME NQ
futures execution, exchange trade VWAP, or long-term profitability.

**Decision:** Weak/negative preliminary result after costs; **INCONCLUSIVE**
about the creator's complete long-term trading edge because the high-fidelity
source supports just 37 signal-eligible sessions and 31 trades.

## Why we replaced the earlier backtest

The previous 2019-2025 studies computed daily true ranges manually using
Polars on Dukascopy USATECH.IDX/USD BID CFD. These were NOT the stated
15-session SMA of an existing ATR series and the source's daily price
history stopped at 15:14 CT. The older findings remain an explicitly
different *CFD-proxy* trial and cannot falsify the creator's specification.

The replacement data already exists in the canonical LSE store:
`/home/quant/dev/quant/ml4t-data/.data/store/lse_futures_minute_NQ/year=2025`
with four September-December Parquet files. The provider labels the
instrument `NQ.F`; exact dated-contract and roll semantics remain unknown.
Only these 2025 partitions were read. No 2026 source file was read.

The 2025 data has 99,179 source rows. Exactly 66 sessions have every
minute from 00:00 through 15:59 America/Chicago CT. The predeclared
daily indicator warmup leaves 37 sessions from October 30 through
December 31, 2025 and 70 qualifying completed-bar signal observations.

## Accurate feature engineering (code identities)

`scripts/run_volt_break_engineer_lse_20261012.py`

1. Build daily OHLCV from fully observed 00:00-15:59 CT minutes.
   Use a DST-aware IANA clock. Reject missing or shortened days
   rather than forward filling futures prices.
2. `ml4t.engineer.compute_features(daily_ohlcv, [{"name":"atr",
   "params":{"period":14},"output":"daily_atr14"}])` calculates
   standard Wilder ATR(14). **ATR(14) is a declared conventional
   assumption** because the original speaker did not identify the
   inner `ATR_Daily` period.
3. `ml4t.engineer.features.trend.sma(daily_atr14,period=15)`
   computes the 15-session SMA **of the daily ATR**. Use the
   previous completed day's value at the next midnight CT open.
   This is NOT a 15-bar intraday ATR and NOT simply the mean of
   15 true ranges. Verified ATR/SMA outputs against independent
   TA-Lib ATR/SMA references to tolerance 1e-6.
4. Fixed noise-up barrier for the research day:
   `P_open_at_00_CT + 0.30 * prior_completed_SMA15(ATR14_daily)`.
5. `ml4t.engineer.compute_features(minute_ohlcv,
   [{"name":"typprice","output":"ml4t_typical_price"}])` provides
   typical price, parity-tested to independent TA-Lib TYPPRICE.
6. `ml4t-engineer` does NOT ship an anchored VWAP feature.
   For this **one mathematical operation only**, the runner uses
   pandas session-grouped cumulative volume-weighted typical price:
   `cumsum(ml4t_typprice * LSE_reported_volume)/cumsum(volume)`,
   reset at midnight CT. It does not compute custom Polars indicators.
   This is a minute-OHLCV VWAP approximation, NOT verified trade-level
   CME futures VWAP. No hidden volume is synthesized.
7. A 30-minute bar closes at minute index 599, 629,...,839 CT.
   The indicator checks that completed minute's close against
   both the fixed barrier and anchored VWAP. A qualifying order
   enters on the source OPEN at 600, 630,...,840 CT via the
   already-tested native NEXT_BAR engine pathway.

## Native execution

`ml4t-backtest 0.1.7` Engine/Broker owns orders, fills, cash,
margin and trade P&L. The previously tested entry-minute
`VoltBreakNativeEngine` adapter immediately evaluates the
native fixed-point protective rule after native entry fill.
Its stop-first convention is conservative when a one-minute
bar contains both stop and target levels.
- One NQ-equivalent, $20/index point.
- TP +40 points (+$800 gross), SL -75 points (-$1,500 gross).
- Up to three entries per trading day, re-enter when flat and
  the last completed 30-minute bar qualifies.
- Flatten by market at 14:30 CT source open.
- No overnight positions; no news filter.

## Backtest results (all on same 37 sessions, 2025-10-30 to 2025-12-31)

| Cost | Trades | Win rate | P&L USD | Avg USD/trade | Profit factor | Sharpe | Calmar |
|---|---:|---:|---:|---:|---:|---:|---:|
| None | 31 | 64.5% | +110 | +3.55 | 1.007 | +0.049 | +0.111 |
| Illustrative | 31 | 64.5% | -210 | -6.77 | 0.986 | -0.067 | -0.209 |
| Double | 31 | 64.5% | -530 | -17.10 | 0.966 | -0.184 | -0.518 |

Illustrative costs: $2.50 commission per fill and 0.25 points
adverse fill slippage. Double uses $5 and 0.50 points.
No costs are claimed as real broker measurements.
Sharpe/Calmar use a $1,000,000 hypothetical account and the
37 signal-eligible days, NOT a 2019-2025 full-year sample.
The tiny sample makes these annualized ratios unstable.

## Independent verification

`scripts/audit_volt_break_engineer_lse_20261012.py` independently
checked all three native trade CSVs:
- Exactly 31 native buys, 31 native sells and 31 closed trades.
- All 31 entry timestamps match a **previously completed**
  30-minute bar's engineered qualifying signal.
- Entry on 10:00-14:00 CT half-hour opening boundaries only.
- Maximum three entries on any CT session.
- Entry and exit on same CT day; zero exits after 14:30 CT.
- All trade prices x $20 multiplier reconcile to native gross
  trade P&L, and closed-trade net P&L reconciles to Engine equity.
- Two 14:30 CT time exits and 29 earlier protective exits
  on each cost run. Native export's generic `exit_reason=signal`
  is not reliable for separating STOP versus LIMIT; do not claim
  a precise exit-reason breakdown without a separate event audit.
- The native lifecycle synthetic suite passed 16/16 cases.
- Four 2025 Parquet SHA256 fingerprints matched LSE source metadata.
- The 2026 reserved period and prior research were not modified.

## Remaining limitations and next research action

This is the **requested corrected feature pipeline and completed backtest**.
It removes the prior ATR implementation error, preserves original
barrier/entry/TP/SL rules and uses a futures-series reference rather than
a CFD. But exact creator parity cannot be asserted without:
- original indicator source or documented daily ATR inner period;
- independently validated NQ.F continuous/roll rules;
- true CME tick/trade-volume VWAP and bid/ask execution series;
- sufficient pre-2025 complete 1-minute NQ futures history.

The current local historical LSE NQ.F store starts in
September 2025 (2026 partitions exist but remain sealed).
Do not substitute the 2011 Dukascopy BID CFD series as a faithful
input because it lacks the session end and authentic volume.

**Decision: NOT APPROVED for trading.** Phase 5/6 validation is not
justified on only 31 trades. If more authentic NQ history becomes
available, extend the SAME documented ML4T Engineer rules with no
data-dependent parameter tuning, then assess chronological stability.

## Reproduction

From `/home/quant/dev/quant/quant-research`:

`.venv/bin/python -m scripts.run_volt_break_engineer_lse_20261012`

`.venv/bin/python -m scripts.audit_volt_break_engineer_lse_20261012`

Files:
- `config/research_sessions/volt_break_nq_lse_ml4t_engineer_20261012.yaml`
- `scripts/run_volt_break_engineer_lse_20261012.py`
- `scripts/audit_volt_break_engineer_lse_20261012.py`
- `run_log/research_sessions/volt_break_nq_20261012/phase4_engineer_lse/`
  - `feature_parity.json` plus daily ATR/volatility and signal CSVs;
  - `zero/`, `illustrative/`, `double/` native trades, fills, NAV and metrics;
  - `independent_execution_audit.json`.

No Git commit or push; no real order. Existing dirty work untouched.
