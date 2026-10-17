# Mechanical Premia — three-candidate comparison, verified interim checkpoint

**Date:** 2026-10-14 Asia/Bangkok (2026-10-13 UTC)
**Status:** RUNNING, NOT FULL / NOT APPROVED. Latest direct three-way verifier: 138/252 unique native summary/fill/trade/equity cells verified.
**User request:** Full annual index CFD backtest 2013–2026 YTD, original DE30 vs JP225 replacement vs US500/US100 only.

## Locked candidates and method

| Candidate | H1 breakout | D1 mean reversion |
|---|---|---|
| C1 original | US500, US100, DE30 | US500, US100, DE30, EU50 |
| C2 Nikkei | US500, US100, JP225 | US500, US100, JP225, EU50 |
| C3 US-only | US500, US100 | US500, US100 |

Each uses fixed article-style 23.36% nominal risk budget for H1, 76.64% D1. Each sleeve distributes its weight equally among the 3/4, 3/4, or 2/2 eligible instruments, total nominal 1% account risk and 1.9x capped gross. No indicator retuning or manual trade PnL simulation. Native `ml4t.backtest.Engine`, registered `ml4t.engineer` features.
Input: canonical Dukascopy 1-minute BID OHLCV. Independent $100,000 annual accounts reset every Jan1. 2026 YTD ends Oct11. Base cost 1bp commission +2bps slippage per side. 1.5x and 2x source-risk costs declared.

## Complete source-weighted annual snapshots currently verified

These figures are % change in SYNTHETIC annual reset account, not FX-converted/broker-executable USD returns.

| Year | C1 original | C2 JP225 | C3 US-only |
|---|---:|---:|---:|
| 2013 | +2.97% | +5.39% | +5.98% |
| 2014 | +1.29% | +1.70% | +3.34% |
| 2015 | -1.00% | -0.87% | -0.89% |
| 2016 | -0.60% | +0.84% | -0.75% |
| 2023 | +2.67% | +4.45% | +3.42% |
| 2025 | +4.43% | +3.34% | +5.89% |
| 2026 YTD | +3.20% | +4.07% | +5.32% |

Other years are pending for at least one candidate, therefore excluded from complete three-way comparisons.

## 2025/2026 YTD direct cost stress of candidate 3

- 2025 C3 source: +5.89% at 1x, +4.86% at 1.5x, +3.85% at 2x.
- 2026 YTD C3 source: +5.32% at 1x, +4.74% at 1.5x, +4.16% at 2x.

No real broker spread or financing in the above; actual live viability unknown.

## Execution recovery and audit

- Existing C1 all 84 annual native cells completed in previous sessions.
- Existing C2 completed 30 cells before stopping at RESOURCE_BLOCKED; preserving all valid results.
- C3 is a newly frozen session `mechanicalpremia-us500-us100-2013-2026-v1`.
- A new source-priority job in tmux `ml4t-premia-threeway-priority` first fills the missing 14-year C2/C3 source-weighted annual results, then executes the remaining registered C3/C2 sleeve, equal risk, and cost stress cells in serial, skipping verified summaries.
- Worker progress: `docs/audit/mechanicalpremia_threeway_priority_log.jsonl`. The VPS has ~23GiB RAM, nearly full swap, and several unrelated workloads; the worker waits for >=2.6GiB MemAvailable rather than terminating or killing unrelated processes.
- Another tmux `ml4t-premia-source-report` writes the all-year source report when the 42 source-weighted cells exist.
- After all 252 native cells pass direct summary/fill/trade/equity audits, the integrated pipeline writes `docs/audit/mechanicalpremia_three_candidates_2013_2026/report.md`, `all_annual_metrics.csv`, and `summary.json` and registers terminal trial evidence. These final files are **not yet verified to exist** at this checkpoint.
- Regression C3 native four legs, cutoff, source risk weights: 3/3 tests passed; prior JP225 tests 3/3 passed. No orders placed live.

## Known limits

- Full-period report is pending, no winner selected yet.
- Historical dates previously observed; C2/C3 are post-selection exploratory variants and have NO fresh holdout.
- Source H1 initial stop has entry-minute protection gap; source MT5 trading clock and broker fills are unqualified.
- C1/C2 mix USD, EUR and JPY price-unit returns without FX conversion; real CFD notional, contract tick/multiplier, ASK spreads and overnight financing missing.
- Annual resets and end-of-year unclosed trade marks cannot establish genuine continuous full-horizon Sharpe, CAGR or Calmar.
- EU50 D1 eligible only after June 2014; 2013 C1/C2 universe smaller.

**Scientific decision:** INCONCLUSIVE / no promotion. No live orders, no protected data after 2026-10-11 used.
