# Independent review: corrected one-bar 2026 regime audit

**Review type:** read-only re-audit of corrected historical evidence.  
**Status:** `VERIFIED` for ledger pairing, accounting, session labels, and feature-release timing. `EXPLORATORY`; strategy status remains `NOT_APPROVED`.

## Scope

This review used the existing annual ledgers and source-minute files. It did not run the strategy or change its rules. It did not read observations after 2026-07-14. It did not place orders or make a commit.

The analysis is in [`promote/one_bar_nq_30m/scripts/analyze_regime_2026.py`](../../promote/one_bar_nq_30m/scripts/analyze_regime_2026.py). The regenerated report, metrics, CSV files, chart, source hashes, and method record are in [`reports/regime_2026`](../../promote/one_bar_nq_30m/reports/regime_2026/README.md). The provenance manifest covers the corrected package files.

## VERIFIED

- **Native exit type:** the audit paired even `fills.csv` row indices as entries and odd indices as exits. It checked both fill timestamps against the same row in `trades.csv`. It joined the native exit `order_type` to `evaluation_trades.csv` by `(entry_time, exit_time, direction)` with one-to-one validation. All nine full-tick annual ledgers from 2018 through 2026 passed these checks.
- **2026 exit attribution:** 238 trades reconcile to 44 `STOP` exits totaling **−$48,058.76** and 194 `MARKET` exits totaling **+$33,891.80**. Their sum equals the frozen full-tick net of **−$14,166.96**. The raw trade exit label `signal` is not used to classify exits.
- **Monthly controls:** March has 10 STOP exits / **−$10,101.28** and 28 MARKET exits / **+$3,311.52**. May has 3 / **−$3,032.48** and 39 / **+$7,098.32**. June has 11 / **−$11,450.28** and 21 / **+$2,254.82**. Monthly total PnL sums to the annual total. Matched January–July 14 STOP frequency from 2018–2025 is reported by calendar month.
- **Accounting:** 238 trades; zero-cost net **−$10,806.96**; full-tick net **−$14,166.96**; scenario difference **$3,360.00**. These values remain unchanged. Separate zero-cost and full-tick paths are not assumed to match at every exit.
- **Chicago RTH:** entry timestamps use the `America/Chicago` timezone with daylight-saving rules. RTH is 08:30 inclusive to 15:00 exclusive. The corrected report has 61 RTH and 177 overnight trades. Their counts sum to 238 and PnL sums to **−$14,166.96**.
- **Feature release:** every complete 30-minute bar releases at `bar_start + 30 minutes`. The backward as-of join accepts only release times at or before entry. The audit checks this for every report row. The focused test rebuilds ATR and efficiency features from synthetic one-minute inputs. It confirms that an entry in minute 29 does not see that bar's completed feature and that changing a future one-minute row does not change earlier joined values.
- **Fixed stop context:** the stop remains 50 points, or $1,000 at the illustrative $20-per-point multiplier. The full-year 2018 median entry price is **6,966.5**, so 50 points is **71.8 bp**. The 2026 median is **25,828.5**, so 50 points is **19.4 bp**. Matched January–July 14 pre-entry ATR(20) medians are **27.9 points** for 2018–2025 and **66.7 points** for 2026.
- **STOP probability by fixed-stop / pre-entry ATR tercile:** the 2018–2025 matched sample has 8.3% (n=614) in the low-ratio tercile, 5.4% (n=612) in the middle tercile, and 1.0% (n=613) in the high tercile. The 2026 sample has 17.9% (n=224) in the low tercile and 28.6% (n=14) in the middle tercile; it has no high-tercile observations. These are descriptive groups. No stop threshold was selected or changed.
- **Source:** the source manifest hash and all 115 scanned source-partition hashes match the frozen identity. The source is Dukascopy USATECH.IDX/USD BID-only proxy data, not a verified dated CME NQ contract.
- **Checks:** focused tests pass; package verification passes; `git diff --check` passes. The chart was opened and visually checked. It shows monthly total PnL alongside STOP and MARKET exit PnL, monthly STOP frequency against the 2018–2025 same-month reference, and the corrected regime panels.

## INFERENCE

The 50-point stop was smaller relative to both price and pre-entry ATR in 2026 than the historical reference. The higher STOP frequency is consistent with this tighter relative distance. This comparison does not show that stop distance caused the losses. Trade entries, market conditions, event order, and execution all differ across observations.

The market-exit group was profitable as a whole. This does not mean every breakout succeeded. The 44 stopped trades lost more than the 194 scheduled market exits gained.

## HYPOTHESIS

March geopolitical shocks, the April–May rebound, and June technology rotation provide period context only. They do not identify causes of the observed trade results. No event-time causal analysis was performed.

## Limits

- One-minute OHLC cannot resolve event order within the entry or exit minute. The 51 observed nominal 50-point touches include both boundary minutes and are not equivalent to native STOP fills.
- Native OCO behavior is non-atomic. Gap fills can exceed the nominal stop risk.
- The underlying quotes are BID-only proxy data. CME NQ contract mapping, bid/ask execution, exchange fees, and market impact are not verified.
- The report has no day-cluster confidence intervals. The historical trial ledger is incomplete, so a reliable Deflated Sharpe Ratio is not available.
- The macro statements remain contextual hypotheses. They do not support a causal conclusion.

## Verification record

- Focused suite: `uv run python -m pytest promote/one_bar_nq_30m/tests/test_regime_2026.py` — **6 passed**.
- Package integrity: `uv run python promote/one_bar_nq_30m/scripts/verify_package.py` — **386 package files and 3 YAML files verified**.
- Whitespace check: `git diff --check` — passed.
- No strategy runner or holdout was used.
