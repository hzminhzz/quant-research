# VWAP Pullback + ADX — Phase 2 qualified proxy / Phase 3 first event study

Date: 2026-10-12. Repository: `/home/quant/dev/quant/quant-research`.
Session: `vwap_pullback_adx_nq_20261012_proxy_v2`. Original immutable session: `vwap_pullback_adx_nq_20261012`.
State: **EXPLORATORY / NOT_APPROVED**. Phase 4 was not executed.

## Objective and reproducibility

Test the registered cash-open opening-range breakout / VWAP reclaim hypothesis on a
source that actually includes the 15:55 America/Chicago futures exit window.
Test whether ADX(14)>20 with the first non-increasing observation improves
forward-price outcomes relative to the no-ADX VWAP reclaim.

- Source: `/home/quant/dev/quant/ml4t-data/.artifacts/lse-orb/raw-nq/futures_NQ.F_1m.parquet`, SHA256 `c12e2aaf9e7a4bbe8224d09a53bc7416f7088a2693d87adf3de0138fbf6a8edd`.
- Materialization: `data/processed/vwap_adx_nqf_2026h1_1m.parquet`, SHA256 `a0670b34b2175ca0df4a7ab98fa79bb02650cf4cce64ed67261ad29f706ebaad`. 191,538 rows (Dec 15, 2025 through June 30, 2026; warm-up before development).
- Session freeze SHA256 of spec payload: `891bd7cae686ff7bf56569b044b03c34b80f412805e087276569572c59d53c00`.
- Materialization source script: `scripts/materialize_vwap_adx_nqf_phase2_20261012.py`.
- Event study script: `scripts/run_vwap_pullback_adx_phase3_20261012.py` (SHA256 `0cd7fa32fba53d050bf0cba0fc63e41abd36dfe4fd1df7db0ae9ff3768fc20b7`).
- Inputs and evidence: `run_log/vwap_pullback_adx_nq_20261012_proxy_v2/phase2_source_manifest.json`, `phase2_quality_report.json`, `phase3_event_study.json`, `phase3_events.parquet`.
- Validation tests: `uv run python -m pytest -o addopts='' tests/test_vwap_pullback_adx_phase3_20261012.py -q` (4 passed).
- Independent replay: 195 event records, next-open to next-close one-minute gross outcome reproduced with exactly 0 absolute difference; all 52 B3 ADX observations had ADX>20 and ADX[t]<=ADX[t-1]; all adjacent minute timestamps valid.
- Development-only outcome: **2026-01-01 to 2026-06-30**. No July-October 2026 trial, no prospective final holdout accessed.

## Phase 2 gate

**PASS — price-signal research on a vendor-defined futures proxy**. Data input audit passed.
Source log and ml4t-data research specification explicitly classify LSE `NQ.F` as a
*provider-defined continuous series, not a dated CME NQ chain*. Its provider volume
is not verified CME exchange-traded volume. Therefore, VWAP is a **source-volume-weighted proxy**.

- 123 scheduled full XNYS cash sessions in the development period.
- 122 sessions had 30 consecutive 08:30–08:59 CT OR bars and a complete 08:30–15:55 CT minute grid.
- 2026-03-06 excluded due to a 1-minute continuity failure.
- No included OR had a zero-volume bar.
- UTC timezone-aware timestamps; converted to America/Chicago across the March DST change.
- Source 191,538 rows: sorted/unique, zero OHLC validity failures, zero nulls, zero nonpositive volumes.
- ML4T `compute_features(..., adx(14))` matches TA-Lib's Wilder ADX numerical implementation (max absolute difference below 1e-8).
- Existing Dukascopy CFD long history, `index_minute_NQ` staged rebuild, remains a separate long-history price proxy; it has no 15:55 CT bars and is not spliced into the LSE study.

**Still unqualified:** dated CME contract mapping, continuous roll behavior, true traded volume, bid/ask spread, stop execution, broker+clearing commissions and true futures PnL. Exact futures execution qualification remains blocked, not secretly waived by this proxy pass.

## Phase 3: first-session event study, before costs

Each included cash day contributes at most one first OR breakout (B1),
one first OR+VWAP reclaim (B2), and one first ADX-gated signal (B3).
This is **not** the user's original uncapped reentry / TP / SL strategy backtest.
The signal triggers on a completed minute; forward outcomes use the **next minute's open**
to the last completed minute's close after 1, 5, 10, or 30 minutes.
No signal uses future values. Per-event CIs use 2,000 deterministic
day-cluster bootstrap resamples; one first event per day.

Session counts: **122 valid → 83 B1 → 60 B2 → 52 B3**.

| Horizon | B1 mean points | B2 mean points (n) | B3 mean points (n) | B3 minus B2 paired same-day mean (n) |
|---|---:|---:|---:|---:|
| 1 minute | -2.05 | +3.47 (60) | +0.97 (52) | -1.23 (52) |
| 5 minutes | -3.56 | +8.15 (60) | +6.68 (52) | -0.25 (52) |
| 10 minutes | -2.53 | +11.55 (60) | +13.62 (52) | +0.38 (52) |
| 30 minutes | +5.22 | +14.40 (59) | +0.31 (50) | -15.26 (50) |

For **B3 10-minute gross forward outcome**, day-bootstrap 95% CI is
**[+4.46, +23.10] points**, but the corresponding **paired B3-minus-B2**
interval is **[-11.08, +12.28] points**. This does *not* establish incremental
ADX value. B3 delays entry; conditioning on days when it eventually qualifies
is selection, not evidence of causal ADX uplift.

The ADX wait interval measured from first B2 reclaim to first B3 signal
averages 43.75 minutes and has a median of 4.5 minutes, indicating long
tail delays and possible different candidate reclaim sequences.

**Research interpretation:**
1. The price-only VWAP reclaim hypothesis has a positive observed development
   mean at 1/5/10 minutes, but B2 uncertainty intervals cross zero at all
   registered horizons. This is preliminary, not a verified economic edge.
2. ADX qualifying events show a positive mean at 10 minutes. **Increment over
   paired B2 is statistically inconclusive** at all horizons. Do not adopt the
   filter based on unpaired comparison.
3. The 30-minute B3 mean is near zero; this is a warning of horizon sensitivity.
4. These are **gross event paths, not executable net returns or strategy trades**.
   No commissions, spread, slippage, contract roll, TP / SL barrier paths,
   partial fills, hard flat or repeated entries have been simulated.

## Trials, validation and interpretation

The two Phase 3 diagnostic execution attempts before a successful run included:
- First invocation failed on a Polars string-literal error in an `is_between`
  predicate before any event-study artifact was written. The script was corrected.
- The first version of the synthetic missing-minute unit test was wrong: it
  removed the 08:32 candle rather than the 09:02 successor candle. Corrected;
  focused test suite now passes 4/4.
- No alternate parameter variants or outcome-targeted tuning were run.

The original Phase 1 frozen specification was not edited. Session v2 explicitly
declares its source correction and the narrower *first-event-per-day* Phase 3
scope before this outcome was inspected. No holdout has been unlocked.

**Decision:** Phase 2 PASS for *proxy research only*. Phase 3 initial event
study COMPLETE, incremental ADX evidence **INCONCLUSIVE**. Research is not
adopted, rejected, or live-qualified. For Phase 4, use the native `ml4t.backtest`
Strategy/Engine and retain exact next-open, fixed TP/SL, OCO ordering and
commission/spread/stop slippage. Do not call a vendor-defined continuous
series a dated CME future. If authentic CME executable data are unavailable,
label any Phase 4 execution as **proxy-only exploratory** with a blocker on
true futures deployability.
