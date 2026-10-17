# B0 cross-index transfer — Phase 1 and Phase 2 registration

**Status: Registered; source audit completed. No new backtests. EXPLORATORY / NOT APPROVED.**

## Research question

Does the original NQ B0 one-bar breakout edge replicate on the S&P 500, DAX, Nikkei 225, and Hang Seng? The proposed mechanism is short-lived continuation after a breakout of recent intraday extremes, possibly because directional orders execute over several minutes. The falsifier is absent expectancy after realistic costs or results explained by source gaps, exchange sessions, or ambiguous fills.

The reference is the untouched NQ promoted package at promote/one_bar_nq_30m. Its already-observed native cost-aware replay had 5,462 trades and +$166,107.92 through July 14, 2026. This result uses a BID-only index/CFD proxy and is not evidence of live CME NQ execution.

## Exact frozen strategy

- Decision: previous **50 fully completed 30-minute bars**; buy STOP at their highest high, sell STOP at their lowest low.
- Intended cancellation of the opposite order after first entry, maximum **two filled entries per Chicago session**, long and short, 17:00 America/Chicago extended-session anchor.
- Exit at **immediately following 30-minute opening print** or earlier protective STOP.
- The original B0 stop is **50 index points** on **one illustrative NQ-equivalent contract**, meaning $1,000 nominal stop-trigger risk on NQ at $20 per point, excluding gap losses.
- No ATR adjustment, percentage stop, volatility or volume filter, independent parameter fitting, or changed entry/exit rule.

## Phase 2 — Canonical data verified

The data-quality scan read price observations **only from January 1, 2013 through July 14, 2026 UTC**, although some source folders contain later metadata and prices that were not evaluated.

| Instrument | In-scope 1m rows | Complete / observed 30m bins | Incomplete observed bins | Readiness |
|---|---:|---:|---:|---|
| NQ, frozen control | 3,883,929 | 121,319 / 133,063 (91.2%) | 11,744 | Control exists |
| ES, index proxy | 3,775,266 | 93,909 / 134,675 (69.7%) | 40,766 | Source found; timing quality caution |
| DAX | 1,857,320 | 61,218 / 62,319 (98.2%) | 1,101 | Source found; product mapping pending |
| Nikkei 225 | 1,149,061 | 25,502 / 41,011 (62.2%) | 15,509 | Source found; timing quality caution |
| Hang Seng / HK33 | No verified 1m store | Not applicable | Not applicable | **1m blocked; 5m available** |

All four one-minute sources have **zero duplicate timestamps, null OHLC, nonfinite OHLC and impossible OHLC ranges** in the scanned window. Gaps include exchange closures and holidays; the raw discontinuity count is not proof of vendor outages. Completely absent 30-minute intervals are not counted as observed bins. Preserve actual one-minute execution rows even when decision bars are incomplete.

Source details:
- NQ: canonical index_minute_NQ is the same partition set as the frozen B0 source manifest; it is NOT verified dated CME futures.
- ES: canonical index_minute_ES contains **14 earlier monthly partitions** with core OHLCV columns and **163 later partitions** with additional year/month columns. The read-only loader selects only common columns. A separate lse_futures_minute_ES source covers a shorter history and must not be silently combined with this proxy.
- DAX and Nikkei: canonical index_minute_DAX and index_minute_NIKKEI225 have UTC-aware timestamps. Their product type, quote side, point value and executable cost model require verification.
- Hang Seng: the repository contains **data/processed/HK33_5m_2017_2026.parquet** with 172,108 in-scope **five-minute** observations of HK33/HKD, but a 1m Hang Seng source was not verified. A 5m input cannot reproduce intraminute order of 1m stop executions.

## Crucial risk comparability limitation

**The same 50-index-point stop is not the same $1,000 stop on every index.** An index-price proxy is not an actual futures contract. ES, DAX, Nikkei and Hang Seng use different contract multipliers, tick sizes and quote currencies. The original B0 NQ dollar P&L must not be copied to other markets.

The preregistered literal B0 transfer is a signal-path **diagnostic** in index points and synthetic price-risk units only. Before an executable USD backtest, verify product and venue, dated contracts/rolls, tick and currency multiplier, historical point-in-time FX, commissions/spread, margins and session calendars. A cash-risk-normalized $1,000 version or an exchange-local session port is a **different trial** and requires explicit pre-registration. Do not silently change the Chicago session or optimize stop width by instrument.

## Next research gate

1. Confirm or locate a true **Hang Seng 1-minute source**, or explicitly approve a separate 5-minute-quality trial.
2. Resolve the executable instrument mappings and whether the transfer test should retain literal 50-point stops or implement a separately registered equal-dollar-risk port.
3. Test source trading-session validity, missing scheduled next-bar opening prints, lookahead, native non-atomic OCO and same-minute ordering.
4. Only then run per-index Phase 3 diagnostics and Phase 4 native ml4t.backtest.Engine replays. Compare win rate, profit factor, per-risk expectancy, daily Sharpe, Calmar, maximum drawdown, costs and paired block-bootstrap Monte Carlo. Preserve all trials and inconclusive outcomes.

## Reproduction and artifacts

- Session YAML: config/research_sessions/one_bar_b0_cross_indices_20261012.yaml
- Audit script: scripts/audit_one_bar_b0_cross_indices_20261012.py
- Source metadata: run_log/one_bar_b0_cross_indices_20261012/source_manifest.json
- Quality findings: run_log/one_bar_b0_cross_indices_20261012/phase2_quality.json
- Trial ledger: run_log/one_bar_b0_cross_indices_20261012/trial_ledger.json
- Tests: tests/test_one_bar_b0_cross_indices_20261012.py

**Provenance:** The source manifest records each Parquet path, byte size, footer row count and schema type. It is a preliminary metadata identity, not a complete content-hash manifest. Full per-partition hashes must be pinned before native strategy runs.

All research outcomes are historical or provisional. No live orders or Git commits/pushes were made.
