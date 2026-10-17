# VOLT BREAK — Phase 3 Alpha Diagnostics (2026-10-12)

## Decision

**NEGATIVE EXPLORATORY PRICE CONTINUATION / NOT_APPROVED.**
The original joint noise-barrier-plus-VWAP first-entry signal did not
exhibit positive average 30-minute continuation on the Dukascopy USATECH.IDX/USD
BID 1-minute index CFD source under the explicitly registered SMA15(previous
daily true ranges) candidate interpretation. It underperformed matched
non-trigger same-year and CT-clock observations. This is an event study,
not a native TP/SL strategy simulation or executable NQ futures replication.

No protected September–October 2026 outcome was read. No order was placed.
No trading parameter was tuned to choose a profitable result.

## Source and sample

- Canonical source: `/home/quant/dev/quant/ml4t-data/.data/store/index_minute_NQ`
- Provider: Dukascopy `USATECH.IDX/USD` **BID** CFD; true CME NQ
  futures prices and CME-executed trade volumes were not observed.
- Source scan: all 96 monthly partitions for **2018–2025**, with
  2018 supporting ATR warmup. **2019–2025** are retrospective development.
- Source files independently verified: **96/96 SHA256 matches** against
  `run_log/one_bar_dukascopy_2013_2026_20261011/source_manifest.json`.
- 1,576 CT dates have every 1-minute timestamp from 00:00 to 14:29
  and an open quote at 14:30. Only 156 / 491 CT dates have a valid
  prior-15-session ATR under strict / relaxed prior-session coverage.
  This is the major study limitation, not a reason to cherry-pick dates.
- Prior daily true range uses Globex-like 17:00 previous evening through
  approximately 16:14 CT. The phase-3 indicator is the average of the
  **15 previous** complete daily true ranges, lagged by one session.
  The source author's `SMA15(ATR_Daily)` might require separate ATR
  smoothing; the exact original definition remains **unverified**.
- Midnight open is first 00:00 CT source open. Static barrier =
  midnight open + 0.30 * lagged ATR.
- VWAP is a **proxy** using cumulative (H+L+C)/3 times provider volume units
  from midnight through the last completed 1m row of the 30m signal bar.
  It is NOT the actual NQ contract VWAP.
- Signal first qualifying completed 30m bar close: 10:00 through 14:00
  America/Chicago; next-open quote is the source 1m open exactly at the
  decision bar boundary. No bar-end close or quote beyond that boundary
  is used for entry.
- Primary analysis is the **first** joint qualifying close per day.
  Subsequent trade reentry and exit execution are Phase 4, not inferred here.

## Registered exploratory trials (kept separate)

| Diagnostic | Strict v1 (prior daily session >=1300 bars) | Additional coverage v2 (>=1000 bars) |
|---|---:|---:|
| Complete 00:00–14:30 research days | 1,576 | 1,576 |
| Days with prior-15 ATR eligible | 156 | 491 |
| First joint qualifying signals | 63 | 217 |
| Gross 30-minute markout (index points) | -4.498 | -5.014 |
| Matched 30-minute excess (index points) | -9.177 | -7.290 |
| HAC p (matched 30-minute excess) | 0.0482 | 0.00425 |
| Holm adjusted p over 3 declared horizons | 0.1447 | 0.01275 |
| Matched 60-minute excess (index points) | -7.373 | -6.341 |
| Matched 14:30-exit excess (index points) | -10.693 | -5.411 |

Gross 30-minute equivalent at the illustrative **$20/point** multiplier is
**-$89.96 / -$100.29** respectively, **not executable NQ P&L**. Neither
commission nor actual CFD/CME bid/ask, slippage, TP/SL, stops, risk,
margin, inventory or reentry was modeled. The reported gross markout
subtracts the entry 10:00–14:00 quote OPEN from the 30-minute forward
boundary OPEN, which avoids placing an order on the known completed
candle CLOSE.

### Confidence and controls

- Year-and-CT-clock nontrigger controls, minimum five controls per event.
- One first signal per day, HAC 5-lag intercept inference with
  three-horizon Holm adjustment.
- **v1**, n=63: matched 30m 95% HAC CI
  [-18.283, -0.071] points, adjusted p=0.1447 (not significant).
- **v2**, n=217: matched 30m 95% HAC CI
  [-12.288, -2.292] points, adjusted p=0.01275 (significant negative).
- v2 matched 60-minute 95% HAC CI [-12.580, -0.102]
  points but adjusted p=0.09275; v2 14:30 point estimate -5.411,
  p=0.5157.
- These confidence intervals condition on estimated matched control
  means and do not fully propagate uncertainty from control estimation.
  They are descriptive, not causal flow proof or strategy P&L confidence.
- Yearly v2 next-30m matched excess was positive in 2020 and 2023,
  negative in 2019, 2021, 2022, 2024 and 2025. Results have weak
  year stability.
- Descriptive filter decomposition from v2 first-hit days:
  barrier-only 217 signals / -5.43 gross points;
  VWAP-only 383 / +1.24 gross points; joint 217 / -5.01 points.
  These are nonidentical selected groups, not randomized comparisons
  and not permission to adopt VWAP-only as a new selected winner.

## Data-quality sensitivity: why two trials exist

v1 required each of the 15 preceding Globex-like sessions to have
at least 1,300 recorded minutes. Independent investigation
(`scripts/audit_volt_break_atr_session_count_20261012.py`) showed most
normal days have about 1,335 minutes, while the source contains
occasional truncated 60, 1,079, 1,215 or 1,275-minute sessions.
The 15-session rolling requirement discards most trial days after
each such interruption.

After inspection and **after v1 outcomes were observed**, the
coverage-only v2 rule was independently registered as
`config/research_sessions/volt_break_nq_phase3_atr_coverage_v2_20261012.yaml`
with minimum 1,000 observed daily minute bars. All other signal
parameters, horizons, controls and pricing remained the same.
V2 has more events, but its daily ATR can be distorted by missing
portions of overnight sessions. It is **not a clean independent OOS
confirmation**. Both trial outcomes and reasons are preserved.

## Verdict / acceptance gates

1. **Phase 3 delivered** as retrospective exploratory study.
2. Directional continuation screen: **NEGATIVE** under both fixed variants.
3. Exact strategy thesis with +$800 TP/-$1,500 SL and up to 3 reentries:
   **UNTESTED**. Reentry and path-dependent fills can materially change
   P&L versus simple 30m markouts, but Phase 3 does not justify claiming
   a positive edge.
4. Actual futures VWAP and exact original daily ATR interpretation:
   **UNVERIFIED**. Do not say this reproduces Matteo's strategy.
5. Do not open protected 2026 final history, promote the strategy,
   or select a winner from filter/coverage variations.

## Reproduction & independent checks

Run from `/home/quant/dev/quant/quant-research`:

- `.venv/bin/python scripts/run_volt_break_phase3_20261012.py`
- `.venv/bin/python scripts/run_volt_break_phase3_atr_coverage_v2_20261012.py`
- `.venv/bin/python scripts/audit_volt_break_atr_session_count_20261012.py`
- `.venv/bin/python scripts/verify_volt_break_phase3_sources_20261012.py`

Artifacts:

- `run_log/research_sessions/volt_break_nq_20261012/phase3_strict_results.json`
- `run_log/research_sessions/volt_break_nq_20261012/phase3_atr_coverage_v2_results.json`
- `config/research_sessions/volt_break_nq_phase3_2019_2025_20261012.yaml`
- `config/research_sessions/volt_break_nq_phase3_atr_coverage_v2_20261012.yaml`

The external 2018–2025 source file integrity gate passed **96/96**.
Scripts compiled successfully. No repository-wide tests were run because
only task-owned research scripts and reports were added, not shared library
code. No Git commit or push was made; existing unrelated changes remain.

Next decision: only run a narrow native ML4T Phase 4 baseline on a
clearly labeled CFD-proxy sample if testing the specific TP/SL path
is worth additional effort. Do not optimize filters based on these
observed results.
