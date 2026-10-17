# VOLT BREAK — Feature/Source Fidelity Audit (2026-10-12)

## Corrected decision

The Phase 4 native ML4T simulation is reproducible under its **declared proxy
rules**, but those rules are NOT verified to replicate Matteo Conti's actual
VOLT BREAK. **Do not conclude the original strategy fails. Do not promote
to Phase 5 or 6 before resolving source fidelity.** Keep original outcomes
and their trial ledger intact as failed/weak *proxy* variants. Do not rewrite
them as an exact replication.

## Original-strategy source

Video transcript (third-party, not authenticated creator code):
https://sozai.app/transcript/hedge-fund-manager-cracks-prop-trading/

Around 11:38–13:05, Matteo discusses the average true range of the previous
15 sessions and 0.30 multiplier. Around 17:51–18:23 he describes using
session observations from midnight CT through 5pm Eastern / **4pm CT**.
At 53:46–54:23 he calls the feature a 15-daily moving average of daily
ATR and says the VWAP anchor is midnight CT. This source does NOT
specify the inner daily ATR lookback/smoothing length; don't invent one.

## What was really implemented

Source:
`scripts/run_volt_break_phase4_native_20261012.py`,
`scripts/volt_break_native_adapter_20261012.py`.

Features were built directly in Polars, NOT with `ml4t-engineer`.
- 00:00 CT source OPEN: consistent with spoken anchor.
- 00:00 CT VWAP: cumulative one-minute typical-price
  `(high+low+close)/3 * provider_volume_units`; **not** authentic
  exchange NQ futures VWAP.
- Daily ATR candidate: mean of 15 prior **daily true ranges**
  from source-defined Globex-like 17:00 previous CT day through
  16:14 current CT day, not confirmed daily `ATR_Daily` lookback
  and **different daily window** than transcript's 00:00–16:00 CT.
  The rolling mean is lagged one completed session; no identified
  same-session forward data in this feature, but its identity differs.
- The 2019–2025 strict >=1300-minute prior session filter resulted
  in only 156 ATR-eligible dates; broader >=1000-minute filter resulted
  in 491. These are retrospective *coverage sensitivities*, not
  verified market filters.

## Independent historical data availability audit

`scripts/audit_volt_break_feature_parity_20261012.py` scanned only
2018–2025 canonical Dukascopy minute OHLCV; 2026 final history unopened.

For each year 2019–2025:
- Median observed minutes from 00:00 to 15:59 CT = **915**.
- Median *last* minute index = **914**, representing **15:14 CT**.
- Maximum last minute index = 914 each year.
- Strictly complete 00:00–15:59 inclusive 960-minute sessions = **ZERO**.

Therefore an exact daily ATR using the speaker's 00:00–16:00 CT full
range CANNOT be computed from this Dukascopy CFD store without
unobserved afternoon prices or an explicit, unverified shortening
assumption. The audit did not run an altered trading system or
select whichever alternative performed better.

The full daily average-of-TR and nested Wilder(14) possibilities were
probed for complete source data only. Both had zero eligible days under
the 960-minute full-data gate; a signal-parity comparison to the
original proxy cannot be identified. The nested Wilder(14) option is
an **unverified hypothesis**, not an assertion that it matches the
creator's implementation.

## Research implications

- Phase 4 existing outcomes:
  - strict cohort, illustrative costs: 110 trades, +$155.84,
    Sharpe +0.008, profit factor 1.003.
  - broader cohort, illustrative costs: 387 trades, -$11,907.46,
    Sharpe -0.234, profit factor 0.928.
- These disfavor the **implemented CFD-proxy variant**; they do not
  falsify a different daily ATR window/ATR smoothing or authentic
  CME-volume VWAP strategy.
- Robustness and chronological validation in Phases 5–6 would test
  the wrong implementation; **not recommended** at this stage.

## Proposed limited next gate

1. Establish the creator's actual `ATR_Daily` implementation
   (what daily window, whether Wilder14/ATR14 or true range, whether
   `SMA15(ATR_daily)` is nested, and exact VWAP source/price basis).
2. Check whether the approved available data can reconstruct those
   inputs. If the missing 15:15–15:59 CT source and true futures volume
   cannot be supplied, classify as **proxy-only/inconclusive**.
3. If a faithful input can be constructed, independently compare at
   least a few fixed calendar dates of barrier and session VWAP
   against the source platform before reopening historical trials;
   register the new implementation as a separate versioned trial.
4. Only if that exact feature passes parity and historical after-cost
   expectancy is credible should Phases 5–6 begin. Continue to protect
   the 2026 holdout.

## Verification

- Existing native Phase 4 tests: 16/16 passed earlier in session.
- Source identity prior audit: 96/96 matched monthly files.
- New script: `scripts/audit_volt_break_feature_parity_20261012.py`
- New immutable diagnostic: `run_log/research_sessions/volt_break_nq_20261012/phase4_native/phase4_feature_parity_diagnostic_20261012.json`
- No live orders, no 2026 data read, no commit/push, unrelated dirty
  work preserved. No new PnL or strategy selection performed.
